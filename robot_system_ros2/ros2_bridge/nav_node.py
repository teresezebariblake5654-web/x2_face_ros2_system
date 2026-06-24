#!/usr/bin/env python3
"""Navigation ROS2 node — Nav2 NavigateToPose + NAV_RESULT events."""

from __future__ import annotations

import time
from typing import Optional

import rclpy
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from std_msgs.msg import String

from ros2_bridge.bus_adapter import QoSProfiles, Ros2BusAdapter
from ros2_bridge.core.event_metrics import EventMetrics
from ros2_bridge.core.runtime_state import RuntimeState
from ros2_bridge.event_codec import decode_event
from ros2_bridge.node_utils import init_runtime_state, install_heartbeat, safe_call
from ros2_bridge.path_setup import ensure_robot_system_path

ensure_robot_system_path()

from config import NAV_RETRY_MAX, NAV_TIMEOUT  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.system_clock import SystemClock  # noqa: E402
from core.types import Event, EventType, NavResult, Priority  # noqa: E402
from utils.logger import get_logger, setup_logging  # noqa: E402

logger = get_logger(__name__)


class _BridgingEventBus(EventBus):
    def __init__(self, adapter: Ros2BusAdapter) -> None:
        super().__init__()
        self._adapter = adapter

    def publish(self, event: Event) -> None:
        self._adapter.publish(event)


class NavNode(Node):
    def __init__(self) -> None:
        super().__init__("nav_node")
        setup_logging()
        self._runtime = init_runtime_state(self)
        install_heartbeat(self)
        self._metrics = EventMetrics.get()

        base_adapter = Ros2BusAdapter(self, EventBus(), "nav_node")
        self._bus = _BridgingEventBus(base_adapter)
        base_adapter._bus = self._bus

        self._nav_client = ActionClient(self, NavigateToPose, "navigate_to_pose")
        self._pending_goal: Optional[Event] = None
        self._pending_pose: Optional[PoseStamped] = None
        self._retry_count = 0
        self._deadline = 0.0

        self.create_subscription(
            String, "/robot_events", self._on_robot_event, QoSProfiles.ROBOT_EVENTS
        )
        self.create_subscription(
            PoseStamped, "/nav_goal", self._on_nav_goal, QoSProfiles.NAV
        )
        self.create_timer(0.2, self._tick_nav)

        self.get_logger().info("NavNode v1.0 online (nav/action mutex enabled)")

    def _on_nav_goal(self, msg: PoseStamped) -> None:
        trace_id = f"nav-goal-{SystemClock.now():.3f}"
        event = Event(
            type=EventType.NAV_EXECUTE,
            source="nav_node",
            trace_id=trace_id,
            priority=Priority.CRITICAL,
            payload={"action": "go_to", "location": "pose_goal"},
        )
        self._begin_nav(event, msg)

    def _on_robot_event(self, msg: String) -> None:
        try:
            event = decode_event(msg.data)
        except (ValueError, KeyError):
            return
        if event.type == EventType.NAV_EXECUTE:
            self._begin_nav(event, None)
        elif event.type == EventType.NAV_REQUEST:
            derived = Event.from_parent(
                event,
                EventType.NAV_EXECUTE,
                source="nav_node",
                payload=dict(event.payload),
            )
            self._begin_nav(derived, None)

    def _begin_nav(self, event: Event, pose: Optional[PoseStamped]) -> None:
        if self._runtime.get("is_action_busy"):
            self.get_logger().info("Nav rejected — action in progress")
            self._publish_failed(event, NavResult.REJECTED, "action_busy", 0)
            return
        if self._pending_goal is not None:
            self._publish_failed(event, NavResult.REJECTED, "nav_busy", 0)
            return

        self._runtime.update("is_nav_busy", True)
        self._metrics.set_nav_status("busy")
        self._pending_goal = event
        self._pending_pose = pose
        self._retry_count = 0
        self._deadline = SystemClock.now() + NAV_TIMEOUT
        self._publish_started(event)

    def _tick_nav(self) -> None:
        safe_call(self, self._do_tick_nav)

    def _do_tick_nav(self) -> None:
        if self._pending_goal is None:
            return

        event = self._pending_goal
        if SystemClock.now() >= self._deadline:
            self._finish(event, NavResult.TIMEOUT, "timeout")
            return

        if not self._nav_client.server_is_ready():
            self._mock_navigate(event)
            return

        if not hasattr(self, "_goal_sent"):
            goal = NavigateToPose.Goal()
            goal.pose = self._pending_pose or self._default_pose(event)
            self._goal_future = self._nav_client.send_goal_async(goal)
            self._goal_future.add_done_callback(self._goal_response_callback)
            self._goal_sent = True

    def _goal_response_callback(self, future) -> None:
        if self._pending_goal is None:
            return
        event = self._pending_goal
        goal_handle = future.result()
        if goal_handle is None or not goal_handle.accepted:
            self._retry_count += 1
            if self._retry_count <= NAV_RETRY_MAX:
                self.get_logger().warning(f"Nav goal rejected, retry {self._retry_count}")
                del self._goal_sent
                return
            self._finish(event, NavResult.FAILED, "goal_rejected")
            return

        self._result_future = goal_handle.get_result_async()
        self._result_future.add_done_callback(self._result_callback)

    def _result_callback(self, future) -> None:
        if self._pending_goal is None:
            return
        event = self._pending_goal
        result = future.result()
        if result is not None and result.status == 4:
            self._finish(event, NavResult.SUCCESS, "ok")
        else:
            self._retry_count += 1
            if self._retry_count <= NAV_RETRY_MAX:
                del self._goal_sent
                return
            self._finish(event, NavResult.FAILED, "nav_failed")

    def _mock_navigate(self, event: Event) -> None:
        self.get_logger().info("Nav2 unavailable — mock navigation")
        time.sleep(0.3)
        self._finish(event, NavResult.SUCCESS, "mock_ok")

    def _default_pose(self, event: Event) -> PoseStamped:
        pose = PoseStamped()
        pose.header.frame_id = "map"
        pose.header.stamp = self.get_clock().now().to_msg()
        loc = event.payload.get("location", "lobby")
        preset = {"lobby": (1.0, 0.0), "charging_station": (0.0, 0.0)}
        x, y = preset.get(loc, (0.5, 0.0))
        pose.pose.position.x = float(x)
        pose.pose.position.y = float(y)
        pose.pose.orientation.w = 1.0
        return pose

    def _publish_started(self, event: Event) -> None:
        started = Event.from_parent(
            event,
            EventType.NAV_STARTED,
            source="nav_node",
            priority=Priority.CRITICAL,
            payload={
                "action": event.payload.get("action", "go_to"),
                "location": event.payload.get("location", "pose"),
            },
        )
        self._bus.publish(started)

    def _finish(self, event: Event, result: NavResult, reason: str) -> None:
        self._runtime.update("is_nav_busy", False)
        self._metrics.set_nav_status("idle")
        if result == NavResult.SUCCESS:
            self._publish_result(event, result, reason, self._retry_count)
        else:
            self._publish_failed(event, result, reason, self._retry_count)
        self._pending_goal = None
        self._pending_pose = None
        if hasattr(self, "_goal_sent"):
            del self._goal_sent

    def _publish_result(self, event: Event, result: NavResult, reason: str, retries: int) -> None:
        completed = Event.from_parent(
            event,
            EventType.NAV_COMPLETED,
            source="nav_node",
            priority=Priority.CRITICAL,
            payload={
                "action": event.payload.get("action", "go_to"),
                "location": event.payload.get("location", "pose"),
                "result": result.value,
                "success": True,
                "reason": reason,
                "retries": retries,
            },
        )
        self._bus.publish(completed)

    def _publish_failed(self, event: Event, result: NavResult, reason: str, retries: int) -> None:
        failed = Event.from_parent(
            event,
            EventType.NAV_FAILED,
            source="nav_node",
            priority=Priority.CRITICAL,
            payload={
                "action": event.payload.get("action", "go_to"),
                "location": event.payload.get("location", "pose"),
                "result": result.value,
                "reason": reason,
                "retries": retries,
            },
        )
        self._bus.publish(failed)

    def destroy_node(self) -> None:
        self._runtime.update("is_nav_busy", False)
        self._bus.stop()
        super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = NavNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        RuntimeState.instance().record_error("nav_node", str(exc))
    finally:
        if node:
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

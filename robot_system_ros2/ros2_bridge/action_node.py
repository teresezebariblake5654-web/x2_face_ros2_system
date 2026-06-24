#!/usr/bin/env python3
"""Action ROS2 node — subscribes /action_commands, executes gestures."""

from __future__ import annotations

import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from ros2_bridge.bus_adapter import QoSProfiles, Ros2BusAdapter
from ros2_bridge.core.runtime_state import RuntimeState
from ros2_bridge.event_codec import action_command_from_json, decode_event
from ros2_bridge.node_utils import init_runtime_state, install_heartbeat, monotonic, safe_call
from ros2_bridge.path_setup import ensure_robot_system_path

ensure_robot_system_path()

from behavior.action_executor import ActionExecutor  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.types import Event, EventType, Priority  # noqa: E402
from utils.logger import get_logger, setup_logging  # noqa: E402

logger = get_logger(__name__)


class _BridgingEventBus(EventBus):
    def __init__(self, adapter: Ros2BusAdapter, runtime: RuntimeState) -> None:
        super().__init__()
        self._adapter = adapter
        self._runtime = runtime

    def publish(self, event: Event) -> None:
        if event.type in (EventType.ACTION_COMPLETED, EventType.ACTION_FAILED):
            self._runtime.update("is_action_busy", False)
        self._adapter.publish(event)


class ActionNode(Node):
    def __init__(self) -> None:
        super().__init__("action_node")
        setup_logging()
        self._runtime = init_runtime_state(self)
        install_heartbeat(self)

        base_adapter = Ros2BusAdapter(self, EventBus(), "action_node")
        self._bus = _BridgingEventBus(base_adapter, self._runtime)
        base_adapter._bus = self._bus

        self._bus.register_consumer("action_executor", [EventType.ACTION_REQUEST])
        self._executor = ActionExecutor(self._bus)

        self.create_subscription(
            String, "/action_commands", self._on_action_cmd, QoSProfiles.COMMANDS
        )
        self.create_subscription(
            String, "/robot_events", self._on_robot_event, QoSProfiles.ROBOT_EVENTS
        )

        self._executor.start()
        self.get_logger().info("ActionNode v1.0 online (nav/action mutex enabled)")

    def _on_action_cmd(self, msg: String) -> None:
        safe_call(self, self._handle_action_cmd, msg)

    def _handle_action_cmd(self, msg: String) -> None:
        if self._runtime.get("is_nav_busy"):
            self.get_logger().info("Action rejected — navigation in progress")
            return

        data = action_command_from_json(msg.data)
        gesture = data.get("action_type", "")
        payload = data.get("payload_json", {})
        if isinstance(payload, str):
            payload = json.loads(payload)

        trace_id = data.get("trace_id", "")
        self._runtime.update("is_action_busy", True)
        self._runtime.update("last_action_time", monotonic())

        event = Event(
            type=EventType.ACTION_REQUEST,
            source="action_node",
            trace_id=trace_id or "action-cmd",
            priority=Priority.NORMAL,
            payload={"gesture": gesture, **payload},
        )
        self._bus.publish(event)

    def _on_robot_event(self, msg: String) -> None:
        try:
            event = decode_event(msg.data)
        except (json.JSONDecodeError, ValueError, KeyError):
            return
        if event.type == EventType.ACTION_REQUEST:
            if self._runtime.get("is_nav_busy"):
                return
            safe_call(self, self._bus.publish, event)

    def destroy_node(self) -> None:
        self._runtime.update("is_action_busy", False)
        self._executor.stop()
        self._bus.stop()
        super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = ActionNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        RuntimeState.instance().record_error("action_node", str(exc))
    finally:
        if node:
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

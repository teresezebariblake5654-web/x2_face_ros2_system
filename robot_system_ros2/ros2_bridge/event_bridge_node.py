#!/usr/bin/env python3
"""Central ROS2 <-> EventBus bridge node (distributed event relay)."""

from __future__ import annotations

import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from ros2_bridge.bus_adapter import QoSProfiles
from ros2_bridge.core.event_metrics import EventMetrics
from ros2_bridge.core.runtime_state import RuntimeState
from ros2_bridge.event_codec import decode_event, encode_event
from ros2_bridge.node_utils import init_runtime_state, install_heartbeat
from ros2_bridge.path_setup import ensure_robot_system_path

ensure_robot_system_path()

from core.event_bus import EventBus  # noqa: E402
from core.types import Event  # noqa: E402
from utils.logger import get_logger, setup_logging  # noqa: E402

logger = get_logger(__name__)


class EventBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__("event_bridge_node")
        setup_logging()
        init_runtime_state(self)
        install_heartbeat(self)
        self._metrics = EventMetrics.get()

        self._bus = EventBus()
        self._bus.register_consumer("bridge_monitor", None)
        self._pub = self.create_publisher(String, "/robot_events", QoSProfiles.ROBOT_EVENTS)
        self._sub = self.create_subscription(
            String, "/robot_events", self._on_event, QoSProfiles.ROBOT_EVENTS
        )
        self._seen: set[str] = set()
        self.create_timer(0.05, self._drain_local)
        self.get_logger().info("EventBridgeNode v1.0 online (Schema 1.0 + QoS)")

    def _on_event(self, msg: String) -> None:
        try:
            event = decode_event(msg.data)
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            self._metrics.record_drop()
            self.get_logger().warning(f"Invalid event: {exc}")
            return
        if event.event_id in self._seen:
            self._metrics.record_drop()
            return
        self._seen.add(event.event_id)
        self._bus.publish(event)

    def _drain_local(self) -> None:
        for event in self._bus.drain("bridge_monitor", max_items=32):
            if event.event_id in self._seen:
                continue
            self._seen.add(event.event_id)
            out = String()
            out.data = encode_event(event)
            self._pub.publish(out)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = EventBridgeNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        RuntimeState.instance().record_error("event_bridge_node", str(exc))
    finally:
        if node:
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

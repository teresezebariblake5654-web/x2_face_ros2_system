"""Shared helpers for ROS2 wrapper nodes."""

from __future__ import annotations

import time
from typing import Callable, TypeVar

from rclpy.node import Node
from std_msgs.msg import String

from ros2_bridge.bus_adapter import QoSProfiles
from ros2_bridge.core.runtime_state import RuntimeState

T = TypeVar("T")


def init_runtime_state(node: Node) -> RuntimeState:
    """Initialize and log RuntimeState for a node."""
    rs = RuntimeState.instance()
    rs.update("system_health", {"status": "initializing", "node": node.get_name()})
    node.get_logger().info(f"RuntimeState initialized for {node.get_name()}")
    rs.update("system_health", {"status": "ready", "node": node.get_name()})
    return rs


def install_heartbeat(node: Node, period: float = 1.0) -> None:
    """Periodic heartbeat into RuntimeState and /node_heartbeat (1Hz)."""
    rs = RuntimeState.instance()
    pub = node.create_publisher(String, "/node_heartbeat", QoSProfiles.COMMANDS)

    def _beat() -> None:
        name = node.get_name()
        rs.heartbeat(name)
        msg = String()
        msg.data = name
        pub.publish(msg)

    node.create_timer(period, _beat)


def safe_call(node: Node, fn: Callable[..., T], *args, **kwargs) -> T | None:
    """Run callable; log and downgrade on failure."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        RuntimeState.instance().record_error(node.get_name(), str(exc))
        node.get_logger().error(f"Safe downgrade: {exc}")
        return None


def monotonic() -> float:
    return time.monotonic()

"""Attach ROS2 topics to a local in-process EventBus (no core modifications)."""

from __future__ import annotations

import json
import threading
from collections import deque
from typing import Callable, Deque, Optional, Set

from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from ros2_bridge.backpressure_controller import EventBackpressureController
from ros2_bridge.core.event_metrics import EventMetrics
from ros2_bridge.core.runtime_state import RuntimeState
from ros2_bridge.event_codec import _LEGACY_TO_V1, decode_event, encode_event
from ros2_bridge.path_setup import ensure_robot_system_path

ensure_robot_system_path()

from core.event_bus import EventBus  # noqa: E402
from core.types import Event, EventType  # noqa: E402


class QoSProfiles:
    """Standardized QoS — all topics must use these profiles."""

    ROBOT_EVENTS = QoSProfile(
        reliability=ReliabilityPolicy.BEST_EFFORT,
        history=HistoryPolicy.KEEP_LAST,
        depth=50,
        durability=DurabilityPolicy.VOLATILE,
    )
    COMMANDS = QoSProfile(
        reliability=ReliabilityPolicy.RELIABLE,
        history=HistoryPolicy.KEEP_LAST,
        depth=10,
        durability=DurabilityPolicy.VOLATILE,
    )
    AUDIO = QoSProfile(
        reliability=ReliabilityPolicy.RELIABLE,
        history=HistoryPolicy.KEEP_LAST,
        depth=5,
        durability=DurabilityPolicy.VOLATILE,
    )
    NAV = QoSProfile(
        reliability=ReliabilityPolicy.RELIABLE,
        history=HistoryPolicy.KEEP_LAST,
        depth=5,
        durability=DurabilityPolicy.VOLATILE,
    )


class Ros2BusAdapter:
    """Bridges local EventBus with /robot_events using Schema v1.0 + QoS."""

    def __init__(self, node: Node, bus: EventBus, node_name: str) -> None:
        self._node = node
        self._bus = bus
        self._node_name = node_name
        self._pub = node.create_publisher(String, "/robot_events", QoSProfiles.ROBOT_EVENTS)
        self._sub = node.create_subscription(
            String,
            "/robot_events",
            self._on_ros_message,
            QoSProfiles.ROBOT_EVENTS,
        )
        self._seen: Set[str] = set()
        self._seen_order: Deque[str] = deque(maxlen=4096)
        self._lock = threading.Lock()
        self._action_hook: Optional[Callable[[Event], None]] = None
        self._audio_hook: Optional[Callable[[Event], None]] = None
        self._metrics = EventMetrics.get()
        self._runtime = RuntimeState.instance()
        self._backpressure = EventBackpressureController()

    def set_action_hook(self, hook: Callable[[Event], None]) -> None:
        self._action_hook = hook

    def set_audio_hook(self, hook: Callable[[Event], None]) -> None:
        self._audio_hook = hook

    @staticmethod
    def _v1_type(event: Event) -> str:
        return _LEGACY_TO_V1.get(event.type, event.type.value)

    def get_backpressure_state(self) -> dict:
        return self._backpressure.get_load_state()

    def publish(self, event: Event, *, relay: bool = True) -> None:
        """Publish through backpressure gate — sole entry point (no bypass)."""
        v1_type = self._v1_type(event)
        if not self._backpressure.should_accept(v1_type):
            self._metrics.record_drop()
            return

        self._backpressure.push(event, v1_type)
        try:
            super(EventBus, self._bus).publish(event)
            if relay:
                self._publish_out(event)
        except Exception as exc:
            self._runtime.record_error(self._node_name, f"publish:{exc}")
            self._node.get_logger().error(f"EventBus publish failed: {exc}")
        finally:
            self._backpressure.release(event)

    def publish_out(self, event: Event) -> None:
        """Deprecated — routes through publish() so backpressure cannot be bypassed."""
        self.publish(event, relay=True)

    def _publish_out(self, event: Event) -> None:
        """Publish local event to ROS2 after bus dispatch."""
        with self._lock:
            if event.event_id in self._seen:
                return
            self._mark_seen(event.event_id)

        try:
            msg = String()
            msg.data = encode_event(event)
            self._pub.publish(msg)
        except Exception as exc:
            self._metrics.record_drop()
            self._runtime.record_error(self._node_name, f"publish_out:{exc}")
            self._node.get_logger().warning(f"encode/publish failed: {exc}")
            return

        v1_type = self._v1_type(event)
        self._metrics.record_event(v1_type, event.trace_id, event.source or self._node_name)

        if event.type == EventType.ACTION_REQUEST and self._action_hook:
            self._action_hook(event)
        if event.type in (EventType.TTS_REQUEST, EventType.LLM_REQUEST) and self._audio_hook:
            self._audio_hook(event)

    def _mark_seen(self, event_id: str) -> None:
        self._seen.add(event_id)
        self._seen_order.append(event_id)
        if len(self._seen_order) >= 4096:
            old = self._seen_order.popleft()
            self._seen.discard(old)

    def _on_ros_message(self, msg: String) -> None:
        try:
            event = decode_event(msg.data)
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            self._metrics.record_drop()
            self._node.get_logger().warning(f"Bad event JSON: {exc}")
            return

        with self._lock:
            if event.event_id in self._seen:
                self._metrics.record_drop()
                return
            self._mark_seen(event.event_id)

        self.publish(event, relay=False)

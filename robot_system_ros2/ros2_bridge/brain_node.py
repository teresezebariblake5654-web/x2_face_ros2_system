#!/usr/bin/env python3
"""Brain ROS2 node — thin wrapper around RobotBrain with watchdog."""

from __future__ import annotations

import json
from typing import Dict, FrozenSet

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from ros2_bridge.bus_adapter import QoSProfiles, Ros2BusAdapter
from ros2_bridge.core.runtime_state import RuntimeState
from ros2_bridge.event_codec import action_command_to_json, audio_command_to_json, decode_event
from ros2_bridge.node_utils import init_runtime_state, install_heartbeat, monotonic, safe_call
from ros2_bridge.node_watchdog import NodeWatchdog
from ros2_bridge.path_setup import ensure_robot_system_path

ensure_robot_system_path()

from config import BRAIN_TICK_INTERVAL  # noqa: E402
from core.brain import RobotBrain  # noqa: E402
from core.cooldown_manager import CooldownManager  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.state_machine import StateMachine  # noqa: E402
from core.types import Event, EventType, Priority  # noqa: E402
from utils.logger import get_logger, setup_logging  # noqa: E402

logger = get_logger(__name__)

FACE_IDLE_TIMEOUT = 3.0
ACTION_RESPONSE_TIMEOUT = 2.0
ACTION_FAILURE_SAFE_THRESHOLD = 3
SAFE_RECOVERY_TTS = "system recovering"

_NAV_EVENT_TYPES: FrozenSet[EventType] = frozenset({
    EventType.NAV_REQUEST,
    EventType.NAV_EXECUTE,
    EventType.NAV_STARTED,
    EventType.NAV_COMPLETED,
    EventType.NAV_FAILED,
})

_FSM_LIFECYCLE_TYPES: FrozenSet[EventType] = frozenset({
    EventType.SYSTEM_TICK,
    EventType.STATE_CHANGED,
    EventType.GREETING_COMPLETE,
    EventType.FSM_TIMER_EXPIRED,
    EventType.ACTION_COMPLETED,
    EventType.ACTION_FAILED,
})


class SystemMode:
    FULL = "FULL"
    DEGRADED = "DEGRADED"
    SAFE = "SAFE"


class _BridgingEventBus(EventBus):
    def __init__(
        self,
        adapter: Ros2BusAdapter,
        runtime: RuntimeState,
        on_event,
        mode_allows,
    ) -> None:
        super().__init__()
        self._adapter = adapter
        self._runtime = runtime
        self._on_event = on_event
        self._mode_allows = mode_allows

    def publish(self, event: Event) -> None:
        if not self._mode_allows(event):
            return
        try:
            self._on_event(event)
            self._adapter.publish(event)
        except Exception as exc:
            self._runtime.record_error("brain_node", f"publish:{exc}")
            logger.error("Brain bus publish degraded: %s", exc)


class BrainNode(Node):
    def __init__(self) -> None:
        super().__init__("brain_node")
        setup_logging()
        self._runtime = init_runtime_state(self)
        install_heartbeat(self)

        self._last_face_time = monotonic()
        self._pending_actions: Dict[str, dict] = {}
        self._brain_alive = True
        self._mode = SystemMode.FULL
        self._action_failure_count = 0
        self._watchdog = NodeWatchdog.get()
        self._watchdog.record_heartbeat("brain_node")

        self._adapter = Ros2BusAdapter(self, EventBus(), "brain_node")
        self._bus = _BridgingEventBus(
            self._adapter, self._runtime, self._track_event, self._mode_allows_event
        )
        self._adapter._bus = self._bus

        self._adapter.set_action_hook(self._forward_action)
        self._adapter.set_audio_hook(self._forward_audio)

        self._cooldowns = CooldownManager()
        self._state_machine = StateMachine(self._bus, self._cooldowns)
        self._register_consumers()
        self._brain = RobotBrain(self._bus, self._state_machine, self._cooldowns)

        self._action_pub = self.create_publisher(String, "/action_commands", QoSProfiles.COMMANDS)
        self._audio_pub = self.create_publisher(String, "/audio_commands", QoSProfiles.AUDIO)
        self._mode_pub = self.create_publisher(String, "/system_mode", QoSProfiles.COMMANDS)

        self.create_subscription(
            String, "/robot_events", self._on_robot_event, QoSProfiles.ROBOT_EVENTS
        )
        self.create_subscription(
            String, "/node_heartbeat", self._on_node_heartbeat, QoSProfiles.COMMANDS
        )

        safe_call(self, self._brain.start)
        self.create_timer(BRAIN_TICK_INTERVAL, self._spin_tick)
        self.create_timer(0.5, self._watchdog_tick)
        self.get_logger().info("BrainNode v1.0 online (watchdog enabled)")

    def _on_node_heartbeat(self, msg: String) -> None:
        self._watchdog.record_heartbeat(msg.data)

    def _mode_allows_event(self, event: Event) -> bool:
        mode = self._mode
        et = event.type

        if mode == SystemMode.FULL:
            return True

        if mode == SystemMode.DEGRADED:
            if et in _NAV_EVENT_TYPES:
                return False
            if et in (EventType.FACE_UNKNOWN, EventType.ACTION_REQUEST, EventType.LLM_REQUEST):
                return False
            if et == EventType.FACE_RECOGNIZED:
                return True
            if et == EventType.TTS_REQUEST:
                return True
            return et in _FSM_LIFECYCLE_TYPES

        if et == EventType.SYSTEM_TICK:
            return True
        if et == EventType.TTS_REQUEST and event.payload.get("recovery"):
            return True
        return False

    def _compute_mode(self) -> str:
        node_status = self._watchdog.get_node_status()
        brain_status = node_status.get("brain", "FAILED")
        if brain_status != "OK" or self._action_failure_count >= ACTION_FAILURE_SAFE_THRESHOLD:
            return SystemMode.SAFE
        if node_status.get("vision") == "FAILED":
            return SystemMode.DEGRADED
        return SystemMode.FULL

    def _update_system_mode(self) -> None:
        new_mode = self._compute_mode()
        if new_mode != self._mode:
            old_mode = self._mode
            self._mode = new_mode
            self._runtime.update("system_mode", new_mode)
            self.get_logger().warning("System mode: %s -> %s", old_mode, new_mode)
            if new_mode == SystemMode.SAFE and old_mode != SystemMode.SAFE:
                self._emit_safe_recovery_tts()
        self._publish_system_mode()

    def _publish_system_mode(self) -> None:
        msg = String()
        msg.data = json.dumps({"mode": self._mode})
        self._mode_pub.publish(msg)

    def _emit_safe_recovery_tts(self) -> None:
        event = Event(
            type=EventType.TTS_REQUEST,
            source="brain_node",
            priority=Priority.NORMAL,
            payload={"text": SAFE_RECOVERY_TTS, "recovery": True},
        )
        self._do_forward_audio(event)

    def _register_consumers(self) -> None:
        self._bus.register_consumer("robot_brain", [
            EventType.FACE_RECOGNIZED,
            EventType.FACE_UNKNOWN,
            EventType.NAV_REQUEST,
            EventType.LLM_MESSAGE,
            EventType.SYSTEM_TICK,
            EventType.NAV_STARTED,
            EventType.NAV_COMPLETED,
            EventType.NAV_FAILED,
            EventType.ENROLL_CANDIDATE,
            EventType.STATE_CHANGED,
            EventType.FSM_TIMER_EXPIRED,
            EventType.ACTION_COMPLETED,
            EventType.ACTION_FAILED,
        ])

    def _track_event(self, event: Event) -> None:
        if event.type in (EventType.FACE_RECOGNIZED, EventType.FACE_UNKNOWN):
            self._last_face_time = monotonic()
            self._runtime.update("last_face_time", self._last_face_time)
            pid = event.payload.get("person_id")
            if pid:
                self._runtime.update("current_person_id", pid)

        if event.type == EventType.STATE_CHANGED:
            to_state = event.payload.get("to")
            if to_state:
                self._runtime.update("current_fsm_state", to_state)

        if event.type == EventType.ACTION_REQUEST:
            self._pending_actions[event.trace_id] = {
                "time": monotonic(),
                "retried": False,
                "event": event,
            }

        if event.type in (EventType.ACTION_COMPLETED, EventType.ACTION_FAILED):
            self._pending_actions.pop(event.trace_id, None)
            self._runtime.update("last_action_time", monotonic())
            if event.type == EventType.ACTION_FAILED:
                self._action_failure_count += 1

    def _on_robot_event(self, msg: String) -> None:
        try:
            event = decode_event(msg.data)
        except Exception:
            return
        if event.type in (EventType.ACTION_COMPLETED, EventType.ACTION_FAILED):
            self._track_event(event)

    def _forward_action(self, event: Event) -> None:
        safe_call(self, self._do_forward_action, event)

    def _do_forward_action(self, event: Event) -> None:
        if self._mode != SystemMode.FULL:
            self.get_logger().info("Action suppressed — system mode=%s", self._mode)
            return
        if self._runtime.get("is_nav_busy"):
            self.get_logger().info("Action suppressed — nav busy")
            return
        msg = String()
        msg.data = action_command_to_json(
            event.payload.get("gesture", ""),
            event.payload,
            event.trace_id,
        )
        self._action_pub.publish(msg)

    def _forward_audio(self, event: Event) -> None:
        safe_call(self, self._do_forward_audio, event)

    def _do_forward_audio(self, event: Event) -> None:
        if self._mode == SystemMode.SAFE and not event.payload.get("recovery"):
            self.get_logger().info("Audio suppressed — SAFE mode")
            return
        if self._mode == SystemMode.DEGRADED and event.type == EventType.LLM_REQUEST:
            self.get_logger().info("LLM suppressed — DEGRADED mode")
            return
        if event.type == EventType.TTS_REQUEST and self._runtime.get("is_speaking"):
            self.get_logger().info("Duplicate TTS blocked (is_speaking=True)")
            return
        if event.type == EventType.TTS_REQUEST:
            self._runtime.update("is_speaking", True)
        cmd = "tts" if event.type == EventType.TTS_REQUEST else "llm_request"
        msg = String()
        msg.data = audio_command_to_json(cmd, event.payload, event.trace_id)
        self._audio_pub.publish(msg)

    def _spin_tick(self) -> None:
        safe_call(self, self._do_spin_tick)

    def _do_spin_tick(self) -> None:
        tick = Event(type=EventType.SYSTEM_TICK, source="brain_node", payload={})
        self._bus.publish(tick)

    def _watchdog_tick(self) -> None:
        safe_call(self, self._do_watchdog)

    def _do_watchdog(self) -> None:
        now = monotonic()
        self._update_system_mode()

        if self._mode == SystemMode.SAFE:
            return

        if now - self._last_face_time > FACE_IDLE_TIMEOUT:
            if self._runtime.get("current_fsm_state") != "IDLE":
                self._runtime.update("current_fsm_state", "IDLE")
                self.get_logger().debug("Watchdog: IDLE fallback (no face 3s)")

        for trace_id, info in list(self._pending_actions.items()):
            if now - info["time"] <= ACTION_RESPONSE_TIMEOUT:
                continue
            if info["retried"]:
                self._pending_actions.pop(trace_id, None)
                continue
            info["retried"] = True
            info["time"] = now
            self.get_logger().warning(f"Watchdog: retry action trace={trace_id}")
            self._do_forward_action(info["event"])

    def destroy_node(self) -> None:
        safe_call(self, self._brain.stop)
        self._bus.stop()
        super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = BrainNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        RuntimeState.instance().record_error("brain_node", f"fatal:{exc}")
        if node:
            node.get_logger().error(f"Brain crash contained: {exc}")
    finally:
        if node:
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

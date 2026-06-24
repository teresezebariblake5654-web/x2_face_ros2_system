#!/usr/bin/env python3
"""Audio ROS2 node — TTS + LLM wrapper."""

from __future__ import annotations

import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from ros2_bridge.bus_adapter import QoSProfiles, Ros2BusAdapter
from ros2_bridge.core.runtime_state import RuntimeState
from ros2_bridge.event_codec import audio_command_from_json, decode_event
from ros2_bridge.node_utils import init_runtime_state, install_heartbeat, safe_call
from ros2_bridge.path_setup import ensure_robot_system_path

ensure_robot_system_path()

from audio.llm_client import LLMClient  # noqa: E402
from audio.tts_engine import TTSEngine  # noqa: E402
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
        if event.type == EventType.LLM_MESSAGE:
            self._runtime.update("is_speaking", False)
        self._adapter.publish(event)


class AudioNode(Node):
    def __init__(self) -> None:
        super().__init__("audio_node")
        setup_logging()
        self._runtime = init_runtime_state(self)
        install_heartbeat(self)

        base_adapter = Ros2BusAdapter(self, EventBus(), "audio_node")
        self._bus = _BridgingEventBus(base_adapter, self._runtime)
        base_adapter._bus = self._bus

        self._bus.register_consumer("tts_engine", [EventType.TTS_REQUEST])
        self._bus.register_consumer("llm_client", [EventType.LLM_REQUEST])

        self._tts = TTSEngine(self._bus)
        self._llm = LLMClient(self._bus)

        self.create_subscription(
            String, "/audio_commands", self._on_audio_cmd, QoSProfiles.AUDIO
        )
        self.create_subscription(
            String, "/robot_events", self._on_robot_event, QoSProfiles.ROBOT_EVENTS
        )

        self._tts.start()
        self._llm.start()
        self.create_timer(2.0, self._speaking_timeout)
        self.get_logger().info("AudioNode v1.0 online")

    def _speaking_timeout(self) -> None:
        if self._runtime.get("is_speaking"):
            self._runtime.update("is_speaking", False)

    def _on_audio_cmd(self, msg: String) -> None:
        safe_call(self, self._handle_audio, msg)

    def _handle_audio(self, msg: String) -> None:
        data = audio_command_from_json(msg.data)
        cmd = data.get("cmd_type", "tts")
        payload = data.get("payload", {})
        trace_id = data.get("trace_id", "audio-cmd")

        if cmd == "tts":
            self._runtime.update("is_speaking", True)

        if cmd == "llm_request":
            event = Event(
                type=EventType.LLM_REQUEST,
                source="audio_node",
                trace_id=trace_id,
                priority=Priority.HIGH,
                payload=payload,
            )
        else:
            event = Event(
                type=EventType.TTS_REQUEST,
                source="audio_node",
                trace_id=trace_id,
                payload=payload,
            )
        self._bus.publish(event)

    def _on_robot_event(self, msg: String) -> None:
        try:
            event = decode_event(msg.data)
        except (json.JSONDecodeError, ValueError, KeyError):
            return
        if event.type in (EventType.TTS_REQUEST, EventType.LLM_REQUEST):
            safe_call(self, self._bus.publish, event)

    def destroy_node(self) -> None:
        self._runtime.update("is_speaking", False)
        self._llm.stop()
        self._tts.stop()
        self._bus.stop()
        super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = AudioNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        RuntimeState.instance().record_error("audio_node", str(exc))
    finally:
        if node:
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Vision ROS2 node — FaceEngine + RecognitionService wrapper."""

from __future__ import annotations

import time

import rclpy
from rclpy.node import Node

from ros2_bridge.bus_adapter import Ros2BusAdapter
from ros2_bridge.core.runtime_state import RuntimeState
from ros2_bridge.node_utils import init_runtime_state, install_heartbeat
from ros2_bridge.path_setup import ensure_robot_system_path

ensure_robot_system_path()

from config import FACE_ENGINE_INTERVAL  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.types import Event, EventType  # noqa: E402
from utils.logger import get_logger, setup_logging  # noqa: E402
from vision.face_db import FaceDB  # noqa: E402
from vision.face_engine import FaceEngine  # noqa: E402
from vision.recognition_service import RecognitionService  # noqa: E402

logger = get_logger(__name__)


class _BridgingEventBus(EventBus):
    def __init__(self, adapter: Ros2BusAdapter, runtime: RuntimeState) -> None:
        super().__init__()
        self._adapter = adapter
        self._runtime = runtime

    def publish(self, event: Event) -> None:
        if event.type in (EventType.FACE_RECOGNIZED, EventType.FACE_UNKNOWN, EventType.FACE_DEPARTED):
            self._runtime.update("last_face_time", time.monotonic())
            pid = event.payload.get("person_id")
            if pid:
                self._runtime.update("current_person_id", pid)
        self._adapter.publish(event)


class VisionNode(Node):
    def __init__(self) -> None:
        super().__init__("vision_node")
        setup_logging()
        self._runtime = init_runtime_state(self)
        install_heartbeat(self)

        base_adapter = Ros2BusAdapter(self, EventBus(), "vision_node")
        self._bus = _BridgingEventBus(base_adapter, self._runtime)
        base_adapter._bus = self._bus

        self._face_db = FaceDB()
        self._bus.register_consumer("recognition_service", [EventType.FACE_RAW_DETECTED])

        self._recognition = RecognitionService(self._bus, self._face_db)
        self._face_engine = FaceEngine(self._bus, self._face_db)

        self._recognition.start()
        self._face_engine.start()
        self.get_logger().info(
            f"VisionNode v1.0 online (face interval={FACE_ENGINE_INTERVAL}s)"
        )

    def destroy_node(self) -> None:
        self._face_engine.stop()
        self._recognition.stop()
        self._bus.stop()
        super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = VisionNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        RuntimeState.instance().record_error("vision_node", str(exc))
    finally:
        if node:
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

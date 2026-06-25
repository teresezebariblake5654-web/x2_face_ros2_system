#!/usr/bin/env python3
"""
Robot Greeting System — industrial entry point.

Run: cd robot_system && python3 main.py
"""

from __future__ import annotations

import signal
import sys
import time

from adapters.robot_sdk_adapter import RobotSDKAdapter
from audio.llm_client import LLMClient
from audio.tts_engine import TTSEngine
from behavior.action_executor import ActionExecutor
from config import DEMO_MODE, FACE_ENGINE_INTERVAL
from core.brain import RobotBrain
from core.cooldown_manager import CooldownManager
from core.event_bus import EventBus
from core.health_monitor import HealthMonitor
from core.state_machine import StateMachine
from core.trace_logger import TraceLogger
from core.types import Event, EventType, Priority
from face_core.repository import FaceRepository
from navigation.nav_client import NavClient
from navigation.nav_controller import NavController
from utils.logger import get_logger, setup_logging
from vision.face_db import FaceDB
from vision.face_engine import FaceEngine
from vision.recognition_service import RecognitionService

logger = get_logger(__name__)


class RobotSystem:
    def __init__(self) -> None:
        setup_logging()
        logger.info("=" * 60)
        logger.info("Robot Greeting System — Commercial Deployment v3")
        logger.info("=" * 60)

        self._bus = EventBus()
        self._cooldowns = CooldownManager()
        self._state_machine = StateMachine(self._bus, self._cooldowns)
        self._register_consumers()

        self._face_db = FaceDB()
        self._face_repo = FaceRepository(self._face_db)
        self._sdk = RobotSDKAdapter()

        self._face_engine = FaceEngine(self._bus, self._face_repo)
        self._recognition = RecognitionService(self._bus, self._face_repo)
        self._brain = RobotBrain(
            self._bus,
            self._state_machine,
            self._cooldowns,
            face_repo=self._face_repo,
        )
        self._action_executor = ActionExecutor(self._bus, sdk=self._sdk)
        self._tts = TTSEngine(self._bus)
        self._llm = LLMClient(self._bus)
        self._nav_client = NavClient()
        self._nav_controller = NavController(self._bus, self._nav_client)
        self._health = HealthMonitor(self._bus, self._action_executor, self._face_engine)

        self._running = False

    def _register_consumers(self) -> None:
        self._bus.register_consumer("robot_brain", [
            EventType.FACE_RECOGNIZED,
            EventType.FACE_UNKNOWN,
            EventType.FACE_DEPARTED,
            EventType.NAV_REQUEST,
            EventType.LLM_MESSAGE,
            EventType.SYSTEM_TICK,
            EventType.NAV_STARTED,
            EventType.NAV_COMPLETED,
            EventType.NAV_FAILED,
            EventType.ACTION_FAILED,
            EventType.ENROLL_CANDIDATE,
            EventType.STATE_CHANGED,
            EventType.FSM_TIMER_EXPIRED,
        ])
        self._bus.register_consumer("recognition_service", [EventType.FACE_RAW_DETECTED])
        self._bus.register_consumer("action_executor", [EventType.ACTION_REQUEST])
        self._bus.register_consumer("tts_engine", [EventType.TTS_REQUEST])
        self._bus.register_consumer("llm_client", [EventType.LLM_REQUEST])
        self._bus.register_consumer("nav_controller", [EventType.NAV_EXECUTE])

    def start(self) -> None:
        logger.info("Starting subsystems...")
        self._action_executor.start()
        self._tts.start()
        self._llm.start()
        self._nav_controller.start()
        self._recognition.start()
        self._brain.start()
        self._face_engine.start()
        self._health.start()
        self._running = True
        logger.info("All subsystems online. Face interval=%.1fs DEMO_MODE=%s", FACE_ENGINE_INTERVAL, DEMO_MODE)
        if DEMO_MODE:
            self._schedule_demo_nav(delay=10.0)
        else:
            logger.info("Demo navigation disabled (set ROBOT_DEMO_MODE=1 to enable)")

    def _schedule_demo_nav(self, delay: float) -> None:
        import threading

        def _fire() -> None:
            time.sleep(delay)
            if not self._running:
                return
            logger.info("[Demo] Injecting NAV_REQUEST -> lobby")
            self._bus.publish(
                Event(
                    type=EventType.NAV_REQUEST,
                    source="demo_scheduler",
                    priority=Priority.CRITICAL,
                    payload={"action": "go_to", "location": "lobby"},
                )
            )

        threading.Thread(target=_fire, name="DemoNav", daemon=True).start()

    def stop(self) -> None:
        logger.info("Shutting down...")
        self._running = False
        self._health.stop()
        self._face_engine.stop()
        self._brain.stop()
        self._recognition.stop()
        self._nav_controller.stop()
        self._llm.stop()
        self._tts.stop()
        self._action_executor.stop()
        self._bus.stop()
        trace = TraceLogger.get().snapshot()
        logger.info("Shutdown. bus=%s trace=%s", self._bus.stats, trace)

    def run_forever(self) -> None:
        self.start()
        signal.signal(signal.SIGINT, lambda *_: None)
        signal.signal(signal.SIGTERM, lambda *_: None)
        try:
            while self._running:
                time.sleep(1.0)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt")
        finally:
            self.stop()


def main() -> int:
    RobotSystem().run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())

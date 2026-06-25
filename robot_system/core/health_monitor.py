"""Subsystem health monitor — periodic thread liveness checks."""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict

from config import HEALTH_CHECK_INTERVAL
from core.event_bus import EventBus
from utils.logger import get_logger

logger = get_logger(__name__)


class HealthMonitor:
    """Logs system_health every 10 seconds (configurable)."""

    def __init__(
        self,
        bus: EventBus,
        action_executor: Any,
        face_engine: Any,
        interval: float = HEALTH_CHECK_INTERVAL,
    ) -> None:
        self._bus = bus
        self._executor = action_executor
        self._face_engine = face_engine
        self._interval = interval
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="HealthMonitor", daemon=True)
        self._thread.start()
        logger.info("HealthMonitor started (interval=%.0fs)", self._interval)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=self._interval + 2.0)

    def snapshot(self) -> Dict[str, bool]:
        return {
            "event_bus": self._bus.is_dispatcher_alive(),
            "executor": self._executor.is_alive,
            "face_engine": self._face_engine.is_alive,
        }

    def _loop(self) -> None:
        while self._running:
            health = self.snapshot()
            logger.info("system_health %s", json.dumps(health, ensure_ascii=False))
            time.sleep(self._interval)

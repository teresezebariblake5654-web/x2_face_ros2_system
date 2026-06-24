"""Isolated navigation SDK client — NO direct calls from other modules."""

from __future__ import annotations

import threading
import time

from utils.logger import get_logger

logger = get_logger(__name__)


class NavClient:
    """Mock robot navigation SDK (Unitree / ROS2 adapter goes here)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_location: str | None = None
        self._is_moving = False

    @property
    def current_location(self) -> str | None:
        with self._lock:
            return self._current_location

    @property
    def is_moving(self) -> bool:
        with self._lock:
            return self._is_moving

    def go_to(self, location: str) -> bool:
        with self._lock:
            if self._is_moving:
                logger.warning("[NavSDK] Already moving, reject go_to(%s)", location)
                return False
            self._is_moving = True
        logger.info("[NavSDK] go_to(%s) — navigating...", location)
        time.sleep(0.5)  # simulate SDK call latency
        with self._lock:
            self._current_location = location
            self._is_moving = False
        logger.info("[NavSDK] Arrived at %s", location)
        return True

    def return_to_charge(self) -> bool:
        logger.info("[NavSDK] return_to_charge() — heading to charging station")
        return self.go_to("charging_station")

    def cancel(self) -> None:
        with self._lock:
            self._is_moving = False
        logger.info("[NavSDK] Navigation cancelled")

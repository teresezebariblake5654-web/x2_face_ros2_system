"""Centralized cooldown management — all cooldowns live here."""

from __future__ import annotations

import threading
from typing import Dict, Optional

from config import DIALOG_TIMEOUT, GREETING_COOLDOWN, NAV_TIMEOUT
from core.system_clock import SystemClock
from utils.logger import get_logger

logger = get_logger(__name__)


class CooldownManager:
    """Tracks named cooldown / timeout windows using monotonic time."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._deadlines: Dict[str, float] = {}
        self._durations: Dict[str, float] = {
            "greeting": GREETING_COOLDOWN,
            "dialog": DIALOG_TIMEOUT,
            "navigation": NAV_TIMEOUT,
        }

    def start(self, name: str, duration: Optional[float] = None) -> None:
        dur = duration if duration is not None else self._durations.get(name, 5.0)
        deadline = SystemClock.now() + dur
        with self._lock:
            self._deadlines[name] = deadline
        logger.debug("Cooldown '%s' started (%.1fs)", name, dur)

    def stop(self, name: str) -> None:
        with self._lock:
            self._deadlines.pop(name, None)

    def clear_all(self) -> None:
        with self._lock:
            self._deadlines.clear()

    def is_active(self, name: str) -> bool:
        with self._lock:
            deadline = self._deadlines.get(name)
            if deadline is None:
                return False
            return SystemClock.now() < deadline

    def expired(self, name: str) -> bool:
        with self._lock:
            deadline = self._deadlines.get(name)
            if deadline is None:
                return False
            return SystemClock.now() >= deadline

    def remaining(self, name: str) -> float:
        with self._lock:
            deadline = self._deadlines.get(name)
            if deadline is None:
                return 0.0
            return max(0.0, deadline - SystemClock.now())

    def on_state_enter(self, state: str) -> None:
        if state == "COOLDOWN":
            self.start("greeting")
        elif state == "DIALOG":
            self.start("dialog")
        elif state == "NAVIGATION":
            self.start("navigation")
        elif state == "IDLE":
            self.stop("greeting")
            self.stop("dialog")
            self.stop("navigation")

    def check_expirations(self) -> list[str]:
        """Return names of cooldowns that just expired."""
        expired: list[str] = []
        with self._lock:
            now = SystemClock.now()
            for name, deadline in list(self._deadlines.items()):
                if now >= deadline:
                    expired.append(name)
                    del self._deadlines[name]
        return expired

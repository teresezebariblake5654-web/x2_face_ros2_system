"""Monotonic timer utilities."""

from __future__ import annotations

from typing import Optional

from core.system_clock import SystemClock


class Timer:
    def __init__(self, duration: float) -> None:
        self.duration = duration
        self._deadline: Optional[float] = None

    def start(self) -> None:
        self._deadline = SystemClock.now() + self.duration

    def reset(self, duration: Optional[float] = None) -> None:
        if duration is not None:
            self.duration = duration
        self.start()

    def is_active(self) -> bool:
        return self._deadline is not None

    def expired(self) -> bool:
        if self._deadline is None:
            return False
        return SystemClock.now() >= self._deadline

    def remaining(self) -> float:
        if self._deadline is None:
            return self.duration
        return max(0.0, self._deadline - SystemClock.now())

    def stop(self) -> None:
        self._deadline = None

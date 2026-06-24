"""Monotonic system clock — wall-clock time is forbidden for control logic."""

from __future__ import annotations

import time


class SystemClock:
    """Single source of monotonic timestamps for FSM, cooldowns, and events."""

    _boot: float = time.monotonic()

    @classmethod
    def now(cls) -> float:
        return time.monotonic()

    @classmethod
    def elapsed_since_boot(cls) -> float:
        return cls.now() - cls._boot

    @classmethod
    def reset_boot_reference(cls) -> None:
        cls._boot = time.monotonic()

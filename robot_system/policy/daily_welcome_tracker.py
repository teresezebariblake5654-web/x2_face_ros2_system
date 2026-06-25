"""Track per-person welcome state within a calendar day."""

from __future__ import annotations

import threading
from datetime import date


class DailyWelcomeTracker:
    """
    售楼迎宾惯例：
      - 当日首次识别 → 完整欢迎
      - 当日再次出现 → 静默点头，不播报
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._date = ""
        self._welcomed: set[str] = set()

    def _roll_day(self) -> None:
        today = date.today().isoformat()
        if today != self._date:
            self._date = today
            self._welcomed.clear()

    def has_welcomed_today(self, person_id: str) -> bool:
        with self._lock:
            self._roll_day()
            return person_id in self._welcomed

    def mark_welcomed_today(self, person_id: str) -> None:
        with self._lock:
            self._roll_day()
            self._welcomed.add(person_id)

    def welcomed_count_today(self) -> int:
        with self._lock:
            self._roll_day()
            return len(self._welcomed)

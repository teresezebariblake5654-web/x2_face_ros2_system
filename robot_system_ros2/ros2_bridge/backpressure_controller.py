"""Event backpressure — sampling for high-frequency FACE, blocking for critical paths."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Optional, Set

FACE_TYPES: Set[str] = frozenset({"FACE_RECOGNIZED", "FACE_UNKNOWN"})
CRITICAL_TYPES: Set[str] = frozenset({"ACTION", "AUDIO", "NAV"})

FACE_HIGH_WATERMARK = 150
SAMPLING_DIVISOR = 3


class EventBackpressureController:
    """Tracks in-flight events; drops/samples FACE under load, blocks critical types."""

    def __init__(
        self,
        queue_max_size: int = 200,
        drop_policy: str = "drop_oldest",
        sampling_mode: bool = True,
    ) -> None:
        self.queue_max_size = queue_max_size
        self.drop_policy = drop_policy
        self.sampling_mode = sampling_mode

        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._queue: Deque[Any] = deque()
        self._event_times: Deque[float] = deque(maxlen=512)
        self._dropped_events_count = 0
        self._face_sample_counter = 0

    @staticmethod
    def _is_face(event_type: str) -> bool:
        return event_type in FACE_TYPES

    @staticmethod
    def _is_critical(event_type: str) -> bool:
        return event_type in CRITICAL_TYPES

    def should_accept(self, event_type: str) -> bool:
        """Return False when a FACE event should be dropped (sampling under load)."""
        with self._lock:
            size = len(self._queue)
            if self._is_face(event_type) and self.sampling_mode and size > FACE_HIGH_WATERMARK:
                self._face_sample_counter += 1
                if self._face_sample_counter % SAMPLING_DIVISOR != 0:
                    self._dropped_events_count += 1
                    return False
            return True

    def push(self, event: Any, event_type: str) -> None:
        """Enqueue in-flight event; block critical types, drop-oldest for FACE."""
        with self._cond:
            if self._is_critical(event_type):
                while len(self._queue) >= self.queue_max_size:
                    self._cond.wait(timeout=0.05)
            elif len(self._queue) >= self.queue_max_size:
                if self.drop_policy == "drop_oldest" and self._queue:
                    self._queue.popleft()
                    self._dropped_events_count += 1

            self._queue.append(event)
            self._event_times.append(time.monotonic())

    def release(self, event: Any) -> None:
        """Remove an in-flight event after publish completes."""
        with self._cond:
            try:
                self._queue.remove(event)
            except ValueError:
                pass
            self._cond.notify_all()

    def get_load_state(self) -> dict:
        now = time.monotonic()
        with self._lock:
            recent = sum(1 for t in self._event_times if now - t <= 1.0)
            return {
                "dropped_events_count": self._dropped_events_count,
                "current_queue_size": len(self._queue),
                "event_rate_estimate": float(recent),
            }

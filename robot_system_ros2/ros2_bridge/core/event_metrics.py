"""Lightweight event metrics collector for monitor / observability."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Optional


class EventMetrics:
    """Thread-safe metrics; monitor aggregates from /robot_events in its process."""

    _instance: Optional["EventMetrics"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._data_lock = threading.Lock()
        self._event_times: Deque[float] = deque(maxlen=512)
        self._face_pending: Dict[str, float] = {}
        self._latencies: Deque[float] = deque(maxlen=128)
        self._dropped = 0
        self._node_last_seen: Dict[str, float] = {}
        self._nav_status = "idle"

    @classmethod
    def get(cls) -> "EventMetrics":
        with cls._lock:
            if cls._instance is None:
                cls._instance = EventMetrics()
            return cls._instance

    def record_event(self, event_type: str, trace_id: str, source: str = "") -> None:
        now = time.monotonic()
        with self._data_lock:
            self._event_times.append(now)
            if source:
                self._node_last_seen[source] = now
            if event_type in ("FACE_RECOGNIZED", "FACE_UNKNOWN"):
                self._face_pending[trace_id] = now
            if event_type == "ACTION" and trace_id in self._face_pending:
                latency = now - self._face_pending.pop(trace_id)
                self._latencies.append(latency)

    def record_drop(self) -> None:
        with self._data_lock:
            self._dropped += 1

    def set_nav_status(self, status: str) -> None:
        with self._data_lock:
            self._nav_status = status

    def event_rate(self) -> float:
        now = time.monotonic()
        with self._data_lock:
            recent = [t for t in self._event_times if now - t <= 1.0]
        return float(len(recent))

    def avg_face_to_action_latency(self) -> float:
        with self._data_lock:
            if not self._latencies:
                return 0.0
            return sum(self._latencies) / len(self._latencies)

    def dropped_count(self) -> int:
        with self._data_lock:
            return self._dropped

    def node_alive_map(self, timeout: float = 5.0) -> Dict[str, bool]:
        now = time.monotonic()
        with self._data_lock:
            return {
                name: (now - ts) <= timeout
                for name, ts in self._node_last_seen.items()
            }

    def nav_status(self) -> str:
        with self._data_lock:
            return self._nav_status

    def snapshot(self) -> dict:
        return {
            "event_rate": self.event_rate(),
            "avg_latency_face_to_action": self.avg_face_to_action_latency(),
            "dropped_events_count": self.dropped_count(),
            "node_alive_map": self.node_alive_map(),
            "nav_status": self.nav_status(),
        }

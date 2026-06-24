"""Cross-process node liveness watchdog — 1Hz heartbeat, OK / DEGRADED / FAILED."""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional, Tuple

REGISTERED_NODES: Tuple[str, ...] = ("vision", "brain", "action", "nav", "audio")

NODE_NAME_ALIASES: Dict[str, str] = {
    "vision": "vision",
    "vision_node": "vision",
    "brain": "brain",
    "brain_node": "brain",
    "action": "action",
    "action_node": "action",
    "nav": "nav",
    "nav_node": "nav",
    "audio": "audio",
    "audio_node": "audio",
}

DEGRADED_THRESHOLD_SEC = 3.0
FAILED_THRESHOLD_SEC = 8.0


class NodeWatchdog:
    """Tracks registered node heartbeats and exposes liveness status."""

    _instance: Optional["NodeWatchdog"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._heartbeats: Dict[str, float] = {}

    @classmethod
    def get(cls) -> "NodeWatchdog":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = NodeWatchdog()
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    @staticmethod
    def _normalize_node(node: str) -> Optional[str]:
        return NODE_NAME_ALIASES.get(node)

    def record_heartbeat(self, node: str) -> None:
        """Record a heartbeat from a registered node (expected at 1Hz)."""
        short = self._normalize_node(node)
        if short is None:
            return
        with self._lock:
            self._heartbeats[short] = time.monotonic()

    def _status_for_age(self, age_sec: float) -> str:
        if age_sec > FAILED_THRESHOLD_SEC:
            return "FAILED"
        if age_sec > DEGRADED_THRESHOLD_SEC:
            return "DEGRADED"
        return "OK"

    def get_node_status(self) -> dict:
        now = time.monotonic()
        with self._lock:
            heartbeats = dict(self._heartbeats)

        status: Dict[str, str] = {}
        for name in REGISTERED_NODES:
            last = heartbeats.get(name)
            if last is None:
                status[name] = "FAILED"
            else:
                status[name] = self._status_for_age(now - last)
        return status

    def failed_nodes_count(self) -> int:
        return sum(1 for state in self.get_node_status().values() if state == "FAILED")

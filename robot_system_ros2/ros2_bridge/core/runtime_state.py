"""Process-local singleton runtime state for ROS2 wrapper layer."""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from typing import Any, Dict, Optional


class RuntimeState:
    """Thread-safe singleton holding cross-node observable runtime fields."""

    _instance: Optional["RuntimeState"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = {
            "current_person_id": None,
            "current_fsm_state": "IDLE",
            "last_face_time": 0.0,
            "last_action_time": 0.0,
            "is_speaking": False,
            "is_nav_busy": False,
            "is_action_busy": False,
            "system_health": {
                "status": "initializing",
                "node": "unknown",
                "errors": [],
            },
        }

    @classmethod
    def instance(cls) -> "RuntimeState":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = RuntimeState()
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    def update(self, key: str, value: Any) -> None:
        with self._lock:
            if key == "system_health" and isinstance(value, dict):
                base = dict(self._data.get("system_health", {}))
                base.update(value)
                self._data["system_health"] = base
            else:
                self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return deepcopy(self._data)

    def heartbeat(self, node_name: str) -> None:
        with self._lock:
            health = dict(self._data.get("system_health", {}))
            health["node"] = node_name
            health["last_heartbeat"] = time.monotonic()
            health["status"] = "alive"
            self._data["system_health"] = health

    def record_error(self, node_name: str, error: str) -> None:
        with self._lock:
            health = dict(self._data.get("system_health", {}))
            errors = list(health.get("errors", []))
            errors.append(f"{node_name}:{error}")
            health["errors"] = errors[-20:]
            health["status"] = "degraded"
            self._data["system_health"] = health

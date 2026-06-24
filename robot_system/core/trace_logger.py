"""Global trace / observability — event lifecycle, state, and action history."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from core.system_clock import SystemClock
from utils.logger import get_logger

logger = get_logger(__name__)

_MAX_CHAIN = 256
_MAX_HISTORY = 512


@dataclass
class TraceRecord:
    trace_id: str
    stage: str
    module: str
    detail: str
    timestamp: float = field(default_factory=SystemClock.now)


class TraceLogger:
    """Records event flow chains and histories for deployment debugging."""

    _instance: Optional["TraceLogger"] = None

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._chains: Dict[str, List[str]] = {}
        self._state_history: Deque[str] = deque(maxlen=_MAX_HISTORY)
        self._action_history: Deque[str] = deque(maxlen=_MAX_HISTORY)
        self._event_lifecycle: Deque[TraceRecord] = deque(maxlen=_MAX_HISTORY)

    @classmethod
    def get(cls) -> "TraceLogger":
        if cls._instance is None:
            cls._instance = TraceLogger()
        return cls._instance

    def log_lifecycle(
        self,
        trace_id: str,
        module: str,
        stage: str,
        detail: str = "",
    ) -> None:
        record = TraceRecord(trace_id=trace_id, stage=stage, module=module, detail=detail)
        with self._lock:
            self._event_lifecycle.append(record)
            chain = self._chains.setdefault(trace_id, [])
            chain.append(f"{module}:{stage}")
        msg = f"[{trace_id}] {module} | {stage}"
        if detail:
            msg += f" | {detail}"
        logger.info(msg)

    def log_chain(self, trace_id: str, *stages: str) -> None:
        """Append readable pipeline stages, e.g. FACE -> BRAIN -> FSM -> ACTION."""
        pipeline = " -> ".join(stages)
        with self._lock:
            self._chains.setdefault(trace_id, []).append(pipeline)
        logger.info("[%s] %s", trace_id, pipeline)

    def log_state_transition(
        self,
        trace_id: str,
        old_state: str,
        new_state: str,
        reason: str = "",
    ) -> None:
        entry = f"{old_state}->{new_state}"
        if reason:
            entry += f" ({reason})"
        with self._lock:
            self._state_history.append(entry)
        self.log_chain(trace_id, "FSM", f"{old_state}->{new_state}")
        logger.info("[%s] FSM transition: %s", trace_id, entry)

    def log_action(self, trace_id: str, gesture: str, status: str = "EXEC") -> None:
        entry = f"{gesture}:{status}"
        with self._lock:
            self._action_history.append(entry)
        self.log_chain(trace_id, "ACTION", gesture)
        logger.info("[%s] ACTION %s %s", trace_id, gesture, status)

    def get_chain(self, trace_id: str) -> List[str]:
        with self._lock:
            return list(self._chains.get(trace_id, []))

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "state_history": list(self._state_history)[-20:],
                "action_history": list(self._action_history)[-20:],
                "active_traces": len(self._chains),
            }

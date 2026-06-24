"""Event routing — classifies events and applies priority/state gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.priority import PriorityArbiter
from core.state_machine import StateMachine
from core.trace_logger import TraceLogger
from core.types import Event, EventType, RobotState
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RouteDecision:
    allowed: bool
    reason: str
    category: Optional[str] = None
    defer: bool = False
    preempt: bool = False


class EventRouter:
    """Pure routing layer — no business logic, no side effects."""

    _CATEGORY_MAP = {
        EventType.FACE_RECOGNIZED: "face_known",
        EventType.FACE_UNKNOWN: "face_unknown",
        EventType.NAV_REQUEST: "navigation",
        EventType.LLM_MESSAGE: "dialog",
        EventType.NAV_STARTED: "nav_lifecycle",
        EventType.NAV_COMPLETED: "nav_lifecycle",
        EventType.NAV_FAILED: "nav_lifecycle",
        EventType.ENROLL_CANDIDATE: "enrollment",
        EventType.FSM_TIMER_EXPIRED: "fsm_timer",
        EventType.GREETING_COMPLETE: "fsm_internal",
        EventType.SYSTEM_TICK: "tick",
        EventType.STATE_CHANGED: "state_notify",
    }

    def __init__(self, state_machine: StateMachine, arbiter: PriorityArbiter) -> None:
        self._sm = state_machine
        self._arbiter = arbiter
        self._trace = TraceLogger.get()

    def route(self, event: Event) -> RouteDecision:
        self._trace.log_lifecycle(event.trace_id, "ROUTER", "RECEIVE", event.type.value)

        if event.type == EventType.SYSTEM_TICK:
            return RouteDecision(True, "tick", "tick")

        if event.type == EventType.STATE_CHANGED:
            return RouteDecision(True, "notify", "state_notify")

        state = self._sm.state
        allowed, reason = self._arbiter.can_process(event, state)

        if not allowed:
            if event.type == EventType.NAV_REQUEST and self._arbiter.should_preempt(event, state):
                self._trace.log_chain(event.trace_id, "ROUTER", "PREEMPT", event.type.value)
                return RouteDecision(
                    False,
                    reason,
                    "navigation",
                    defer=True,
                    preempt=True,
                )
            self._trace.log_lifecycle(event.trace_id, "ROUTER", "DROP", reason)
            logger.info(
                "[Router] DROP %s | state=%s | %s",
                event.type.value,
                state.value,
                reason,
            )
            return RouteDecision(False, reason)

        category = self._CATEGORY_MAP.get(event.type, "unknown")
        self._trace.log_chain(event.trace_id, "ROUTER", "BRAIN", category.upper())
        return RouteDecision(True, "ok", category)

    def should_defer_nav(self, state: RobotState) -> bool:
        return state not in (RobotState.IDLE,)

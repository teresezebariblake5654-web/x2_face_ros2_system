"""Unified finite-state machine — sole entry for all state transitions."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

from core.cooldown_manager import CooldownManager
from core.event_bus import EventBus
from core.system_clock import SystemClock
from core.trace_logger import TraceLogger
from core.types import Event, EventType, NavResult, RobotState
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TransitionResult:
    changed: bool
    old_state: RobotState
    new_state: RobotState
    reason: str = ""


class StateMachine:
    """
    Central FSM. ALL state changes MUST go through transition(event).
    No other module may mutate state directly.
    """

    def __init__(self, bus: EventBus, cooldowns: CooldownManager) -> None:
        self._bus = bus
        self._cooldowns = cooldowns
        self._trace = TraceLogger.get()
        self._lock = threading.Lock()
        self._state = RobotState.IDLE
        self._last_face_id: Optional[str] = None

    @property
    def state(self) -> RobotState:
        with self._lock:
            return self._state

    @property
    def last_face_id(self) -> Optional[str]:
        with self._lock:
            return self._last_face_id

    def remember_face(self, person_id: str) -> None:
        with self._lock:
            self._last_face_id = person_id

    def transition(self, event: Event) -> TransitionResult:
        """Unique state transition entry point."""
        with self._lock:
            old = self._state
            new = self._resolve(old, event)
            reason = event.payload.get("reason", event.type.value)

            if new == old:
                return TransitionResult(False, old, new, reason)

            self._state = new
            logger.info("FSM: %s -> %s (%s)", old.value, new.value, reason)

        self._cooldowns.on_state_enter(new.value)
        self._trace.log_state_transition(event.trace_id, old.value, new.value, reason)
        self._bus.publish(
            Event.from_parent(
                event,
                EventType.STATE_CHANGED,
                source="state_machine",
                payload={"from": old.value, "to": new.value, "reason": reason},
            )
        )
        return TransitionResult(True, old, new, reason)

    def _resolve(self, state: RobotState, event: Event) -> RobotState:
        et = event.type

        if et == EventType.FSM_TIMER_EXPIRED:
            timer = event.payload.get("timer_name", "")
            if state == RobotState.COOLDOWN and timer == "greeting":
                return RobotState.IDLE
            if state == RobotState.DIALOG and timer == "dialog":
                return RobotState.IDLE
            if state == RobotState.NAVIGATION and timer == "navigation":
                return RobotState.ERROR
            return state

        if et == EventType.FACE_RECOGNIZED and state in (RobotState.IDLE, RobotState.DIALOG):
            pid = event.payload.get("person_id")
            if pid:
                self._last_face_id = pid
            return RobotState.GREETING

        if et == EventType.FACE_UNKNOWN and state in (RobotState.IDLE, RobotState.DIALOG):
            return RobotState.GREETING

        if et == EventType.GREETING_COMPLETE and state == RobotState.GREETING:
            return RobotState.COOLDOWN

        if et == EventType.NAV_REQUEST and state == RobotState.IDLE:
            return RobotState.NAVIGATION

        if et == EventType.NAV_STARTED and state in (RobotState.IDLE, RobotState.NAVIGATION):
            return RobotState.NAVIGATION

        if et == EventType.NAV_COMPLETED and state == RobotState.NAVIGATION:
            result = event.payload.get("result", "")
            if result == NavResult.SUCCESS.value:
                return RobotState.IDLE
            return RobotState.ERROR

        if et == EventType.NAV_FAILED:
            return RobotState.ERROR

        if et == EventType.LLM_MESSAGE and state in (
            RobotState.IDLE,
            RobotState.GREETING,
        ):
            return RobotState.DIALOG

        if et == EventType.LLM_MESSAGE and state == RobotState.COOLDOWN:
            return RobotState.COOLDOWN

        return state

    def tick(self) -> list[Event]:
        """Process cooldown expirations; emit FSM timer events."""
        expired = self._cooldowns.check_expirations()
        events: list[Event] = []
        state = self.state

        timer_map = {
            "greeting": RobotState.COOLDOWN,
            "dialog": RobotState.DIALOG,
            "navigation": RobotState.NAVIGATION,
        }

        for name in expired:
            expected = timer_map.get(name)
            if expected and state != expected:
                continue
            trace_id = f"timer-{name}-{SystemClock.now():.3f}"
            events.append(
                Event(
                    type=EventType.FSM_TIMER_EXPIRED,
                    source="state_machine",
                    trace_id=trace_id,
                    payload={"timer_name": name},
                )
            )
        return events

    def can_greet(self) -> bool:
        return self.state in (RobotState.IDLE, RobotState.DIALOG)

    def can_navigate(self) -> bool:
        return self.state == RobotState.IDLE

    def can_dialog(self) -> bool:
        return self.state in (
            RobotState.IDLE,
            RobotState.GREETING,
            RobotState.DIALOG,
            RobotState.COOLDOWN,
        )

    def recover_from_error(self, event: Event) -> TransitionResult:
        with self._lock:
            if self._state != RobotState.ERROR:
                return TransitionResult(False, self._state, self._state)
            old = self._state
            self._state = RobotState.IDLE
        self._cooldowns.clear_all()
        self._trace.log_state_transition(
            event.trace_id, old.value, RobotState.IDLE.value, "error_recovery"
        )
        return TransitionResult(True, old, RobotState.IDLE, "error_recovery")

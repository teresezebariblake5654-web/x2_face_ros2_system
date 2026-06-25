"""Policy layer — pure decision logic, delegates to behavior policies."""

from __future__ import annotations

from typing import Optional

from behavior.dialog_policy import DialogPolicy
from behavior.farewell_policy import FarewellPolicy
from behavior.greeting_policy import GreetingPolicy
from behavior.nav_policy import NavPolicy
from core.policy_types import DeferredNav, PolicyCommand, PolicyOutcome
from core.state_machine import StateMachine
from core.trace_logger import TraceLogger
from core.types import Event, EventType, NavResult, RobotState
from face_core.repository import FaceRepository
from policy.welcome_policy import WelcomePolicy
from utils.logger import get_logger

logger = get_logger(__name__)


class PolicyLayer:
    """
    Evaluates events and returns PolicyOutcome.
    Contains NO execution — only decisions.
    """

    def __init__(
        self,
        state_machine: StateMachine,
        face_repo: Optional[FaceRepository] = None,
    ) -> None:
        self._sm = state_machine
        repo = face_repo or FaceRepository()
        welcome = WelcomePolicy()
        self._greeting = GreetingPolicy(repo, welcome)
        self._farewell = FarewellPolicy(welcome)
        self._nav = NavPolicy()
        self._dialog = DialogPolicy()
        self._trace = TraceLogger.get()
        self._pending_nav: Optional[DeferredNav] = None

    @property
    def pending_nav(self) -> Optional[DeferredNav]:
        return self._pending_nav

    def clear_pending_nav(self) -> Optional[DeferredNav]:
        nav = self._pending_nav
        self._pending_nav = None
        return nav

    def set_pending_nav(self, action: str, location: str, trace_id: str) -> None:
        self._pending_nav = DeferredNav(action, location, trace_id)

    def set_sales_engaged(self, engaged: bool) -> None:
        self._greeting._throttle.set_sales_engaged(engaged)

    def evaluate(self, event: Event, category: str) -> PolicyOutcome:
        self._trace.log_lifecycle(event.trace_id, "POLICY", "EVAL", category)
        state = self._sm.state

        if category == "face_known":
            return self._greeting.known_face(event, state, self._sm.can_greet())
        if category == "face_unknown":
            return self._greeting.unknown_face(event, state, self._sm.can_greet())
        if category == "face_departed":
            return self._farewell.departed(event, state)
        if category == "navigation":
            return self._nav.request(event, state, self._sm.can_navigate())
        if category == "dialog":
            return self._dialog.llm_response(event, state, self._sm.can_dialog())
        if category == "nav_lifecycle":
            return self._nav.lifecycle(event, state)
        if category == "enrollment":
            return PolicyOutcome(
                trace_id=event.trace_id,
                notes=f"candidate={event.payload.get('candidate_id')}",
            )
        if category == "fsm_timer":
            return PolicyOutcome(trace_id=event.trace_id, fsm_events=["timer"])
        return PolicyOutcome(trace_id=event.trace_id)

    def build_deferred_nav_outcome(self, nav: DeferredNav) -> PolicyOutcome:
        logger.info("[Policy] Processing deferred NAV %s -> %s", nav.action, nav.location)
        fake = Event(
            type=EventType.NAV_REQUEST,
            source="policy_layer",
            trace_id=nav.trace_id,
            payload={"action": nav.action, "location": nav.location, "deferred": True},
        )
        return self._nav.request(fake, RobotState.IDLE, True)

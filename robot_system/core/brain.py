"""
RobotBrain — thin orchestrator.

Responsibilities ONLY:
  - EventRouter (route)
  - PolicyLayer (evaluate)
  - Delegate FSM transitions to StateMachine
  - Delegate command publish to CommandEmitter

NO business logic lives here.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Optional

from config import BRAIN_TICK_INTERVAL, ERROR_AUTO_RECOVERY, ERROR_RECOVERY_DELAY_SEC
from core.command_emitter import CommandEmitter
from core.cooldown_manager import CooldownManager
from core.event_bus import EventBus
from core.event_router import EventRouter
from core.policy_layer import PolicyLayer
from core.policy_types import PolicyOutcome
from core.priority import PriorityArbiter
from core.state_machine import StateMachine
from core.trace_logger import TraceLogger
from core.types import Event, EventType, Priority, RobotState
from utils.logger import get_logger

if TYPE_CHECKING:
    from face_core.repository import FaceRepository

logger = get_logger(__name__)


class RobotBrain:
    def __init__(
        self,
        bus: EventBus,
        state_machine: StateMachine,
        cooldowns: CooldownManager,
        face_repo: Optional["FaceRepository"] = None,
    ) -> None:
        self._bus = bus
        self._sm = state_machine
        self._cooldowns = cooldowns
        self._arbiter = PriorityArbiter()
        self._router = EventRouter(state_machine, self._arbiter)
        self._policy = PolicyLayer(state_machine, face_repo=face_repo)
        self._emitter = CommandEmitter(bus)
        self._trace = TraceLogger.get()
        self._running = False
        self._thread: threading.Thread | None = None
        self._error_since: float | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._tick_loop, name="RobotBrain", daemon=True)
        self._thread.start()
        logger.info("RobotBrain started (router+policy only, tick=%.2fs)", BRAIN_TICK_INTERVAL)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def set_sales_engaged(self, engaged: bool) -> None:
        self._policy.set_sales_engaged(engaged)

    def _tick_loop(self) -> None:
        while self._running:
            self._bus.publish_tick(source="robot_brain")
            for event in self._bus.drain("robot_brain", max_items=32):
                self.process(event)
            self.tick()
            time.sleep(BRAIN_TICK_INTERVAL)

    def tick(self) -> None:
        for timer_event in self._sm.tick():
            self._trace.log_lifecycle(timer_event.trace_id, "BRAIN", "TIMER", timer_event.type.value)
            self._sm.transition(timer_event)

        if self._sm.state == RobotState.IDLE:
            self._arbiter.clear_active_priority()
            pending = self._policy.clear_pending_nav()
            if pending:
                fake = Event(
                    type=EventType.NAV_REQUEST,
                    source="robot_brain",
                    trace_id=pending.trace_id,
                    payload={"action": pending.action, "location": pending.location},
                    priority=Priority.CRITICAL,
                )
                self._sm.transition(fake)
                outcome = self._policy.build_deferred_nav_outcome(pending)
                self._emitter.emit(fake, outcome)
                self._arbiter.set_active_priority(Priority.CRITICAL)

        if self._sm.state == RobotState.ERROR:
            now = time.monotonic()
            if self._error_since is None:
                self._error_since = now
                logger.warning("[Brain] FSM entered ERROR; recovery in %.1fs", ERROR_RECOVERY_DELAY_SEC)
            elif ERROR_AUTO_RECOVERY and (now - self._error_since) >= ERROR_RECOVERY_DELAY_SEC:
                recovery = Event(
                    type=EventType.SYSTEM_TICK,
                    source="robot_brain",
                    trace_id="error-recovery",
                    payload={"reason": "auto_recovery"},
                )
                self._sm.recover_from_error(recovery)
                self._error_since = None
                logger.info("[Brain] FSM recovered from ERROR after delay")
        else:
            self._error_since = None

    def process(self, event: Event) -> None:
        """Route -> category handler -> FSM -> Policy -> Emit."""
        decision = self._router.route(event)
        if not decision.allowed:
            if event.type == EventType.NAV_REQUEST:
                self._policy.set_pending_nav(
                    event.payload.get("action", "go_to"),
                    event.payload.get("location", "lobby"),
                    event.trace_id,
                )
            return

        if decision.category in ("tick", "state_notify"):
            return

        category = decision.category or "unknown"
        self._trace.log_chain(event.trace_id, "EVENT", "BRAIN", category.upper())

        if category in ("face_known", "face_unknown"):
            self._handle_face_event(event, category)
        elif category == "face_departed":
            self._handle_farewell_event(event)
        elif category in ("navigation", "nav_lifecycle"):
            self._handle_navigation_event(event, category)
        elif category == "dialog":
            self._handle_dialog_event(event, category)
        elif category == "action_lifecycle":
            self._handle_action_lifecycle(event)
        else:
            self._handle_system_event(event, category)

    def _handle_face_event(self, event: Event, category: str) -> None:
        if not self._sm.can_greet():
            logger.info("[Brain] greeting blocked state=%s", self._sm.state.value)
            return

        outcome = self._policy.evaluate(event, category)
        if outcome.notes == "guard_pending":
            logger.debug("[Brain] greeting deferred: recognition guard")
            return

        self._sm.transition(event)

        person_id = event.payload.get("person_id")
        if category == "face_known" and person_id:
            self._sm.remember_face(person_id)

        if outcome.commands:
            self._emitter.emit(event, outcome)

        self._finalize_greeting(event, outcome)
        self._arbiter.clear_active_priority()

    def _handle_navigation_event(self, event: Event, category: str) -> None:
        if category == "navigation":
            outcome = self._policy.evaluate(event, category)
            if outcome.notes == "nav_deferred":
                self._policy.set_pending_nav(
                    event.payload.get("action", "go_to"),
                    event.payload.get("location", "lobby"),
                    event.trace_id,
                )
                return
            self._sm.transition(event)
            if outcome.commands:
                self._emitter.emit(event, outcome)
            if self._sm.state == RobotState.NAVIGATION:
                self._arbiter.set_active_priority(Priority.CRITICAL)
            return

        if category == "nav_lifecycle":
            if event.type in (EventType.NAV_COMPLETED, EventType.NAV_FAILED):
                self._sm.transition(event)
                self._arbiter.clear_active_priority()

        outcome = self._policy.evaluate(event, category)
        if outcome.commands:
            self._emitter.emit(event, outcome)

    def _handle_system_event(self, event: Event, category: str) -> None:
        if category == "fsm_timer":
            self._sm.transition(event)
            return

        outcome = self._policy.evaluate(event, category)
        if outcome.commands:
            self._emitter.emit(event, outcome)
        self._finalize_greeting(event, outcome)

    def _handle_farewell_event(self, event: Event) -> None:
        if self._sm.state in (RobotState.NAVIGATION, RobotState.ERROR):
            return
        outcome = self._policy.evaluate(event, "face_departed")
        if not outcome.commands:
            return
        self._emitter.emit(event, outcome)

    def _handle_action_lifecycle(self, event: Event) -> None:
        if event.type != EventType.ACTION_FAILED:
            return
        if self._sm.state != RobotState.GREETING:
            return
        logger.warning(
            "[Brain] ACTION_FAILED during GREETING — completing greeting trace=%s",
            event.trace_id,
        )
        fake = Event.from_parent(
            event,
            EventType.GREETING_COMPLETE,
            source="robot_brain",
            payload={"reason": "action_failed_abort"},
        )
        self._emitter.emit_greeting_complete(fake)
        self._sm.transition(fake)

    def _handle_dialog_event(self, event: Event, category: str) -> None:
        self._sm.transition(event)
        outcome = self._policy.evaluate(event, category)
        if outcome.commands:
            self._emitter.emit(event, outcome)
        self._finalize_greeting(event, outcome)
        self._trace.log_chain(event.trace_id, "LLM", "BRAIN", "TTS")

    def _finalize_greeting(self, event: Event, outcome: PolicyOutcome) -> None:
        if "greeting_complete" not in outcome.fsm_events:
            return
        self._emitter.emit_greeting_complete(event)
        self._sm.transition(
            Event.from_parent(
                event,
                EventType.GREETING_COMPLETE,
                source="robot_brain",
                payload={"reason": "greeting_done"},
            )
        )
        self._trace.log_chain(event.trace_id, "FACE", "BRAIN", "FSM", "ACTION", "TTS")

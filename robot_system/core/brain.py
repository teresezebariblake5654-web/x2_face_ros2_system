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

from config import BRAIN_TICK_INTERVAL
from core.command_emitter import CommandEmitter
from core.cooldown_manager import CooldownManager
from core.event_bus import EventBus
from core.event_router import EventRouter
from core.policy_layer import PolicyLayer
from core.priority import PriorityArbiter
from core.state_machine import StateMachine
from core.trace_logger import TraceLogger
from core.types import Event, EventType, Priority, RobotState
from utils.logger import get_logger

logger = get_logger(__name__)


class RobotBrain:
    def __init__(
        self,
        bus: EventBus,
        state_machine: StateMachine,
        cooldowns: CooldownManager,
    ) -> None:
        self._bus = bus
        self._sm = state_machine
        self._cooldowns = cooldowns
        self._arbiter = PriorityArbiter()
        self._router = EventRouter(state_machine, self._arbiter)
        self._policy = PolicyLayer(state_machine)
        self._emitter = CommandEmitter(bus)
        self._trace = TraceLogger.get()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._tick_loop, name="RobotBrain", daemon=True)
        self._thread.start()
        logger.info("RobotBrain started (router+policy only, tick=%.2fs)", BRAIN_TICK_INTERVAL)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

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
            recovery = Event(
                type=EventType.SYSTEM_TICK,
                source="robot_brain",
                trace_id="error-recovery",
                payload={"reason": "auto_recovery"},
            )
            self._sm.recover_from_error(recovery)

    def process(self, event: Event) -> None:
        """Route -> FSM -> Policy -> Emit."""
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

        if category in ("face_known", "face_unknown", "fsm_timer"):
            if category in ("face_known", "face_unknown") and not self._sm.can_greet():
                logger.info("[Brain] greeting blocked state=%s", self._sm.state.value)
                return
            if category in ("face_known", "face_unknown"):
                outcome = self._policy.evaluate(event, category)
                self._sm.transition(event)
                if category == "face_known":
                    pid = event.payload.get("person_id")
                    if pid:
                        self._sm.remember_face(pid)
                if outcome.commands:
                    self._emitter.emit(event, outcome)
                if "greeting_complete" in outcome.fsm_events:
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
                self._arbiter.clear_active_priority()
                return
            self._sm.transition(event)
            return

        if category == "face_known":
            pid = event.payload.get("person_id")
            if pid:
                self._sm.remember_face(pid)

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

        if category == "dialog":
            self._sm.transition(event)

        outcome = self._policy.evaluate(event, category)

        if outcome.commands:
            self._emitter.emit(event, outcome)

        if "greeting_complete" in outcome.fsm_events:
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

        if category == "dialog":
            self._trace.log_chain(event.trace_id, "LLM", "BRAIN", "TTS")

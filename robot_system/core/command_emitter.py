"""Command emitter — translates PolicyOutcome into EventBus events."""

from __future__ import annotations

from core.event_bus import EventBus
from core.policy_types import CommandType, PolicyCommand, PolicyOutcome
from core.trace_logger import TraceLogger
from core.types import Event, EventType, Priority
from utils.logger import get_logger

logger = get_logger(__name__)


class CommandEmitter:
    """Publishes downstream events from policy decisions. No business logic."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._trace = TraceLogger.get()

    def emit(self, parent: Event, outcome: PolicyOutcome) -> None:
        for cmd in outcome.commands:
            self._emit_command(parent, cmd)

    def emit_greeting_complete(self, parent: Event) -> None:
        evt = Event.from_parent(
            parent,
            EventType.GREETING_COMPLETE,
            source="command_emitter",
            payload={"reason": "greeting_done"},
        )
        self._bus.publish(evt)

    def _emit_command(self, parent: Event, cmd: PolicyCommand) -> None:
        if cmd.cmd_type == CommandType.ACTION:
            gesture = cmd.payload.get("gesture", "")
            self._trace.log_action(parent.trace_id, gesture, "REQUEST")
            self._bus.publish(
                Event.from_parent(
                    parent,
                    EventType.ACTION_REQUEST,
                    source="command_emitter",
                    payload=cmd.payload,
                )
            )
        elif cmd.cmd_type == CommandType.TTS:
            self._trace.log_chain(parent.trace_id, "TTS", cmd.payload.get("text", "")[:40])
            self._bus.publish(
                Event.from_parent(
                    parent,
                    EventType.TTS_REQUEST,
                    source="command_emitter",
                    payload=cmd.payload,
                )
            )
        elif cmd.cmd_type == CommandType.LLM_REQUEST:
            self._trace.log_chain(parent.trace_id, "LLM", "REQUEST")
            self._bus.publish(
                Event.from_parent(
                    parent,
                    EventType.LLM_REQUEST,
                    source="command_emitter",
                    priority=Priority.HIGH,
                    payload=cmd.payload,
                )
            )
        elif cmd.cmd_type == CommandType.NAV_EXECUTE:
            self._trace.log_chain(parent.trace_id, "NAV", "EXECUTE")
            self._bus.publish(
                Event.from_parent(
                    parent,
                    EventType.NAV_EXECUTE,
                    source="command_emitter",
                    priority=Priority.CRITICAL,
                    payload=cmd.payload,
                )
            )
        elif cmd.cmd_type == CommandType.LOG:
            logger.info("[PolicyLog] %s", cmd.payload.get("message", ""))

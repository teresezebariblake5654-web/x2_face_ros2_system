"""Event schema registry — defines required payload fields per event type."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set

from core.types import EventType


@dataclass(frozen=True)
class EventSchema:
    event_type: EventType
    required_payload: FrozenSet[str] = field(default_factory=frozenset)
    optional_payload: FrozenSet[str] = field(default_factory=frozenset)
    description: str = ""


class EventSchemaRegistry:
    """Central registry for event payload validation."""

    def __init__(self) -> None:
        self._schemas: Dict[EventType, EventSchema] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        specs: List[EventSchema] = [
            EventSchema(EventType.FACE_RECOGNIZED, frozenset({"person_id", "name", "score"})),
            EventSchema(EventType.FACE_UNKNOWN, frozenset({"score"})),
            EventSchema(EventType.FACE_RAW_DETECTED, frozenset({"embedding"})),
            EventSchema(EventType.NAV_REQUEST, frozenset(), frozenset({"action", "location"})),
            EventSchema(EventType.NAV_EXECUTE, frozenset(), frozenset({"action", "location", "trace_id"})),
            EventSchema(
                EventType.NAV_COMPLETED,
                frozenset({"result"}),
                frozenset({"action", "location", "success", "retries"}),
            ),
            EventSchema(
                EventType.NAV_FAILED,
                frozenset({"result"}),
                frozenset({"action", "location", "reason", "retries"}),
            ),
            EventSchema(EventType.NAV_STARTED, frozenset(), frozenset({"action", "location"})),
            EventSchema(
                EventType.LLM_MESSAGE,
                frozenset({"text", "intent", "confidence"}),
                frozenset({"request_id", "context"}),
            ),
            EventSchema(EventType.LLM_REQUEST, frozenset({"text"}), frozenset({"context"})),
            EventSchema(EventType.ACTION_REQUEST, frozenset({"gesture"})),
            EventSchema(EventType.TTS_REQUEST, frozenset({"text"})),
            EventSchema(EventType.SYSTEM_TICK, frozenset()),
            EventSchema(EventType.STATE_CHANGED, frozenset({"from", "to"})),
            EventSchema(EventType.ENROLL_CANDIDATE, frozenset({"candidate_id"})),
            EventSchema(EventType.GREETING_COMPLETE, frozenset()),
            EventSchema(EventType.FSM_TIMER_EXPIRED, frozenset({"timer_name"})),
            EventSchema(EventType.ACTION_COMPLETED, frozenset({"gesture"})),
            EventSchema(EventType.ACTION_FAILED, frozenset({"gesture", "reason"})),
        ]
        for schema in specs:
            self.register(schema)

    def register(self, schema: EventSchema) -> None:
        self._schemas[schema.event_type] = schema

    def get(self, event_type: EventType) -> Optional[EventSchema]:
        return self._schemas.get(event_type)

    def known_types(self) -> Set[EventType]:
        return set(self._schemas.keys())

    def validate_payload(self, event_type: EventType, payload: dict) -> tuple[bool, str]:
        schema = self._schemas.get(event_type)
        if schema is None:
            return True, "ok (no schema)"
        missing = schema.required_payload - set(payload.keys())
        if missing:
            return False, f"missing fields: {sorted(missing)}"
        return True, "ok"


# Singleton registry
REGISTRY = EventSchemaRegistry()

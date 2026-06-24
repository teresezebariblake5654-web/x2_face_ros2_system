"""Event validation against schema registry."""

from __future__ import annotations

from core.event_schema import REGISTRY
from core.types import Event, EventType
from utils.logger import get_logger

logger = get_logger(__name__)


class EventValidator:
    """Validates event envelope and payload before bus publish."""

    def __init__(self) -> None:
        self._registry = REGISTRY

    def validate(self, event: Event) -> tuple[bool, str]:
        if not event.event_id:
            return False, "event_id required"
        if not event.trace_id:
            return False, "trace_id required"
        if event.timestamp <= 0:
            return False, "timestamp must be positive monotonic value"

        etype = event.type
        if isinstance(etype, str):
            try:
                etype = EventType(etype)
            except ValueError:
                return False, f"unknown event type: {etype}"

        ok, msg = self._registry.validate_payload(etype, event.payload)
        if not ok:
            return False, msg
        return True, "ok"

    def validate_or_warn(self, event: Event) -> bool:
        ok, msg = self.validate(event)
        if not ok:
            logger.warning("Event validation failed [%s]: %s", event.event_id, msg)
        return ok

"""Event Schema v1.0 codec — JSON encode/decode with backward compatibility."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict

from ros2_bridge.path_setup import ensure_robot_system_path

ensure_robot_system_path()

from core.types import Event, EventType, Priority  # noqa: E402

SCHEMA_VERSION = "1.0"

# v1.0 canonical type names
V1_FACE_RECOGNIZED = "FACE_RECOGNIZED"
V1_FACE_UNKNOWN = "FACE_UNKNOWN"
V1_GREETING = "GREETING"
V1_ACTION = "ACTION"
V1_NAV = "NAV"
V1_AUDIO = "AUDIO"

_LEGACY_TO_V1: Dict[EventType, str] = {
    EventType.FACE_RECOGNIZED: V1_FACE_RECOGNIZED,
    EventType.FACE_UNKNOWN: V1_FACE_UNKNOWN,
    EventType.FACE_DEPARTED: V1_FACE_RECOGNIZED,
    EventType.FACE_CAPACITY_REPORT: V1_FACE_RECOGNIZED,
    EventType.FACE_RAW_DETECTED: V1_FACE_RECOGNIZED,
    EventType.GREETING_COMPLETE: V1_GREETING,
    EventType.STATE_CHANGED: V1_GREETING,
    EventType.ACTION_REQUEST: V1_ACTION,
    EventType.ACTION_COMPLETED: V1_ACTION,
    EventType.ACTION_FAILED: V1_ACTION,
    EventType.NAV_REQUEST: V1_NAV,
    EventType.NAV_EXECUTE: V1_NAV,
    EventType.NAV_STARTED: V1_NAV,
    EventType.NAV_COMPLETED: V1_NAV,
    EventType.NAV_FAILED: V1_NAV,
    EventType.TTS_REQUEST: V1_AUDIO,
    EventType.LLM_REQUEST: V1_AUDIO,
    EventType.LLM_MESSAGE: V1_AUDIO,
}


def _json_safe(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if hasattr(obj, "tolist"):
        return obj.tolist()
    return str(obj)


def _priority_to_name(priority: Priority) -> str:
    return priority.name if isinstance(priority, Priority) else str(priority)


def _priority_from_name(name: str) -> Priority:
    try:
        return Priority[name]
    except KeyError:
        return Priority.NORMAL


def _map_legacy_type(legacy: str) -> str:
    try:
        return _LEGACY_TO_V1.get(EventType(legacy), legacy)
    except ValueError:
        return legacy


def encode_event(event: Event) -> str:
    """Encode Event to Schema v1.0 JSON (all publishes must use this)."""
    v1_type = _LEGACY_TO_V1.get(event.type, event.type.value)
    payload = _json_safe(dict(event.payload))
    payload["_legacy_type"] = event.type.value
    payload["_event_id"] = event.event_id
    payload["_source"] = event.source
    payload["_priority"] = _priority_to_name(event.priority)

    envelope = {
        "schema": SCHEMA_VERSION,
        "trace_id": event.trace_id,
        "timestamp": float(event.timestamp),
        "type": v1_type,
        "payload": payload,
    }
    return json.dumps(envelope, ensure_ascii=False)


def decode_event(raw: str) -> Event:
    """Decode Schema v1.0 or legacy JSON into internal Event."""
    data: Dict[str, Any] = json.loads(raw)

    if data.get("schema") == SCHEMA_VERSION:
        payload = dict(data.get("payload", {}))
        legacy_type = payload.pop("_legacy_type", None)
        event_id = payload.pop("_event_id", uuid.uuid4().hex[:12])
        source = payload.pop("_source", "ros2_bridge")
        priority = _priority_from_name(payload.pop("_priority", "NORMAL"))

        if legacy_type:
            etype = EventType(legacy_type)
        else:
            v1 = data.get("type", "")
            etype = _v1_to_legacy(v1, payload)

        return Event(
            type=etype,
            payload=payload,
            event_id=event_id,
            trace_id=data.get("trace_id", uuid.uuid4().hex[:12]),
            timestamp=float(data.get("timestamp", 0.0)),
            source=source,
            priority=priority,
        )

    # Legacy backward compatibility
    legacy_type_raw = data.get("type", "")
    try:
        etype = EventType(legacy_type_raw)
    except ValueError:
        etype = _v1_to_legacy(legacy_type_raw, data.get("payload", {}))

    return Event(
        type=etype,
        payload=data.get("payload", {}),
        event_id=data.get("event_id", uuid.uuid4().hex[:12]),
        trace_id=data.get("trace_id", uuid.uuid4().hex[:12]),
        timestamp=float(data.get("timestamp", 0.0)),
        source=data.get("source", "ros2_bridge"),
        priority=_priority_from_name(data.get("priority", "NORMAL")),
    )


def _v1_to_legacy(v1_type: str, payload: dict) -> EventType:
    if v1_type == V1_FACE_UNKNOWN:
        return EventType.FACE_UNKNOWN
    if v1_type == V1_FACE_RECOGNIZED:
        return EventType.FACE_RECOGNIZED
    if v1_type == V1_GREETING:
        return EventType.GREETING_COMPLETE
    if v1_type == V1_ACTION:
        gesture = payload.get("gesture", "")
        if payload.get("reason"):
            return EventType.ACTION_FAILED
        if payload.get("elapsed") is not None:
            return EventType.ACTION_COMPLETED
        return EventType.ACTION_REQUEST
    if v1_type == V1_NAV:
        if payload.get("result") in ("FAILED", "TIMEOUT", "REJECTED"):
            return EventType.NAV_FAILED
        if payload.get("success") is True or payload.get("result") == "SUCCESS":
            return EventType.NAV_COMPLETED
        if payload.get("action") == "go_to" and "location" in payload:
            return EventType.NAV_EXECUTE
        return EventType.NAV_STARTED
    if v1_type == V1_AUDIO:
        if payload.get("text") and payload.get("intent"):
            return EventType.LLM_MESSAGE
        if payload.get("context"):
            return EventType.LLM_REQUEST
        return EventType.TTS_REQUEST
    return EventType.SYSTEM_TICK


# Public aliases
event_to_json = encode_event
event_from_json = decode_event


def action_command_to_json(gesture: str, payload: dict, trace_id: str = "") -> str:
    return json.dumps(
        {
            "schema": SCHEMA_VERSION,
            "action_type": gesture,
            "payload_json": _json_safe(payload),
            "trace_id": trace_id,
        },
        ensure_ascii=False,
    )


def action_command_from_json(raw: str) -> dict:
    return json.loads(raw)


def audio_command_to_json(cmd_type: str, payload: dict, trace_id: str = "") -> str:
    return json.dumps(
        {
            "schema": SCHEMA_VERSION,
            "cmd_type": cmd_type,
            "payload": _json_safe(payload),
            "trace_id": trace_id,
        },
        ensure_ascii=False,
    )


def audio_command_from_json(raw: str) -> dict:
    return json.loads(raw)

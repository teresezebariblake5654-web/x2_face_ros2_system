"""Shared type definitions: events, states, priorities."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Dict, Optional
import uuid

from core.system_clock import SystemClock


class EventType(str, Enum):
    FACE_RECOGNIZED = "FACE_RECOGNIZED"
    FACE_UNKNOWN = "FACE_UNKNOWN"
    FACE_RAW_DETECTED = "FACE_RAW_DETECTED"
    NAV_REQUEST = "NAV_REQUEST"
    NAV_EXECUTE = "NAV_EXECUTE"
    NAV_STARTED = "NAV_STARTED"
    NAV_COMPLETED = "NAV_COMPLETED"
    NAV_FAILED = "NAV_FAILED"
    LLM_MESSAGE = "LLM_MESSAGE"
    LLM_REQUEST = "LLM_REQUEST"
    SYSTEM_TICK = "SYSTEM_TICK"
    ACTION_REQUEST = "ACTION_REQUEST"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    ACTION_FAILED = "ACTION_FAILED"
    TTS_REQUEST = "TTS_REQUEST"
    STATE_CHANGED = "STATE_CHANGED"
    ENROLL_CANDIDATE = "ENROLL_CANDIDATE"
    GREETING_COMPLETE = "GREETING_COMPLETE"
    FSM_TIMER_EXPIRED = "FSM_TIMER_EXPIRED"


class RobotState(str, Enum):
    IDLE = "IDLE"
    GREETING = "GREETING"
    COOLDOWN = "COOLDOWN"
    NAVIGATION = "NAVIGATION"
    DIALOG = "DIALOG"
    ERROR = "ERROR"


class Priority(IntEnum):
    LOW = 10
    NORMAL = 50
    HIGH = 80
    CRITICAL = 100


class GestureType(str, Enum):
    WAVE = "wave"
    TURN_HEAD = "turn_head"
    QUESTION_MARK = "question_mark"
    POINT = "point"


class NavResult(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    REJECTED = "REJECTED"


class LLMIntent(str, Enum):
    SMALLTALK = "smalltalk"
    QUESTION = "question"
    UNKNOWN = "unknown"


@dataclass
class Event:
    """
    Standardized event envelope.

    Serialized format:
        {event_id, trace_id, type, timestamp, payload}
    """

    type: EventType
    payload: Dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=SystemClock.now)
    source: str = "unknown"
    priority: Priority = Priority.NORMAL

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "trace_id": self.trace_id,
            "type": self.type.value,
            "timestamp": self.timestamp,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_parent(
        cls,
        parent: "Event",
        event_type: EventType,
        source: str,
        payload: Optional[Dict[str, Any]] = None,
        priority: Optional[Priority] = None,
    ) -> "Event":
        """Create child event inheriting trace_id from parent."""
        return cls(
            type=event_type,
            payload=payload or {},
            trace_id=parent.trace_id,
            source=source,
            priority=priority if priority is not None else parent.priority,
        )

    def __repr__(self) -> str:
        return (
            f"Event({self.type.value}, trace={self.trace_id}, "
            f"src={self.source}, id={self.event_id})"
        )


@dataclass
class FaceRecord:
    person_id: str
    name: str
    embedding: Any
    embedding_version: int = 1
    created_at: float = field(default_factory=SystemClock.now)
    last_seen: float = 0.0
    confidence_threshold: float = 0.75


@dataclass
class LLMResponse:
    text: str
    intent: LLMIntent
    confidence: float

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "intent": self.intent.value,
            "confidence": self.confidence,
        }

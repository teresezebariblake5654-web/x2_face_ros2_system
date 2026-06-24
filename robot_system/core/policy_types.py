"""Policy commands emitted after decision — no execution here."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CommandType(str, Enum):
    ACTION = "ACTION"
    TTS = "TTS"
    LLM_REQUEST = "LLM_REQUEST"
    NAV_EXECUTE = "NAV_EXECUTE"
    FSM_SIGNAL = "FSM_SIGNAL"
    LOG = "LOG"


@dataclass
class PolicyCommand:
    cmd_type: CommandType
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyOutcome:
    """Result of policy evaluation — Brain forwards to CommandEmitter."""
    trace_id: str
    commands: List[PolicyCommand] = field(default_factory=list)
    fsm_events: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class DeferredNav:
    action: str
    location: str
    trace_id: str

"""Farewell business policy — visitor departure handling."""

from __future__ import annotations

import threading
from typing import Optional

from config import FAREWELL_PERSON_COOLDOWN
from core.policy_types import CommandType, PolicyCommand, PolicyOutcome
from core.system_clock import SystemClock
from core.types import Event, RobotState
from policy.welcome_policy import WelcomePolicy
from utils.logger import get_logger

logger = get_logger(__name__)

_SILENT_NOD_ANGLE = 12


class FarewellPolicy:
    """Decides farewell commands when a visitor leaves the welcome zone."""

    def __init__(self, welcome_policy: Optional[WelcomePolicy] = None) -> None:
        self._welcome = welcome_policy or WelcomePolicy()
        self._lock = threading.Lock()
        self._last_farewell: dict[str, float] = {}

    def departed(self, event: Event, state: RobotState) -> PolicyOutcome:
        if state in (RobotState.NAVIGATION, RobotState.ERROR, RobotState.GREETING):
            return PolicyOutcome(trace_id=event.trace_id, notes="farewell_blocked_state")

        person_id = event.payload.get("person_id", "")
        name = event.payload.get("name") or person_id or "访客"
        now = SystemClock.now()

        with self._lock:
            if person_id:
                last = self._last_farewell.get(person_id)
                if last is not None and (now - last) < FAREWELL_PERSON_COOLDOWN:
                    return PolicyOutcome(trace_id=event.trace_id, notes="farewell_cooldown")
                self._last_farewell[person_id] = now

        text = self._welcome.closing_remark()
        logger.info("[FarewellPolicy] %s departed — closing remark", name)
        return PolicyOutcome(
            trace_id=event.trace_id,
            commands=[
                PolicyCommand(
                    CommandType.ACTION,
                    {"gesture": "turn_head", "angle": _SILENT_NOD_ANGLE},
                ),
                PolicyCommand(CommandType.TTS, {"text": text, "lang": "zh-CN"}),
            ],
            notes="farewell",
        )

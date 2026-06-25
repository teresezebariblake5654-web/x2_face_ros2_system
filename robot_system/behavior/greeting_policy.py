"""Greeting business policy — known / unknown face handling."""

from __future__ import annotations

from typing import Callable, List, Optional

from config import DAILY_SILENT_REPEAT
from core.policy_types import CommandType, PolicyCommand, PolicyOutcome
from core.system_clock import SystemClock
from core.types import Event, RobotState
from face_core.repository import FaceRepository
from policy.daily_welcome_tracker import DailyWelcomeTracker
from policy.recognition_guard import UNKNOWN_IDENTITY, RecognitionGuard
from policy.speech_throttle import SpeechThrottle
from policy.welcome_policy import WelcomePolicy
from utils.logger import get_logger

logger = get_logger(__name__)

_SILENT_NOD_ANGLE = 12
_DEFAULT_TURN_ANGLE = 25
_GROUP_TURN_ANGLE = 20


class GreetingPolicy:
    """Decides greeting commands for face events."""

    def __init__(
        self,
        face_repo: Optional[FaceRepository] = None,
        welcome_policy: Optional[WelcomePolicy] = None,
        daily_tracker: Optional[DailyWelcomeTracker] = None,
        recognition_guard: Optional[RecognitionGuard] = None,
        speech_throttle: Optional[SpeechThrottle] = None,
    ) -> None:
        self._repo = face_repo or FaceRepository()
        self._welcome = welcome_policy or WelcomePolicy()
        self._daily = daily_tracker or DailyWelcomeTracker()
        self._guard = recognition_guard or RecognitionGuard()
        self._throttle = speech_throttle or SpeechThrottle()

    def known_face(self, event: Event, state: RobotState, can_greet: bool) -> PolicyOutcome:
        if not can_greet:
            logger.info("[GreetingPolicy] blocked state=%s", state.value)
            return PolicyOutcome(trace_id=event.trace_id, notes="greet_blocked")

        person_id = event.payload.get("person_id", "unknown")
        name = event.payload.get("name", person_id)
        score = event.payload.get("score", 0.0)
        vip_level = event.payload.get("vip_level") or self._repo.get_vip_level(person_id)

        return self._greet_with_guards(
            event=event,
            identity=person_id,
            name=name,
            vip_level=vip_level,
            score=score,
            known=True,
        )

    def unknown_face(self, event: Event, state: RobotState, can_greet: bool) -> PolicyOutcome:
        if not can_greet:
            return PolicyOutcome(trace_id=event.trace_id, notes="greet_blocked")

        score = event.payload.get("score", 0.0)
        vip_level = event.payload.get("vip_level", "first_visit")
        return self._greet_with_guards(
            event=event,
            identity=UNKNOWN_IDENTITY,
            name=None,
            vip_level=vip_level,
            score=score,
            known=False,
        )

    def _greet_with_guards(
        self,
        *,
        event: Event,
        identity: str,
        name: Optional[str],
        vip_level: str,
        score: float,
        known: bool,
    ) -> PolicyOutcome:
        self._guard.observe(event, identity)
        guard = self._guard.evaluate(identity, event)
        if not guard.ready:
            return PolicyOutcome(trace_id=event.trace_id, notes="guard_pending")

        if known and DAILY_SILENT_REPEAT and self._daily.has_welcomed_today(identity):
            logger.info("[GreetingPolicy] SILENT nod %s — welcomed today", identity)
            return self._nod_only(event, notes="silent_repeat_nod")

        level_resolver: Callable[[str], str] = (
            (lambda i: self._guard.vip_level_of(i, self._repo.get_vip_level(i)))
            if known
            else (lambda i: self._guard.vip_level_of(i, "first_visit"))
        )
        speech = self._throttle.evaluate(
            identity=identity,
            group_mode=guard.group_mode,
            group_size=guard.group_size,
            identities_in_window=self._guard.identities_in_window(),
            vip_level_of=level_resolver,
            now=SystemClock.now(),
        )

        if not speech.allow_speech:
            logger.info("[GreetingPolicy] speech blocked: %s", speech.reason)
            if speech.allow_nod:
                return self._nod_only(event, notes=f"speech_blocked:{speech.reason}")
            return PolicyOutcome(trace_id=event.trace_id, notes=f"speech_blocked:{speech.reason}")

        if guard.group_mode:
            return self._group_welcome(event, guard.group_size, identity)

        welcome_text = (
            self._welcome.resolve(name=name, level=vip_level)
            if name
            else self._welcome.resolve(is_stranger=True)
        )
        if known and DAILY_SILENT_REPEAT:
            self._daily.mark_welcomed_today(identity)
        self._throttle.record_tts(identity=identity, group=False)

        label = "KNOWN" if known else "UNKNOWN"
        logger.info(
            "[GreetingPolicy] %s %s score=%.3f level=%s",
            label,
            name or identity,
            score,
            vip_level,
        )

        return PolicyOutcome(
            trace_id=event.trace_id,
            commands=[
                *self._gesture_commands(vip_level),
                PolicyCommand(CommandType.TTS, {"text": welcome_text, "lang": "zh-CN"}),
            ],
            fsm_events=["greeting_complete"],
            notes="known_face_pipeline" if known else "unknown_face_pipeline",
        )

    def _group_welcome(self, event: Event, group_size: int, identity: str) -> PolicyOutcome:
        text = self._welcome.group_welcome()
        self._throttle.record_tts(identity=identity, group=True)
        logger.info("[GreetingPolicy] GROUP policy size=%d — unified welcome, no names", group_size)
        return PolicyOutcome(
            trace_id=event.trace_id,
            commands=[
                *self._gesture_commands("group", group=True),
                PolicyCommand(CommandType.TTS, {"text": text, "lang": "zh-CN"}),
            ],
            fsm_events=["greeting_complete"],
            notes="group_policy",
        )

    def _gesture_commands(self, vip_level: str, *, group: bool = False) -> List[PolicyCommand]:
        if group:
            angle = _GROUP_TURN_ANGLE
            actions = ["turn_head", "wave"]
        else:
            strategy = self._welcome.get_strategy(vip_level)
            gesture = strategy.get("gesture", {}) if strategy else {}
            angle = float(gesture.get("turn_head_angle", _DEFAULT_TURN_ANGLE))
            actions = list(gesture.get("actions", ["turn_head", "wave"]))

        commands: List[PolicyCommand] = []
        for action in actions:
            if action == "turn_head":
                commands.append(
                    PolicyCommand(CommandType.ACTION, {"gesture": "turn_head", "angle": angle})
                )
            elif action == "wave":
                commands.append(PolicyCommand(CommandType.ACTION, {"gesture": "wave"}))
        if not commands:
            commands.append(
                PolicyCommand(CommandType.ACTION, {"gesture": "turn_head", "angle": _DEFAULT_TURN_ANGLE})
            )
        return commands

    def _nod_only(self, event: Event, notes: str) -> PolicyOutcome:
        return PolicyOutcome(
            trace_id=event.trace_id,
            commands=[
                PolicyCommand(
                    CommandType.ACTION,
                    {"gesture": "turn_head", "angle": _SILENT_NOD_ANGLE},
                ),
            ],
            fsm_events=["greeting_complete"],
            notes=notes,
        )

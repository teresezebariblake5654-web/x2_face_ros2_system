"""Greeting business policy — known / unknown face handling."""

from __future__ import annotations

from core.policy_types import CommandType, PolicyCommand, PolicyOutcome
from core.types import Event, RobotState
from utils.logger import get_logger

logger = get_logger(__name__)


class GreetingPolicy:
    """Decides greeting commands for face events."""

    def known_face(self, event: Event, state: RobotState, can_greet: bool) -> PolicyOutcome:
        if not can_greet:
            logger.info("[GreetingPolicy] blocked state=%s", state.value)
            return PolicyOutcome(trace_id=event.trace_id, notes="greet_blocked")

        person_id = event.payload.get("person_id", "unknown")
        name = event.payload.get("name", person_id)
        score = event.payload.get("score", 0.0)
        logger.info("[GreetingPolicy] KNOWN %s (%s) score=%.3f", name, person_id, score)

        return PolicyOutcome(
            trace_id=event.trace_id,
            commands=[
                PolicyCommand(CommandType.ACTION, {"gesture": "turn_head", "angle": 25}),
                PolicyCommand(CommandType.ACTION, {"gesture": "wave"}),
                PolicyCommand(CommandType.TTS, {"text": f"您好，{name}！欢迎回来！", "lang": "zh-CN"}),
                PolicyCommand(
                    CommandType.LLM_REQUEST,
                    {
                        "text": f"用户 {name} 到来，请生成简短问候",
                        "context": {"intent": "greet", "name": name, "known": True},
                    },
                ),
            ],
            fsm_events=["greeting_complete"],
            notes="known_face_pipeline",
        )

    def unknown_face(self, event: Event, state: RobotState, can_greet: bool) -> PolicyOutcome:
        if not can_greet:
            return PolicyOutcome(trace_id=event.trace_id, notes="greet_blocked")

        score = event.payload.get("score", 0.0)
        logger.info("[GreetingPolicy] UNKNOWN best_score=%.3f", score)

        return PolicyOutcome(
            trace_id=event.trace_id,
            commands=[
                PolicyCommand(CommandType.ACTION, {"gesture": "turn_head", "angle": 15}),
                PolicyCommand(CommandType.ACTION, {"gesture": "question_mark"}),
                PolicyCommand(CommandType.TTS, {"text": "您好，我还不太认识您。", "lang": "zh-CN"}),
                PolicyCommand(
                    CommandType.LLM_REQUEST,
                    {
                        "text": "检测到未知访客，请生成友好提示",
                        "context": {"intent": "unknown", "known": False},
                    },
                ),
            ],
            fsm_events=["greeting_complete"],
            notes="unknown_face_pipeline",
        )

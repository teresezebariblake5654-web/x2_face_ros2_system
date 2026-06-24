"""Dialog business policy — LLM response handling (text/TTS only)."""

from __future__ import annotations

from core.policy_types import CommandType, PolicyCommand, PolicyOutcome
from core.types import Event, RobotState
from utils.logger import get_logger

logger = get_logger(__name__)


class DialogPolicy:
    """Pure dialog policy — never emits action or nav commands from LLM."""

    def llm_response(self, event: Event, state: RobotState, can_dialog: bool) -> PolicyOutcome:
        text = event.payload.get("text", event.payload.get("reply", ""))
        intent = event.payload.get("intent", "unknown")
        confidence = event.payload.get("confidence", 0.0)

        logger.info(
            "[DialogPolicy] LLM intent=%s conf=%.2f text=%s",
            intent,
            confidence,
            text[:60],
        )

        if state == RobotState.NAVIGATION:
            return PolicyOutcome(trace_id=event.trace_id, notes="suppressed_during_nav")

        if state == RobotState.ERROR:
            return PolicyOutcome(trace_id=event.trace_id, notes="suppressed_during_error")

        commands = [PolicyCommand(CommandType.TTS, {"text": text, "lang": "zh-CN"})]

        # Only add point gesture for active dialog, not cooldown TTS-only
        if state in (RobotState.IDLE, RobotState.GREETING, RobotState.DIALOG):
            if intent in ("smalltalk", "question"):
                commands.append(
                    PolicyCommand(CommandType.ACTION, {"gesture": "point", "target": "visitor"})
                )

        return PolicyOutcome(trace_id=event.trace_id, commands=commands, notes="dialog_tts")

    def should_open_dialog(self, state: RobotState, trigger: str) -> bool:
        if state in (RobotState.NAVIGATION, RobotState.ERROR):
            return False
        return trigger in ("greeting_followup", "user_question", "unknown_prompt")

    def build_greet_prompt(self, name: str, known: bool) -> tuple[str, dict]:
        if known:
            return (
                f"用户 {name} 到来，请生成简短问候",
                {"intent": "greet", "name": name, "known": True},
            )
        return (
            "检测到未知访客，请生成友好提示",
            {"intent": "unknown", "known": False},
        )

"""Navigation business policy."""

from __future__ import annotations

from core.policy_types import CommandType, PolicyCommand, PolicyOutcome
from core.types import Event, NavResult, RobotState
from utils.logger import get_logger

logger = get_logger(__name__)


class NavPolicy:
    """Decides navigation commands and lifecycle responses."""

    def request(self, event: Event, state: RobotState, can_navigate: bool) -> PolicyOutcome:
        action = event.payload.get("action", "go_to")
        location = event.payload.get("location", "lobby")

        if not can_navigate:
            logger.info("[NavPolicy] defer NAV (state=%s)", state.value)
            return PolicyOutcome(
                trace_id=event.trace_id,
                notes="nav_deferred",
                commands=[
                    PolicyCommand(
                        CommandType.LOG,
                        {"message": f"nav_deferred:{action}->{location}"},
                    )
                ],
            )

        logger.info("[NavPolicy] authorize NAV %s -> %s", action, location)
        return PolicyOutcome(
            trace_id=event.trace_id,
            commands=[
                PolicyCommand(
                    CommandType.NAV_EXECUTE,
                    {"action": action, "location": location},
                ),
            ],
            notes="nav_authorized",
        )

    def lifecycle(self, event: Event, state: RobotState) -> PolicyOutcome:
        et = event.type.value
        if et == "NAV_STARTED":
            loc = event.payload.get("location", "")
            return PolicyOutcome(
                trace_id=event.trace_id,
                commands=[PolicyCommand(CommandType.LOG, {"message": f"nav_started:{loc}"})],
            )

        if et == "NAV_COMPLETED":
            result = event.payload.get("result", NavResult.SUCCESS.value)
            loc = event.payload.get("location", "")
            cmds = [PolicyCommand(CommandType.LOG, {"message": f"nav_done:{result}"})]
            if result == NavResult.SUCCESS.value:
                cmds.append(PolicyCommand(CommandType.TTS, {"text": f"已到达{loc}", "lang": "zh-CN"}))
            return PolicyOutcome(trace_id=event.trace_id, commands=cmds)

        if et == "NAV_FAILED":
            reason = event.payload.get("reason", "unknown")
            result = event.payload.get("result", NavResult.FAILED.value)
            return PolicyOutcome(
                trace_id=event.trace_id,
                commands=[
                    PolicyCommand(CommandType.TTS, {"text": "导航失败，请稍后重试。", "lang": "zh-CN"}),
                    PolicyCommand(CommandType.LOG, {"message": f"nav_failed:{result}:{reason}"}),
                ],
            )

        return PolicyOutcome(trace_id=event.trace_id)

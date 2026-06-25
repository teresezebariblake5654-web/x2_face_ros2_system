"""Unified robot SDK interface — Mock implementation for 灵犀 X2 integration."""

from __future__ import annotations

from utils.logger import get_logger

logger = get_logger(__name__)


class RobotSDKAdapter:
    """
    Single entry point for robot hardware actions.
    Replace method bodies with 灵犀 X2 SDK calls during deployment.
    """

    def wave(self) -> None:
        logger.info("[SDK] wave()")

    def turn_head(self, angle: float = 30.0) -> None:
        logger.info("[SDK] turn_head(%.1f°)", angle)

    def point(self, target: str = "forward") -> None:
        logger.info("[SDK] point(%s)", target)

    def navigate_to(self, location: str) -> bool:
        logger.info("[SDK] navigate_to(%s)", location)
        return True

    def speak(self, text: str, lang: str = "zh-CN") -> None:
        logger.info("[SDK] speak(%s): %s", lang, text)

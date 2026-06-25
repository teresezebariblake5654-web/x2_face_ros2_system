"""ROS2 Humble adapter layer — stub for future topic/action integration."""

from __future__ import annotations

from typing import Any, Callable, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


class Ros2Adapter:
    """
    Thin ROS2 bridge placeholder.
    Wire to rclpy Node publish/subscribe/action clients in deployment.
    """

    def publish(self, topic: str, message: Any) -> None:
        logger.debug("[ROS2] publish(%s) — stub", topic)

    def subscribe(self, topic: str, callback: Callable[[Any], None]) -> None:
        logger.debug("[ROS2] subscribe(%s) — stub", topic)

    def call_action(self, action_name: str, goal: Optional[dict] = None) -> None:
        logger.debug("[ROS2] call_action(%s) — stub", action_name)

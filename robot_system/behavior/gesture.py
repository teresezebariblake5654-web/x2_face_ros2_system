"""Gesture type definitions and metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from core.types import GestureType


@dataclass(frozen=True)
class GestureSpec:
    name: str
    duration_sec: float
    description: str


GESTURE_CATALOG: Dict[GestureType, GestureSpec] = {
    GestureType.WAVE: GestureSpec("wave", 2.0, "Friendly hand wave greeting"),
    GestureType.TURN_HEAD: GestureSpec("turn_head", 1.5, "Turn head toward person"),
    GestureType.QUESTION_MARK: GestureSpec("question_mark", 2.0, "Confused/question pose"),
    GestureType.POINT: GestureSpec("point", 1.5, "Point toward direction or object"),
}


def describe(gesture: GestureType) -> str:
    spec = GESTURE_CATALOG.get(gesture)
    return spec.description if spec else gesture.value

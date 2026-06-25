"""Face data access layer — Brain must not touch FaceDB directly."""

from face_core.capacity_manager import (
    CapacityFullError,
    CapacityManager,
    CapacityStats,
    is_permanent_level,
    is_permanent_record,
)
from face_core.repository import FaceRepository

__all__ = [
    "CapacityFullError",
    "CapacityManager",
    "CapacityStats",
    "FaceRepository",
    "is_permanent_level",
    "is_permanent_record",
]

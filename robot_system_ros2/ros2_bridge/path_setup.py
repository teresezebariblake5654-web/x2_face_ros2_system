"""Ensure robot_system package is importable without modifying its layout."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _share_robot_system_paths() -> list[Path]:
    paths: list[Path] = []
    prefix = os.environ.get("AMENT_PREFIX_PATH", "")
    for part in prefix.split(os.pathsep):
        if not part:
            continue
        paths.append(Path(part) / "share" / "robot_system_ros2" / "robot_system")
    colcon_prefix = os.environ.get("COLCON_PREFIX_PATH", "")
    for part in colcon_prefix.split(os.pathsep):
        if not part:
            continue
        paths.append(Path(part) / "robot_system" / "share" / "robot_system_ros2" / "robot_system")
    return paths


def ensure_robot_system_path() -> Path:
    """Add robot_system root to sys.path (dev + colcon install layouts)."""
    here = Path(__file__).resolve()
    candidates = [
        here.parents[1] / "robot_system",
        here.parents[2] / "robot_system",
        * _share_robot_system_paths(),
        Path(os.environ.get("ROBOT_SYSTEM_PATH", "")),
    ]
    for path in candidates:
        if path.is_dir() and (path / "core").is_dir():
            root = str(path.resolve())
            if root not in sys.path:
                sys.path.insert(0, root)
            return path
    raise ImportError(
        "robot_system not found. Build/install robot_system_ros2 or set ROBOT_SYSTEM_PATH."
    )

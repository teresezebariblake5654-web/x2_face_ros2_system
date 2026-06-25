"""Recognition guard — debounce, identity confirm, zone dwell, group sensing."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

from config import (
    GROUP_DETECTION_WINDOW_SEC,
    GROUP_GREETING_THRESHOLD,
    IDENTITY_CONFIRM_COUNT,
    RECOGNITION_DEBOUNCE_SEC,
    WELCOME_ZONE_DWELL_SEC,
)
from core.system_clock import SystemClock
from core.types import Event
from utils.logger import get_logger

logger = get_logger(__name__)

UNKNOWN_IDENTITY = "unknown"


@dataclass(frozen=True)
class GuardVerdict:
    """Result of recognition guard evaluation."""

    ready: bool
    reason: str
    identity: str
    group_size: int
    group_mode: bool
    debounce_ok: bool
    confirm_ok: bool
    zone_ok: bool


class RecognitionGuard:
    """
    售楼级识别保护：
      1. 同一身份连续 ≥ debounce 秒
      2. 最近 N 次识别结果一致
      3. 欢迎区域内停留 ≥ zone_dwell 秒
      4. 统计窗口内人数（群体模式）
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._history: Deque[str] = deque(maxlen=IDENTITY_CONFIRM_COUNT)
        self._identity_since: Dict[str, float] = {}
        self._zone_since: Dict[str, float] = {}
        self._vip_levels: Dict[str, str] = {}
        self._observations: Deque[Tuple[float, str, int]] = deque()

    def observe(self, event: Event, identity: str) -> None:
        now = SystemClock.now()
        in_zone = bool(event.payload.get("in_welcome_zone", True))
        person_count = int(event.payload.get("person_count", 1))
        vip_level = event.payload.get("vip_level")

        with self._lock:
            self._history.append(identity)
            self._observations.append((now, identity, person_count))
            self._prune_observations(now)
            if vip_level:
                self._vip_levels[identity] = str(vip_level)

            if in_zone:
                self._identity_since.setdefault(identity, now)
                self._zone_since.setdefault(identity, now)
            else:
                self._identity_since.pop(identity, None)
                self._zone_since.pop(identity, None)
                self._vip_levels.pop(identity, None)

    def evaluate(self, identity: str, event: Event) -> GuardVerdict:
        now = SystemClock.now()

        with self._lock:
            self._prune_observations(now)
            group_size = self._estimate_group_size(now)
            group_mode = group_size >= GROUP_GREETING_THRESHOLD

            debounce_ok = False
            started = self._identity_since.get(identity)
            if started is not None:
                debounce_ok = (now - started) >= RECOGNITION_DEBOUNCE_SEC

            confirm_ok = (
                len(self._history) >= IDENTITY_CONFIRM_COUNT
                and len(set(self._history)) == 1
                and self._history[-1] == identity
            )

            zone_ok = False
            zone_started = self._zone_since.get(identity)
            if zone_started is not None:
                zone_ok = (now - zone_started) >= WELCOME_ZONE_DWELL_SEC

            ready = debounce_ok and confirm_ok and zone_ok
            reason = "ok"
            if not debounce_ok:
                reason = "debounce_pending"
            elif not confirm_ok:
                reason = "identity_unconfirmed"
            elif not zone_ok:
                reason = "zone_dwell_pending"

            if ready:
                logger.info(
                    "[RecognitionGuard] READY identity=%s group=%d mode=%s",
                    identity,
                    group_size,
                    group_mode,
                )
            else:
                logger.debug(
                    "[RecognitionGuard] HOLD %s identity=%s debounce=%s confirm=%s zone=%s",
                    reason,
                    identity,
                    debounce_ok,
                    confirm_ok,
                    zone_ok,
                )

            return GuardVerdict(
                ready=ready,
                reason=reason,
                identity=identity,
                group_size=group_size,
                group_mode=group_mode,
                debounce_ok=debounce_ok,
                confirm_ok=confirm_ok,
                zone_ok=zone_ok,
            )

    def identities_in_window(self) -> List[str]:
        with self._lock:
            now = SystemClock.now()
            self._prune_observations(now)
            return list({ident for _, ident, _ in self._observations})

    def vip_level_of(self, identity: str, fallback: str = "regular_customer") -> str:
        with self._lock:
            return self._vip_levels.get(identity, fallback)

    def _prune_observations(self, now: float) -> None:
        cutoff = now - GROUP_DETECTION_WINDOW_SEC
        while self._observations and self._observations[0][0] < cutoff:
            self._observations.popleft()

    def _estimate_group_size(self, now: float) -> int:
        if not self._observations:
            return 1
        max_reported = max(count for _, _, count in self._observations)
        distinct = len({ident for _, ident, _ in self._observations})
        return max(max_reported, distinct)

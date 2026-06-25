"""Speech throttle — person/global cooldown, sales protection, VIP priority, group policy."""

from __future__ import annotations

import random
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional

from config import (
    GLOBAL_GREETING_INTERVAL,
    GROUP_GREETING_THRESHOLD,
    PERSON_GREETING_COOLDOWN,
    SALES_ENGAGED,
)
from core.system_clock import SystemClock
from policy.recognition_guard import UNKNOWN_IDENTITY
from policy.welcome_policy import LEVEL_PRIORITY
from utils.logger import get_logger

logger = get_logger(__name__)

GROUP_WELCOMES: List[str] = [
    "欢迎各位光临。请先在前台登记，我们为您安排参观。",
    "欢迎各位莅临销售中心。这边请，我先为您介绍整体安排。",
    "欢迎各位，今天现场开放沙盘和样板区，请随我至接待区。",
    "欢迎各位到来。当前参观人数较多，请先在前台稍作登记。",
    "欢迎各位。今天的参观路线我已为您准备好，请这边走。",
]


@dataclass(frozen=True)
class SpeechVerdict:
    allow_speech: bool
    allow_nod: bool
    reason: str
    primary_identity: Optional[str] = None


class SpeechThrottle:
    """
    售楼级播报保护：
      - 单人 30 分钟内只欢迎一次（TTS）
      - 全局两次 TTS 间隔 ≥ 20 秒
      - sales_engaged 时禁止主动播报
      - VIP 身份优先于普通客户
      - ≥3 人群体统一欢迎，不连续报姓名
    """

    def __init__(self, sales_engaged: Optional[bool] = None) -> None:
        self._lock = threading.Lock()
        self._sales_engaged = SALES_ENGAGED if sales_engaged is None else sales_engaged
        self._last_global_tts = 0.0
        self._person_last_tts: dict[str, float] = {}
        self._last_group_tts = 0.0

    @property
    def sales_engaged(self) -> bool:
        with self._lock:
            return self._sales_engaged

    def set_sales_engaged(self, engaged: bool) -> None:
        with self._lock:
            self._sales_engaged = engaged
            logger.info("[SpeechThrottle] sales_engaged=%s", engaged)

    def group_welcome(self) -> str:
        return random.choice(GROUP_WELCOMES)

    def evaluate(
        self,
        *,
        identity: str,
        group_mode: bool,
        group_size: int,
        identities_in_window: List[str],
        vip_level_of: Callable[[str], str],
        now: Optional[float] = None,
    ) -> SpeechVerdict:
        now = now or SystemClock.now()

        with self._lock:
            if self._sales_engaged:
                return SpeechVerdict(False, True, "sales_engaged")

            if group_mode and group_size >= GROUP_GREETING_THRESHOLD:
                if (now - self._last_global_tts) < GLOBAL_GREETING_INTERVAL:
                    return SpeechVerdict(False, True, "global_throttle")
                if (now - self._last_group_tts) < GLOBAL_GREETING_INTERVAL:
                    return SpeechVerdict(False, True, "group_throttle")
                return SpeechVerdict(True, True, "group_policy")

            primary = self._select_primary_identity(identities_in_window, vip_level_of)
            if primary and identity != primary:
                return SpeechVerdict(False, True, "vip_priority_wait")

            if (now - self._last_global_tts) < GLOBAL_GREETING_INTERVAL:
                return SpeechVerdict(False, True, "global_throttle")

            if identity != UNKNOWN_IDENTITY:
                last = self._person_last_tts.get(identity)
                if last is not None and (now - last) < PERSON_GREETING_COOLDOWN:
                    return SpeechVerdict(False, True, "person_cooldown")

            return SpeechVerdict(True, True, "ok", primary_identity=primary or identity)

    def record_tts(self, *, identity: Optional[str], group: bool = False, now: Optional[float] = None) -> None:
        now = now or SystemClock.now()
        with self._lock:
            self._last_global_tts = now
            if group:
                self._last_group_tts = now
            elif identity and identity != UNKNOWN_IDENTITY:
                self._person_last_tts[identity] = now

    @staticmethod
    def _select_primary_identity(
        identities: List[str],
        vip_level_of: Callable[[str], str],
    ) -> Optional[str]:
        if not identities:
            return None
        if len(identities) == 1:
            return identities[0]

        def rank(ident: str) -> int:
            if ident == UNKNOWN_IDENTITY:
                return len(LEVEL_PRIORITY) + 10
            level = vip_level_of(ident)
            try:
                return LEVEL_PRIORITY.index(level)
            except ValueError:
                return len(LEVEL_PRIORITY)

        return min(identities, key=rank)


from policy.recognition_guard import UNKNOWN_IDENTITY

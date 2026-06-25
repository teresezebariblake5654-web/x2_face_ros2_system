"""Welcome message policy — VIP level based greetings loaded from vip_level.yaml."""

from __future__ import annotations

import random
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_YAML = Path(__file__).with_name("vip_level.yaml")

# 等级优先级（高 → 低）
LEVEL_PRIORITY: List[str] = [
    "executive",
    "director",
    "sales_director",
    "consultant",
    "vip_customer",
    "regular_customer",
    "first_visit",
]

# 兼容旧接口：is_vip=True 映射等级
VIP_FLAG_LEVEL = "vip_customer"


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError:
        logger.warning("PyYAML not installed; using built-in fallback levels")
        return {}
    if not path.exists():
        logger.warning("VIP level config not found: %s", path)
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


class WelcomePolicy:
    """Generates welcome TTS text by vip_level; Brain must not assemble strings."""

    _RECENT_SIZE = 5

    def __init__(self, config_path: Path | str | None = None) -> None:
        self._config_path = Path(config_path) if config_path else _DEFAULT_YAML
        self._config = _load_yaml(self._config_path)
        self._levels: Dict[str, Dict[str, Any]] = self._config.get("vip_level", {})
        self._defaults: Dict[str, str] = self._config.get("defaults", {})
        self._recent: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self._RECENT_SIZE)
        )
        if self._levels:
            logger.info(
                "[WelcomePolicy] loaded %d vip levels from %s",
                len(self._levels),
                self._config_path.name,
            )

    def get_strategy(self, level: str) -> Dict[str, Any]:
        """Return strategy block for a vip level."""
        entry = self._levels.get(level, {})
        return dict(entry.get("strategy", {}))

    def get_label(self, level: str) -> str:
        entry = self._levels.get(level, {})
        return str(entry.get("label", level))

    def list_levels(self) -> List[str]:
        return [k for k in LEVEL_PRIORITY if k in self._levels]

    def _resolve_level(
        self,
        *,
        level: Optional[str] = None,
        is_vip: bool = False,
        is_stranger: bool = False,
        is_first_visit: bool = False,
    ) -> str:
        if level and level in self._levels:
            return level
        if is_stranger:
            return self._defaults.get("unknown_face_level", "first_visit")
        if is_first_visit:
            return "first_visit"
        if is_vip:
            return VIP_FLAG_LEVEL
        return self._defaults.get("fallback_level", "regular_customer")

    def _pick(self, level: str, *, name: str | None = None) -> str:
        entry = self._levels.get(level)
        if not entry:
            text = f"{name}，欢迎光临。" if name else "欢迎光临。"
            logger.warning("[WelcomePolicy] unknown level=%s, using fallback", level)
            return text

        pool: List[str] = list(entry.get("welcomes", []))
        if not pool:
            return f"{name}，欢迎光临。" if name else "欢迎光临。"

        recent = self._recent[level]
        candidates = [t for t in pool if t not in recent] or pool
        template = random.choice(candidates)

        if "{name}" in template:
            if name:
                text = template.format(name=name)
            else:
                text = template.replace("{name}，", "").replace("{name},", "").strip()
        else:
            text = template

        recent.append(template)
        logger.info("[WelcomePolicy] level=%s label=%s", level, entry.get("label", level))
        return text

    def welcome_by_level(self, level: str, name: str | None = None) -> str:
        return self._pick(level, name=name)

    def vip_welcome(self, name: str) -> str:
        return self.welcome_by_level(VIP_FLAG_LEVEL, name=name)

    def normal_welcome(self, name: str) -> str:
        return self.welcome_by_level("regular_customer", name=name)

    def first_visit_welcome(self, name: str | None = None) -> str:
        return self.welcome_by_level("first_visit", name=name)

    def stranger_welcome(self) -> str:
        level = self._defaults.get("unknown_face_level", "first_visit")
        return self._pick(level)

    def group_welcome(self) -> str:
        return self._pick("group")

    def tour_invitation(self) -> str:
        tours = [
            "沙盘区已就绪，我带您过去，从整体规划开始看起。",
            "样板区今天开放，建议实地感受一下层高和采光。",
            "您关注的户型在实景样板里有还原，我们现在过去？",
            "这边请。先从品牌墙开始，再过渡到沙盘，动线会更清晰。",
            "景观示范段值得亲自走一趟，我们现在过去看看？",
        ]
        return random.choice(tours)

    def closing_remark(self) -> str:
        closings = [
            "今天先到这里。资料您带上，回去慢慢看，有疑问随时联系案场。",
            "感谢您的到访。案场随时欢迎您再来。",
            "辛苦您了。今天的几个要点都在册子里，回去对比会方便些。",
        ]
        return random.choice(closings)

    def resolve(
        self,
        *,
        name: str | None = None,
        level: Optional[str] = None,
        is_vip: bool = False,
        is_stranger: bool = False,
        is_first_visit: bool = False,
    ) -> str:
        resolved = self._resolve_level(
            level=level,
            is_vip=is_vip,
            is_stranger=is_stranger,
            is_first_visit=is_first_visit,
        )
        if is_stranger and not name:
            return self._pick(resolved)
        return self._pick(resolved, name=name)

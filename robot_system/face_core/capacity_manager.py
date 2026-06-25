"""Face database capacity management — 灵犀 X2 SDK hard limit 1000 identities."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Sequence

from config import (
    FACE_DB_MAX_CAPACITY,
    FACE_CAPACITY_EMERGENCY_THRESHOLD,
    FACE_CAPACITY_WARNING_THRESHOLD,
    VISITOR_EXPIRE_DAYS,
)
from core.system_clock import SystemClock
from core.types import Event, EventType, FaceRecord, Priority
from utils.logger import get_logger

if TYPE_CHECKING:
    from face_core.repository import FaceRepository

logger = get_logger(__name__)

# 永久人员 — 禁止删除
LEADER_LEVELS = frozenset({"executive", "director"})
EMPLOYEE_LEVELS = frozenset({"sales_director"})
CONSULTANT_LEVELS = frozenset({"consultant"})
VIP_CUSTOMER_LEVELS = frozenset({"vip_customer"})
PERMANENT_LEVELS = (
    LEADER_LEVELS | EMPLOYEE_LEVELS | CONSULTANT_LEVELS | VIP_CUSTOMER_LEVELS
)
VISITOR_LEVELS = frozenset({"regular_customer", "first_visit"})

SECONDS_PER_DAY = 86400


class CapacityFullError(RuntimeError):
    """Raised when the face database cannot accept a new enrollment."""


@dataclass(frozen=True)
class CapacityStats:
    """Face library population breakdown."""

    total: int
    vip: int
    employee: int
    leader: int
    consultant: int
    visitor: int
    max_capacity: int = FACE_DB_MAX_CAPACITY

    @property
    def permanent(self) -> int:
        return self.total - self.visitor

    @property
    def temporary(self) -> int:
        return self.visitor

    @property
    def remaining(self) -> int:
        return max(0, self.max_capacity - self.total)

    @property
    def is_warning(self) -> bool:
        return self.total >= FACE_CAPACITY_WARNING_THRESHOLD

    @property
    def is_emergency(self) -> bool:
        return self.total >= FACE_CAPACITY_EMERGENCY_THRESHOLD

    @property
    def is_full(self) -> bool:
        return self.total >= self.max_capacity


@dataclass
class MaintenanceResult:
    stats: CapacityStats
    warning_logged: bool = False
    emergency_triggered: bool = False
    expired_removed: List[str] = field(default_factory=list)
    lru_removed: List[str] = field(default_factory=list)

    @property
    def total_removed(self) -> int:
        return len(self.expired_removed) + len(self.lru_removed)


def classify_vip_level(vip_level: str) -> str:
    if vip_level in LEADER_LEVELS:
        return "leader"
    if vip_level in EMPLOYEE_LEVELS:
        return "employee"
    if vip_level in CONSULTANT_LEVELS:
        return "consultant"
    if vip_level in VIP_CUSTOMER_LEVELS:
        return "vip"
    return "visitor"


def is_permanent_level(vip_level: str) -> bool:
    return vip_level in PERMANENT_LEVELS


def is_permanent_record(record: FaceRecord) -> bool:
    return is_permanent_level(record.vip_level) or bool(record.is_vip and record.vip_level not in VISITOR_LEVELS)


class CapacityManager:
    """
    Keeps face DB below SDK limit (1000).

    - Warning at 850+
    - Emergency auto-cleanup at 950+
    - Expire visitors unseen for VISITOR_EXPIRE_DAYS
    - LRU evict visitors when space needed; never delete permanent staff/VIP
    """

    def __init__(
        self,
        repository: "FaceRepository",
        *,
        max_capacity: int = FACE_DB_MAX_CAPACITY,
        warning_threshold: int = FACE_CAPACITY_WARNING_THRESHOLD,
        emergency_threshold: int = FACE_CAPACITY_EMERGENCY_THRESHOLD,
        visitor_expire_days: int = VISITOR_EXPIRE_DAYS,
    ) -> None:
        self._repo = repository
        self._max_capacity = max_capacity
        self._warning_threshold = warning_threshold
        self._emergency_threshold = emergency_threshold
        self._visitor_expire_sec = visitor_expire_days * SECONDS_PER_DAY
        self._lock = threading.Lock()
        self._last_warning_logged = False
        self._last_emergency_logged = False

    def collect_stats(self) -> CapacityStats:
        records = self._repo.list_records()
        vip = employee = leader = consultant = visitor = 0
        for rec in records:
            cat = classify_vip_level(rec.vip_level)
            if cat == "vip":
                vip += 1
            elif cat == "employee":
                employee += 1
            elif cat == "leader":
                leader += 1
            elif cat == "consultant":
                consultant += 1
            else:
                visitor += 1
        return CapacityStats(
            total=len(records),
            vip=vip,
            employee=employee,
            leader=leader,
            consultant=consultant,
            visitor=visitor,
            max_capacity=self._max_capacity,
        )

    def build_capacity_report(self) -> dict:
        stats = self.collect_stats()
        return {
            "report_type": "FACE_CAPACITY_REPORT",
            "total": stats.total,
            "permanent": stats.permanent,
            "temporary": stats.temporary,
            "remaining": stats.remaining,
            "max_capacity": stats.max_capacity,
            "vip": stats.vip,
            "employee": stats.employee,
            "leader": stats.leader,
            "consultant": stats.consultant,
            "visitor": stats.visitor,
            "warning": stats.is_warning,
            "emergency": stats.is_emergency,
            "full": stats.is_full,
        }

    def build_capacity_event(self, source: str = "capacity_manager") -> Event:
        return Event(
            type=EventType.FACE_CAPACITY_REPORT,
            source=source,
            priority=Priority.NORMAL,
            payload=self.build_capacity_report(),
        )

    def run_maintenance(self, now: Optional[float] = None) -> MaintenanceResult:
        """Check thresholds, expire stale visitors, emergency LRU if needed."""
        with self._lock:
            return self._run_maintenance_unlocked(now)

    def _run_maintenance_unlocked(self, now: Optional[float] = None) -> MaintenanceResult:
        now = now if now is not None else self._reference_now()
        stats = self.collect_stats()
        result = MaintenanceResult(stats=stats)

        if stats.total >= self._warning_threshold:
            if not self._last_warning_logged:
                logger.warning(
                    "[Capacity] WARNING: face DB %d/%d (>= %d) — VIP enrollment at risk",
                    stats.total,
                    self._max_capacity,
                    self._warning_threshold,
                )
                self._last_warning_logged = True
            result.warning_logged = True
        else:
            self._last_warning_logged = False

        expired = self._purge_expired_visitors(now)
        result.expired_removed = expired
        stats = self.collect_stats()
        result.stats = stats

        if stats.total >= self._emergency_threshold:
            if not self._last_emergency_logged:
                logger.error(
                    "[Capacity] EMERGENCY: face DB %d/%d (>= %d) — auto cleanup started",
                    stats.total,
                    self._max_capacity,
                    self._emergency_threshold,
                )
                self._last_emergency_logged = True
            result.emergency_triggered = True
            target = self._emergency_threshold - 1
            need = max(0, stats.total - target)
            if need:
                lru = self._lru_evict_visitors(need, now)
                result.lru_removed.extend(lru)
                stats = self.collect_stats()
                result.stats = stats

        logger.info(
            "[Capacity] FACE_CAPACITY_REPORT total=%d permanent=%d temporary=%d remaining=%d",
            stats.total,
            stats.permanent,
            stats.temporary,
            stats.remaining,
        )
        return result

    def ensure_capacity_for_add(
        self,
        *,
        vip_level: str = "regular_customer",
        slots: int = 1,
        now: Optional[float] = None,
    ) -> MaintenanceResult:
        """
        Make room before enrollment. Expires stale visitors then LRU if needed.
        Raises CapacityFullError if permanent entries block all slots.
        """
        with self._lock:
            now = now if now is not None else self._reference_now()
            stats = self.collect_stats()
            if stats.total + slots <= self._max_capacity:
                return MaintenanceResult(stats=stats)

            result = MaintenanceResult(stats=stats)
            expired = self._purge_expired_visitors(now)
            result.expired_removed = expired
            stats = self.collect_stats()
            result.stats = stats

            if stats.total + slots <= self._max_capacity:
                return result

            need = stats.total + slots - self._max_capacity
            lru = self._lru_evict_visitors(need, now)
            result.lru_removed = lru
            stats = self.collect_stats()
            result.stats = stats

            if stats.total + slots > self._max_capacity:
                if is_permanent_level(vip_level):
                    raise CapacityFullError(
                        f"Cannot enroll permanent ({vip_level}): "
                        f"DB {stats.total}/{self._max_capacity}, no evictable visitors"
                    )
                raise CapacityFullError(
                    f"Face DB full ({stats.total}/{self._max_capacity}), "
                    f"cannot add visitor"
                )
            return result

    def safe_delete(self, person_id: str) -> bool:
        """Delete only non-permanent records."""
        return self._repo.delete_person(person_id, force=False)

    def _purge_expired_visitors(self, now: float) -> List[str]:
        removed: List[str] = []
        for rec in self._repo.list_records():
            if is_permanent_record(rec):
                continue
            last = rec.last_seen if rec.last_seen > 0 else rec.created_at
            if now - last >= self._visitor_expire_sec:
                if self._repo.delete_person(rec.person_id):
                    removed.append(rec.person_id)
                    logger.info(
                        "[Capacity] Expired visitor %s (unseen %.0f days)",
                        rec.person_id,
                        (now - last) / SECONDS_PER_DAY,
                    )
        return removed

    def _lru_evict_visitors(self, need: int, now: float) -> List[str]:
        if need <= 0:
            return []
        evictable = [
            rec
            for rec in self._repo.list_records()
            if not is_permanent_record(rec)
        ]
        evictable.sort(
            key=lambda r: r.last_seen if r.last_seen > 0 else r.created_at,
        )
        removed: List[str] = []
        for rec in evictable:
            if len(removed) >= need:
                break
            if self._repo.delete_person(rec.person_id):
                removed.append(rec.person_id)
                logger.info(
                    "[Capacity] LRU evicted visitor %s (last_seen=%.0f)",
                    rec.person_id,
                    rec.last_seen if rec.last_seen > 0 else rec.created_at,
                )
        if len(removed) < need:
            logger.error(
                "[Capacity] LRU incomplete: needed %d, removed %d (permanent protected)",
                need,
                len(removed),
            )
        return removed

    @staticmethod
    def _reference_now() -> float:
        """Wall clock for day-based expiry; monotonic fallback for tests."""
        wall = time.time()
        mono = SystemClock.now()
        return wall if wall > 1_000_000_000 else mono

"""Capacity manager tests — 800 / 950 / 999 / 1000 population scenarios."""

from __future__ import annotations

import time
import unittest

import numpy as np

from core.types import EventType
from face_core.capacity_manager import (
    CapacityFullError,
    CapacityManager,
    is_permanent_record,
)
from face_core.repository import FaceRepository
from vision.face_db import FaceDB, _normalize


def _emb(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return _normalize(rng.standard_normal(128).astype(np.float32))


def _populate(
    repo: FaceRepository,
    *,
    visitors: int = 0,
    vip: int = 0,
    employees: int = 0,
    leaders: int = 0,
    consultants: int = 0,
    last_seen: float | None = None,
) -> None:
    """Bulk fill DB (bypass per-add capacity checks for test setup)."""
    now = time.time()
    seen = last_seen if last_seen is not None else now
    db = repo.backend

    for i in range(leaders):
        pid = db.add_person(f"领导{i}", _emb(i), vip_level="executive" if i % 2 == 0 else "director")
        _set_last_seen(repo, pid, seen)
    for i in range(employees):
        pid = db.add_person(f"员工{i}", _emb(100 + i), vip_level="sales_director")
        _set_last_seen(repo, pid, seen)
    for i in range(consultants):
        pid = db.add_person(f"顾问{i}", _emb(200 + i), vip_level="consultant")
        _set_last_seen(repo, pid, seen)
    for i in range(vip):
        pid = db.add_person(f"VIP{i}", _emb(300 + i), vip_level="vip_customer")
        _set_last_seen(repo, pid, seen)
    for i in range(visitors):
        pid = db.add_person(f"访客{i}", _emb(400 + i), vip_level="regular_customer")
        _set_last_seen(repo, pid, seen)


def _set_last_seen(repo: FaceRepository, person_id: str, ts: float) -> None:
    rec = repo.get_record(person_id)
    assert rec is not None
    rec.last_seen = ts


class CapacityScenarioTests(unittest.TestCase):
    def _make_repo(self) -> tuple[FaceRepository, CapacityManager]:
        db = FaceDB(size=0, seed=False, persist_path="")
        repo = FaceRepository(db)
        mgr = CapacityManager(
            repo,
            max_capacity=1000,
            warning_threshold=850,
            emergency_threshold=950,
            visitor_expire_days=30,
        )
        repo._capacity = mgr
        return repo, mgr

    def test_report_format(self) -> None:
        repo, mgr = self._make_repo()
        _populate(repo, visitors=5, vip=2, employees=1)
        report = mgr.build_capacity_report()
        self.assertEqual(report["report_type"], "FACE_CAPACITY_REPORT")
        self.assertEqual(report["total"], 8)
        self.assertEqual(report["temporary"], 5)
        self.assertEqual(report["permanent"], 3)
        self.assertEqual(report["remaining"], 992)

        event = mgr.build_capacity_event()
        self.assertEqual(event.type, EventType.FACE_CAPACITY_REPORT)
        self.assertEqual(event.payload["remaining"], 992)

    def test_permanent_cannot_delete(self) -> None:
        repo, mgr = self._make_repo()
        pid = repo.backend.add_person("张总", _emb(), vip_level="executive")
        self.assertFalse(mgr.safe_delete(pid))
        self.assertIsNotNone(repo.get_record(pid))

    def test_scenario_800_normal(self) -> None:
        """800人：低于预警线，不触发 emergency cleanup。"""
        repo, mgr = self._make_repo()
        _populate(repo, visitors=750, vip=20, employees=15, leaders=10, consultants=5)
        stats = mgr.collect_stats()
        self.assertEqual(stats.total, 800)
        self.assertFalse(stats.is_warning)
        self.assertFalse(stats.is_emergency)

        result = mgr.run_maintenance(now=time.time())
        self.assertFalse(result.emergency_triggered)
        self.assertEqual(result.stats.total, 800)
        self.assertEqual(result.stats.remaining, 200)

    def test_scenario_950_emergency_cleanup(self) -> None:
        """950人：触发紧急 LRU 清理临时访客。"""
        repo, mgr = self._make_repo()
        now = time.time()
        _populate(
            repo,
            visitors=900,
            vip=20,
            employees=15,
            leaders=10,
            consultants=5,
            last_seen=now,
        )
        self.assertEqual(mgr.collect_stats().total, 950)
        self.assertTrue(mgr.collect_stats().is_emergency)

        result = mgr.run_maintenance(now=now)
        self.assertTrue(result.emergency_triggered)
        self.assertGreater(len(result.lru_removed), 0)
        self.assertLessEqual(result.stats.total, 949)

    def test_scenario_999_lru_on_enroll(self) -> None:
        """999人：新增 VIP 直接成功，总量达 1000。"""
        repo, mgr = self._make_repo()
        now = time.time()
        _populate(
            repo,
            visitors=960,
            vip=15,
            employees=10,
            leaders=10,
            consultants=4,
            last_seen=now,
        )
        self.assertEqual(mgr.collect_stats().total, 999)

        pid = repo.add_person("新VIP", _emb(999), vip_level="vip_customer")
        self.assertIsNotNone(repo.get_record(pid))
        self.assertEqual(mgr.collect_stats().total, 1000)

    def test_scenario_1000_full_vip_protected(self) -> None:
        """1000人且全为永久人员：VIP 无法录入。"""
        repo, mgr = self._make_repo()
        now = time.time()
        _populate(
            repo,
            visitors=0,
            vip=400,
            employees=300,
            leaders=200,
            consultants=100,
            last_seen=now,
        )
        stats = mgr.collect_stats()
        self.assertEqual(stats.total, 1000)
        self.assertTrue(stats.is_full)

        with self.assertRaises(CapacityFullError):
            mgr.ensure_capacity_for_add(vip_level="vip_customer", now=now)

        with self.assertRaises(CapacityFullError):
            repo.add_person("无法录入", _emb(1000), vip_level="vip_customer")

    def test_scenario_1000_visitor_lru_then_add(self) -> None:
        """1000人含可删访客：新增 VIP 时 LRU 清理 1 人后保持满容。"""
        repo, mgr = self._make_repo()
        now = time.time()
        _populate(
            repo,
            visitors=60,
            vip=390,
            employees=300,
            leaders=150,
            consultants=100,
            last_seen=now - 100,
        )
        self.assertEqual(mgr.collect_stats().total, 1000)

        pid = repo.add_person("补录VIP", _emb(1001), vip_level="vip_customer")
        self.assertIsNotNone(repo.get_record(pid))
        self.assertEqual(mgr.collect_stats().total, 1000)

    def test_scenario_expire_stale_visitors(self) -> None:
        """30天未出现临时访客自动删除。"""
        repo, mgr = self._make_repo()
        now = time.time()
        old = now - 31 * 86400
        _populate(repo, visitors=20, vip=2, last_seen=old)
        result = mgr.run_maintenance(now=now)
        self.assertEqual(len(result.expired_removed), 20)
        self.assertEqual(result.stats.total, 2)

    def test_lru_prefers_oldest_visitor(self) -> None:
        repo, mgr = self._make_repo()
        now = time.time()
        old_pid = repo.backend.add_person("老访客", _emb(1), vip_level="regular_customer")
        new_pid = repo.backend.add_person("新访客", _emb(2), vip_level="regular_customer")
        _set_last_seen(repo, old_pid, now - 5000)
        _set_last_seen(repo, new_pid, now - 100)

        removed = mgr._lru_evict_visitors(1, now)
        self.assertEqual(removed, [old_pid])
        self.assertIsNone(repo.get_record(old_pid))
        self.assertIsNotNone(repo.get_record(new_pid))

    def test_is_permanent_levels(self) -> None:
        repo, _ = self._make_repo()
        vip = repo.backend.add_person("客户", _emb(), vip_level="vip_customer")
        visitor = repo.backend.add_person("路人", _emb(2), vip_level="regular_customer")
        self.assertTrue(is_permanent_record(repo.get_record(vip)))
        self.assertFalse(is_permanent_record(repo.get_record(visitor)))


if __name__ == "__main__":
    unittest.main()

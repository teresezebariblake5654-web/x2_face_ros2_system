"""Face embedding database — industrial grade with migration support."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from config import (
    CANDIDATE_POOL_MAX,
    FACE_DB_PERSIST_PATH,
    FACE_DB_SEED,
    FACE_DB_SIZE,
    FACE_EMBEDDING_DIM,
    FACE_EMBEDDING_VERSION,
    FACE_MATCH_THRESHOLD,
)
from core.system_clock import SystemClock
from core.types import FaceRecord
from utils.logger import get_logger

logger = get_logger(__name__)

_VIP_LEVELS = frozenset({
    "executive",
    "director",
    "sales_director",
    "consultant",
    "vip_customer",
})


def _seed_vip_level(index: int) -> str:
    if index == 0:
        return "executive"
    if index == 1:
        return "director"
    if index == 2:
        return "sales_director"
    if index == 3:
        return "consultant"
    if index == 4:
        return "vip_customer"
    return "regular_customer"


def _normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    if norm < 1e-8:
        return vec
    return vec / norm


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a_n = _normalize(a.astype(np.float64))
    b_n = _normalize(b.astype(np.float64))
    return float(np.dot(a_n, b_n))


class FaceDB:
    """In-memory embedding store (200+) with per-person thresholds and migration."""

    CURRENT_EMBEDDING_VERSION = FACE_EMBEDDING_VERSION

    def __init__(
        self,
        size: int = FACE_DB_SIZE,
        dim: int = FACE_EMBEDDING_DIM,
        *,
        persist_path: str | None = None,
        seed: bool | None = None,
    ) -> None:
        self._dim = dim
        self._lock = threading.Lock()
        self._records: Dict[str, FaceRecord] = {}
        self._candidate_pool: Dict[str, FaceRecord] = {}
        path = persist_path if persist_path is not None else FACE_DB_PERSIST_PATH
        self._persist_path: Optional[Path] = Path(path) if path else None
        seed_flag = FACE_DB_SEED if seed is None else seed
        if not self._load_from_disk() and seed_flag:
            self._seed_database(size)
        elif not self._records:
            logger.info("FaceDB empty (no persist file, seed disabled)")

    def _seed_database(self, size: int) -> None:
        rng = np.random.default_rng(42)
        now = SystemClock.now()
        for i in range(size):
            pid = f"user_{i:04d}"
            name = f"访客{i:04d}"
            emb = _normalize(rng.standard_normal(self._dim).astype(np.float32))
            vip_level = _seed_vip_level(i)
            self._records[pid] = FaceRecord(
                person_id=pid,
                name=name,
                embedding=emb,
                embedding_version=self.CURRENT_EMBEDDING_VERSION,
                created_at=now,
                last_seen=0.0,
                confidence_threshold=FACE_MATCH_THRESHOLD,
                is_vip=vip_level in _VIP_LEVELS,
                vip_level=vip_level,
            )
        logger.info(
            "FaceDB v%d initialized with %d identities (dim=%d)",
            self.CURRENT_EMBEDDING_VERSION,
            size,
            self._dim,
        )

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._records)

    def get_record(self, person_id: str) -> Optional[FaceRecord]:
        with self._lock:
            return self._records.get(person_id)

    def get_embedding(self, person_id: str) -> Optional[np.ndarray]:
        with self._lock:
            rec = self._records.get(person_id)
            if rec is None:
                return None
            if rec.embedding_version != self.CURRENT_EMBEDDING_VERSION:
                return None
            return rec.embedding.copy()

    def get_name(self, person_id: str) -> Optional[str]:
        with self._lock:
            rec = self._records.get(person_id)
            return rec.name if rec else None

    def touch_last_seen(self, person_id: str) -> None:
        with self._lock:
            rec = self._records.get(person_id)
            if rec:
                rec.last_seen = SystemClock.now()

    def match(self, embedding: np.ndarray) -> Tuple[Optional[str], float]:
        best_id: Optional[str] = None
        best_score = -1.0
        best_threshold = FACE_MATCH_THRESHOLD

        with self._lock:
            for pid, rec in self._records.items():
                if rec.embedding_version != self.CURRENT_EMBEDDING_VERSION:
                    continue
                score = cosine_similarity(embedding, rec.embedding)
                threshold = rec.confidence_threshold
                if score > best_score:
                    best_score = score
                    best_id = pid
                    best_threshold = threshold

        if best_id and best_score >= best_threshold:
            self.touch_last_seen(best_id)
            return best_id, best_score
        return None, best_score

    def migrate_embedding(
        self,
        person_id: str,
        new_embedding: np.ndarray,
        new_version: int,
        new_threshold: Optional[float] = None,
    ) -> bool:
        """Upgrade-safe: update embedding only when version increases."""
        with self._lock:
            rec = self._records.get(person_id)
            if rec is None:
                return False
            if new_version <= rec.embedding_version:
                logger.warning(
                    "Migration rejected for %s: v%d <= v%d",
                    person_id,
                    new_version,
                    rec.embedding_version,
                )
                return False
            rec.embedding = new_embedding.copy()
            rec.embedding_version = new_version
            if new_threshold is not None:
                rec.confidence_threshold = new_threshold
            logger.info("Migrated %s to embedding v%d", person_id, new_version)
            return True

    def bulk_migrate(self, target_version: int, dim: Optional[int] = None) -> int:
        """Re-seed embeddings for all records below target_version (simulated migration)."""
        dim = dim or self._dim
        rng = np.random.default_rng(99)
        count = 0
        with self._lock:
            for pid, rec in self._records.items():
                if rec.embedding_version >= target_version:
                    continue
                rec.embedding = _normalize(rng.standard_normal(dim).astype(np.float32))
                rec.embedding_version = target_version
                count += 1
        logger.info("Bulk migration: %d records -> v%d", count, target_version)
        return count

    def add_candidate(self, embedding: np.ndarray, label: str | None = None) -> str:
        with self._lock:
            while len(self._candidate_pool) >= CANDIDATE_POOL_MAX:
                oldest = min(
                    self._candidate_pool.items(),
                    key=lambda item: item[1].created_at,
                )[0]
                self._candidate_pool.pop(oldest, None)
                logger.info("[FaceDB] candidate pool full; evicted %s", oldest)
            cid = f"candidate_{len(self._candidate_pool):04d}"
            self._candidate_pool[cid] = FaceRecord(
                person_id=cid,
                name=label or f"未知访客{cid[-4:]}",
                embedding=embedding.copy(),
                embedding_version=self.CURRENT_EMBEDDING_VERSION,
                created_at=SystemClock.now(),
                confidence_threshold=FACE_MATCH_THRESHOLD,
            )
            logger.info("Enrolled candidate %s (pool=%d)", cid, len(self._candidate_pool))
            person_id = cid
        self.save_to_disk()
        return person_id

    def _record_to_dict(self, rec: FaceRecord) -> dict:
        emb = rec.embedding
        if hasattr(emb, "tolist"):
            emb = emb.tolist()
        return {
            "person_id": rec.person_id,
            "name": rec.name,
            "embedding": emb,
            "embedding_version": rec.embedding_version,
            "created_at": rec.created_at,
            "last_seen": rec.last_seen,
            "confidence_threshold": rec.confidence_threshold,
            "is_vip": rec.is_vip,
            "vip_level": rec.vip_level,
        }

    def _dict_to_record(self, data: dict) -> FaceRecord:
        return FaceRecord(
            person_id=data["person_id"],
            name=data["name"],
            embedding=np.array(data["embedding"], dtype=np.float32),
            embedding_version=int(data.get("embedding_version", FACE_EMBEDDING_VERSION)),
            created_at=float(data.get("created_at", SystemClock.now())),
            last_seen=float(data.get("last_seen", 0.0)),
            confidence_threshold=float(data.get("confidence_threshold", FACE_MATCH_THRESHOLD)),
            is_vip=bool(data.get("is_vip", False)),
            vip_level=str(data.get("vip_level", "regular_customer")),
        )

    def _load_from_disk(self) -> bool:
        if self._persist_path is None or not self._persist_path.exists():
            return False
        try:
            with self._persist_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            records = data.get("records", [])
            candidates = data.get("candidates", [])
            with self._lock:
                self._records.clear()
                self._candidate_pool.clear()
                for item in records:
                    rec = self._dict_to_record(item)
                    self._records[rec.person_id] = rec
                for item in candidates:
                    rec = self._dict_to_record(item)
                    self._candidate_pool[rec.person_id] = rec
            logger.info(
                "FaceDB loaded from %s (%d records, %d candidates)",
                self._persist_path,
                len(self._records),
                len(self._candidate_pool),
            )
            return bool(self._records or self._candidate_pool)
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.error("FaceDB load failed: %s", exc)
            return False

    def save_to_disk(self) -> None:
        if self._persist_path is None:
            return
        try:
            with self._lock:
                payload = {
                    "version": self.CURRENT_EMBEDDING_VERSION,
                    "records": [self._record_to_dict(r) for r in self._records.values()],
                    "candidates": [self._record_to_dict(r) for r in self._candidate_pool.values()],
                }
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._persist_path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            tmp.replace(self._persist_path)
            logger.debug("FaceDB saved to %s", self._persist_path)
        except OSError as exc:
            logger.error("FaceDB save failed: %s", exc)

    def promote_candidate(self, candidate_id: str, new_name: str) -> Optional[str]:
        with self._lock:
            rec = self._candidate_pool.pop(candidate_id, None)
            if rec is None:
                return None
            new_id = f"user_{self._next_person_index():04d}"
            self._records[new_id] = FaceRecord(
                person_id=new_id,
                name=new_name,
                embedding=rec.embedding,
                embedding_version=rec.embedding_version,
                created_at=rec.created_at,
                confidence_threshold=rec.confidence_threshold,
            )
            logger.info("Promoted %s -> %s (%s)", candidate_id, new_id, new_name)
        self.save_to_disk()
        return new_id

    def list_known_ids(self) -> List[str]:
        with self._lock:
            return list(self._records.keys())

    def list_records(self) -> List[FaceRecord]:
        with self._lock:
            return list(self._records.values())

    def _next_person_index(self) -> int:
        max_idx = -1
        for pid in self._records:
            if pid.startswith("user_"):
                try:
                    max_idx = max(max_idx, int(pid.split("_", 1)[1]))
                except ValueError:
                    continue
        return max_idx + 1

    def add_person(
        self,
        name: str,
        embedding: np.ndarray,
        *,
        is_vip: bool = False,
        vip_level: str | None = None,
    ) -> str:
        level = vip_level or ("vip_customer" if is_vip else "regular_customer")
        with self._lock:
            person_id = f"user_{self._next_person_index():04d}"
            self._records[person_id] = FaceRecord(
                person_id=person_id,
                name=name,
                embedding=_normalize(embedding.copy()),
                embedding_version=self.CURRENT_EMBEDDING_VERSION,
                created_at=SystemClock.now(),
                confidence_threshold=FACE_MATCH_THRESHOLD,
                is_vip=is_vip or level in _VIP_LEVELS,
                vip_level=level,
            )
            person_id_out = person_id
        self.save_to_disk()
        return person_id_out

    def delete_record(self, person_id: str) -> bool:
        with self._lock:
            if person_id not in self._records:
                return False
            del self._records[person_id]
            deleted = True
        self.save_to_disk()
        return deleted

    def set_vip(self, person_id: str, is_vip: bool) -> bool:
        with self._lock:
            rec = self._records.get(person_id)
            if rec is None:
                return False
            rec.is_vip = is_vip
            return True

    def is_vip(self, person_id: str) -> bool:
        with self._lock:
            rec = self._records.get(person_id)
            return bool(rec and rec.is_vip)

    def get_vip_level(self, person_id: str) -> str:
        with self._lock:
            rec = self._records.get(person_id)
            return rec.vip_level if rec else "regular_customer"

    def set_vip_level(self, person_id: str, vip_level: str) -> bool:
        with self._lock:
            rec = self._records.get(person_id)
            if rec is None:
                return False
            rec.vip_level = vip_level
            rec.is_vip = vip_level in _VIP_LEVELS
            updated = True
        self.save_to_disk()
        return updated

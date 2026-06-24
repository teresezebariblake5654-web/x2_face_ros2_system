"""Face embedding database — industrial grade with migration support."""

from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple

import numpy as np

from config import (
    FACE_DB_SIZE,
    FACE_EMBEDDING_DIM,
    FACE_EMBEDDING_VERSION,
    FACE_MATCH_THRESHOLD,
)
from core.system_clock import SystemClock
from core.types import FaceRecord
from utils.logger import get_logger

logger = get_logger(__name__)


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

    def __init__(self, size: int = FACE_DB_SIZE, dim: int = FACE_EMBEDDING_DIM) -> None:
        self._dim = dim
        self._lock = threading.Lock()
        self._records: Dict[str, FaceRecord] = {}
        self._candidate_pool: Dict[str, FaceRecord] = {}
        self._seed_database(size)

    def _seed_database(self, size: int) -> None:
        rng = np.random.default_rng(42)
        now = SystemClock.now()
        for i in range(size):
            pid = f"user_{i:04d}"
            name = f"访客{i:04d}"
            emb = _normalize(rng.standard_normal(self._dim).astype(np.float32))
            self._records[pid] = FaceRecord(
                person_id=pid,
                name=name,
                embedding=emb,
                embedding_version=self.CURRENT_EMBEDDING_VERSION,
                created_at=now,
                last_seen=0.0,
                confidence_threshold=FACE_MATCH_THRESHOLD,
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
            return cid

    def promote_candidate(self, candidate_id: str, new_name: str) -> bool:
        with self._lock:
            rec = self._candidate_pool.pop(candidate_id, None)
            if rec is None:
                return False
            new_id = f"user_{len(self._records):04d}"
            self._records[new_id] = FaceRecord(
                person_id=new_id,
                name=new_name,
                embedding=rec.embedding,
                embedding_version=rec.embedding_version,
                created_at=rec.created_at,
                confidence_threshold=rec.confidence_threshold,
            )
            logger.info("Promoted %s -> %s (%s)", candidate_id, new_id, new_name)
            return True

    def list_known_ids(self) -> List[str]:
        with self._lock:
            return list(self._records.keys())

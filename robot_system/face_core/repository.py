"""Face repository — CRUD and VIP management over FaceDB."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from core.types import Event, FaceRecord
from face_core.capacity_manager import CapacityFullError, CapacityManager, is_permanent_record
from utils.logger import get_logger
from vision.face_db import FaceDB

logger = get_logger(__name__)


class FaceRepository:
    """Single access point for face data; business layer must not use FaceDB directly."""

    def __init__(
        self,
        face_db: FaceDB | None = None,
        capacity_manager: CapacityManager | None = None,
    ) -> None:
        self._db = face_db or FaceDB()
        self._capacity = capacity_manager or CapacityManager(self)

    @property
    def capacity(self) -> CapacityManager:
        return self._capacity

    @property
    def backend(self) -> FaceDB:
        """Internal backend reference for legacy vision modules."""
        return self._db

    def add_person(
        self,
        name: str,
        embedding: np.ndarray,
        *,
        is_vip: bool = False,
        vip_level: str | None = None,
    ) -> str:
        level = vip_level or ("vip_customer" if is_vip else "regular_customer")
        self._capacity.ensure_capacity_for_add(vip_level=level)
        person_id = self._db.add_person(name, embedding, is_vip=is_vip, vip_level=level)
        logger.info("[FaceRepository] added %s (%s) level=%s", name, person_id, level)
        return person_id

    def delete_person(self, person_id: str, *, force: bool = False) -> bool:
        if not force:
            record = self.get_record(person_id)
            if record is None:
                return False
            if is_permanent_record(record):
                logger.warning(
                    "[FaceRepository] Refused delete permanent %s (level=%s)",
                    person_id,
                    record.vip_level,
                )
                return False
        deleted = self._db.delete_record(person_id)
        if deleted:
            logger.info("[FaceRepository] deleted %s", person_id)
        return deleted

    def get_record(self, person_id: str) -> Optional[FaceRecord]:
        return self._db.get_record(person_id)

    def list_records(self) -> List[FaceRecord]:
        return self._db.list_records()

    def query_person(self, person_id: str) -> Optional[Dict[str, Any]]:
        record = self._db.get_record(person_id)
        if record is None:
            return None
        return self._to_dict(record)

    def set_vip(self, person_id: str, is_vip: bool = True) -> bool:
        updated = self._db.set_vip(person_id, is_vip)
        if updated:
            logger.info("[FaceRepository] VIP=%s for %s", is_vip, person_id)
        return updated

    def is_vip(self, person_id: str) -> bool:
        return self._db.is_vip(person_id)

    def get_vip_level(self, person_id: str) -> str:
        return self._db.get_vip_level(person_id)

    def set_vip_level(self, person_id: str, vip_level: str) -> bool:
        updated = self._db.set_vip_level(person_id, vip_level)
        if updated:
            logger.info("[FaceRepository] vip_level=%s for %s", vip_level, person_id)
        return updated

    def match(self, embedding: np.ndarray) -> Tuple[Optional[str], float]:
        return self._db.match(embedding)

    def get_name(self, person_id: str) -> Optional[str]:
        return self._db.get_name(person_id)

    def get_embedding(self, person_id: str) -> Optional[np.ndarray]:
        return self._db.get_embedding(person_id)

    def list_known_ids(self) -> List[str]:
        return self._db.list_known_ids()

    def add_candidate(self, embedding: np.ndarray, label: str | None = None) -> str:
        return self._db.add_candidate(embedding, label)

    def promote_candidate(self, candidate_id: str, new_name: str, *, vip_level: str | None = None) -> bool:
        level = vip_level or "regular_customer"
        self._capacity.ensure_capacity_for_add(vip_level=level)
        new_id = self._db.promote_candidate(candidate_id, new_name)
        if new_id is None:
            return False
        if vip_level:
            self.set_vip_level(new_id, vip_level)
        return True

    def run_capacity_maintenance(self):
        return self._capacity.run_maintenance()

    def capacity_report(self) -> dict:
        return self._capacity.build_capacity_report()

    def capacity_event(self, source: str = "face_repository") -> Event:
        return self._capacity.build_capacity_event(source=source)

    @staticmethod
    def _to_dict(record: FaceRecord) -> Dict[str, Any]:
        return {
            "person_id": record.person_id,
            "name": record.name,
            "is_vip": record.is_vip,
            "vip_level": record.vip_level,
            "embedding_version": record.embedding_version,
            "created_at": record.created_at,
            "last_seen": record.last_seen,
            "confidence_threshold": record.confidence_threshold,
        }


__all__ = ["FaceRepository", "CapacityFullError"]

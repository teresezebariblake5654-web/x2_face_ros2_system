"""Face recognition service — EventBus only."""

from __future__ import annotations

import threading
from typing import Dict, Optional

import numpy as np

from config import ZONE_EXIT_TIMEOUT_SEC
from core.event_bus import EventBus
from core.system_clock import SystemClock
from core.trace_logger import TraceLogger
from core.types import Event, EventType, Priority
from face_core.repository import FaceRepository
from policy.recognition_guard import UNKNOWN_IDENTITY
from utils.logger import get_logger
from vision.face_db import FaceDB

logger = get_logger(__name__)


class RecognitionService:
    def __init__(self, bus: EventBus, face_repo: FaceRepository | FaceDB) -> None:
        self._bus = bus
        if isinstance(face_repo, FaceRepository):
            self._repo = face_repo
        else:
            self._repo = FaceRepository(face_repo)
        self._trace = TraceLogger.get()
        self._running = False
        self._thread: threading.Thread | None = None
        self._presence: Dict[str, dict] = {}
        self._maint_counter = 0

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="RecognitionService", daemon=True)
        self._thread.start()
        logger.info("RecognitionService started")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while self._running:
            self._check_departures()
            event = self._bus.get_event("recognition_service", timeout=0.2)
            if event and event.type == EventType.FACE_RAW_DETECTED:
                self._handle_raw(event)
                self._maint_counter += 1
                if self._maint_counter % 20 == 0:
                    self._repo.run_capacity_maintenance()

    def _check_departures(self) -> None:
        now = SystemClock.now()
        for person_id, info in list(self._presence.items()):
            if now - info["last_seen"] >= ZONE_EXIT_TIMEOUT_SEC:
                self._publish_departed(person_id, info, parent_trace=info.get("trace_id", "departure"))
                del self._presence[person_id]

    def _handle_raw(self, event: Event) -> None:
        embedding = event.payload.get("embedding")
        if embedding is None:
            return
        if not isinstance(embedding, np.ndarray):
            embedding = np.array(embedding, dtype=np.float32)

        in_zone = bool(event.payload.get("in_welcome_zone", True))
        if not in_zone:
            self._depart_all_present(event.trace_id)
            return

        person_id, score = self._repo.match(embedding)
        if person_id:
            name = self._repo.get_name(person_id) or person_id
            vip_level = self._repo.get_vip_level(person_id)
            self._presence[person_id] = {
                "name": name,
                "vip_level": vip_level,
                "last_seen": SystemClock.now(),
                "trace_id": event.trace_id,
            }
            self._trace.log_chain(event.trace_id, "FACE", "MATCH", name)
            logger.info("[Vision] Matched %s (%s) score=%.3f", name, person_id, score)
            self._bus.publish(
                Event.from_parent(
                    event,
                    EventType.FACE_RECOGNIZED,
                    source="recognition_service",
                    priority=Priority.NORMAL,
                    payload={
                        "person_id": person_id,
                        "name": name,
                        "score": score,
                        "vip_level": vip_level,
                        "in_welcome_zone": in_zone,
                        "person_count": event.payload.get("person_count", 1),
                    },
                )
            )
        else:
            logger.info("[Vision] Unknown face best_score=%.3f", score)
            self._presence[UNKNOWN_IDENTITY] = {
                "name": None,
                "vip_level": "first_visit",
                "last_seen": SystemClock.now(),
                "trace_id": event.trace_id,
            }
            self._bus.publish(
                Event.from_parent(
                    event,
                    EventType.FACE_UNKNOWN,
                    source="recognition_service",
                    priority=Priority.NORMAL,
                    payload={
                        "score": score,
                        "vip_level": "first_visit",
                        "in_welcome_zone": in_zone,
                        "person_count": event.payload.get("person_count", 1),
                    },
                )
            )
            candidate_id = self._repo.add_candidate(embedding)
            self._bus.publish(
                Event.from_parent(
                    event,
                    EventType.ENROLL_CANDIDATE,
                    source="recognition_service",
                    priority=Priority.LOW,
                    payload={"candidate_id": candidate_id},
                )
            )

    def _depart_all_present(self, trace_id: str) -> None:
        for person_id, info in list(self._presence.items()):
            self._publish_departed(person_id, info, parent_trace=trace_id)
        self._presence.clear()

    def _publish_departed(self, person_id: str, info: dict, parent_trace: str) -> None:
        name = info.get("name") or (person_id if person_id != UNKNOWN_IDENTITY else None)
        logger.info("[Vision] Departed %s", name or person_id)
        parent = Event(
            type=EventType.FACE_RAW_DETECTED,
            source="recognition_service",
            trace_id=parent_trace,
            payload={},
        )
        payload: dict = {
            "vip_level": info.get("vip_level", "regular_customer"),
            "reason": "zone_exit",
        }
        if person_id != UNKNOWN_IDENTITY:
            payload["person_id"] = person_id
        if name:
            payload["name"] = name
        self._bus.publish(
            Event.from_parent(
                parent,
                EventType.FACE_DEPARTED,
                source="recognition_service",
                priority=Priority.NORMAL,
                payload=payload,
            )
        )

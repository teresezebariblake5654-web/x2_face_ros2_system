"""Face recognition service — EventBus only."""

from __future__ import annotations

import threading

import numpy as np

from core.event_bus import EventBus
from core.trace_logger import TraceLogger
from core.types import Event, EventType, Priority
from utils.logger import get_logger
from vision.face_db import FaceDB

logger = get_logger(__name__)


class RecognitionService:
    def __init__(self, bus: EventBus, face_db: FaceDB) -> None:
        self._bus = bus
        self._face_db = face_db
        self._trace = TraceLogger.get()
        self._running = False
        self._thread: threading.Thread | None = None

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
            event = self._bus.get_event("recognition_service", timeout=0.2)
            if event and event.type == EventType.FACE_RAW_DETECTED:
                self._handle_raw(event)

    def _handle_raw(self, event: Event) -> None:
        embedding = event.payload.get("embedding")
        if embedding is None:
            return
        if not isinstance(embedding, np.ndarray):
            embedding = np.array(embedding, dtype=np.float32)

        person_id, score = self._face_db.match(embedding)
        if person_id:
            name = self._face_db.get_name(person_id) or person_id
            self._trace.log_chain(event.trace_id, "FACE", "MATCH", name)
            logger.info("[Vision] Matched %s (%s) score=%.3f", name, person_id, score)
            self._bus.publish(
                Event.from_parent(
                    event,
                    EventType.FACE_RECOGNIZED,
                    source="recognition_service",
                    priority=Priority.NORMAL,
                    payload={"person_id": person_id, "name": name, "score": score},
                )
            )
        else:
            logger.info("[Vision] Unknown face best_score=%.3f", score)
            self._bus.publish(
                Event.from_parent(
                    event,
                    EventType.FACE_UNKNOWN,
                    source="recognition_service",
                    priority=Priority.NORMAL,
                    payload={"score": score},
                )
            )
            candidate_id = self._face_db.add_candidate(embedding)
            self._bus.publish(
                Event.from_parent(
                    event,
                    EventType.ENROLL_CANDIDATE,
                    source="recognition_service",
                    priority=Priority.LOW,
                    payload={"candidate_id": candidate_id},
                )
            )

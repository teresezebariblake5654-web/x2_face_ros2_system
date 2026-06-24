"""Simulated face detection — publishes FACE_RAW_DETECTED every 3s."""

from __future__ import annotations

import random
import threading
import time

import numpy as np

from config import FACE_ENGINE_INTERVAL, FACE_EMBEDDING_DIM
from core.event_bus import EventBus
from core.types import Event, EventType, Priority
from utils.logger import get_logger
from vision.face_db import FaceDB, _normalize

logger = get_logger(__name__)


class FaceEngine:
    def __init__(self, bus: EventBus, face_db: FaceDB, interval: float = FACE_ENGINE_INTERVAL) -> None:
        self._bus = bus
        self._face_db = face_db
        self._interval = interval
        self._running = False
        self._thread: threading.Thread | None = None
        self._rng = np.random.default_rng()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="FaceEngine", daemon=True)
        self._thread.start()
        logger.info("FaceEngine started (interval=%.1fs)", self._interval)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=self._interval + 1.0)

    def _loop(self) -> None:
        tick = 0
        while self._running:
            tick += 1
            is_known = random.random() < 0.6
            if is_known:
                person_id = random.choice(self._face_db.list_known_ids())
                embedding = self._face_db.get_embedding(person_id)
                if embedding is None:
                    embedding = _normalize(self._rng.standard_normal(FACE_EMBEDDING_DIM).astype(np.float32))
                noise = self._rng.normal(0, 0.02, size=embedding.shape).astype(np.float32)
                embedding = _normalize(embedding + noise)
                logger.info("[FaceEngine] KNOWN capture -> %s", person_id)
            else:
                embedding = _normalize(self._rng.standard_normal(FACE_EMBEDDING_DIM).astype(np.float32))
                logger.info("[FaceEngine] UNKNOWN capture")

            self._bus.publish(
                Event(
                    type=EventType.FACE_RAW_DETECTED,
                    source="face_engine",
                    priority=Priority.NORMAL,
                    payload={"embedding": embedding, "simulated_known": is_known, "tick": tick},
                )
            )
            time.sleep(self._interval)

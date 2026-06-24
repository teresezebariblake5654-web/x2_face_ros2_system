"""Placeholder TTS — EventBus consumer only."""

from __future__ import annotations

import threading

from core.event_bus import EventBus
from core.trace_logger import TraceLogger
from core.types import Event, EventType
from utils.logger import get_logger

logger = get_logger(__name__)


class TTSEngine:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._trace = TraceLogger.get()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="TTSEngine", daemon=True)
        self._thread.start()
        logger.info("TTSEngine started (mock)")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while self._running:
            event = self._bus.get_event("tts_engine", timeout=0.2)
            if event and event.type == EventType.TTS_REQUEST:
                text = event.payload.get("text", "")
                self._trace.log_chain(event.trace_id, "TTS", "SPEAK", text[:40])
                logger.info("[TTS] (%s): %s", event.payload.get("lang", "zh-CN"), text)

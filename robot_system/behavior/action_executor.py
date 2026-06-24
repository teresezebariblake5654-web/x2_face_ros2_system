"""Unified action executor — queue, lock, timeout."""

from __future__ import annotations

import queue
import threading
import time

from config import ACTION_QUEUE_MAX, ACTION_TIMEOUT
from behavior.gesture import GESTURE_CATALOG, describe
from core.event_bus import EventBus
from core.system_clock import SystemClock
from core.trace_logger import TraceLogger
from core.types import Event, EventType, GestureType
from utils.logger import get_logger

logger = get_logger(__name__)


class ActionExecutor:
    """Serializes gestures via queue + lock; enforces per-action timeout."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._trace = TraceLogger.get()
        self._running = False
        self._ingress_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._action_queue: queue.Queue[Event] = queue.Queue(maxsize=ACTION_QUEUE_MAX)
        self._lock = threading.Lock()
        self._current: Event | None = None

    def start(self) -> None:
        self._running = True
        self._ingress_thread = threading.Thread(target=self._ingress_loop, name="ActionIngress", daemon=True)
        self._worker_thread = threading.Thread(target=self._worker_loop, name="ActionWorker", daemon=True)
        self._ingress_thread.start()
        self._worker_thread.start()
        logger.info("ActionExecutor started (queue=%d, timeout=%.1fs)", ACTION_QUEUE_MAX, ACTION_TIMEOUT)

    def stop(self) -> None:
        self._running = False
        for t in (self._ingress_thread, self._worker_thread):
            if t:
                t.join(timeout=3.0)

    def _ingress_loop(self) -> None:
        while self._running:
            event = self._bus.get_event("action_executor", timeout=0.2)
            if event and event.type == EventType.ACTION_REQUEST:
                try:
                    self._action_queue.put(event, block=False)
                except queue.Full:
                    logger.error("[Action] queue full; drop %s", event.payload.get("gesture"))
                    self._publish_failed(event, "queue_full")

    def _worker_loop(self) -> None:
        while self._running:
            try:
                event = self._action_queue.get(timeout=0.3)
            except queue.Empty:
                continue
            if not self._lock.acquire(blocking=False):
                try:
                    self._action_queue.put_nowait(event)
                except queue.Full:
                    self._publish_failed(event, "lock_contention")
                time.sleep(0.05)
                continue
            try:
                self._current = event
                self._execute(event)
            finally:
                self._current = None
                self._lock.release()

    def _execute(self, event: Event) -> None:
        gesture_raw = event.payload.get("gesture", "")
        try:
            gesture = GestureType(gesture_raw)
        except ValueError:
            logger.error("[Action] unknown gesture: %s", gesture_raw)
            self._publish_failed(event, "unknown_gesture")
            return

        spec = GESTURE_CATALOG.get(gesture)
        duration = min(spec.duration_sec if spec else 1.0, ACTION_TIMEOUT)
        self._trace.log_action(event.trace_id, gesture.value, "START")
        logger.info("[Action] EXECUTE %s — %s (timeout=%.1fs)", gesture.value, describe(gesture), duration)

        start = SystemClock.now()
        try:
            if gesture == GestureType.WAVE:
                self.wave()
            elif gesture == GestureType.POINT:
                self.point(event.payload.get("target", "forward"))
            elif gesture == GestureType.QUESTION_MARK:
                self.question_mark()
            elif gesture == GestureType.TURN_HEAD:
                self.turn_head(event.payload.get("angle", 30))
            time.sleep(min(duration, 0.3))
        except Exception as exc:
            self._publish_failed(event, str(exc))
            return

        elapsed = SystemClock.now() - start
        if elapsed > ACTION_TIMEOUT:
            self._publish_failed(event, "timeout")
            return

        self._trace.log_action(event.trace_id, gesture.value, "DONE")
        self._bus.publish(
            Event.from_parent(
                event,
                EventType.ACTION_COMPLETED,
                source="action_executor",
                payload={"gesture": gesture.value, "elapsed": elapsed},
            )
        )

    def _publish_failed(self, event: Event, reason: str) -> None:
        gesture = event.payload.get("gesture", "unknown")
        self._trace.log_action(event.trace_id, gesture, f"FAIL:{reason}")
        self._bus.publish(
            Event.from_parent(
                event,
                EventType.ACTION_FAILED,
                source="action_executor",
                payload={"gesture": gesture, "reason": reason},
            )
        )

    def wave(self) -> None:
        logger.info("[Action] >>> wave()")

    def turn_head(self, angle: float = 30) -> None:
        logger.info("[Action] >>> turn_head(%.1f°)", angle)

    def question_mark(self) -> None:
        logger.info("[Action] >>> question_mark()")

    def point(self, target: str = "forward") -> None:
        logger.info("[Action] >>> point(%s)", target)

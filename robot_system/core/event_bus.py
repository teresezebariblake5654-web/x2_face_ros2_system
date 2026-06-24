"""Thread-safe EventBus — validate, trace, fan-out dispatch only."""

from __future__ import annotations

import queue
import threading
from typing import Dict, List, Optional, Set

from config import EVENT_QUEUE_MAX_SIZE
from core.event_validator import EventValidator
from core.system_clock import SystemClock
from core.trace_logger import TraceLogger
from core.types import Event, EventType, Priority
from utils.logger import get_logger

logger = get_logger(__name__)


class EventBus:
    """Pure event distribution — no business logic."""

    def __init__(self, maxsize: int = EVENT_QUEUE_MAX_SIZE) -> None:
        self._ingress: queue.Queue[Event] = queue.Queue(maxsize=maxsize)
        self._consumer_queues: Dict[str, queue.Queue[Event]] = {}
        self._consumer_filters: Dict[str, Optional[Set[EventType]]] = {}
        self._lock = threading.Lock()
        self._running = True
        self._validator = EventValidator()
        self._trace = TraceLogger.get()
        self._stats = {"published": 0, "dispatched": 0, "rejected": 0}
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop, name="EventBusDispatcher", daemon=True
        )
        self._dispatcher.start()

    def register_consumer(
        self,
        name: str,
        event_types: Optional[List[EventType]] = None,
        maxsize: int = EVENT_QUEUE_MAX_SIZE,
    ) -> None:
        with self._lock:
            if name in self._consumer_queues:
                return
            self._consumer_queues[name] = queue.Queue(maxsize=maxsize)
            self._consumer_filters[name] = set(event_types) if event_types else None

    def publish(self, event: Event) -> None:
        if not self._running:
            logger.warning("EventBus stopped; dropping %s", event)
            return

        if event.timestamp <= 0:
            event.timestamp = SystemClock.now()

        if not self._validator.validate_or_warn(event):
            with self._lock:
                self._stats["rejected"] += 1
            return

        self._trace.log_lifecycle(
            event.trace_id, "EventBus", "PUBLISH", f"{event.type.value} id={event.event_id}"
        )

        try:
            self._ingress.put(event, block=False)
            with self._lock:
                self._stats["published"] += 1
        except queue.Full:
            logger.error("EventBus ingress full; dropped %s", event.type.value)

    def get_event(self, consumer: str, timeout: float = 0.5) -> Optional[Event]:
        q = self._consumer_queues.get(consumer)
        if q is None:
            raise KeyError(f"Unknown consumer '{consumer}'")
        try:
            event = q.get(timeout=timeout)
            self._trace.log_lifecycle(
                event.trace_id, consumer, "CONSUME", event.type.value
            )
            return event
        except queue.Empty:
            return None

    def drain(self, consumer: str, max_items: int = 64) -> List[Event]:
        q = self._consumer_queues.get(consumer)
        if q is None:
            return []
        events: List[Event] = []
        for _ in range(max_items):
            try:
                event = q.get_nowait()
                self._trace.log_lifecycle(
                    event.trace_id, consumer, "DRAIN", event.type.value
                )
                events.append(event)
            except queue.Empty:
                break
        return events

    def _dispatch_loop(self) -> None:
        while self._running:
            try:
                event = self._ingress.get(timeout=0.1)
            except queue.Empty:
                continue
            with self._lock:
                routes = list(self._consumer_queues.items())
                filters = dict(self._consumer_filters)
            for name, q in routes:
                allowed = filters.get(name)
                if allowed is not None and event.type not in allowed:
                    continue
                try:
                    q.put(event, block=False)
                    with self._lock:
                        self._stats["dispatched"] += 1
                except queue.Full:
                    logger.error("Consumer '%s' queue full; dropped %s", name, event.type.value)

    def stop(self) -> None:
        self._running = False
        self._dispatcher.join(timeout=2.0)

    @property
    def stats(self) -> dict:
        with self._lock:
            return dict(self._stats)

    def publish_tick(self, source: str = "main") -> None:
        self.publish(
            Event(
                type=EventType.SYSTEM_TICK,
                source=source,
                priority=Priority.LOW,
                payload={},
            )
        )

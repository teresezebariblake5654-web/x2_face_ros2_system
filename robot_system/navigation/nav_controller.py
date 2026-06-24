"""Industrial navigation controller — timeout, retry, result FSM."""

from __future__ import annotations

import threading
import time

from config import NAV_RETRY_MAX, NAV_TIMEOUT
from core.event_bus import EventBus
from core.system_clock import SystemClock
from core.trace_logger import TraceLogger
from core.types import Event, EventType, NavResult, Priority
from navigation.nav_client import NavClient
from utils.logger import get_logger

logger = get_logger(__name__)


class NavController:
    """Only module allowed to call NavClient."""

    def __init__(self, bus: EventBus, nav_client: NavClient) -> None:
        self._bus = bus
        self._nav = nav_client
        self._trace = TraceLogger.get()
        self._running = False
        self._thread: threading.Thread | None = None
        self._busy = threading.Lock()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="NavController", daemon=True)
        self._thread.start()
        logger.info("NavController started (timeout=%.0fs, retry=%d)", NAV_TIMEOUT, NAV_RETRY_MAX)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=NAV_TIMEOUT + 2)

    def _loop(self) -> None:
        while self._running:
            event = self._bus.get_event("nav_controller", timeout=0.2)
            if event and event.type == EventType.NAV_EXECUTE:
                threading.Thread(
                    target=self._execute_nav,
                    args=(event,),
                    name=f"NavJob-{event.trace_id[:8]}",
                    daemon=True,
                ).start()

    def _execute_nav(self, event: Event) -> None:
        if not self._busy.acquire(blocking=False):
            self._emit_failed(
                event,
                NavResult.REJECTED,
                "controller_busy",
                retries=0,
            )
            return

        try:
            action = event.payload.get("action", "go_to")
            location = event.payload.get("location", "lobby")
            self._trace.log_chain(event.trace_id, "NAV", "START", location)

            self._bus.publish(
                Event.from_parent(
                    event,
                    EventType.NAV_STARTED,
                    source="nav_controller",
                    priority=Priority.CRITICAL,
                    payload={"action": action, "location": location},
                )
            )

            result, retries = self._run_with_retry(event, action, location)
            if result == NavResult.SUCCESS:
                self._bus.publish(
                    Event.from_parent(
                        event,
                        EventType.NAV_COMPLETED,
                        source="nav_controller",
                        priority=Priority.CRITICAL,
                        payload={
                            "action": action,
                            "location": location,
                            "result": result.value,
                            "success": True,
                            "retries": retries,
                        },
                    )
                )
                logger.info("[NavController] SUCCESS %s -> %s (retries=%d)", action, location, retries)
            else:
                self._emit_failed(event, result, f"nav_{result.value.lower()}", retries)
        finally:
            self._busy.release()

    def _run_with_retry(self, event: Event, action: str, location: str) -> tuple[NavResult, int]:
        deadline = SystemClock.now() + NAV_TIMEOUT
        last_result = NavResult.FAILED

        for attempt in range(NAV_RETRY_MAX + 1):
            if SystemClock.now() >= deadline:
                return NavResult.TIMEOUT, attempt

            remaining = deadline - SystemClock.now()
            success = self._call_sdk(action, location, min(remaining, NAV_TIMEOUT / 2))
            if success:
                return NavResult.SUCCESS, attempt

            last_result = NavResult.FAILED
            if attempt < NAV_RETRY_MAX:
                logger.warning("[NavController] retry %d/%d", attempt + 1, NAV_RETRY_MAX)
                time.sleep(0.3)

        if SystemClock.now() >= deadline:
            return NavResult.TIMEOUT, NAV_RETRY_MAX
        return last_result, NAV_RETRY_MAX

    def _call_sdk(self, action: str, location: str, timeout: float) -> bool:
        start = SystemClock.now()
        if action == "return_to_charge":
            ok = self._nav.return_to_charge()
        else:
            ok = self._nav.go_to(location)
        elapsed = SystemClock.now() - start
        if elapsed > timeout:
            logger.warning("[NavController] SDK call exceeded slice (%.2fs)", elapsed)
            return False
        return ok

    def _emit_failed(
        self,
        event: Event,
        result: NavResult,
        reason: str,
        retries: int,
    ) -> None:
        action = event.payload.get("action", "go_to")
        location = event.payload.get("location", "lobby")
        self._trace.log_chain(event.trace_id, "NAV", "FAILED", result.value)
        self._bus.publish(
            Event.from_parent(
                event,
                EventType.NAV_FAILED,
                source="nav_controller",
                priority=Priority.CRITICAL,
                payload={
                    "action": action,
                    "location": location,
                    "result": result.value,
                    "reason": reason,
                    "retries": retries,
                },
            )
        )
        logger.error("[NavController] FAILED %s result=%s reason=%s", location, result.value, reason)

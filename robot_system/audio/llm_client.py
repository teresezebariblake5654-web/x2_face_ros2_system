"""Mock LLM client — structured output, no action/nav side effects."""

from __future__ import annotations

import threading

from core.event_bus import EventBus
from core.trace_logger import TraceLogger
from core.types import Event, EventType, LLMIntent, LLMResponse, Priority
from utils.logger import get_logger

logger = get_logger(__name__)


class LLMClient:
    """Listens for LLM_REQUEST, replies with structured LLM_MESSAGE only."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._trace = TraceLogger.get()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="LLMClient", daemon=True)
        self._thread.start()
        logger.info("LLMClient started (structured mock, offline)")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while self._running:
            event = self._bus.get_event("llm_client", timeout=0.2)
            if event and event.type == EventType.LLM_REQUEST:
                self._handle_request(event)

    def _handle_request(self, event: Event) -> None:
        user_text = event.payload.get("text", "")
        context = event.payload.get("context", {})
        response = self.generate_structured(user_text, context)
        self._trace.log_chain(event.trace_id, "LLM", "RESPONSE", response.intent.value)
        logger.info(
            "[LLM] intent=%s conf=%.2f text=%s",
            response.intent.value,
            response.confidence,
            response.text[:60],
        )
        payload = response.to_dict()
        payload["request_id"] = event.event_id
        payload["context"] = context
        self._bus.publish(
            Event.from_parent(
                event,
                EventType.LLM_MESSAGE,
                source="llm_client",
                priority=Priority.HIGH,
                payload=payload,
            )
        )

    @staticmethod
    def generate_structured(text: str, context: dict | None = None) -> LLMResponse:
        """Pure text generation — structured, no side effects."""
        context = context or {}
        if context.get("intent") == "greet":
            name = context.get("name", "朋友")
            return LLMResponse(
                text=f"您好，{name}！很高兴再次见到您。",
                intent=LLMIntent.SMALLTALK,
                confidence=0.92,
            )
        if context.get("intent") == "unknown":
            return LLMResponse(
                text="您好，我暂时还不认识您。如需登记，请联系工作人员。",
                intent=LLMIntent.UNKNOWN,
                confidence=0.88,
            )
        if "天气" in text or "?" in text or "？" in text:
            return LLMResponse(
                text="今天天气不错，适合参观体验。",
                intent=LLMIntent.QUESTION,
                confidence=0.75,
            )
        if any(k in text.lower() for k in ("你好", "您好", "hello", "hi")):
            return LLMResponse(
                text="您好！欢迎来到我们的展厅，有什么可以帮您的吗？",
                intent=LLMIntent.SMALLTALK,
                confidence=0.85,
            )
        return LLMResponse(
            text="好的，我明白了。还有其他问题吗？",
            intent=LLMIntent.SMALLTALK,
            confidence=0.70,
        )

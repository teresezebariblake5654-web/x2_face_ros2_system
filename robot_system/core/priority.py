"""Priority arbitration for conflicting robot behaviors."""

from __future__ import annotations

from core.types import Event, EventType, Priority, RobotState

EVENT_PRIORITY_MAP: dict[EventType, Priority] = {
    EventType.NAV_REQUEST: Priority.CRITICAL,
    EventType.NAV_EXECUTE: Priority.CRITICAL,
    EventType.NAV_STARTED: Priority.CRITICAL,
    EventType.NAV_COMPLETED: Priority.CRITICAL,
    EventType.NAV_FAILED: Priority.CRITICAL,
    EventType.LLM_MESSAGE: Priority.HIGH,
    EventType.LLM_REQUEST: Priority.HIGH,
    EventType.FACE_RECOGNIZED: Priority.NORMAL,
    EventType.FACE_UNKNOWN: Priority.NORMAL,
    EventType.FACE_DEPARTED: Priority.NORMAL,
    EventType.ACTION_REQUEST: Priority.NORMAL,
    EventType.TTS_REQUEST: Priority.NORMAL,
    EventType.FACE_RAW_DETECTED: Priority.NORMAL,
    EventType.ENROLL_CANDIDATE: Priority.LOW,
    EventType.SYSTEM_TICK: Priority.LOW,
    EventType.STATE_CHANGED: Priority.LOW,
    EventType.FSM_TIMER_EXPIRED: Priority.LOW,
    EventType.GREETING_COMPLETE: Priority.NORMAL,
}

STATE_BLOCK_RULES: dict[RobotState, set[EventType]] = {
    RobotState.NAVIGATION: {
        EventType.FACE_RECOGNIZED,
        EventType.FACE_UNKNOWN,
        EventType.LLM_REQUEST,
    },
    RobotState.COOLDOWN: {
        EventType.FACE_RECOGNIZED,
        EventType.FACE_UNKNOWN,
    },
    RobotState.GREETING: {
        EventType.FACE_RECOGNIZED,
        EventType.FACE_UNKNOWN,
        EventType.FACE_DEPARTED,
        EventType.NAV_REQUEST,
    },
    RobotState.ERROR: {
        EventType.FACE_RECOGNIZED,
        EventType.FACE_UNKNOWN,
        EventType.NAV_REQUEST,
        EventType.LLM_REQUEST,
    },
}


class PriorityArbiter:
    def __init__(self) -> None:
        self._current_task_priority: Priority = Priority.LOW

    def event_priority(self, event: Event) -> Priority:
        return EVENT_PRIORITY_MAP.get(event.type, event.priority)

    def set_active_priority(self, priority: Priority) -> None:
        self._current_task_priority = priority

    def clear_active_priority(self) -> None:
        self._current_task_priority = Priority.LOW

    def can_process(self, event: Event, state: RobotState) -> tuple[bool, str]:
        prio = self.event_priority(event)
        blocked = STATE_BLOCK_RULES.get(state, set())
        if event.type in blocked:
            return False, f"blocked by state {state.value}"

        if prio < self._current_task_priority and event.type not in (
            EventType.SYSTEM_TICK,
            EventType.STATE_CHANGED,
            EventType.NAV_COMPLETED,
            EventType.NAV_FAILED,
            EventType.FSM_TIMER_EXPIRED,
            EventType.LLM_MESSAGE,
            EventType.ENROLL_CANDIDATE,
        ):
            return False, f"priority {prio.name} < active {self._current_task_priority.name}"
        return True, "ok"

    def should_preempt(self, event: Event, state: RobotState) -> bool:
        if event.type != EventType.NAV_REQUEST:
            return False
        return state in (RobotState.DIALOG, RobotState.GREETING, RobotState.COOLDOWN)

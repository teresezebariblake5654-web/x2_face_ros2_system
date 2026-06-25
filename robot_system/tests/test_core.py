"""Unit tests for robot_system core modules."""

from __future__ import annotations

import os
import tempfile
import unittest

import numpy as np

from core.cooldown_manager import CooldownManager
from core.event_bus import EventBus
from core.state_machine import StateMachine
from core.types import Event, EventType, NavResult, RobotState
from core.policy_types import CommandType
from behavior.farewell_policy import FarewellPolicy
from behavior.greeting_policy import GreetingPolicy
from vision.face_db import FaceDB, _normalize


class StateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._bus = EventBus()
        self.sm = StateMachine(self._bus, CooldownManager())

    def tearDown(self) -> None:
        self._bus.stop()

    def test_greet_flow(self) -> None:
        evt = Event(
            type=EventType.FACE_RECOGNIZED,
            source="test",
            payload={"person_id": "user_0001"},
        )
        self.sm.transition(evt)
        self.assertEqual(self.sm.state, RobotState.GREETING)
        done = Event.from_parent(evt, EventType.GREETING_COMPLETE, source="test", payload={})
        self.sm.transition(done)
        self.assertEqual(self.sm.state, RobotState.COOLDOWN)

    def test_nav_only_from_idle(self) -> None:
        cooldown = Event(
            type=EventType.GREETING_COMPLETE,
            source="test",
            payload={"person_id": "x"},
        )
        self.sm._state = RobotState.COOLDOWN
        nav = Event(type=EventType.NAV_REQUEST, source="test", payload={"location": "lobby"})
        self.sm.transition(nav)
        self.assertEqual(self.sm.state, RobotState.COOLDOWN)

    def test_nav_failed_enters_error(self) -> None:
        self.sm._state = RobotState.NAVIGATION
        failed = Event(type=EventType.NAV_FAILED, source="test", payload={})
        self.sm.transition(failed)
        self.assertEqual(self.sm.state, RobotState.ERROR)


class GreetingPolicyTests(unittest.TestCase):
    def test_vip_strategy_uses_yaml_angle(self) -> None:
        policy = GreetingPolicy()
        cmds = policy._gesture_commands("executive")
        turn = next(c for c in cmds if c.payload.get("gesture") == "turn_head")
        self.assertEqual(turn.payload["angle"], 30.0)

    def test_guard_pending_returns_no_commands(self) -> None:
        policy = GreetingPolicy()
        evt = Event(
            type=EventType.FACE_RECOGNIZED,
            source="test",
            payload={
                "person_id": "user_0001",
                "name": "测试",
                "vip_level": "consultant",
                "in_welcome_zone": True,
                "person_count": 1,
            },
        )
        outcome = policy.known_face(evt, RobotState.IDLE, True)
        self.assertEqual(outcome.notes, "guard_pending")
        self.assertEqual(outcome.commands, [])


class FarewellPolicyTests(unittest.TestCase):
    def test_departed_emits_tts(self) -> None:
        policy = FarewellPolicy()
        evt = Event(
            type=EventType.FACE_DEPARTED,
            source="test",
            payload={"person_id": "user_0001", "name": "张三"},
        )
        outcome = policy.departed(evt, RobotState.IDLE)
        self.assertEqual(outcome.notes, "farewell")
        self.assertTrue(any(c.cmd_type == CommandType.TTS for c in outcome.commands))


class FaceDBPersistenceTests(unittest.TestCase):
    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "face_db.json")
            db = FaceDB(size=0, seed=False, persist_path=path)
            emb = _normalize(np.random.randn(128).astype(np.float32))
            pid = db.add_person("持久化测试", emb, is_vip=True)

            db2 = FaceDB(size=0, seed=False, persist_path=path)
            self.assertEqual(db2.get_name(pid), "持久化测试")
            self.assertEqual(db2.get_vip_level(pid), "vip_customer")


if __name__ == "__main__":
    unittest.main()

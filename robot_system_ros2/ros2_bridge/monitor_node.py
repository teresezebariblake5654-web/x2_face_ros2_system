#!/usr/bin/env python3
"""System monitor — 1Hz /system_health observability publisher."""

from __future__ import annotations

import json
import os
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from ros2_bridge.bus_adapter import QoSProfiles
from ros2_bridge.core.event_metrics import EventMetrics
from ros2_bridge.core.runtime_state import RuntimeState
from ros2_bridge.event_codec import decode_event
from ros2_bridge.node_utils import init_runtime_state, install_heartbeat
from ros2_bridge.node_watchdog import NodeWatchdog


class MonitorNode(Node):
    def __init__(self) -> None:
        super().__init__("monitor_node")
        init_runtime_state(self)
        install_heartbeat(self)

        self._runtime = RuntimeState.instance()
        self._metrics = EventMetrics.get()
        self._watchdog = NodeWatchdog.get()
        self._system_mode = "FULL"
        self._start_time = time.monotonic()
        self._process_start = time.process_time()

        self._health_pub = self.create_publisher(String, "/system_health", QoSProfiles.COMMANDS)
        self.create_subscription(
            String,
            "/robot_events",
            self._on_robot_event,
            QoSProfiles.ROBOT_EVENTS,
        )
        self.create_subscription(
            String,
            "/node_heartbeat",
            self._on_node_heartbeat,
            QoSProfiles.COMMANDS,
        )
        self.create_subscription(
            String,
            "/system_mode",
            self._on_system_mode,
            QoSProfiles.COMMANDS,
        )
        self.create_timer(1.0, self._publish_health)
        self.get_logger().info("MonitorNode online — publishing /system_health at 1Hz")

    def _on_node_heartbeat(self, msg: String) -> None:
        self._watchdog.record_heartbeat(msg.data)

    def _on_system_mode(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            mode = data.get("mode")
            if mode:
                self._system_mode = mode
        except (json.JSONDecodeError, TypeError):
            pass

    def _on_robot_event(self, msg: String) -> None:
        try:
            event = decode_event(msg.data)
        except Exception:
            self._metrics.record_drop()
            return

        from ros2_bridge.event_codec import _LEGACY_TO_V1  # noqa: WPS433

        v1 = _LEGACY_TO_V1.get(event.type, event.type.value)
        source = event.source or "unknown"
        self._metrics.record_event(v1, event.trace_id, source)

        if v1 in ("FACE_RECOGNIZED", "FACE_UNKNOWN"):
            self._runtime.update("last_face_time", time.monotonic())
            pid = event.payload.get("person_id")
            if pid:
                self._runtime.update("current_person_id", pid)

        if event.type.value.startswith("NAV"):
            if event.type.value in ("NAV_STARTED", "NAV_EXECUTE"):
                self._metrics.set_nav_status("busy")
                self._runtime.update("is_nav_busy", True)
            elif event.type.value in ("NAV_COMPLETED", "NAV_FAILED"):
                self._metrics.set_nav_status("idle")
                self._runtime.update("is_nav_busy", False)

        if event.type.value.startswith("ACTION"):
            if event.type.value == "ACTION_REQUEST":
                self._runtime.update("is_action_busy", True)
                self._runtime.update("last_action_time", time.monotonic())
            elif event.type.value in ("ACTION_COMPLETED", "ACTION_FAILED"):
                self._runtime.update("is_action_busy", False)

        if event.type.value == "TTS_REQUEST":
            self._runtime.update("is_speaking", True)
        if event.type.value == "LLM_MESSAGE":
            self._runtime.update("is_speaking", False)

        if event.type.value == "STATE_CHANGED":
            to_state = event.payload.get("to")
            if to_state:
                self._runtime.update("current_fsm_state", to_state)

    def _publish_health(self) -> None:
        cpu_time = time.process_time() - self._process_start
        uptime = time.monotonic() - self._start_time
        metrics = self._metrics.snapshot()
        runtime = self._runtime.snapshot()
        node_status = self._watchdog.get_node_status()

        health = {
            "schema": "1.0",
            "timestamp": time.monotonic(),
            "uptime_sec": round(uptime, 2),
            "node_alive_map": metrics["node_alive_map"],
            "node_status": node_status,
            "failed_nodes_count": self._watchdog.failed_nodes_count(),
            "mode": self._system_mode,
            "event_rate": metrics["event_rate"],
            "avg_latency_face_to_action": round(metrics["avg_latency_face_to_action"], 4),
            "dropped_events_count": metrics["dropped_events_count"],
            "nav_status": metrics["nav_status"],
            "cpu_time_monitor_sec": round(cpu_time, 4),
            "runtime_state": runtime,
            "pid": os.getpid(),
        }

        msg = String()
        msg.data = json.dumps(health, ensure_ascii=False)
        self._health_pub.publish(msg)
        self._runtime.update("system_health", {"status": "monitoring", "last_publish": time.monotonic()})


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MonitorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        RuntimeState.instance().record_error("monitor_node", str(exc))
        node.get_logger().error(f"Monitor degraded: {exc}")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

from launch import LaunchDescription
from launch.actions import LogInfo, TimerAction
from launch_ros.actions import Node


def _node(name: str, executable: str, delay: float = 0.0) -> TimerAction:
    return TimerAction(
        period=delay,
        actions=[
            Node(
                package="robot_system_ros2",
                executable=executable,
                name=name,
                output="screen",
            ),
        ],
    )


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        LogInfo(msg="[launch] robot_system_ros2 v1.0 — RuntimeState pipeline starting"),
        _node("event_bridge_node", "event_bridge_node", 0.0),
        _node("vision_node", "vision_node", 1.0),
        _node("brain_node", "brain_node", 2.0),
        LogInfo(msg="[launch] brain_node scheduled — RuntimeState watchdog active"),
        _node("action_node", "action_node", 3.0),
        _node("nav_node", "nav_node", 3.0),
        _node("audio_node", "audio_node", 3.0),
        _node("monitor_node", "monitor_node", 4.0),
        LogInfo(msg="[launch] All nodes scheduled (staggered startup)"),
    ])

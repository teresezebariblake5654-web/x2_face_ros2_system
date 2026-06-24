from setuptools import setup

package_name = "robot_system_ros2"

setup(
    name=package_name,
    version="0.1.0",
    packages=["ros2_bridge", "ros2_bridge.core"],
    package_dir={"": "."},
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/robot_system.launch.py"]),
    ],
    install_requires=["setuptools", "numpy"],
    zip_safe=True,
    maintainer="robot_system",
    maintainer_email="dev@robot.local",
    description="ROS2 wrapper nodes for robot_system",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "vision_node = ros2_bridge.vision_node:main",
            "brain_node = ros2_bridge.brain_node:main",
            "action_node = ros2_bridge.action_node:main",
            "nav_node = ros2_bridge.nav_node:main",
            "audio_node = ros2_bridge.audio_node:main",
            "event_bridge_node = ros2_bridge.event_bridge_node:main",
            "monitor_node = ros2_bridge.monitor_node:main",
        ],
    },
)

cmake_minimum_required(VERSION 3.8)
project(robot_system_ros2)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(geometry_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/Event.msg"
  "msg/Action.msg"
  "msg/NavGoal.msg"
  "msg/Face.msg"
  DEPENDENCIES geometry_msgs
)

ament_export_dependencies(rosidl_default_runtime)

# Install python package (modules only; scripts installed below)
ament_python_install_package(ros2_bridge
  PACKAGE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/ros2_bridge
)

# Install node executables from wrapper scripts (entry_points equivalent)
set(_ros2_nodes
  event_bridge_node
  brain_node
  vision_node
  action_node
  nav_node
  audio_node
  monitor_node
)
foreach(_node ${_ros2_nodes})
  install(PROGRAMS
    ${CMAKE_CURRENT_SOURCE_DIR}/ros2_bridge/${_node}.py
    DESTINATION lib/${PROJECT_NAME}
    RENAME ${_node}
  )
endforeach()

# Install robot_system source tree for runtime import (wrapper only)
install(
  DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/../robot_system/
  DESTINATION share/${PROJECT_NAME}/robot_system
  FILES_MATCHING
  PATTERN "*.py"
  PATTERN "*.yaml"
)

# Install launch files
install(
  DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

ament_package()

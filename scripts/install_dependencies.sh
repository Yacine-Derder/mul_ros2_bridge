#!/usr/bin/env bash
set -euo pipefail
# Explicit operator invocation; does not run as part of deployment rendering.
sudo apt-get update
sudo apt-get install -y python3-colcon-common-extensions python3-serial python3-pytest python3-yaml \
  ros-jazzy-ros-base ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-diagnostic-msgs \
  ros-jazzy-rosidl-default-generators ros-jazzy-rosbag2

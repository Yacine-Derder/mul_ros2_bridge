#!/usr/bin/env bash
set -eo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source /opt/ros/jazzy/setup.bash
cd "$ROOT"
# Keep offline testing independent of the running robot's DDS participants.
export ROS_DOMAIN_ID=212
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
colcon build --event-handlers console_cohesion+
source "$ROOT/install/setup.bash"
colcon test --event-handlers console_cohesion+ --return-code-on-test-failure
colcon test-result --verbose

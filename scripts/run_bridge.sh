#!/usr/bin/env bash
set -eo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
: "${ALR_ID:?set ALR_ID to 132..135}"
source /opt/ros/jazzy/setup.bash
source "$ROOT/install/setup.bash"
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-42}
export RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}
args=("alr_id:=$ALR_ID" "baud_rate:=${BAUD_RATE:-115200}")
if [[ -n ${SERIAL_DEVICE:-} ]]; then
  args+=("serial_device:=$SERIAL_DEVICE")
fi
exec ros2 launch mul_lps_bridge bridge.launch.py "${args[@]}"

# Deployment, operation and rollback

These are operator instructions. No remote robot was accessed and no system service was changed during implementation.

## Each ALR

Authenticate to the private GitHub repository, clone into `/home/waverover/mul_ros2_ws`, then run `scripts/install_dependencies.sh` if needed and `scripts/build_and_test.sh`. The latter can be rerun. Do not source the unrelated WaveRover workspace to build this overlay. Source `/opt/ros/jazzy/setup.bash` followed by this workspace's `install/setup.bash` for use. Defaults align with existing Cyclone DDS and domain 42; offline tests use localhost domain 212. PC subscribers need a compatible ROS setup, message package and DDS domain/discovery connectivity.

Select the correct LPS stable path using `ls -l /dev/serial/by-id/`. For access, inspect `id` and device group permissions. If necessary the operator can run `sudo usermod -aG dialout waverover` and log out/in. Avoid world-writable chmod and running ROS as root. Ensure another serial monitor or bridge is not holding the port. The exclusive POSIX lock is advisory against cooperating processes; it cannot prevent arbitrary programs bypassing it.

A normal launch is shown in README. `ALR_ID=133 SERIAL_DEVICE=/dev/serial/by-id/... ./scripts/run_bridge.sh` is another foreground entry point. The role follows firmware automatically; the bridge does not set reference/follower roles or plans. Configuration paths and launch overrides allow real differences in device/baud/rate warning timeout without code forks. Serial startup is not guaranteed to start RF: the firmware must already be configured by the operator. Do not use bridge installation as an implicit firmware configuration step.

## Optional systemd (after physical acceptance)

Render idempotently, substituting host ID and stable serial path:

```bash
cd /home/waverover/mul_ros2_ws
./scripts/deploy.sh --alr-id 132 --device /dev/serial/by-id/YOUR_LPS_DEVICE --baud 115200
```

This writes only ignored `deployment/` files, with no daemon reload, service install or enable. Review the rendered unit and env. Paths/users with unsupported interpolation characters are rejected. Then the operator may explicitly activate:

```bash
sudo install -d -m 0755 /etc/mul_lps_bridge
sudo install -m 0644 deployment/132.env /etc/mul_lps_bridge/132.env
sudo install -m 0644 deployment/mul-lps-bridge@.service /etc/systemd/system/mul-lps-bridge@.service
sudo systemctl daemon-reload
sudo systemctl enable --now mul-lps-bridge@132.service
systemctl status mul-lps-bridge@132.service
journalctl -u mul-lps-bridge@132.service -f
```

For 133–135 use their matching env/instance. The unit runs as the rendering user with `dialout`, sources Jazzy and this overlay, uses domain 42/Cyclone DDS, and restarts on process failure. Serial disconnects are normally recovered within the running process. It does not depend on or modify `waverover.service`. Never launch a second bridge against the same serial descriptor. Stop the optional bridge service before running acceptance again. Raw logging is off for normal service use by default; configure a writable, rotated raw-log path in a reviewed YAML/launch extension if desired.

## Debugging

- No connection: inspect `/uwb/alr_ID/connection` last_error, device existence, permissions, ambiguous autodetection or another serial owner. Retry is automatic; there is no need to restart the robot stack.
- Connected but stale: confirm firmware version/verbosity/plan and its expected emission patterns manually. Quiet can suppress success; older firmware/AR emits human text without MR1. Bridge never changes firmware to fix silence. An idle tty read is not an unplug event.
- Malformed/oversized: enable `raw_log:=/absolute/writable/raw.log`, inspect hex chunks and pinned MR1 contract; verify baud and firmware generation. No log is automatically uploaded.
- Reporter mismatch: validate USB board and host mapping; changing host identity does not change firmware reporter. Measurements remain published.
- Queue drops: inspect CPU/storage/DDS subscriber pressure and increase bounded queue/depth or batch only with a measured reason. Raw logging can add storage load. Status measures parser traffic, not network delivery.
- No remote topic: check domain, RMW, namespace and subscriber QoS, then DDS networking/discovery separately. This package does not reconfigure the network. Status subscribers wanting retained state must request transient-local.
- Apparent time jumps: host reception time is wall clock; firmware markers wrap and are local. Compare only with a justified PC clock model and capture/boot context.

## Rollback

Operator: `sudo systemctl disable --now mul-lps-bridge@132.service` stops only this optional instance. Remove its env/unit if retiring it, then daemon-reload. For a code rollback stop this instance, select a known git commit in this workspace and rebuild/test before relaunch. To avoid stale install files after incompatible package changes, remove only this workspace's `build/`, `install/` and `log/` before rebuilding. Keep evidence separately. The WaveRover service and workspace need no rollback because they are untouched.

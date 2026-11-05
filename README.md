# MUL ROS 2 bridge

Standalone ROS 2 Jazzy workspace for ALRs 132–135 on Ubuntu 24.04. One read-only Python bridge handles reference and follower radios, AA and FF, and preserves endpoint reports and failures for PC aggregation. It does no deduplication, range filtering, geometry estimation, clock synchronization, firmware configuration or serial command transmission.

Private repository: https://github.com/Yacine-Derder/mul_ros2_bridge . Firmware contract is pinned in [PROTOCOL.md](docs/PROTOCOL.md); actual installed firmware version remains a hardware check.

## Build and verify

```bash
cd /home/waverover/mul_ros2_ws
# Only if dependencies are missing (uses apt/sudo):
./scripts/install_dependencies.sh
./scripts/build_and_test.sh
```

Current local result: **92 offline tests passed, none failed or skipped; both packages build and install.**

The build/test script installs into this workspace with colcon, sources Jazzy and the new overlay, and runs the offline tests on domain 212 with localhost discovery and Cyclone DDS. It opens only generated pseudo-terminals, never physical serial devices. It returns nonzero for build/test failures. No changes to shell startup, networking or WaveRover services are needed. Dependencies are declared in package manifests; `rosdep install --from-paths src --ignore-src -r -y --rosdistro jazzy` is an alternative dependency installation method on a ROS-configured host.

## Physical retest: operator only

```bash
/home/waverover/mul_ros2_ws/scripts/acceptance_test.sh --duration 60
```

Run only after the ongoing recording has finished and released the serial port. Select the LPS by-id device, confirm baud (default 115200) and type `yes`. The script launches its own bridge in domain 42 by default, subscribes to typed ranges/status/diagnostics, saves JSONL and rotating raw-byte logs, checks every received measurement against its raw MR1 record, prints PASS/FAIL, and stops its own processes. Add `--rosbag` to record those three topics. `--output /absolute/new/directory`, `--min-messages N`, `--min-success N`, `--require-kinds 1 4`, `--stale-timeout SECONDS` and `--duration SECONDS` control capture and checks. Use `--help` for all options. Unattended use requires an explicit `--device /dev/serial/by-id/... --baud 115200 --yes`.

PASS requires at least one message and one successful measurement by default, matching reporter/host identity, consistent parsed fields, no observed sequence gaps, no malformed/oversized/dropped records or raw-log write errors, current connection and diagnostics, and a running bridge through capture. Failed ranges are retained and allowed. FF is not required unless explicitly requested: the active plan may not schedule it. PASS confirms the serial/ROS path, not physical accuracy, all six geometry edges, clock synchronization or firmware RF reliability. Evidence defaults to ignored `evidence/`; do not commit logs. See [HANDOFF.md](docs/HANDOFF.md).

## Launch after hardware approval

```bash
source /opt/ros/jazzy/setup.bash
source /home/waverover/mul_ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=42 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ros2 launch mul_lps_bridge bridge.launch.py alr_id:=132 serial_device:=/dev/serial/by-id/YOUR_LPS_DEVICE baud_rate:=115200
```

Substitute `alr_id:=133`, `134` or `135` on that host; no role setting or code change is needed when reference ownership changes. Default topics are `/uwb/alr_<ID>/ranges`, `/connection` and `/diagnostics` under the same prefix. Override `namespace:=/custom/prefix` if needed. `config:=/absolute/custom.yaml` selects a custom YAML; the selected launch ALR ID always overrides YAML identity. Without launch, `ros2 run mul_lps_bridge bridge --ros-args -p alr_id:=132` also uses the standard prefix. An explicit ROS namespace takes precedence.

Unset or empty `SERIAL_DEVICE` in `scripts/run_bridge.sh` omits the optional launch argument; `ALR_ID` remains required and `BAUD_RATE` defaults to 115200. Omitted `serial_device` auto-selects only when exactly one distinct `/dev/serial/by-id/*Bitcraze*` device exists. It retries when absent or ambiguous and never falls back to arbitrary ttyUSB/ttyACM devices. Stable device IDs are preferred; no board serial number is committed. Explicit paths support adapters and PTYs. The driver requests exclusive access, asserts DTR and disables RTS before every open, including automatic reconnects. Bitcraze USB CDC firmware uses DTR to recognize an active serial client and gate ongoing telemetry; RTS is unused and hardware flow control stays disabled. This handshake sends no serial commands. Actual USB/OS behavior must be verified on each host; ALR 132 passed the November 5 retest. Stop other monitors first. Metadata-only `ls -l /dev/serial/by-id/` is safe for device discovery.

```bash
ros2 topic echo /uwb/alr_132/ranges
ros2 topic echo /uwb/alr_132/connection --qos-durability transient_local
ros2 topic echo /uwb/alr_132/diagnostics
ros2 topic hz /uwb/alr_132/ranges
ros2 topic info /uwb/alr_132/ranges --verbose
```

Ranges default to reliable, volatile KEEP_LAST depth 100. Status is reliable/transient-local depth 1; diagnostics reliable/volatile depth 10. For best-effort ranges set `qos_reliability: best_effort` in YAML and use compatible subscribers (`ros2 topic echo ... --qos-reliability best_effort`). Finite queues can lose data; counters and sequence gaps expose bridge overflow. DDS/network loss outside the bridge requires subscriber-side monitoring.

## Packages and parameters

`mul_interfaces` generates `RangeMeasurement` and `ConnectionStatus` C/Python type support. `mul_lps_bridge` contains the pure parser, bounded serial worker, ROS adapter, launch and four configs. See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for message semantics and data flow.

| Parameter | Default | Purpose |
|---|---|---|
| alr_id | 132 | Host identity; never substitutes firmware reporter |
| serial_device | empty | Explicit path or unambiguous Bitcraze by-id discovery |
| baud_rate | 115200 | Serial line coding; verify on hardware |
| qos_depth / qos_reliability | 100 / reliable | Range publisher KEEP_LAST history/reliability |
| queue_size / publish_batch | 1024 / 100 | Parsed queue capacity / max records drained per 10 ms |
| line_limit | 512 | Byte bound for all console lines; MR1 independently capped at 128 including CRLF |
| reconnect_min / reconnect_max | 0.5 / 10.0 | Interruptible exponential retry seconds |
| stale_timeout | 10.0 | Warning after no validly parsed MR1; failed MR1 also counts as traffic |
| raw_log | empty | Optional rotating JSONL chunk log; byte-exact hex, wall receive ns, session and connection generation |
| raw_log_bytes / raw_log_backups | 5000000 / 3 | Active-file rotation target and archive count |

Parameters require restart; dynamic identity/transport changes are rejected. Raw-log files may exceed rotation target by one bounded read chunk. Timeouts do not force disconnect: a quiet radio remains connected and reports stale. Reporter mismatches warn but do not discard measurements. No synchronized ROS acquisition time or fabricated missing measurements are generated.

## Deployment and troubleshooting

[DEPLOYMENT.md](docs/DEPLOYMENT.md) covers per-host installation, serial permissions, optional systemd activation, rollback and debugging. [TESTING.md](docs/TESTING.md) lists offline coverage and limits. [PROGRESS.md](docs/PROGRESS.md) records milestones. The November 5 deployment correction passed 92 offline tests and a 20-second physical ALR 132 acceptance capture (48 ranges) plus an empty-device launcher capture (47 ranges, no bridge errors, clean shutdown). This is foreground hardware validation, not systemd or reboot validation. System service installation requires operator sudo; remote hosts require trusted SSH access. See [DEPLOYMENT_STATUS.md](docs/DEPLOYMENT_STATUS.md) for the exact scope and remaining steps. No existing service or firmware configuration was changed.

# First hardware handoff

Run `/home/waverover/mul_ros2_ws/scripts/acceptance_test.sh --duration 60` on ALR 132. This is the first step that opens the physical LPS descriptor. Select/confirm the LPS stable device and baud and type `yes`. All development tests used mocks/PTYS; this physical command has deliberately not been executed.

The script uses the existing ROS domain if exported, otherwise 42, and Cyclone DDS if no RMW is exported. It confirms device existence without opening it, creates a unique evidence directory, starts subscribers, optionally starts rosbag, launches the bridge with rotating raw logs, captures for the configured duration, checks typed fields/raw agreement, reporter mapping, sequence continuity, counts, diagnostics and connection health, then terminates only its own process groups. SIGINT or exceptions produce FAIL evidence and cleanup. A short duration may end before discovery/first periodic status; use at least several seconds and a duration suitable for the configured plan. Evidence metadata includes serial path, baud, duration and ROS environment. JSONL saves failures as well as successes. The final summary is machine-readable `summary.json` and is printed with PASS/FAIL. Exit 0 means PASS; nonzero means failure/cancel/error. A process killed by SIGKILL or host power loss cannot execute cleanup.

Optional: `--rosbag`, `--require-kinds 1 4` (only if the active plan schedules both), `--min-messages 10`, `--min-success 1`, `--stale-timeout 30`, `--output /absolute/new/path`. `--min-success 0` permits a deliberately failures-only capture, but never treats those ranges as successful. PASS does not require absence of firmware ranging failures. Inspect reasons and traffic rates separately.

Remaining physical checks:

1. Confirm deployed firmware actually implements the pinned MR1 contract, baud/USB control-line behavior and stable host-to-board mapping. No firmware query or configuration was sent during implementation.
2. Observe reference AA and follower AA/FF streams on their actual hosts. Offline follower fixtures match firmware definitions but are synthetic; no authentic live follower captures were available locally.
3. Confirm rates, plan changes, actual RF failures, firmware drops, quiet-mode effects, genuine USB unplug/replug and reboot segmentation. Epochs may repeat; process/connection generations cannot establish all board reboots.
4. Check PC delivery with production discovery/QoS and validate six-edge geometry inputs at the PC. The Pi deliberately does not deduplicate endpoint reports or solve positions.
5. Compare distances to independently measured geometry and evaluate timing/accuracy scientifically. The acceptance script validates data transport and structure, not clock synchronization or range calibration.

No existing WaveRover services were changed; the service was inactive at discovery and remained inactive. No remote SSH, real serial access, RF command or firmware flash was performed. Optional systemd remains uninstalled and disabled by this work.

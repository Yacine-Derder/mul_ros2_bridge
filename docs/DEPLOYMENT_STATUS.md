# Deployment verification — November 5, 2026

## Verified offline on ALR 132

Both packages built/installed; **92 tests passed, zero failures/errors/skips**.
The suite includes the launcher fix (unset/empty/explicit serial devices on all
four IDs), baud/environment preservation, required ALR_ID, all four installed
wrapper launches with synthetic PTYs and SIGINT shutdown, exclusive serial
access and USB CDC connect/reconnect settings, renderer idempotence, generated
unit syntax and shared-lock contention. ROS resolves both installed packages.
All four environment files and the systemd template were rendered locally in
ignored `deployment/`; no system unit was installed.

## Hardware actually tested

After verifying that `/dev/ttyACM0` had no owner, the existing acceptance
collector opened ALR 132's stable Bitcraze USB device at 115200 for 20 seconds.
Result: **PASS**, 48 range messages (24 successful, 24 failed MR1 ranges), all
AA/kind 1 and reporter 132, 18 diagnostics. Latest status: connected=true,
stale=false, empty last_error; malformed, oversized, queue_dropped,
disconnects, reporter_mismatches and raw_log_errors all zero. Diagnostics
reported `Receiving MR1`. The collector stopped its own bridge and released
the device. No firmware commands were sent. Evidence is preserved locally in
`evidence/deployment_20261105_alr132/` and intentionally untracked.

A second fully recorded 20-second physical check ran `run_bridge.sh` with
`ALR_ID=132` and `SERIAL_DEVICE=`. Automatic discovery selected the expected
stable device and produced **47 ranges and 18 diagnostics**, all reporting
`Receiving MR1`, connected=true, stale=false, empty last_error, and every
error/drop counter listed above equal to 0.
Sending SIGINT to the launch parent produced a clean child exit and parent
return code 0. Evidence is in
`evidence/deployment_20261105_launcher_auto132_retry/`.

An initial direct-wrapper check aborted on an unsaved telemetry assertion, so
its telemetry result is inconclusive. Its preserved shutdown log exposed a
second SIGINT interrupting cleanup when parent and child were signaled together.
The template now uses `KillMode=mixed` to signal the launch parent only; it
forwards SIGINT to the child. The recorded repeat and all four offline wrapper
shutdown tests use that signal path and passed.

These were foreground launches, not systemd services.
Wrapper-to-installed-ROS behavior was also tested on synthetic PTYs for all
four IDs. This session did not physically unplug a USB device,
inject a process crash or reboot a robot. The earlier four-robot end-to-end
validation described by the operator was not repeated here; this new capture
observed AA only, without requiring FF traffic.

## Deployment and access status

| ALR | Access established this session | Systemd deployment | Service telemetry | Reboot |
|---|---|---|---|---|
| 132 | Local workspace; sudo requires password | Prepared; not installed/enabled | Not tested; foreground hardware PASS | Not performed |
| 133 | SSH stopped at unknown host key | Prepared; remote state unverified | Not tested | Not performed |
| 134 | SSH stopped at unknown host key | Prepared; remote state unverified | Not tested | Not performed |
| 135 | SSH stopped at unknown host key | Prepared; remote state unverified | Not tested | Not performed |

On ALR 132, no MUL systemd unit was loaded and legacy waverover.service was
disabled at inspection. Its state was not changed. Remote authentication/sudo
could not be assessed beyond the host-key check. SSH to 192.168.1.16 also
stopped at an unknown host key; central-PC discovery was not tested.
No credentials were requested/recovered and no SSH configuration was changed.

Follow [DEPLOYMENT.md](DEPLOYMENT.md) for exact local commands on each ALR:
stop the known manual bridge cleanly, verify serial ownership, pull/build/test,
render with that host's stable device, inspect/install/enable the matching
service, and check fresh connection/diagnostics/ranges. Then verify all four
topics from the PC. Reboot sequentially only after confirming experiment
inactivity, remote access and safe recovery; record a changed boot ID and
repeat telemetry checks before proceeding to the next robot.

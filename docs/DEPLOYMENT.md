# Permanent four-ALR deployment, operation and rollback

Run one bridge on each ALR: 132 at 192.168.1.132, 133 at .133, 134 at .134,
135 at .135. The central PC (disalpc61, 192.168.1.16) is a subscriber only.
Do not install this service on the PC. Preserve the disabled legacy
`waverover.service`, firmware, identities, RF plans and existing ROS network.
No shell startup file changes are needed.

## Launcher and service behavior

`ALR_ID=132 ./scripts/run_bridge.sh` selects exactly one distinct
`/dev/serial/by-id/*Bitcraze*` device, retrying if absent or ambiguous. Unset or
empty `SERIAL_DEVICE` omits that launch argument entirely. An explicit
`SERIAL_DEVICE=/dev/serial/by-id/...` overrides discovery; `BAUD_RATE` defaults
to 115200 and supports explicit overrides. Never pass `serial_device:=` on the
ROS command line. All four YAML files retain their correct identities and the
validated transport settings.

The generated template runs as `waverover` with `dialout`, sources Jazzy then
this workspace's installed overlay, and uses domain 42, Cyclone DDS and SUBNET
discovery. It removes inherited ROS_LOCALHOST_ONLY/ROS_STATIC_PEERS from the
service environment. It checks ALR_ID against the systemd instance. All
instances share an advisory `flock` in `/run/mul-lps-bridge/serial.lock`, held
through exec, preventing competing systemd launches on a host. This uses Ubuntu's
existing util-linux; no new daemon or package infrastructure is required.
The runtime directory is preserved across stops so concurrent instances cannot
replace the lock inode. Direct manual ROS launches do not use this service lock:
always check device ownership first. Pyserial also requests exclusive access;
advisory locking cannot exclude programs that deliberately bypass it.

`Restart=always` covers unexpected exits, including a successful ros2 launch
exit after child failure; explicit `systemctl stop` suppresses restart.
Unlimited restart attempts are spaced five seconds apart. USB disconnects use
the existing bounded reconnect loop without restarting ROS. Every open asserts
DTR=True, RTS=False, with flow control disabled and no serial commands.
With `KillMode=mixed`, SIGINT reaches the launch parent once, which forwards it
to the bridge for graceful shutdown; the group is forcibly stopped only after
the 20-second timeout. Signaling parent and child simultaneously can deliver
SIGINT twice and interrupt serial-worker cleanup. No dependency on the
WaveRover stack is introduced.

## Access and manual bridge handover

Use existing trusted SSH access if available. Unknown host keys must be checked
against a fingerprint obtained from that robot's console/operator before
accepting them. Do not guess passwords or change SSH configuration to gain access.
Each robot requires operator sudo for installing/enabling the system service.

Before service activation, stop any manual bridge with Ctrl-C in its original
terminal and wait for shutdown. If that terminal is unavailable, inspect only
owners of the selected device:

```bash
ls -l /dev/serial/by-id/
sudo fuser -v /dev/ttyACM0
# Inspect an actual PID from that output (replace 12345):
ps -p 12345 -o user,pid,ppid,args
# Only after verifying it is the intended bridge and its experiment is finished:
kill -INT 12345
# Wait for clean exit; check again. Do not use pkill/killall patterns.
sudo fuser -v /dev/ttyACM0
```

Use the actual resolved device rather than ttyACM0 if it differs. Do not stop
unrelated serial users. An empty fuser result is required before activation.

## Exact installation commands on each robot

Open a terminal on the target ALR. Select its one ID:

```bash
export ALR_ID=132  # on ALR 132 only
# export ALR_ID=133  # on ALR 133 only
# export ALR_ID=134  # on ALR 134 only
# export ALR_ID=135  # on ALR 135 only
```

After the manual bridge handover above, run this same block on each ALR. It
refuses dirty checkouts, wrong host addresses, ambiguous devices, other active
bridge instances and occupied ports. Rerunning updates/restarts only this MUL
instance. Never run it during an active experiment.

```bash
bash <<'SH'
set -eo pipefail
: "${ALR_ID:?export the correct ALR_ID first}"
case "$ALR_ID" in 132|133|134|135) ;; *) exit 1 ;; esac
ip -4 -o addr show | awk '{print $4}' | cut -d/ -f1 | grep -Fx "192.168.1.$ALR_ID"
cd /home/waverover/mul_ros2_ws
test -z "$(git status --porcelain)" || { echo 'Preserve local changes before updating'; exit 1; }
test "$(git branch --show-current)" = main
git pull --ff-only origin main
./scripts/build_and_test.sh
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 pkg prefix mul_lps_bridge
ros2 pkg prefix mul_interfaces
mapfile -t devices < <(compgen -G '/dev/serial/by-id/*Bitcraze*' || true)
test "${#devices[@]}" = 1 || { echo 'Select/review a unique stable Bitcraze device'; exit 1; }
SERIAL_DEVICE=${devices[0]}
unit="mul-lps-bridge@$ALR_ID.service"
for other in 132 133 134 135; do
  if [ "$other" != "$ALR_ID" ] && systemctl is-active --quiet "mul-lps-bridge@$other.service"; then
    echo "Another MUL instance is active: $other"; exit 1
  fi
done
sudo -v
# Stop only this managed instance if this is a repeat deployment.
if systemctl is-active --quiet "$unit"; then sudo systemctl stop "$unit"; fi
# Listing/ownership checks do not open or configure the serial device.
sudo fuser -v "$(readlink -f "$SERIAL_DEVICE")" || true
if sudo fuser -s "$(readlink -f "$SERIAL_DEVICE")"; then
  echo 'Port occupied: complete the manual handover first'; exit 1
fi
./scripts/deploy.sh --alr-id "$ALR_ID" --device "$SERIAL_DEVICE" --baud 115200
systemd-analyze verify deployment/mul-lps-bridge@.service
cat "deployment/$ALR_ID.env" deployment/mul-lps-bridge@.service
sudo install -d -m 0755 /etc/mul_lps_bridge
sudo install -m 0644 "deployment/$ALR_ID.env" "/etc/mul_lps_bridge/$ALR_ID.env"
sudo install -m 0644 deployment/mul-lps-bridge@.service /etc/systemd/system/mul-lps-bridge@.service
sudo systemctl daemon-reload
sudo systemctl enable --now "$unit"
sleep 5
systemctl is-enabled "$unit"
systemctl is-active "$unit"
systemctl show "$unit" -p User -p MainPID -p NRestarts -p ExecMainStatus
journalctl -u "$unit" -n 30 --no-pager
SH
```

The renderer itself is offline and idempotent; it never installs/enables/stops
services. `deployment/` is ignored and may contain all four rendered env files,
but install only the matching env on each host. Explicit stable paths are
preferred for permanent use. Do not add a device-unit dependency: the bridge
must remain alive and reconnect after unplug/replug.

## Read-only telemetry verification

On each ALR, retain its exported ALR_ID and run the following after activation
and again after reboot. These subscribers never open the serial port. Source
only Jazzy and this overlay, with the already validated network settings:

```bash
source /opt/ros/jazzy/setup.bash
source /home/waverover/mul_ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=42 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
unset ROS_LOCALHOST_ONLY ROS_STATIC_PEERS
ros2 topic echo "/uwb/alr_$ALR_ID/connection" mul_interfaces/msg/ConnectionStatus --qos-durability transient_local --once --timeout 20
ros2 topic echo "/uwb/alr_$ALR_ID/diagnostics" diagnostic_msgs/msg/DiagnosticArray --once --timeout 20
ros2 topic echo "/uwb/alr_$ALR_ID/ranges" mul_interfaces/msg/RangeMeasurement --once --timeout 20
sleep 20
ros2 topic echo "/uwb/alr_$ALR_ID/connection" mul_interfaces/msg/ConnectionStatus --qos-durability transient_local --once --timeout 20
```

Require the expected stable device, host ID, `connected: true`, `stale: false`,
empty last_error, increasing measurements, and diagnostics `Receiving MR1`
(level 0). Inspect malformed, oversized, queue_dropped, reporter_mismatches,
raw_log_errors and disconnects: they should be zero for a clean new session,
with no increase over the observation interval. A stale, absent or warning
sample is a failed check even if systemd reports active. Preserve logs and
investigate rather than changing firmware. Failed MR1 ranges are valid traffic.
An unplug test and injected process crash are separate hardware tests and must
be scheduled outside experiments; offline tests alone do not validate them.

On disalpc61, use its existing ROS/installed message workspace and the same
network environment, then run **subscriber commands only**:

```bash
ros2 topic list | grep -E '^/uwb/alr_(132|133|134|135)/ranges$'
for alr in 132 133 134 135; do
  ros2 topic echo "/uwb/alr_$alr/ranges" mul_interfaces/msg/RangeMeasurement --once --timeout 20
done
```

All four exact range topics must be present together, and each must supply a
fresh measurement. This is a discovery and delivery check, not geometry or RF
accuracy validation.

## Controlled sequential reboot validation

Do this only after the operator confirms no active experiment, working remote
login, trusted host keys and safe console/power recovery. Do not infer those
conditions from an idle bridge or a free serial port. No reboot is authorized
by a successful offline test. Complete one robot's recovery before the next.

From the controller, substitute exactly one robot at a time:

```bash
ALR_ID=132  # then 133, then 134, then 135, only after each preceding PASS
ssh -t "waverover@192.168.1.$ALR_ID" 'cat /proc/sys/kernel/random/boot_id; uptime -s; sudo reboot'
# Wait for this host to return; authenticate normally if needed:
ssh "waverover@192.168.1.$ALR_ID" "cat /proc/sys/kernel/random/boot_id; uptime -s; systemctl is-enabled mul-lps-bridge@$ALR_ID.service; systemctl is-active mul-lps-bridge@$ALR_ID.service; journalctl -b -u mul-lps-bridge@$ALR_ID.service -n 30 --no-pager"
```

Record changed boot ID, enabled/active status and repeat the complete read-only
telemetry block for that ID, preferably from the PC too. Only then mark that
robot's reboot validation PASS and move to the next. A restart is not a reboot.

## Monitoring, recovery and rollback

On the target ALR with ALR_ID exported:

```bash
journalctl -u "mul-lps-bridge@$ALR_ID.service" -f
systemctl status "mul-lps-bridge@$ALR_ID.service" --no-pager
sudo systemctl restart "mul-lps-bridge@$ALR_ID.service"
sudo systemctl disable --now "mul-lps-bridge@$ALR_ID.service"
```

Restart/disable only outside an active experiment. Disable stops this MUL
instance only and prevents boot activation. For code rollback, stop this
instance, select a reviewed commit and rebuild/test before starting it again.
Preserve datasets, logs, evidence, original packages and services. No WaveRover
service change or rollback is needed.

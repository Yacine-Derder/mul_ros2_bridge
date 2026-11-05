"""Offline launcher/deployment checks: fake ros2 or synthetic PTYs only."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from test_tooling import ROOT, load


@pytest.fixture
def launcher(tmp_path):
    (tmp_path/'scripts').mkdir()
    (tmp_path/'install').mkdir()
    (tmp_path/'bin').mkdir()
    shutil.copy2(ROOT/'scripts/run_bridge.sh', tmp_path/'scripts/run_bridge.sh')
    (tmp_path/'install/setup.bash').write_text('export MUL_OVERLAY_SOURCED=yes\n')
    ros2 = tmp_path/'bin/ros2'
    ros2.write_text('#!/usr/bin/python3\nimport json, os, sys\n'
                    'print(json.dumps(dict(args=sys.argv[1:], env=dict(os.environ))))\n')
    ros2.chmod(0o755)
    env = dict(os.environ, PATH=f'{tmp_path}/bin:'+os.environ['PATH'])
    for key in ('ALR_ID', 'SERIAL_DEVICE', 'BAUD_RATE', 'ROS_DOMAIN_ID',
                'RMW_IMPLEMENTATION'):
        env.pop(key, None)
    return tmp_path/'scripts/run_bridge.sh', env


@pytest.mark.parametrize('alr', range(132,136))
@pytest.mark.parametrize('device', [None, '', '/dev/serial/by-id/usb-Bitcraze-test'])
def test_launcher_optional_device(launcher, alr, device):
    script, env = launcher
    env['ALR_ID'] = str(alr)
    if device is not None:
        env['SERIAL_DEVICE'] = device
    result = subprocess.run([str(script)], env=env, capture_output=True, text=True, check=True)
    actual = json.loads(result.stdout)
    expected = ['launch', 'mul_lps_bridge', 'bridge.launch.py',
                f'alr_id:={alr}', 'baud_rate:=115200']
    if device:
        expected.append(f'serial_device:={device}')
    assert actual['args'] == expected
    assert all(not arg.endswith(':=') for arg in actual['args'])
    assert actual['env']['ROS_DOMAIN_ID'] == '42'
    assert actual['env']['RMW_IMPLEMENTATION'] == 'rmw_cyclonedds_cpp'
    assert actual['env']['MUL_OVERLAY_SOURCED'] == 'yes'
    assert actual['env']['ROS_DISTRO'] == 'jazzy'


def test_launcher_preserves_environment_and_baud(launcher):
    script, env = launcher
    env.update(ALR_ID='133', BAUD_RATE='230400', ROS_DOMAIN_ID='212',
               RMW_IMPLEMENTATION='rmw_cyclonedds_cpp',
               ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST')
    actual = json.loads(subprocess.check_output([str(script)], env=env, text=True))
    assert 'baud_rate:=230400' in actual['args']
    for key in ('ROS_DOMAIN_ID', 'RMW_IMPLEMENTATION', 'ROS_AUTOMATIC_DISCOVERY_RANGE'):
        assert actual['env'][key] == env[key]


def test_launcher_requires_identity(launcher):
    script, env = launcher
    result = subprocess.run([str(script)], env=env, capture_output=True, text=True)
    assert result.returncode != 0 and 'ALR_ID' in result.stderr
    assert not result.stdout


def test_unit_and_environments(tmp_path):
    deploy = load('deploy')
    for alr in range(132,136):
        deploy.render(ROOT, tmp_path, alr)
        assert (tmp_path/f'{alr}.env').read_text() == (
            f'ALR_ID={alr}\nSERIAL_DEVICE=\nBAUD_RATE=115200\n')
    unit = (tmp_path/'mul-lps-bridge@.service').read_text()
    for line in ('User=waverover', 'SupplementaryGroups=dialout',
                 'Environment=ROS_DOMAIN_ID=42',
                 'Environment=RMW_IMPLEMENTATION=rmw_cyclonedds_cpp',
                 'Environment=ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET',
                 'UnsetEnvironment=ROS_LOCALHOST_ONLY ROS_STATIC_PEERS',
                 'ExecStartPre=/usr/bin/test ${ALR_ID} = %i',
                 'Restart=always', 'StartLimitIntervalSec=0',
                 'KillSignal=SIGINT', 'KillMode=mixed',
                 'RuntimeDirectoryPreserve=yes', 'WantedBy=multi-user.target'):
        assert line in unit
    assert 'waverover.service' not in unit and '@WORKSPACE@' not in unit
    subprocess.run(['systemd-analyze', 'verify', str(tmp_path/'mul-lps-bridge@.service')],
                   check=True, capture_output=True, text=True)
    # Same lock used by all instances, held across exec; no serial port involved.
    lock = tmp_path/'serial.lock'
    with lock.open('w') as handle:
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        command = ['/usr/bin/flock', '--nonblock', '--no-fork', str(lock), '/usr/bin/true']
        assert subprocess.run(command).returncode == 1
    assert subprocess.run(command).returncode == 0

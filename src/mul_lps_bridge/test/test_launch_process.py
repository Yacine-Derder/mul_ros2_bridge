"""Execute installed launch/entry point using Linux pseudo-terminals only."""
import os
import pty
import signal
import subprocess
import time
import pytest
import rclpy
from mul_interfaces.msg import RangeMeasurement
from test_parser import GOOD
from test_ros import spin_until


@pytest.mark.parametrize('alr',range(132,136))
def test_installed_launch_process(alr,tmp_path):
    master,slave=pty.openpty()
    process=None
    node=None
    rclpy.init()
    with (tmp_path/'launch.log').open('w+') as log:
        try:
            node=rclpy.create_node(f'offline_launch_observer_{alr}')
            received=[]
            node.create_subscription(RangeMeasurement,f'/uwb/alr_{alr}/ranges',received.append,10)
            process=subprocess.Popen(['ros2','launch','mul_lps_bridge','bridge.launch.py',
                f'alr_id:={alr}',f'serial_device:={os.ttyname(slave)}'],
                stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            # Allow discovery, repeatedly feed synthetic traffic, then validate it.
            end=time.monotonic()+8
            while not received and time.monotonic()<end and process.poll() is None:
                os.write(master,(GOOD+'\n').encode())
                rclpy.spin_once(node,timeout_sec=.1)
            log.flush()
            assert received, (tmp_path/'launch.log').read_text()
            assert received[0].host_alr_id==alr and received[0].reporter==132
            assert received[0].raw_record==GOOD
            os.killpg(process.pid,signal.SIGINT)
            process.wait(timeout=5)
            assert process.returncode==0, (tmp_path/'launch.log').read_text()
        finally:
            if process and process.poll() is None:
                os.killpg(process.pid,signal.SIGKILL)
                process.wait(timeout=5)
            if node:
                node.destroy_node()
            rclpy.try_shutdown()
            os.close(master)
            os.close(slave)

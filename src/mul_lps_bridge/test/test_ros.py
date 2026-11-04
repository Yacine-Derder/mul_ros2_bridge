import importlib.util
import os
from pathlib import Path
import pty
import time
import pytest
import yaml
import rclpy
from rclpy.parameter import Parameter
from rclpy.serialization import serialize_message, deserialize_message
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from mul_interfaces.msg import RangeMeasurement, ConnectionStatus
from diagnostic_msgs.msg import DiagnosticArray
from mul_lps_bridge.node import Bridge, to_message
from mul_lps_bridge.parser import parse
from test_parser import GOOD, FIX


def spin_until(nodes, predicate, seconds=5):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        for node in nodes:
            rclpy.spin_once(node,timeout_sec=.01)
        if predicate():
            return
    assert predicate()


@pytest.mark.parametrize('line',[GOOD,(FIX/'reference.txt').read_text().splitlines()[2],
 (FIX/'follower_synthetic.txt').read_text().splitlines()[2]])
def test_serialization(line):
    m=parse(line)
    msg=to_message(m,1700000000123456789,132,'session',2,3)
    decoded=deserialize_message(serialize_message(msg),RangeMeasurement)
    assert decoded==msg
    assert decoded.received_at.nanosec==123456789
    assert decoded.reporter==m.reporter and decoded.timestamp_dtu==m.timestamp_dtu
    assert decoded.has_range==(m.status==0)
    assert decoded.has_power_indicator==(m.status==0)


def test_ros_pty_publication_diagnostics_and_staleness():
    master,slave=pty.openpty()
    rclpy.init()
    bridge=observer=None
    try:
        bridge=Bridge(namespace='/offline/alr_133',parameter_overrides=[
            Parameter('alr_id',value=133),Parameter('serial_device',value=os.ttyname(slave)),
            Parameter('stale_timeout',value=.2)])
        observer=rclpy.create_node('mul_offline_observer')
        ranges,statuses,diags=[],[],[]
        observer.create_subscription(RangeMeasurement,'/offline/alr_133/ranges',ranges.append,100)
        observer.create_subscription(ConnectionStatus,'/offline/alr_133/connection',statuses.append,
            QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL))
        observer.create_subscription(DiagnosticArray,'/offline/alr_133/diagnostics',diags.append,10)
        spin_until([bridge,observer],lambda: bridge.ranges.get_subscription_count()==1)
        fixture=(FIX/'follower_synthetic.txt').read_text()
        os.write(master,(GOOD+'\n'+fixture+GOOD+'\n').encode())
        spin_until([bridge,observer],lambda: len(ranges)==6 and bool(diags))
        assert [m.sequence for m in ranges]==list(range(1,7))
        assert ranges[0].reporter==132 and ranges[0].host_alr_id==133
        assert ranges[0].raw_record==ranges[-1].raw_record  # no deduplication
        assert any(m.kind==4 and not m.valid and not m.has_range for m in ranges)
        assert len({m.capture_session for m in ranges})==1
        assert all(m.received_at.sec>0 for m in ranges)
        spin_until([bridge,observer],lambda: bool(statuses) and statuses[-1].stale)
        assert statuses[-1].measurements==6 and statuses[-1].reporter_mismatches==4
        result=bridge.set_parameters([Parameter('alr_id',value=134)])[0]
        assert not result.successful
        # A late status subscriber receives latched connection state.
        late=[]
        observer.create_subscription(ConnectionStatus,'/offline/alr_133/connection',late.append,
            QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL))
        spin_until([bridge,observer],lambda: bool(late))
    finally:
        if bridge:
            bridge.destroy_node()
        if observer:
            observer.destroy_node()
        rclpy.try_shutdown()
        os.close(master)
        os.close(slave)


@pytest.mark.parametrize('alr',range(132,136))
def test_launch_config(alr):
    from ament_index_python.packages import get_package_share_directory
    from launch import LaunchContext
    share=Path(get_package_share_directory('mul_lps_bridge'))
    config=yaml.safe_load((share/'config'/f'alr_{alr}.yaml').read_text())['/**']['ros__parameters']
    assert config['alr_id']==alr and 'role' not in config
    spec=importlib.util.spec_from_file_location('bridge_launch',share/'launch'/'bridge.launch.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ctx=LaunchContext()
    ctx.launch_configurations.update(dict(alr_id=str(alr),config='',serial_device='/dev/pts/example',
        baud_rate='115200',namespace='',raw_log=''))
    actions=module.configure(ctx)
    assert len(actions)==1 and actions[0].node_executable=='bridge'
    assert module.generate_launch_description()

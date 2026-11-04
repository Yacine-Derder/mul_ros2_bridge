import importlib.util
from pathlib import Path
import subprocess
import sys
from collections import Counter
import pytest
from mul_interfaces.msg import ConnectionStatus
from mul_lps_bridge.node import to_message
from mul_lps_bridge.parser import parse
from test_parser import GOOD

ROOT=Path(__file__).resolve().parents[3]


def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deployment_render_idempotent(tmp_path):
    deploy=load('deploy')
    for alr in range(132,136):
        deploy.render(ROOT,tmp_path,alr,'/dev/serial/by-id/usb-Bitcraze',user='waverover')
        unit=(tmp_path/'mul-lps-bridge@.service').read_text()
        assert '@WORKSPACE@' not in unit and str(ROOT) in unit
        assert f'ALR_ID={alr}' in (tmp_path/f'{alr}.env').read_text()
        deploy.render(ROOT,tmp_path,alr,'/dev/serial/by-id/usb-Bitcraze',user='waverover')
        assert unit==(tmp_path/'mul-lps-bridge@.service').read_text()
    with pytest.raises(ValueError):
        deploy.render(ROOT,tmp_path,132,'/dev/tty;danger')


def test_acceptance_field_validation_and_assessment():
    tool=load('acceptance')
    msg=to_message(parse(GOOD),1700000000123456789,132,'session',1,1)
    assert tool.validate_message(msg,132)==[]
    msg.distance_mm+=1
    assert tool.validate_message(msg,132)
    assert tool.validate_message(msg,133)
    status=ConnectionStatus(connected=True,stale=False)
    counts=Counter(total=2,success=1,kind_1=2)
    assert tool.assess(counts,status,1,[],1,1,[1],True)==[]
    assert tool.assess(counts,status,1,[],1,1,[4],True)
    status.queue_dropped=1
    assert tool.assess(counts,status,1,[],1,1,[],True)
    status.queue_dropped=0
    status.stale=True
    assert tool.assess(counts,status,1,[],1,1,[],True)
    assert tool.assess(Counter(),None,0,[],1,1,[],False)


@pytest.mark.parametrize('script',['acceptance_test.sh','build_and_test.sh','deploy.sh','install_dependencies.sh','run_bridge.sh'])
def test_shell_syntax(script):
    subprocess.run(['bash','-n',str(ROOT/'scripts'/script)],check=True)


def test_acceptance_help_only():
    # Never execute a capture. --help exits before serial selection/opening.
    result=subprocess.run([sys.executable,str(ROOT/'scripts'/'acceptance.py'),'--help'],capture_output=True,text=True,check=True)
    assert '--rosbag' in result.stdout and '--duration' in result.stdout

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


@pytest.mark.parametrize('bag',[False,True])
def test_synthetic_acceptance_end_to_end(bag,tmp_path):
    """Run full evidence collector, explicitly PTY-only and synthetic labeled."""
    import os
    import pty
    import time
    import json
    import signal
    master,slave=pty.openpty()
    process=None
    output=tmp_path/'synthetic_evidence'
    with (tmp_path/'collector.log').open('w+') as log:
        try:
            command=[sys.executable,str(ROOT/'scripts'/'acceptance.py'),
                '--synthetic','--device',os.ttyname(slave),'--yes','--duration','3',
                '--output',str(output)]
            if bag:
                command.append('--rosbag')
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            end=time.monotonic()+20
            failure=(Path(__file__).parent/'fixtures'/'reference.txt').read_text().splitlines()[2]
            while process.poll() is None and time.monotonic()<end:
                os.write(master,(GOOD+'\n'+failure+'\n').encode())
                time.sleep(.05)
            assert process.poll() is not None, 'synthetic collector hung'
            log.flush()
            assert process.returncode==0,(tmp_path/'collector.log').read_text()
            summary=json.loads((output/'summary.json').read_text())
            metadata=json.loads((output/'metadata.json').read_text())
            assert summary['result']=='PASS' and summary['synthetic'] and metadata['synthetic']
            assert summary['counts']['success']>0 and summary['counts']['failure']>0
            assert summary['diagnostics']>0
            assert (output/'raw.log').exists()
            if bag:
                assert (output/'bag'/'metadata.yaml').exists()
            # Exclusive bridge handle was closed; can reopen the PTY after cleanup.
            import serial
            with serial.Serial(os.ttyname(slave),exclusive=True,timeout=.1):
                pass
        finally:
            if process and process.poll() is None:
                os.killpg(process.pid,signal.SIGKILL)
                process.wait(timeout=5)
            os.close(master)
            os.close(slave)


@pytest.mark.parametrize('interrupt',[False,True])
def test_synthetic_acceptance_failure_and_interrupt_cleanup(interrupt,tmp_path):
    import os
    import pty
    import time
    import json
    import signal
    import serial
    master,slave=pty.openpty()
    process=None
    output=tmp_path/'synthetic_failure_evidence'
    try:
        process=subprocess.Popen([sys.executable,str(ROOT/'scripts'/'acceptance.py'),
            '--synthetic','--device',os.ttyname(slave),'--yes','--duration','2',
            '--output',str(output)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,start_new_session=True)
        if interrupt:
            end=time.monotonic()+5
            while not (output/'bridge.log').exists() and time.monotonic()<end:
                time.sleep(.01)
            # This signal interrupts an active collector; it must stop its bridge.
            time.sleep(.5)
            process.send_signal(signal.SIGINT)
        stdout,_=process.communicate(timeout=12)
        assert process.returncode==1,stdout
        summary=json.loads((output/'summary.json').read_text())
        assert summary['result']=='FAIL' and summary['synthetic']
        assert summary['errors']
        with serial.Serial(os.ttyname(slave),exclusive=True,timeout=.1):
            pass
    finally:
        if process and process.poll() is None:
            os.killpg(process.pid,signal.SIGKILL)
            process.wait(timeout=5)
        os.close(master)
        os.close(slave)

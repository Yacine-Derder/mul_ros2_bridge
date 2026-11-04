#!/usr/bin/env python3
"""Operator-only physical capture. Unit tests exercise analysis without hardware."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
import yaml

import rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from diagnostic_msgs.msg import DiagnosticArray
from mul_interfaces.msg import RangeMeasurement, ConnectionStatus
from mul_lps_bridge.parser import parse
from rosidl_runtime_py.convert import message_to_ordereddict


def stop_process(process):
    if process is None or process.poll() is not None:
        return
    os.killpg(process.pid,signal.SIGINT)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGTERM)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL)
            process.wait(timeout=3)


def validate_message(msg, alr):
    errors=[]
    try:
        source=parse(msg.raw_record)
        if source is None:
            return ['raw record is not MR1']
        for key in ('kind','reporter','initiator','responder','cycle','timestamp_dtu',
                    'epoch','plan_fingerprint','status','reason'):
            if getattr(msg,key)!=getattr(source,key):
                errors.append('raw/typed mismatch: '+key)
        if msg.valid != (source.status==0) or msg.has_range != (source.distance_mm is not None):
            errors.append('validity/presence mismatch')
        if msg.has_range and (msg.distance_mm!=source.distance_mm or msg.raw_distance_mm!=source.raw_distance_mm):
            errors.append('distance mismatch')
        if msg.has_power_indicator!=(source.power_corrected is not None) or msg.power_corrected!=bool(source.power_corrected):
            errors.append('power indicator mismatch')
        if msg.marker!=source.marker or msg.clock_domain!='dw1000_local_40bit':
            errors.append('clock marker mismatch')
    except ValueError as exc:
        errors.append('raw parse: '+str(exc))
    if msg.host_alr_id!=alr or msg.reporter!=alr:
        errors.append('host/reporter mismatch; verify USB-to-ALR assignment')
    if msg.received_at.sec<=0 or not msg.capture_session or msg.connection_generation<1 or msg.sequence<1:
        errors.append('missing host reception/session provenance')
    return errors


def assess(counts, status, diagnostics, errors, min_messages, min_success, require_kinds, alive):
    failures=list(errors)
    if counts['total']<min_messages:
        failures.append(f"received {counts['total']} messages; require {min_messages}")
    if counts['success']<min_success:
        failures.append(f"received {counts['success']} successful ranges; require {min_success}")
    for kind in require_kinds:
        if not counts['kind_'+str(kind)]:
            failures.append(f'missing required kind {kind}')
    if not alive:
        failures.append('bridge exited unexpectedly')
    if status is None:
        failures.append('no connection status received')
    else:
        if not status.connected or status.stale:
            failures.append('final connection is disconnected/stale')
        for key in ('malformed','oversized','queue_dropped','reporter_mismatches'):
            if getattr(status,key):
                failures.append(f'{key}={getattr(status,key)}')
    if not diagnostics:
        failures.append('no diagnostics received')
    return list(dict.fromkeys(failures))


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--alr-id',type=int,choices=range(132,136),default=132)
    ap.add_argument('--device',help='prefer /dev/serial/by-id/...')
    ap.add_argument('--baud',type=int,default=115200)
    ap.add_argument('--duration',type=float,default=60)
    ap.add_argument('--min-messages',type=int,default=1)
    ap.add_argument('--min-success',type=int,default=1)
    ap.add_argument('--require-kinds',type=int,nargs='*',choices=[1,4],default=[])
    ap.add_argument('--stale-timeout',type=float,default=10)
    ap.add_argument('--rosbag',action='store_true')
    ap.add_argument('--yes',action='store_true',help='confirm explicitly supplied device and baud noninteractively')
    ap.add_argument('--output',type=Path)
    args=ap.parse_args(argv)
    if args.duration<=0 or args.baud<=0 or args.min_messages<1 or args.min_success<0 or args.stale_timeout<=0:
        ap.error('invalid duration, baud, thresholds or stale timeout')
    if args.yes and not args.device:
        ap.error('--yes requires an explicit --device')
    device=args.device
    if not device:
        ports=sorted(glob.glob('/dev/serial/by-id/*'))
        if not ports:
            ap.error('no stable serial devices found; supply --device explicitly')
        for index,port in enumerate(ports,1):
            print(f'{index}: {port}')
        answer=input('Select LPS device number or full path: ').strip()
        if answer.isdigit() and 1<=int(answer)<=len(ports):
            device=ports[int(answer)-1]
        elif answer.startswith('/'):
            device=answer
        else:
            ap.error('invalid device selection')
    if not Path(device).exists():
        ap.error('device does not exist')
    if not args.yes:
        value=input(f'Baud rate [{args.baud}]: ').strip()
        if value:
            args.baud=int(value)
        if args.baud<=0:
            ap.error('baud must be positive')
        if input(f'Open {device} at {args.baud}, read ALR {args.alr_id} for {args.duration}s? [yes/NO]: ').strip().lower()!='yes':
            print('Cancelled; device was not opened.')
            return 2
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    root=Path(__file__).resolve().parent.parent
    out=args.output or root/'evidence'/f'alr_{args.alr_id}_{stamp}_{uuid.uuid4().hex[:6]}'
    out=out.resolve()
    out.mkdir(parents=True,exist_ok=False)
    os.chmod(out,0o700)
    base=f'/uwb/alr_{args.alr_id}'
    bridge=bag=node=None
    counts=Counter()
    errors=[]
    last_status=[None]
    last_sequence=[None]
    session=[None]
    diag_count=[0]
    handles=[]
    summary={}
    rclpy.init(args=[])
    try:
        node=rclpy.create_node('mul_acceptance_'+uuid.uuid4().hex[:8])
        if node.count_publishers(base+'/ranges'):
            raise RuntimeError('ranges already has a publisher; stop the existing bridge before acceptance')
        measurements=(out/'measurements.jsonl').open('w')
        statuses=(out/'connection.jsonl').open('w')
        diagnostics=(out/'diagnostics.jsonl').open('w')
        handles.extend([measurements,statuses,diagnostics])
        def save(handle,msg):
            handle.write(json.dumps(message_to_ordereddict(msg))+'\n')
            handle.flush()
        def on_range(msg):
            counts['total']+=1
            if session[0] is not None and msg.capture_session!=session[0]:
                if 'multiple bridge sessions observed' not in errors:
                    errors.append('multiple bridge sessions observed')
            session[0]=msg.capture_session
            if last_sequence[0] is not None and msg.sequence!=last_sequence[0]+1:
                if 'measurement sequence gap/reordering' not in errors:
                    errors.append('measurement sequence gap/reordering')
            last_sequence[0]=msg.sequence
            counts['success' if msg.valid else 'failure']+=1
            counts['kind_'+str(msg.kind)]+=1
            counts['reporter_'+str(msg.reporter)]+=1
            for error in validate_message(msg,args.alr_id):
                if error not in errors and len(errors)<100:
                    errors.append(error)
            save(measurements,msg)
        def on_status(msg):
            last_status[0]=msg
            save(statuses,msg)
        def on_diag(msg):
            diag_count[0]+=1
            save(diagnostics,msg)
        node.create_subscription(RangeMeasurement,base+'/ranges',on_range,
            QoSProfile(depth=1000,reliability=ReliabilityPolicy.RELIABLE))
        node.create_subscription(ConnectionStatus,base+'/connection',on_status,
            QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL))
        node.create_subscription(DiagnosticArray,base+'/diagnostics',on_diag,100)
        metadata=dict(device=device,baud=args.baud,alr_id=args.alr_id,duration=args.duration,
                      domain=os.environ.get('ROS_DOMAIN_ID'),rmw=os.environ.get('RMW_IMPLEMENTATION'),
                      started_utc=stamp,synthetic=False)
        (out/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
        if args.rosbag:
            bag_log=(out/'rosbag.log').open('w');handles.append(bag_log)
            bag=subprocess.Popen(['ros2','bag','record','-o',str(out/'bag'),base+'/ranges',base+'/connection',base+'/diagnostics'],
                stdout=bag_log,stderr=subprocess.STDOUT,start_new_session=True)
            time.sleep(1)
            if bag.poll() is not None:
                raise RuntimeError('rosbag failed to start; see rosbag.log')
        config=out/'acceptance.yaml'
        config.write_text(yaml.safe_dump({'/**':{'ros__parameters':{'stale_timeout':args.stale_timeout}}}))
        bridge_log=(out/'bridge.log').open('w');handles.append(bridge_log)
        bridge=subprocess.Popen(['ros2','launch','mul_lps_bridge','bridge.launch.py',
            f'alr_id:={args.alr_id}',f'config:={config}',f'serial_device:={device}',f'baud_rate:={args.baud}',
            f'raw_log:={out/"raw.log"}'],stdout=bridge_log,stderr=subprocess.STDOUT,start_new_session=True)
        deadline=time.monotonic()+args.duration
        while time.monotonic()<deadline:
            rclpy.spin_once(node,timeout_sec=min(.1,max(0.0,deadline-time.monotonic())))
            if bridge.poll() is not None:
                break
        errors=assess(counts,last_status[0],diag_count[0],errors,args.min_messages,
                      args.min_success,args.require_kinds,bridge.poll() is None)
        if bag and bag.poll() is not None:
            errors.append('rosbag exited during capture')
        summary=dict(result='FAIL' if errors else 'PASS',counts=dict(counts),errors=errors,
                     diagnostics=diag_count[0],connection=message_to_ordereddict(last_status[0]) if last_status[0] else None,output=str(out))
    except (Exception,KeyboardInterrupt) as exc:
        summary=dict(result='FAIL',counts=dict(counts),errors=[f'{type(exc).__name__}: {exc}'],output=str(out))
    finally:
        stop_process(bridge)
        stop_process(bag)
        if node:
            node.destroy_node()
        rclpy.try_shutdown()
        for handle in handles:
            handle.close()
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
    return 0 if summary.get('result')=='PASS' else 1


if __name__=='__main__':
    sys.exit(main())

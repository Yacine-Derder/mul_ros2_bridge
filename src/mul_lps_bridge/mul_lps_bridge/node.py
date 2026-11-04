"""ROS adapter; serial parsing and I/O remain independently testable."""
import queue
import time
import uuid
import rclpy
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from rcl_interfaces.msg import SetParametersResult
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from mul_interfaces.msg import RangeMeasurement, ConnectionStatus
from .transport import SerialWorker

DEFAULTS = dict(alr_id=132, serial_device='', baud_rate=115200, qos_depth=100,
                qos_reliability='reliable', queue_size=1024, line_limit=512,
                reconnect_min=0.5, reconnect_max=10.0, stale_timeout=10.0,
                raw_log='', raw_log_bytes=5000000, raw_log_backups=3,
                publish_batch=100)


def to_message(m, received_ns, host_id, session, generation, sequence):
    msg = RangeMeasurement()
    msg.received_at.sec, msg.received_at.nanosec = divmod(received_ns, 1000000000)
    msg.host_alr_id, msg.capture_session = host_id, session
    msg.connection_generation, msg.sequence = generation, sequence
    for key in ('kind','initiator','responder','reporter','cycle','timestamp_dtu',
                'epoch','plan_fingerprint','status','reason','raw_record'):
        setattr(msg, key, getattr(m,key))
    msg.valid = m.status == 0
    msg.has_range = m.distance_mm is not None
    msg.distance_mm = m.distance_mm if msg.has_range else 0
    msg.raw_distance_mm = m.raw_distance_mm if msg.has_range else 0
    msg.has_power_indicator = m.power_corrected is not None
    msg.power_corrected = bool(m.power_corrected)
    msg.clock_domain, msg.marker = 'dw1000_local_40bit', m.marker
    return msg


class Bridge(Node):
    def __init__(self, **kwargs):
        super().__init__('mul_lps_bridge', **kwargs)
        for key,value in DEFAULTS.items():
            self.declare_parameter(key,value)
        p = {k:self.get_parameter(k).value for k in DEFAULTS}
        if p['qos_depth'] < 1 or p['publish_batch'] < 1 or p['stale_timeout'] <= 0:
            raise ValueError('depth, batch and stale timeout must be positive')
        if p['qos_reliability'] not in ('reliable','best_effort'):
            raise ValueError('qos_reliability must be reliable or best_effort')
        self.add_on_set_parameters_callback(self._reject_updates)
        self.host_id, self.session = p['alr_id'], str(uuid.uuid4())
        self.stale_timeout, self.batch = p['stale_timeout'], p['publish_batch']
        qos = QoSProfile(depth=p['qos_depth'], reliability=(ReliabilityPolicy.RELIABLE
            if p['qos_reliability']=='reliable' else ReliabilityPolicy.BEST_EFFORT))
        def topic(name):
            return f'/uwb/alr_{self.host_id}/{name}' if self.get_namespace()=='/' else name
        self.ranges = self.create_publisher(RangeMeasurement,topic('ranges'),qos)
        status_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                               durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.status_pub = self.create_publisher(ConnectionStatus,topic('connection'),status_qos)
        self.diag_pub = self.create_publisher(DiagnosticArray,topic('diagnostics'),10)
        self.worker = SerialWorker(self.host_id, p['serial_device'], p['baud_rate'],
            p['queue_size'],p['line_limit'],p['reconnect_min'],p['reconnect_max'],
            p['raw_log'],p['raw_log_bytes'],p['raw_log_backups'],capture_session=self.session)
        self.baud = p['baud_rate']
        self.last_health = None
        self.started = time.monotonic()
        self.worker.start()
        self.steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self.create_timer(0.01,self.drain,clock=self.steady_clock)
        self.create_timer(1.0,self.publish_status,clock=self.steady_clock)

    def _reject_updates(self, params):
        if any(p.name in DEFAULTS or p.name == 'use_sim_time' for p in params):
            return SetParametersResult(successful=False, reason='restart bridge to change configuration')
        return SetParametersResult(successful=True)

    def drain(self):
        for _ in range(self.batch):
            try:
                m, ns, generation, sequence = self.worker.queue.get_nowait()
            except queue.Empty:
                break
            self.ranges.publish(to_message(m,ns,self.host_id,self.session,generation,sequence))

    def publish_status(self):
        s = self.worker.snapshot()
        now = time.monotonic()
        status = ConnectionStatus()
        ns = time.time_ns()  # host wall time, independent of ROS simulation clock
        status.stamp.sec, status.stamp.nanosec = divmod(ns,1000000000)
        status.host_alr_id, status.capture_session = self.host_id,self.session
        status.connection_generation = s['generation']
        status.connected, status.device = s['connected'], s['device']
        status.last_error, status.baud_rate = s['error'],self.baud
        status.seconds_since_byte = now-s['last_byte'] if s['last_byte'] else -1.0
        status.seconds_since_measurement = now-s['last_measurement'] if s['last_measurement'] else -1.0
        status.stale = (not s['last_measurement'] or status.seconds_since_measurement > self.stale_timeout)
        for key in ('bytes_received','lines_received','measurements','malformed','unrelated',
                    'oversized','queue_dropped','disconnects','reporter_mismatches'):
            setattr(status,key,s[key])
        self.status_pub.publish(status)
        d = DiagnosticStatus()
        d.name, d.hardware_id = f'mul/alr_{self.host_id}',s['device']
        if not s['connected']:
            d.level,d.message = DiagnosticStatus.ERROR,'Disconnected: '+s['error']
        elif status.stale:
            d.level,d.message = DiagnosticStatus.WARN,'Connected; no recent MR1 (rate/verbosity/plan unknown)'
        elif s['queue_dropped'] or s['malformed'] or s['oversized'] or s['reporter_mismatches']:
            d.level,d.message = DiagnosticStatus.WARN,'Receiving; inspect cumulative error/drop/reporter counters'
        else:
            d.level,d.message = DiagnosticStatus.OK,'Receiving MR1'
        d.values = [KeyValue(key=k,value=str(v)) for k,v in s.items()]
        array = DiagnosticArray(status=[d])
        array.header.stamp = status.stamp
        self.diag_pub.publish(array)
        health = (d.level,d.message)
        if health != self.last_health:
            self.get_logger().info(d.message)
            self.last_health = health

    def destroy_node(self):
        if hasattr(self,'worker'):
            self.worker.stop()
            self.drain()
            self.publish_status()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = Bridge()
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        if node:
            # Context may already have been shut down by SIGINT.
            if rclpy.ok():
                node.destroy_node()
            else:
                node.worker.stop()
                Node.destroy_node(node)
        rclpy.try_shutdown()

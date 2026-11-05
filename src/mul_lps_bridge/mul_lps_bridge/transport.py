"""Bounded serial worker. No firmware writes, probing commands or RF actions."""
from dataclasses import dataclass, asdict
from pathlib import Path
import glob
import json
import logging
from logging.handlers import RotatingFileHandler
import queue
import threading
import time
import uuid
import serial
from .parser import parse


class RawLogHandler(RotatingFileHandler):
    def handleError(self, record):
        # Logging normally swallows disk errors and floods stderr per chunk.
        # Surface failure to the reader, which disables the optional sink only.
        raise OSError('raw log write/rotation failed')


class Framer:
    def __init__(self, limit=512):
        if limit < 128:
            raise ValueError('line limit must be >=128')
        self.limit = limit
        self.buffer = bytearray()
        self.discarding = False
        self.oversized = 0

    def feed(self, data):
        lines = []
        for byte in data:
            if byte == 10:
                if not self.discarding:
                    lines.append(bytes(self.buffer).rstrip(b'\r'))
                self.buffer.clear()
                self.discarding = False
            elif not self.discarding:
                if len(self.buffer) >= self.limit:
                    self.buffer.clear()
                    self.discarding = True
                    self.oversized += 1
                else:
                    self.buffer.append(byte)
        return lines


def select_device(configured=''):
    if configured:
        return configured
    candidates = sorted(glob.glob('/dev/serial/by-id/*Bitcraze*'))
    # Multiple aliases of the same device are still one device.
    unique = {str(Path(p).resolve()): p for p in candidates}
    if len(unique) != 1:
        raise OSError(f'expected exactly one Bitcraze by-id device, found {len(unique)}; set serial_device')
    return next(iter(unique.values()))


def open_serial(device, baud, timeout):
    port = serial.Serial(port=None, baudrate=baud, timeout=timeout,
                         write_timeout=timeout, exclusive=True)
    # Bitcraze USB CDC gates telemetry on DTR; apply on every open/reconnect.
    # RTS is unused; keep it disabled. No serial commands are transmitted.
    port.dtr = True
    port.rts = False
    port.port = device
    port.open()
    return port


@dataclass
class Stats:
    connected: bool = False
    device: str = ''
    generation: int = 0
    error: str = ''
    bytes_received: int = 0
    lines_received: int = 0
    measurements: int = 0
    malformed: int = 0
    unrelated: int = 0
    oversized: int = 0
    queue_dropped: int = 0
    disconnects: int = 0
    reporter_mismatches: int = 0
    raw_log_errors: int = 0
    raw_log_error: str = ''
    last_byte: float = 0.0
    last_measurement: float = 0.0


class SerialWorker:
    def __init__(self, host_id, device='', baud=115200, queue_size=1024,
                 line_limit=512, reconnect_min=0.5, reconnect_max=10.0,
                 raw_log='', raw_log_bytes=5000000, raw_log_backups=3,
                 factory=open_serial, selector=select_device, capture_session=None):
        if not 0 <= host_id <= 254 or baud <= 0 or queue_size < 1 or reconnect_min <= 0 or reconnect_max < reconnect_min:
            raise ValueError('invalid worker configuration')
        if raw_log_bytes < 1024 or raw_log_backups < 1:
            raise ValueError('raw log must have bounded rotation')
        self.host_id, self.device, self.baud = host_id, device, baud
        self.capture_session = capture_session or str(uuid.uuid4())
        self.queue = queue.Queue(maxsize=queue_size)
        self.line_limit = line_limit
        Framer(line_limit)  # validate before thread starts
        self.reconnect_min, self.reconnect_max = reconnect_min, reconnect_max
        self.factory, self.selector = factory, selector
        self.stats, self.lock = Stats(), threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.raw_logger = None
        if raw_log:
            path = Path(raw_log).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            self.raw_logger = logging.Logger('mul_raw')
            handler = RawLogHandler(path, maxBytes=raw_log_bytes, backupCount=raw_log_backups)
            handler.setFormatter(logging.Formatter('%(message)s'))
            self.raw_logger.addHandler(handler)

    def snapshot(self):
        with self.lock:
            return asdict(self.stats)

    def start(self):
        if self.thread is not None:
            raise RuntimeError('worker already started')
        self.thread = threading.Thread(target=self._run, name='mul_serial', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
            if self.thread.is_alive():
                raise RuntimeError('serial worker did not stop')
        if self.raw_logger:
            for h in self.raw_logger.handlers:
                h.close()

    def _run(self):
        delay = self.reconnect_min
        while not self.stop_event.is_set():
            port = None
            framer = Framer(self.line_limit)  # never combine lines across reconnects
            try:
                device = self.selector(self.device)
                port = self.factory(device, self.baud, 0.1)
                with self.lock:
                    self.stats.connected = True
                    self.stats.device = device
                    self.stats.generation += 1
                    self.stats.error = ''
                    self.stats.last_byte = self.stats.last_measurement = 0.0
                    generation = self.stats.generation
                while not self.stop_event.is_set():
                    data = port.read(4096)
                    if not data:
                        continue
                    delay = self.reconnect_min
                    received_ns, mono = time.time_ns(), time.monotonic()
                    if self.raw_logger:
                        # Hex preserves arbitrary bytes, partial lines, and corruption.
                        try:
                            self.raw_logger.info(json.dumps(dict(capture_session=self.capture_session, received_ns=received_ns, generation=generation, data_hex=data.hex())))
                        except OSError as exc:
                            with self.lock:
                                self.stats.raw_log_errors += 1
                                self.stats.raw_log_error = str(exc)
                            for handler in self.raw_logger.handlers:
                                try:
                                    handler.close()
                                except OSError:
                                    pass
                            self.raw_logger = None  # continue serial publication
                    lines = framer.feed(data)
                    with self.lock:
                        self.stats.bytes_received += len(data)
                        self.stats.last_byte = mono
                        self.stats.lines_received += len(lines)
                        self.stats.oversized += framer.oversized
                        framer.oversized = 0
                    for line in lines:
                        try:
                            measurement = parse(line)
                        except ValueError:
                            with self.lock:
                                self.stats.malformed += 1
                            continue
                        with self.lock:
                            if measurement is None:
                                self.stats.unrelated += 1
                                continue
                            self.stats.measurements += 1
                            sequence = self.stats.measurements
                            self.stats.last_measurement = mono
                            self.stats.reporter_mismatches += measurement.reporter != self.host_id
                        try:
                            self.queue.put_nowait((measurement, received_ns, generation, sequence))
                        except queue.Full:
                            with self.lock:
                                self.stats.queue_dropped += 1
            except (OSError, serial.SerialException, ValueError) as exc:
                with self.lock:
                    self.stats.error = f'{type(exc).__name__}: {exc}'
            finally:
                if port is not None:
                    try:
                        port.close()
                    except (OSError, serial.SerialException):
                        pass
                with self.lock:
                    if self.stats.connected:
                        self.stats.disconnects += 1
                    self.stats.connected = False
            if self.stop_event.wait(delay):
                break
            delay = min(self.reconnect_max, delay * 2)

import os
import pty
import time
import pytest
from mul_lps_bridge.transport import Framer, SerialWorker, select_device
from test_parser import GOOD


def until(predicate, seconds=3):
    end = time.monotonic()+seconds
    while time.monotonic()<end:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def test_framer_bounded_recovery():
    f = Framer(128)
    assert not f.feed(b'MR')
    assert f.feed(b'1\r\nother\n') == [b'MR1', b'other']
    assert f.feed(b'x'*100000) == []
    assert len(f.buffer) == 0 and f.oversized == 1
    assert f.feed(b'\nrecovered\n') == [b'recovered']


def test_selector(monkeypatch):
    monkeypatch.setattr('mul_lps_bridge.transport.glob.glob', lambda _: [])
    with pytest.raises(OSError):
        select_device()
    assert select_device('/explicit') == '/explicit'
    monkeypatch.setattr('mul_lps_bridge.transport.glob.glob', lambda _: ['/one','/two'])
    with pytest.raises(OSError):
        select_device()
    monkeypatch.setattr('mul_lps_bridge.transport.glob.glob', lambda _: ['/one'])
    assert select_device() == '/one'


def test_pty_read_only_partial_corrupt_bounded_and_shutdown(tmp_path):
    master, slave = pty.openpty()
    worker = SerialWorker(133, os.ttyname(slave), queue_size=2, raw_log=str(tmp_path/'raw.log'),raw_log_bytes=1024,raw_log_backups=2)
    try:
        worker.start()
        until(lambda: worker.snapshot()['connected'])
        os.write(master,b'MR')
        time.sleep(.12)
        assert worker.queue.empty()
        os.write(master, b'1 '+GOOD[4:].encode()+b'\r\nMR1 bad\nnoise\n'+b'x'*600+b'\n')
        os.write(master, ((GOOD+'\n')*40).encode())
        until(lambda: worker.snapshot()['measurements'] == 41)
        stats = worker.snapshot()
        assert stats['malformed']==1 and stats['unrelated']==1 and stats['oversized']==1
        assert stats['queue_dropped']==39 and stats['reporter_mismatches']==41
        assert worker.queue.qsize()==2
        m, ns, gen, seq = worker.queue.get_nowait()
        assert m.reporter==132 and ns>0 and gen==1 and seq==1
        # Opening/reading the slave must not transmit bytes to the master.
        os.set_blocking(master, False)
        with pytest.raises(BlockingIOError):
            os.read(master,1024)
        assert len(list(tmp_path.iterdir())) <= 3
    finally:
        worker.stop()
        os.close(master)
        os.close(slave)
    assert not worker.thread.is_alive()


def test_reconnect_clears_partial_and_preserves_duplicate():
    class Port:
        def __init__(self,chunks):
            self.chunks=iter(chunks)
            self.closed=False
        def read(self,n):
            item=next(self.chunks,None)
            if isinstance(item,Exception):
                raise item
            if item is None:
                time.sleep(.01)
                return b''
            return item
        def close(self):
            self.closed=True
    ports=[Port([b'MR1 c=12',OSError('unplug')]),Port([(GOOD+'\n'+GOOD+'\n').encode()])]
    calls=[]
    def factory(*args):
        calls.append(args)
        return ports[len(calls)-1]
    worker=SerialWorker(132,'fake',factory=factory,reconnect_min=.01,reconnect_max=.02)
    try:
        worker.start()
        until(lambda: worker.queue.qsize()==2)
        assert worker.snapshot()['generation']==2
        assert worker.snapshot()['disconnects']==1
        assert worker.snapshot()['malformed']==0
        first, second=worker.queue.get(),worker.queue.get()
        assert first[0]==second[0] and first[2]==second[2]==2 and second[3]==2
    finally:
        worker.stop()
    assert all(p.closed for p in ports)


def test_missing_device_shutdown_interrupts_backoff():
    def absent(_):
        raise OSError('absent')
    worker=SerialWorker(132,selector=absent,reconnect_min=10,reconnect_max=10)
    worker.start()
    until(lambda: 'absent' in worker.snapshot()['error'])
    start=time.monotonic()
    worker.stop()
    assert time.monotonic()-start<1


@pytest.mark.parametrize('kwargs',[{'queue_size':0},{'baud':0},{'line_limit':100},{'reconnect_min':0},{'raw_log_backups':0},{'host_id':255}])
def test_config_validation(kwargs):
    with pytest.raises(ValueError):
        SerialWorker(**({'host_id':132}|kwargs))

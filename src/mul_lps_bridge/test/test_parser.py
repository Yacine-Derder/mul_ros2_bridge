from pathlib import Path
import pytest
from mul_lps_bridge.parser import parse

FIX = Path(__file__).parent / 'fixtures'
GOOD = (FIX/'reference.txt').read_text().splitlines()[0]


def test_authentic_reference():
    rows = [parse(x) for x in (FIX/'reference.txt').read_text().splitlines()]
    assert len(rows) == 4
    assert [x.status for x in rows] == [0,0,1,0]
    assert rows[0].distance_mm == 967 and rows[0].raw_distance_mm == 873
    assert rows[2].distance_mm is None and rows[2].reason == 'timeout'
    assert all(x.reporter == 132 for x in rows)


def test_follower_and_duplicates():
    rows = [parse(x) for x in (FIX/'follower_synthetic.txt').read_text().splitlines()]
    assert rows[0] is None
    aa, ff_i, ff_j, fail = rows[1:]
    assert aa.marker == 'poll_rx' and aa.kind == 1
    assert ff_i.marker == 'poll_tx' and ff_j.marker == 'poll_rx'
    assert ff_i.kind == ff_j.kind == 4
    assert ff_j.timestamp_dtu == 2**40-1
    assert fail.timestamp_dtu == 0 and fail.epoch != ff_j.epoch
    assert fail.plan_fingerprint != ff_j.plan_fingerprint
    assert parse(ff_i.raw_record) == parse(ff_i.raw_record)


@pytest.mark.parametrize('old,new', [
 ('c=644','c=4294967296'), ('c=644','c=-1'), ('i=132','i=255'),
 ('j=133','j=132'), ('l=132','l=134'), ('b=1','b=2'), ('s=0','s=2'),
 ('t=1FCB41C4A4','t=1FCB41C4A'), ('e=0000000000000008','e=0000000000000000'),
 ('p=617AE520','p=XYZ'), ('mm=967','mm=307476'), ('raw=873','raw=-1'),
 ('q=1','q=2'), ('why=ok','why=timeout'), ('mm=967 ','')])
def test_bad_fields(old,new):
    with pytest.raises(ValueError):
        parse(GOOD.replace(old,new))


@pytest.mark.parametrize('line', [GOOD+' c=1', GOOD+' x=1', 'MR1', 'MR1 '+ 'x'*128,
 GOOD.replace(' q=1',''), GOOD.replace('mm=967','mm=1=2'), GOOD+'\nnoise',
 GOOD.encode()+b'\xff', GOOD.replace('b=1','b=4').replace('i=132 j=133','i=134 j=133')])
def test_corrupted(line):
    with pytest.raises(ValueError):
        parse(line)


@pytest.mark.parametrize('line',['','MUL TWR: result=FAILED','AA1 c=1','LOG dropped=20', 'noise MR1 c=1'])
def test_unrelated(line):
    assert parse(line) is None


def test_zero_max_and_failure():
    m = parse(GOOD.replace('mm=967','mm=0').replace('raw=873','raw=307475').replace('c=644','c=4294967295'))
    assert m.distance_mm == 0 and m.cycle == 2**32-1
    fail = GOOD.split(' mm=')[0].replace('s=0','s=1')+' why=timeout'
    assert parse(fail).power_corrected is None
    with pytest.raises(ValueError):
        parse(fail+' mm=0')


def test_deterministic_corruption_fuzz():
    import random
    rng=random.Random(42)
    for _ in range(2000):
        data=bytearray(GOOD.encode())
        for _ in range(rng.randrange(1,5)):
            data[rng.randrange(len(data))]=rng.randrange(256)
        try:
            result=parse(bytes(data))
        except ValueError:
            continue
        if result is not None:
            assert result.reporter in (result.initiator,result.responder)
            assert 0<=result.timestamp_dtu<2**40

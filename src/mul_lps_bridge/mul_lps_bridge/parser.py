"""Strict MR1 v1 validation, based on the pinned firmware contract in PROTOCOL.md."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Measurement:
    cycle: int
    initiator: int
    responder: int
    reporter: int
    timestamp_dtu: int
    epoch: int
    plan_fingerprint: int
    kind: int
    status: int
    distance_mm: int | None
    raw_distance_mm: int | None
    power_corrected: bool | None
    reason: str
    raw_record: str

    @property
    def marker(self):
        return 'failure' if self.status else ('poll_tx' if self.reporter == self.initiator else 'poll_rx')


def parse(line: bytes | str) -> Measurement | None:
    # Only a record at column zero is accepted: avoid matching embedded console text.
    if isinstance(line, bytes):
        if not line.startswith(b'MR1'):
            return None
        try:
            line = line.decode('ascii')
        except UnicodeDecodeError as exc:
            raise ValueError('non-ASCII MR1') from exc
    if not line.startswith('MR1'):
        return None
    text = line.rstrip('\r\n')
    if not text.startswith('MR1 ') or len(text) + 2 > 128 or '\n' in text or '\r' in text:
        raise ValueError('MR1 framing/length')
    fields = {}
    for token in text[4:].split():
        if token.count('=') != 1:
            raise ValueError('malformed token')
        key, value = token.split('=')
        if key in fields:
            raise ValueError('duplicate field')
        fields[key] = value

    def uint(key, bits):
        value = fields.get(key, '')
        if not re.fullmatch(r'[0-9]+', value) or int(value) >= 1 << bits:
            raise ValueError(f'{key}: uint{bits} required')
        return int(value)

    def hexi(key, width):
        value = fields.get(key, '')
        if not re.fullmatch(rf'[0-9a-fA-F]{{{width}}}', value):
            raise ValueError(f'{key}: {width} hex digits required')
        return int(value, 16)

    status = uint('s', 1)
    expected = {'c','i','j','l','t','e','p','b','s','why'}
    if not status:
        expected |= {'mm','raw','q'}
    if fields.keys() != expected:
        raise ValueError('missing/unsupported fields')
    c = uint('c', 32)
    i, j, l = (uint(k, 8) for k in ('i','j','l'))
    if max(i,j,l) > 254 or i == j or l not in (i,j):
        raise ValueError('pair/reporter identity')
    kind = uint('b', 3)
    if kind not in (1,4) or (kind == 4 and i >= j):
        raise ValueError('operation kind/order')
    t, e, p = hexi('t', 10), hexi('e', 16), hexi('p', 8)
    why = fields['why']
    if not re.fullmatch(r'[a-z_]+', why):
        raise ValueError('reason')
    mm = raw = q = None
    if not status:
        if e == 0 or why != 'ok':
            raise ValueError('success epoch/reason')
        mm, raw = uint('mm',32), uint('raw',32)
        if max(mm, raw) > 307475:
            raise ValueError('range outside firmware ToF domain')
        q = bool(uint('q',1))
    return Measurement(c,i,j,l,t,e,p,kind,status,mm,raw,q,why,text)

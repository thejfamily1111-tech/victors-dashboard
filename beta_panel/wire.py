"""Lossless, bounded Beta snapshots independent of the shared 850 KB mailbox."""
import base64
import hashlib
import json
import zlib
from .snapshot import validate, SnapshotError

WIRE_LIMIT = 8_000_000
LOGICAL_LIMIT = 64_000_000
ENCODING = 'beta-zlib-v1'


def encode(snapshot, secrets=()):
    clean = validate(snapshot, secrets=secrets, enforce_limit=False)
    raw = json.dumps(clean, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    if len(raw) > LOGICAL_LIMIT:
        raise SnapshotError('Beta archive exceeds 64 MB; previous complete report retained')
    # Required SQL headers are retained. Missing normal collections make older
    # readers reject this envelope rather than report a fictitious empty ledger.
    out = dict(schema=1, paper=True, observed_at=clean['observed_at'], positions=[], dossiers=[],
               encoding=ENCODING, raw_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
               payload=base64.b64encode(zlib.compress(raw, 6)).decode('ascii'))
    if len(json.dumps(out).encode()) > WIRE_LIMIT - 2000:
        raise SnapshotError('Beta compressed archive exceeds 8 MB; previous complete report retained')
    return out


def decode(snapshot):
    if not isinstance(snapshot, dict):
        raise SnapshotError('Invalid Beta envelope')
    if 'encoding' not in snapshot:
        return validate(snapshot)
    n = snapshot.get('raw_bytes'); payload = snapshot.get('payload')
    if (snapshot.get('encoding') != ENCODING or type(n) is not int or not 0 < n <= LOGICAL_LIMIT
            or not isinstance(payload, str) or len(payload) > WIRE_LIMIT):
        raise SnapshotError('Invalid Beta compression limits')
    try:
        packed = base64.b64decode(payload, validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(packed, n + 1)
        if (len(raw) != n or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
                or hashlib.sha256(raw).hexdigest() != snapshot.get('sha256')):
            raise ValueError()
        result = validate(json.loads(raw), enforce_limit=False)
        if result['observed_at'] != snapshot.get('observed_at'):
            raise ValueError()
        return result
    except (ValueError, TypeError, zlib.error, RecursionError):
        raise SnapshotError('Beta compressed report failed integrity validation') from None

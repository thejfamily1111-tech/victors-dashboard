import base64
from copy import deepcopy
import hashlib
import json
import random
import unittest
import zlib
from beta_panel.wire import encode, decode
from beta_panel.snapshot import CONFIG, OBJECTS, SECTIONS, SnapshotError

def sample():
    return dict(schema=1,paper=True,observed_at='2026-10-14T14:30:00+00:00',config=CONFIG,
                **{k:[] for k in SECTIONS},**{k:{} for k in OBJECTS})

class WireTests(unittest.TestCase):
    def test_large_research_complete_roundtrip(self):
        rng=random.Random(42); s=sample()
        s['dossiers']=[{'id':str(i),'symbol':'AAPL','summary':rng.randbytes(45000).hex()} for i in range(51)]
        s['positions']=[{'id':'open','quantity':3}];s['orders']=[{'id':'pending','status':'new'}]
        packed=encode(s)
        self.assertGreater(len(json.dumps(packed)),850000)
        self.assertEqual(decode(packed), __import__('beta_panel.snapshot',fromlist=['validate']).validate(s))
        self.assertEqual(len(decode(packed)['dossiers']),51)
    def test_legacy_report_and_redaction(self):
        s=sample();s['status']={'api_key':'private','text':'abcdefghSECRET'}
        out=decode(encode(s,secrets=('abcdefghSECRET',)))
        self.assertNotIn('private',json.dumps(out));self.assertNotIn('abcdefghSECRET',json.dumps(out))
        self.assertEqual(decode(sample())['positions'],[])
    def test_corruption_truncation_bomb_trailing(self):
        good=encode(sample())
        cases=[]
        bad=deepcopy(good);bad['raw_bytes']=1;cases.append(bad)
        bad=deepcopy(good);bad['raw_bytes']=64000001;cases.append(bad)
        bad=deepcopy(good);bad['sha256']='0'*64;cases.append(bad)
        bad=deepcopy(good);bad['payload']=bad['payload'][:-4];cases.append(bad)
        bad=deepcopy(good);bad['payload']=base64.b64encode(base64.b64decode(bad['payload'])+b'extra').decode();cases.append(bad)
        bad=deepcopy(good);bad['observed_at']='2026-10-13T00:00:00+00:00';cases.append(bad)
        for bad in cases:
            with self.subTest(bad=list(bad)):
                with self.assertRaises(SnapshotError):decode(bad)
    def test_old_reader_rejects_compressed_envelope(self):
        from beta_panel.snapshot import validate
        with self.assertRaises(SnapshotError):validate(encode(sample()))

if __name__=='__main__':unittest.main()

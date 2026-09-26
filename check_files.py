"""Verify this release's two code files. No secrets, network access or trading."""
from pathlib import Path
import hashlib
BASE=Path(__file__).resolve().parent
EXPECTED={'dashboard.py': '5bf8e12c5155228937bf282cb473af578834460f92b469c8efd128a03fe54965', 'vic.py': '96b59ec8aca3432dd708f4bb1230c7c073633ccc0eed6a20eca089ac6cad6bd6'}
for name, digest in EXPECTED.items():
    path=BASE/name
    if not path.is_file():
        print(name+': MISSING')
        continue
    content=path.read_bytes()
    good=hashlib.sha256(content).hexdigest()==digest
    print(name+(': COMPLETE AND MATCHED' if good else ': DIFFERENT OR INCOMPLETE — extract the original file again')+f' ({len(content.splitlines())} lines)')

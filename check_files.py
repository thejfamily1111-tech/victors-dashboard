"""Verify this release's code and calendar files. No secrets, network access or trading."""
from pathlib import Path
import hashlib
BASE=Path(__file__).resolve().parent
EXPECTED={'dashboard.py': 'f2949f0fc6833247ea667df775ea0ff220193d7e2937b7a9e40eecf251993bc9', 'vic.py': 'e1a750e720e6cc0fc2aa464eaec63ae41d26432603a3cab875c3c5d2dca781a3', 'bls.ics': '92a350111ace106deaab5584e4084366bd367b594a0d0bad116008d82d63e501', 'bls_snapshot.json': 'bdec5c06f6ed2d2474e50acbae43148ebc58680c8d396cd10810eb79324df9cc', 'import_bls_calendar.py': 'e9e33398636ce8a4844e43ebbc2fbdab50cb61359dda9f92f31a3b87e972fd3b'}
for name, digest in EXPECTED.items():
    path=BASE/name
    if not path.is_file():
        print(name+': MISSING')
        continue
    content=path.read_bytes()
    good=hashlib.sha256(content).hexdigest()==digest
    print(name+(': COMPLETE AND MATCHED' if good else ': DIFFERENT OR INCOMPLETE — extract the original file again')+f' ({len(content.splitlines())} lines)')

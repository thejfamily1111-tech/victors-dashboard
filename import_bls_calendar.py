"""Import a freshly browser-downloaded BLS calendar. No network or trading calls.
Usage: python3 import_bls_calendar.py ~/Downloads/bls.ics
Do not re-import an old copy merely to extend its validity.
"""
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from datetime import datetime
from vic import BASE, ET, CALENDARS, parse_ics, atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('calendar',type=Path)
    args=parser.parse_args()
    raw=args.calendar.expanduser().read_bytes()
    if len(raw)>5_000_000:parser.error('Calendar exceeds size limit')
    text=raw.decode('utf-8-sig')
    if 'Bureau of Labor Statistics' not in text:parser.error('Expected the official BLS calendar')
    rows=parse_ics(text,'BLS',CALENDARS['BLS'])
    now=datetime.now(ET)
    if not min(e['date'] for e in rows)<=str(now.date())<=max(e['date'] for e in rows):
        parser.error('Calendar does not cover today')
    tmp=None
    try:
        with tempfile.NamedTemporaryFile(dir=BASE,delete=False) as f:
            tmp=f.name;f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(tmp,BASE/'bls.ics')
    finally:
        if tmp and os.path.exists(tmp):os.unlink(tmp)
    # Hash binding means a concurrent read during replacement fails closed.
    atomic_json(BASE/'bls_snapshot.json',{'sha256':hashlib.sha256(raw).hexdigest(),'imported_at':now.isoformat()})
    print(f'Imported {len(rows)} BLS events. Saved calendar valid for seven days from {now.isoformat()}.')
    print('Restart Streamlit and any standalone VIC process. Scheduled times do not verify publication.')


if __name__=='__main__':main()

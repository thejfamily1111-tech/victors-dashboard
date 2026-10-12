"""Repair only the verified Beta-tab checksum mismatch in Victor Terminal."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

OLD = b"        overview,teamtab,news,research=st.tabs(['Overview','Teams & activity','News & events','Research'])"
NEW = b"""        overview,teamtab,news,research,beta=st.tabs(['Overview','Teams & activity','News & events','Research','Beta Research'])
        with beta:
            from beta_panel.integration import render_beta
            render_beta(d)
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def repair(target):
    target = Path(target).expanduser().resolve()
    manifest_path = target / 'release_manifest.json'
    view_path = target / 'dashboard_views.py'
    if manifest_path.is_symlink() or view_path.is_symlink():
        raise ValueError('Unexpected symlink. No files changed.')
    original_manifest = manifest_path.read_bytes()
    manifest = json.loads(original_manifest)
    hashes = manifest['sha256']
    expected = hashes['dashboard_views.py']
    current = view_path.read_bytes()
    tracked = {}
    mismatches = []
    for name, wanted in hashes.items():
        path = target / name
        if Path(name).is_absolute() or '..' in Path(name).parts or not path.resolve().is_relative_to(target):
            raise ValueError('Unexpected manifest path. No files changed.')
        if path.is_symlink() or not path.is_file():
            mismatches.append(name)
            continue
        data = path.read_bytes()
        tracked[name] = digest(data)
        if tracked[name] != wanted:
            mismatches.append(name)
    if not mismatches:
        print('All tracked files already match. The normal dashboard launcher can run.')
        return None
    if mismatches != ['dashboard_views.py']:
        raise ValueError('Other release files need review: ' + ', '.join(mismatches) + '. No files changed.')
    if current.count(NEW) != 1 or OLD in current or digest(current.replace(NEW, OLD, 1)) != expected:
        raise ValueError('This is not exactly the known Beta-tab change. No files changed; send dashboard_views.py for review.')
    compile(current, str(view_path), 'exec')
    panel = target / 'beta_panel'
    if panel.is_symlink():
        raise ValueError('Unexpected Beta panel symlink. No files changed.')
    for name in ('__init__.py', 'integration.py', 'snapshot.py', 'transport.py', 'ui.py', 'views.py'):
        path = panel / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Beta panel file missing or symlink: ' + name + '. No files changed.')
        compile(path.read_bytes(), str(path), 'exec')
    # The known view edit is the ONLY changed expectation. Other checks stay intact.
    hashes['dashboard_views.py'] = digest(current)
    replacement = (json.dumps(manifest, indent=2) + '\n').encode()
    backup = Path(tempfile.mkdtemp(prefix='dashboard-check-backup-', dir=target))
    shutil.copy2(manifest_path, backup / manifest_path.name)
    shutil.copy2(view_path, backup / view_path.name)
    for name, observed in tracked.items():
        if digest((target / name).read_bytes()) != observed:
            raise ValueError('A source file changed during verification. No files changed.')
    if manifest_path.read_bytes() != original_manifest:
        raise ValueError('The manifest changed during verification. No files changed.')
    staged = None
    try:
        with tempfile.NamedTemporaryFile(dir=target, delete=False) as stream:
            staged = Path(stream.name)
            stream.write(replacement)
        os.chmod(staged, manifest_path.stat().st_mode & 0o777)
        os.replace(staged, manifest_path)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
    print('Repaired the verified Beta-tab checksum. Dashboard source was preserved.')
    print('Backup:', backup)
    return backup


"""Read-only QQQ report diagnostics. Never import project code or call providers."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfo


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def report(path):
    result = {'exists': path.is_file()}
    if not result['exists']:
        return result
    try:
        result['file_modified_utc'] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        if path.stat().st_size > 25_000_000:
            result['error'] = 'report_too_large_for_diagnostic'
            return result
        raw = json.loads(path.read_bytes())
        if not isinstance(raw, dict):
            result['error'] = 'report_is_not_an_object'
            return result
        result['paper_flag'] = raw.get('paper') is True
        result['heartbeat'] = timestamp(raw.get('heartbeat'))
        if path.name == 'teams_telemetry.json':
            teams = raw.get('teams')
            result['teams_field_is_list'] = isinstance(teams, list)
            rows = [row for row in teams if isinstance(row, dict)] if isinstance(teams, list) else []
            result['team_rows'] = len(rows)
            result['paper_team_rows'] = sum(row.get('paper') is True for row in rows)
            times = [timestamp(row.get('heartbeat')) for row in rows]
            result['latest_team_heartbeat'] = max((value for value in times if value), default=None)
            result['dated_today_et_rows'] = sum(row.get('day') == datetime.now(ZoneInfo('America/New_York')).date().isoformat() for row in rows)
    except (OSError, ValueError, TypeError) as exc:
        result['error'] = type(exc).__name__
    return result


def process_ids(pattern):
    try:
        result = subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True, timeout=5)
        if result.returncode not in (0, 1):
            return {'error': 'process_lookup_unavailable'}
        return [int(value) for value in result.stdout.split() if value.isdigit()]
    except (OSError, subprocess.TimeoutExpired):
        return {'error': 'process_lookup_unavailable'}


def uploader_lock(path):
    if not path.is_file():
        return 'lock_file_missing'
    try:
        with path.open('r') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 'held_by_a_process'
            fcntl.flock(stream, fcntl.LOCK_UN)
            return 'not_held'
    except OSError:
        return 'unavailable'


def diagnose(target):
    target = Path(target).expanduser().resolve()
    return {
        'checked_utc': datetime.now(timezone.utc).isoformat(),
        'project_folder_exists': target.is_dir(),
        'teams_report': report(target / 'teams_telemetry.json'),
        'vic_report': report(target / 'vic_telemetry.json'),
        'qqq_uploader_config_file_present': (target / '.telemetry_private' / 'uploader.env').is_file(),
        'qqq_uploader_lock': uploader_lock(target / '.telemetry_sync.lock'),
        'process_pids': {
            'paper_runner': process_ids('run_paper[.]py'),
            'qqq_uploader': process_ids('sync_telemetry[.]py'),
            'streamlit_dashboards': process_ids('streamlit.*dashboard[.]py'),
        },
        'limits': 'Process matches can belong to another folder. Fresh local reports do not prove website receipt. No config contents, account data, provider requests, or orders are exposed or performed.'
    }



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=Path.home() / 'Desktop' / 'Coding')
    args = parser.parse_args()
    try:
        repair(args.target)
        print(json.dumps(diagnose(args.target), indent=2))
    except (OSError, ValueError, KeyError, TypeError, SyntaxError) as exc:
        print('Repair stopped:', str(exc))
        raise SystemExit(1)

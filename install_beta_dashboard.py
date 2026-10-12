"""Add the Beta tab to an existing local Victor dashboard, with a backup."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

OLD = "        overview,teamtab,news,research=st.tabs(['Overview','Teams & activity','News & events','Research'])"
NEW = """        overview,teamtab,news,research,beta=st.tabs(['Overview','Teams & activity','News & events','Research','Beta Research'])
        with beta:
            from beta_panel.integration import render_beta
            render_beta(d)
"""
EXTRA = ('beta_publish.py', 'BETA_TELEMETRY_SETUP.sql', 'BETA_INTEGRATION.md')
PANEL_MODULES = ('__init__.py', 'integration.py', 'snapshot.py', 'transport.py', 'ui.py', 'views.py')


def update_manifest(target, original, files):
    """Extend an intact release, or repair only the exact earlier Beta overlay.

    Never bless arbitrary local edits by regenerating all source fingerprints.
    Every existing entry must match; the sole permitted stale entry is the
    dashboard view whose exact inverse Beta patch matches its recorded base.
    """
    path = target / 'release_manifest.json'
    if not path.exists() and not path.is_symlink():
        return None  # The website checkout has no local release-manifest gate.
    if path.is_symlink():
        raise ValueError('Release manifest must not be a symlink. No files changed.')
    manifest = json.loads(path.read_text())
    hashes = manifest.get('sha256') if isinstance(manifest, dict) else None
    if not isinstance(hashes, dict) or 'dashboard_views.py' not in hashes:
        raise ValueError('Release manifest is not recognized. No files changed.')
    inverse = original.replace(NEW, OLD, 1).encode()
    for name, expected in hashes.items():
        relative = Path(name) if isinstance(name, str) else None
        if (relative is None or relative.is_absolute() or '..' in relative.parts
                or not relative.parts or not isinstance(expected, str)
                or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected)):
            raise ValueError('Release manifest contains an invalid fingerprint entry. No files changed.')
        destination = target / relative
        if (any(parent.is_symlink() for parent in (destination, *destination.parents) if parent != target.parent)
                or not destination.is_file()):
            raise ValueError('A release file is missing or linked: ' + name + '. No files changed.')
        actual = hashlib.sha256(destination.read_bytes()).hexdigest()
        if actual == expected:
            continue
        exact_old_overlay = (name == 'dashboard_views.py' and original.count(NEW) == 1
                             and hashlib.sha256(inverse).hexdigest() == expected)
        if not exact_old_overlay:
            raise ValueError('Unreviewed release mismatch: ' + name + '. No files changed.')
    for relative, content in files.items():
        if relative.suffix == '.py':
            hashes[relative.as_posix()] = hashlib.sha256(content).hexdigest()
    return (json.dumps(manifest, indent=2) + '\n').encode()


def install(source, target):
    source, target = Path(source).resolve(), Path(target).expanduser().resolve()
    view = target / 'dashboard_views.py'
    if not (target / 'dashboard.py').is_file() or not view.is_file():
        raise ValueError('Select the existing Victor dashboard folder containing dashboard.py and dashboard_views.py.')
    original = view.read_bytes().decode('utf-8')
    if OLD not in original:
        if original.count(NEW) != 1 or original.count('from beta_panel.integration import render_beta') != 1:
            raise ValueError('Dashboard version not recognized. No files changed; provide dashboard_views.py for a compatible patch.')
        modified = original
    else:
        if original.count(OLD) != 1 or 'from beta_panel.integration' in original:
            raise ValueError('Ambiguous tab layout. No files changed.')
        modified = original.replace(OLD, NEW, 1)
    compile(modified, str(view), 'exec')
    if not all((source / 'beta_panel' / name).is_file() for name in PANEL_MODULES):
        raise ValueError('The Beta integration package is incomplete. No files changed.')
    paths = [Path(name) for name in EXTRA] + sorted(Path('beta_panel') / p.name for p in (source / 'beta_panel').glob('*.py'))
    files = {Path('dashboard_views.py'): modified.encode()}
    for relative in paths:
        files[relative] = (source / relative).read_bytes()
        if relative.suffix == '.py':
            compile(files[relative], str(relative), 'exec')
    manifest = update_manifest(target, original, files)
    if manifest is not None:
        # Write last: a partially installed overlay must not pass the release gate.
        files[Path('release_manifest.json')] = manifest
    for relative in files:
        destination = target / relative
        if destination.is_symlink() or destination.parent.is_symlink():
            raise ValueError('Integration destinations must not be symlinks. No files changed.')
    backup = Path(tempfile.mkdtemp(prefix='beta-dashboard-' + datetime.now(timezone.utc).strftime('%Y%m%d-'), dir=target))
    existing = set()
    for relative in files:
        destination = target / relative
        if destination.exists():
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, saved)
            existing.add(relative)
    changed = []
    try:
        for relative, content in files.items():
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as tmp:
                tmp.write(content)
                staged = Path(tmp.name)
            try:
                os.replace(staged, destination)
            finally:
                staged.unlink(missing_ok=True)
            changed.append(relative)
    except BaseException:
        for relative in reversed(changed):
            if relative in existing:
                shutil.copy2(backup / relative, target / relative)
            else:
                (target / relative).unlink(missing_ok=True)
        raise
    return backup


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=Path.home() / 'Desktop' / 'Coding')
    args = parser.parse_args()
    try:
        backup = install(Path(__file__).parent, args.target)
        print('Beta Research tab installed. Restart the existing Victor dashboard.')
        print('Backup:', backup)
        print('No bot, .env, ledger, order, or trading settings were changed.')
    except Exception as exc:
        print('Installation stopped:', str(exc))
        raise SystemExit(1)

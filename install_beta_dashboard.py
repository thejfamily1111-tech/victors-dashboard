"""Add the Beta tab to an existing local Victor dashboard, with a backup."""
import argparse
from datetime import datetime, timezone
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


def install(source, target):
    source, target = Path(source).resolve(), Path(target).expanduser().resolve()
    view = target / 'dashboard_views.py'
    if not (target / 'dashboard.py').is_file() or not view.is_file():
        raise ValueError('Select the existing Victor dashboard folder containing dashboard.py and dashboard_views.py.')
    original = view.read_text()
    if OLD not in original:
        if NEW not in original:
            raise ValueError('Dashboard version not recognized. No files changed; provide dashboard_views.py for a compatible patch.')
        modified = original
    else:
        if original.count(OLD) != 1 or 'from beta_panel.integration' in original:
            raise ValueError('Ambiguous tab layout. No files changed.')
        modified = original.replace(OLD, NEW, 1)
    compile(modified, str(view), 'exec')
    paths = [Path(name) for name in EXTRA] + sorted(Path('beta_panel') / p.name for p in (source / 'beta_panel').glob('*.py'))
    files = {Path('dashboard_views.py'): modified.encode()}
    for relative in paths:
        files[relative] = (source / relative).read_bytes()
        if relative.suffix == '.py':
            compile(files[relative], str(relative), 'exec')
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

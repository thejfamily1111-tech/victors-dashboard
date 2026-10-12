"""Offline installer integrity checks; no broker, dashboard, or network calls."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import install_beta_dashboard as installer


def digest(data):
    return hashlib.sha256(data).hexdigest()


class ManifestInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source, self.target = root / 'package', root / 'Coding'
        self.source.mkdir()
        self.target.mkdir()
        (self.source / 'beta_panel').mkdir()
        for name in installer.PANEL_MODULES:
            (self.source / 'beta_panel' / name).write_text('# reviewed module\n')
        for name in installer.EXTRA:
            (self.source / name).write_text('# reviewed extra\n')
        self.original = ('def body():\n    if True:\n' + installer.OLD + '\n').encode()
        (self.target / 'dashboard_views.py').write_bytes(self.original)
        (self.target / 'dashboard.py').write_text('# QQQ dashboard\n')
        (self.target / 'run_paper.py').write_text('# QQQ engine unchanged\n')
        (self.target / '.env').write_text('PRIVATE=unchanged\n')
        self.manifest = {'release': 'existing-QQQ-release', 'sha256': {
            name: digest((self.target / name).read_bytes())
            for name in ('dashboard_views.py', 'dashboard.py', 'run_paper.py')}}
        self.write_manifest()

    def write_manifest(self):
        (self.target / 'release_manifest.json').write_text(json.dumps(self.manifest, indent=2) + '\n')

    def installed_manifest(self):
        return json.loads((self.target / 'release_manifest.json').read_text())

    def assert_release_passes(self):
        for name, expected in self.installed_manifest()['sha256'].items():
            self.assertEqual(digest((self.target / name).read_bytes()), expected, name)

    def test_new_overlay_passes_gate_tracks_dependencies_and_keeps_qqq(self):
        before = (self.target / 'release_manifest.json').read_bytes()
        backup = installer.install(self.source, self.target)
        self.assert_release_passes()
        updated = self.installed_manifest()
        self.assertEqual(updated['release'], self.manifest['release'])
        for name in ('dashboard.py', 'run_paper.py'):
            self.assertEqual(updated['sha256'][name], self.manifest['sha256'][name])
        for name in installer.PANEL_MODULES:
            self.assertIn('beta_panel/' + name, updated['sha256'])
        self.assertIn('beta_publish.py', updated['sha256'])
        self.assertEqual((backup / 'release_manifest.json').read_bytes(), before)
        self.assertEqual((backup / 'dashboard_views.py').read_bytes(), self.original)
        self.assertEqual((self.target / '.env').read_text(), 'PRIVATE=unchanged\n')

    def test_repairs_exact_legacy_overlay_then_reinstall_is_idempotent(self):
        overlaid = self.original.replace(installer.OLD.encode(), installer.NEW.encode(), 1)
        (self.target / 'dashboard_views.py').write_bytes(overlaid)
        installer.install(self.source, self.target)
        self.assert_release_passes()
        first = (self.target / 'release_manifest.json').read_bytes()
        installer.install(self.source, self.target)
        self.assertEqual((self.target / 'release_manifest.json').read_bytes(), first)
        self.assertEqual((self.target / 'dashboard_views.py').read_bytes(), overlaid)

    def test_unknown_views_edit_is_not_blessed(self):
        altered = self.original.replace(installer.OLD.encode(), installer.NEW.encode(), 1) + b'# unexpected\n'
        (self.target / 'dashboard_views.py').write_bytes(altered)
        before = (self.target / 'release_manifest.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Unreviewed release mismatch'):
            installer.install(self.source, self.target)
        self.assertEqual((self.target / 'dashboard_views.py').read_bytes(), altered)
        self.assertEqual((self.target / 'release_manifest.json').read_bytes(), before)
        self.assertFalse((self.target / 'beta_panel').exists())

    def test_other_release_mismatch_is_not_blessed(self):
        (self.target / 'run_paper.py').write_text('# unreviewed engine edit\n')
        with self.assertRaisesRegex(ValueError, 'run_paper.py'):
            installer.install(self.source, self.target)
        self.assertEqual((self.target / 'dashboard_views.py').read_bytes(), self.original)

    def test_missing_tracked_file_is_not_removed_from_manifest(self):
        (self.target / 'run_paper.py').unlink()
        with self.assertRaisesRegex(ValueError, 'missing or linked'):
            installer.install(self.source, self.target)
        self.assertIn('run_paper.py', self.installed_manifest()['sha256'])

    def test_manifest_without_view_fingerprint_refuses(self):
        del self.manifest['sha256']['dashboard_views.py']
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'not recognized'):
            installer.install(self.source, self.target)

    def test_missing_source_module_refuses_before_edit(self):
        (self.source / 'beta_panel' / 'snapshot.py').unlink()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            installer.install(self.source, self.target)
        self.assertEqual((self.target / 'dashboard_views.py').read_bytes(), self.original)

    def test_symlink_manifest_refuses(self):
        path = self.target / 'release_manifest.json'
        saved = self.target.parent / 'manifest.json'
        path.rename(saved)
        path.symlink_to(saved)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            installer.install(self.source, self.target)

    def test_manifest_write_failure_restores_original_files(self):
        before = (self.target / 'release_manifest.json').read_bytes()
        replace = installer.os.replace
        def fail_manifest(source, destination):
            if Path(destination).name == 'release_manifest.json':
                raise OSError('simulated disk failure')
            return replace(source, destination)
        with patch.object(installer.os, 'replace', side_effect=fail_manifest):
            with self.assertRaisesRegex(OSError, 'simulated disk failure'):
                installer.install(self.source, self.target)
        self.assertEqual((self.target / 'release_manifest.json').read_bytes(), before)
        self.assertEqual((self.target / 'dashboard_views.py').read_bytes(), self.original)
        self.assertFalse((self.target / 'beta_publish.py').exists())
        self.assertEqual(list((self.target / 'beta_panel').glob('*.py')), [])

    def test_website_without_manifest_still_installs_without_inventing_gate(self):
        (self.target / 'release_manifest.json').unlink()
        installer.install(self.source, self.target)
        self.assertIn(installer.NEW, (self.target / 'dashboard_views.py').read_text())
        self.assertFalse((self.target / 'release_manifest.json').exists())

    def test_updated_reviewed_module_gets_new_hash_after_old_hash_verification(self):
        installer.install(self.source, self.target)
        source = self.source / 'beta_panel' / 'views.py'
        source.write_text('# updated reviewed module\n')
        installer.install(self.source, self.target)
        self.assert_release_passes()
        self.assertEqual((self.target / 'beta_panel' / 'views.py').read_bytes(), source.read_bytes())


if __name__ == '__main__':
    unittest.main()

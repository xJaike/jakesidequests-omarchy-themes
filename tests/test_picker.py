import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('picker', Path(__file__).parents[1] / 'theme_picker.py')
picker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(picker)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'bundle'
        self.source.mkdir()
        (self.source / 'catalog.json').write_text(json.dumps([{'id': 'sample', 'name': 'Sample', 'series': 'Test', 'color': 'Violet'}]))
        theme = self.source / 'sample'
        theme.mkdir()
        (theme / 'colors.toml').write_text(
            'background = "#123456"\naccent = "#aabbcc"\n'
            'hyprland_active_border = "rgba(aabbccee) rgba(112233ee) 45deg"\n')
        (theme / 'shell.toml').write_text('[bar]\nbackground = "#123456"\n')
        (theme / 'backgrounds').mkdir()
        (theme / 'backgrounds/wallpaper.png').write_bytes(b'example')
        (theme / 'hyprland.lua').write_text('must not copy executable configs')
        self.target = self.root / 'themes'
        self.target.mkdir()
        for name, value in (('ROOT', self.source),):
            p = patch.object(picker, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(picker, 'themes_dir', return_value=self.target)
        p.start()
        self.addCleanup(p.stop)

    def existing(self):
        (self.target / 'sample').mkdir()
        (self.target / 'sample/original').write_text('keep')

    def test_install_only_declarative_files(self):
        self.assertEqual(picker.install('sample'), self.target / 'sample')
        self.assertTrue((self.target / 'sample/colors.toml').exists())
        self.assertFalse((self.target / 'sample/hyprland.lua').exists())

    def test_existing_install_needs_decision(self):
        self.existing()
        with self.assertRaises(picker.NeedsDecision):
            picker.install('sample')
        self.assertEqual((self.target / 'sample/original').read_text(), 'keep')

    def test_replace_keeps_backup(self):
        self.existing()
        picker.install('sample', replace=True)
        self.assertEqual(len(list(self.target.glob('.jake-theme-backup-*/sample/original'))), 1)
        self.assertTrue((self.target / 'sample/colors.toml').exists())

    def test_failed_replace_restores_backup(self):
        self.existing()
        real_rename = Path.rename

        def rename(path, target):
            if Path(target) == self.target / 'sample' and '.jake-theme-stage-' in str(path):
                raise OSError('disk full')
            return real_rename(path, target)

        with patch.object(Path, 'rename', rename), self.assertRaises(OSError):
            picker.install('sample', replace=True)
        self.assertEqual((self.target / 'sample/original').read_text(), 'keep')

    def test_status_values(self):
        with patch.object(picker, 'current_theme', return_value=None):
            self.assertEqual(picker.status('sample'), 'missing')
            picker.install('sample')
            self.assertEqual(picker.status('sample'), 'installed')
            (self.target / 'sample/colors.toml').write_text('background = "#000000"')
            self.assertEqual(picker.status('sample'), 'outdated')
        with patch.object(picker, 'current_theme', return_value='sample'):
            self.assertEqual(picker.status('sample'), 'current')

    def test_current_theme_reads_state_file_then_cli(self):
        state = self.root / 'state'
        (state / 'omarchy/current').mkdir(parents=True)
        (state / 'omarchy/current/theme.name').write_text('sample\n')
        with patch.dict(os.environ, XDG_STATE_HOME=str(state)):
            self.assertEqual(picker.current_theme(), 'sample')
            (state / 'omarchy/current/theme.name').unlink()
            with patch.object(picker.subprocess, 'run') as run:
                run.return_value.returncode = 0
                run.return_value.stdout = 'Sample\n'
                self.assertEqual(picker.current_theme(), 'sample')
                run.return_value.stdout = 'Other\n'
                self.assertIsNone(picker.current_theme())

    def test_apply_surfaces_stderr(self):
        with patch.object(picker.subprocess, 'run') as run:
            run.return_value.returncode = 1
            run.return_value.stderr = 'boom\n'
            with self.assertRaisesRegex(RuntimeError, '^boom$'):
                picker.apply('sample')
        self.assertEqual(run.call_args.args[0], ['omarchy', 'theme', 'set', 'sample'])

    def test_palette_second_color(self):
        palette = picker.palette('sample')
        self.assertEqual(palette['second'], '#112233')
        self.assertEqual(palette['background'], '#123456')

    def test_catalog_requires_series_and_color(self):
        (self.source / 'catalog.json').write_text(json.dumps([{'id': 'sample', 'name': 'Sample'}]))
        with self.assertRaisesRegex(ValueError, 'Missing series/color: sample'):
            picker.catalog()

    def test_unknown_slug_and_symlink_refused(self):
        with self.assertRaises(ValueError):
            picker.install('../outside')
        (self.source / 'sample/link').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):
            picker.catalog()


if __name__ == '__main__':
    unittest.main()

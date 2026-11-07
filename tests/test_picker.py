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
        self.assertEqual(run.call_args.kwargs.get('stdin'), picker.subprocess.DEVNULL)

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


class FootConfigTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def write(self, name, text):
        (self.dir / name).write_text(text)
        return self.dir / name

    def test_alpha_last_setting_wins_across_includes(self):
        self.write('theme.ini', '[colors]\nalpha=0.5\nbackground=101010\n')
        ini = self.write('foot.ini', f'[main]\ninclude={self.dir}/theme.ini\nfont=JetBrainsMono Nerd Font:size=9\n'
                                     '\n[colors-dark]\n# comment\nalpha=0.8\n')
        self.assertEqual(picker.terminal_alpha(ini), 0.8)
        self.assertEqual(picker.terminal_font_family(ini), 'JetBrainsMono Nerd Font')

    def test_alpha_from_include_and_defaults(self):
        self.write('theme.ini', '[colors]\nalpha = 0.6\n')
        ini = self.write('foot.ini', f'[main]\ninclude={self.dir}/theme.ini\n')
        self.assertEqual(picker.terminal_alpha(ini), 0.6)
        self.assertEqual(picker.terminal_alpha(self.dir / 'missing.ini'), 1.0)
        self.assertIsNone(picker.terminal_font_family(self.dir / 'missing.ini'))
        bad = self.write('bad.ini', '[colors]\nalpha=lots\n')
        self.assertEqual(picker.terminal_alpha(bad), 1.0)

    def test_alpha_ignored_outside_color_sections(self):
        ini = self.write('foot.ini', '[main]\nalpha=0.3\n')
        self.assertEqual(picker.terminal_alpha(ini), 1.0)


class StateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'jake-sidequests-themes/state.json'
        self.known = {'a', 'b'} | {f't{i}' for i in range(12)}

    def test_favorite_round_trip(self):
        state = picker.State.load(self.path, self.known)
        self.assertTrue(state.toggle_favorite('a'))
        state.save()
        state = picker.State.load(self.path, self.known)
        self.assertEqual(state.favorites, {'a'})
        self.assertFalse(state.toggle_favorite('a'))

    def test_recent_capped_newest_first_deduplicated(self):
        state = picker.State.load(self.path, self.known)
        for i in range(12):
            state.push_recent(f't{i}')
        state.push_recent('t5')
        self.assertEqual(state.recent[0], 't5')
        self.assertEqual(len(state.recent), 10)
        self.assertEqual(state.recent.count('t5'), 1)

    def test_unknown_slugs_dropped_on_load(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({'favorites': ['gone', 'a'], 'recent': ['gone', 'b']}))
        state = picker.State.load(self.path, {'a', 'b'})
        self.assertEqual(state.favorites, {'a'})
        self.assertEqual(state.recent, ['b'])

    def test_corrupt_file_gives_empty_state(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{nope')
        state = picker.State.load(self.path, self.known)
        self.assertEqual((state.favorites, state.recent), (set(), []))

    def test_save_is_atomic(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"favorites": ["a"], "recent": []}')
        state = picker.State.load(self.path, self.known)
        state.toggle_favorite('b')
        with patch.object(picker.os, 'replace', side_effect=OSError('crash')), self.assertRaises(OSError):
            state.save()
        self.assertEqual(self.path.read_text(), '{"favorites": ["a"], "recent": []}')

    def test_state_path_uses_xdg_state_home(self):
        with patch.dict(os.environ, XDG_STATE_HOME='/x'):
            self.assertEqual(picker.state_path(), Path('/x/jake-sidequests-themes/state.json'))


if __name__ == '__main__':
    unittest.main()

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
import io
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
        (self.source / 'catalog.json').write_text(json.dumps([{'id': 'sample', 'name': 'Sample'}]))
        theme = self.source / 'sample'
        theme.mkdir()
        (theme / 'colors.toml').write_text('background = "#123456"')
        (theme / 'backgrounds').mkdir()
        (theme / 'backgrounds/wallpaper.png').write_bytes(b'example')
        (theme / 'hyprland.lua').write_text('must not copy executable configs')
        self.target = self.root / 'themes'
        self.target.mkdir()
        self.root_patch = patch.object(picker, 'ROOT', self.source)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.dir_patch = patch.object(picker, 'themes_dir', return_value=self.target)
        self.dir_patch.start()
        self.addCleanup(self.dir_patch.stop)

    def test_install_only_declarative_files(self):
        self.assertTrue(picker.install('sample'))
        self.assertTrue((self.target / 'sample/colors.toml').exists())
        self.assertFalse((self.target / 'sample/hyprland.lua').exists())

    def test_declined_replacement_preserves_original(self):
        (self.target / 'sample').mkdir()
        (self.target / 'sample/original').write_text('keep')
        with patch.object(picker.subprocess, 'run') as run:
            run.return_value.returncode = 1
            self.assertFalse(picker.install('sample'))
        self.assertEqual((self.target / 'sample/original').read_text(), 'keep')

    def test_confirmed_replacement_keeps_backup(self):
        (self.target / 'sample').mkdir()
        (self.target / 'sample/original').write_text('keep')
        with patch.object(picker.subprocess, 'run') as run:
            run.return_value.returncode = 0
            self.assertTrue(picker.install('sample'))
        self.assertEqual(len(list(self.target.glob('.jake-theme-backup-*/sample/original'))), 1)

    def test_unknown_slug_and_symlink_refused(self):
        with self.assertRaises(ValueError):
            picker.install('../outside')
        (self.source / 'sample/link').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):
            picker.catalog()


class PreviewTests(unittest.TestCase):
    def test_preview_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            picker.preview('../outside')

    def test_picker_returns_identifier_and_keeps_terminal_output(self):
        with patch.object(picker.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = 'sample\tSample Theme\n'
            self.assertEqual(picker.choose_theme([{'id': 'sample', 'name': 'Sample Theme'}]), 'sample')
        self.assertNotIn('stderr', run.call_args.kwargs)
        self.assertIn('--preview', run.call_args.args[0])

    def test_wallpaper_and_palette_render_at_preview_size(self):
        with patch.dict(picker.os.environ, FZF_PREVIEW_COLUMNS='2', FZF_PREVIEW_LINES='9'):
            with patch.object(picker.subprocess, 'run') as run:
                run.return_value.stdout = b'\x1bPqimage\x1b\\'
                output = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
                with redirect_stdout(output), patch.object(picker, 'terminal_cell_size', return_value=(10, 20)):
                    picker.preview('a2-desert-memory')
        rendered = output.buffer.getvalue()
        self.assertIn(b'\x1bPqimage', rendered)
        background = picker.tomllib.loads((picker.ROOT / 'a2-desert-memory/colors.toml').read_text())['background']
        self.assertIn(f'background: {background}'.encode(), rendered)
        self.assertIn('20x40', run.call_args.args[0])
        self.assertIn('sixel:-', run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()

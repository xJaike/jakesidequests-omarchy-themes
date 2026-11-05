import importlib.util
import json
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


if __name__ == '__main__':
    unittest.main()

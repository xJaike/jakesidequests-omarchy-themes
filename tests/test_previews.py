import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('previews', ROOT / 'previews.py')
previews = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previews)

PALETTE = {'background': '#101010', 'accent': '#aa00ff', 'second': '#00ccff',
           'lighter_background': '#303030', 'foreground': '#eeeeee'}


class FakeRun:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if self.error:
            raise self.error

        class Result:
            stdout = b'SIXEL'
        return Result()


class PreviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'bundle'
        (self.root / 'sample/backgrounds').mkdir(parents=True)
        (self.root / 'sample/colors.toml').write_text('accent = "#aa00ff"\n')
        (self.root / 'sample/backgrounds/01-wallpaper.png').write_bytes(b'png')
        self.cache = Path(temp.name) / 'cache'

    def make(self, run, on_ready=lambda: None):
        return previews.Previews(self.root, self.cache, lambda slug: PALETTE, run=run, on_ready=on_ready)

    def test_stage_command_uses_palette_and_size(self):
        argv = previews.stage_command(Path('/w.png'), PALETTE, 990, 560)
        joined = ' '.join(argv)
        self.assertEqual(argv[0], 'magick')
        self.assertIn('990x560', joined)
        for color in ('#aa00ff', '#00ccff', '#101010', '#303030'):
            self.assertIn(color, joined)
        self.assertEqual(argv[-1], 'sixel:-')
        self.assertIn('200x112', ' '.join(previews.thumb_command(Path('/w.png'), 200, 112)))

    def test_sample_command_blends_wallpaper_and_draws_text(self):
        segments = [[('❯ ', '#11aa11', None), ('ls', '#eeeeee', None)], [(' selection ', '#eeeeee', '#333366')]]
        argv = previews.sample_command(Path('/w.png'), PALETTE, segments, 590, 400, 0.8, (10, 20), '/f.ttf')
        joined = ' '.join(argv)
        self.assertIn('590x400', joined)
        self.assertIn('xc:#101010', joined)
        self.assertIn('80%', joined)
        self.assertIn('/f.ttf', joined)
        for text in ('❯ ', 'ls', ' selection '):
            self.assertIn(text, argv)
        self.assertIn('#333366', joined)
        # Text offsets must be baselines (no gravity), so text lines up with its row and highlight.
        self.assertLess(argv.index('+gravity'), argv.index('-annotate'))
        self.assertEqual(argv[-1], 'sixel:-')

    def test_render_sample_uses_settings_and_keys_cache_on_them(self):
        run = FakeRun()
        p = self.make(run)
        p.sample_settings(alpha=0.8, cell=(10, 20), font='/f.ttf', segments=lambda palette: [[('x', '#fff', None)]])
        self.assertEqual(p.render('sample', 'sample', 590, 400), b'SIXEL')
        self.assertIn('80%', ' '.join(run.calls[0]))
        p.sample_settings(alpha=0.6, cell=(10, 20), font='/f.ttf', segments=lambda palette: [])
        self.assertIsNone(p.get('sample', 'sample', 590, 400))

    def test_render_caches_on_disk_and_memory(self):
        run = FakeRun()
        first = self.make(run)
        self.assertEqual(first.render('stage', 'sample', 990, 560), b'SIXEL')
        self.assertEqual(first.get('stage', 'sample', 990, 560), b'SIXEL')
        self.assertEqual(run.calls[0][:3], ['nice', '-n', '10'])
        second = self.make(FakeRun(OSError('must not render')))
        self.assertEqual(second.get('stage', 'sample', 990, 560), b'SIXEL')
        self.assertEqual(len(run.calls), 1)

    def test_palette_change_invalidates_cache(self):
        p = self.make(FakeRun())
        p.render('thumb', 'sample', 200, 112)
        (self.root / 'sample/colors.toml').write_text('accent = "#00ff00"\n')
        self.assertIsNone(p.get('thumb', 'sample', 200, 112))

    def test_render_failure_logged_returns_none(self):
        p = self.make(FakeRun(FileNotFoundError('magick')))
        self.assertIsNone(p.render('stage', 'sample', 990, 560))
        self.assertIn('sample', (self.cache / 'picker.log').read_text())

    def test_worker_renders_requested_then_signals(self):
        ready = threading.Event()
        p = self.make(FakeRun(), on_ready=ready.set)
        p.request([('thumb', 'sample', 200, 112)])
        p.start()
        self.addCleanup(p.stop)
        self.assertTrue(ready.wait(2))
        self.assertEqual(p.get('thumb', 'sample', 200, 112), b'SIXEL')

    def test_missing_wallpaper_gives_none(self):
        p = self.make(FakeRun())
        self.assertIsNone(p.get('thumb', 'nope', 200, 112))
        self.assertIsNone(p.render('thumb', 'nope', 200, 112))


if __name__ == '__main__':
    unittest.main()

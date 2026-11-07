import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('tui', ROOT / 'tui.py')
tui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tui)


def inside(rect, cols, rows):
    return rect.x >= 0 and rect.y >= 0 and rect.x + rect.w <= cols and rect.y + rect.h <= rows


class LayoutTests(unittest.TestCase):
    def test_wide_layout(self):
        layout = tui.compute_layout(160, 48, 10, 20)
        self.assertEqual(layout.mode, 'wide')
        self.assertEqual(layout.stage.w, 99)
        self.assertIsNotNone(layout.sample)
        self.assertEqual(layout.stage_px, (990, layout.stage.h * 20))
        self.assertGreaterEqual(len(layout.film), 3)
        for rect in [layout.header, layout.chips, layout.stage, layout.sample, layout.info, *layout.film]:
            self.assertTrue(inside(rect, 160, 48), rect)
        self.assertLess(layout.stage.y + layout.stage.h, layout.info.y + 1)
        self.assertLess(layout.info.y, layout.film[0].y)
        self.assertEqual(layout.sample.y, layout.stage.y)
        self.assertGreaterEqual(layout.sample.x, layout.stage.x + layout.stage.w)
        self.assertEqual(layout.sample_px, (layout.sample.w * 10, layout.sample.h * 20))
        card = layout.film[0]
        self.assertEqual(layout.thumb_px, (card.w * 10, (card.h - 2) * 20))

    def test_narrow_hides_sample(self):
        layout = tui.compute_layout(99, 40, 10, 20)
        self.assertEqual(layout.mode, 'narrow')
        self.assertIsNone(layout.sample)
        self.assertEqual(layout.stage.w, 99)

    def test_tiny(self):
        for cols, rows in ((59, 30), (80, 19)):
            layout = tui.compute_layout(cols, rows, 10, 20)
            self.assertEqual(layout.mode, 'tiny')
            self.assertIsNone(layout.stage)
            self.assertEqual(layout.film, [])

    def test_minimum_three_cards(self):
        layout = tui.compute_layout(60, 20, 10, 20)
        self.assertEqual(len(layout.film), 3)
        for rect in layout.film:
            self.assertTrue(inside(rect, 60, 20), rect)


if __name__ == '__main__':
    unittest.main()

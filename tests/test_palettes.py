import importlib.util
import json
from pathlib import Path
import re
import tomllib
import unittest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('palettes', ROOT / 'tools/derive_palettes.py')
palettes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(palettes)
THEMES = [item['id'] for item in json.loads((ROOT / 'catalog.json').read_text())]
HEX = re.compile(r'#[0-9a-f]{6}')


def colors(slug):
    return tomllib.loads((ROOT / slug / 'colors.toml').read_text())


class PaletteTests(unittest.TestCase):
    def test_text_colors_are_readable_on_background(self):
        for slug in THEMES:
            c = colors(slug)
            for key in ('foreground', 'accent', 'red', 'yellow', 'orange', 'green', 'cyan', 'blue', 'magenta',
                        'bright_red', 'bright_yellow', 'bright_green', 'bright_cyan', 'bright_blue', 'bright_magenta'):
                with self.subTest(theme=slug, color=key):
                    self.assertGreaterEqual(palettes.contrast(c[key], c['background']), 4.5)
            with self.subTest(theme=slug, color='muted'):
                self.assertGreaterEqual(palettes.contrast(c['muted'], c['background']), 3.0)

    def test_terminal_colors_keep_their_meaning(self):
        for slug in set(THEMES) - palettes.HAND_TUNED:
            c = colors(slug)
            for name, (_, low, high) in palettes.ANSI_SLOTS.items():
                with self.subTest(theme=slug, color=name):
                    hue = palettes.hex_to_lch(c[name])[2]
                    self.assertLessEqual(abs(palettes.hue_delta((low + high) / 2, hue)), (high - low) / 2 + 2)

    def test_color_family_boundaries(self):
        lch = palettes.lch
        self.assertEqual(palettes.color_family(lch(0.8, 0.12, 355)), 'Crimson')
        self.assertEqual(palettes.color_family(lch(0.8, 0.12, 10)), 'Crimson')
        self.assertEqual(palettes.color_family(lch(0.8, 0.12, 40)), 'Ember')
        self.assertEqual(palettes.color_family(lch(0.8, 0.12, 85)), 'Gold')
        self.assertEqual(palettes.color_family(lch(0.8, 0.12, 150)), 'Jade')
        self.assertEqual(palettes.color_family(lch(0.8, 0.12, 230)), 'Ocean')
        self.assertEqual(palettes.color_family(lch(0.8, 0.12, 290)), 'Violet')
        self.assertEqual(palettes.color_family(lch(0.8, 0.12, 330)), 'Rose')
        self.assertEqual(palettes.color_family(lch(0.8, 0.03, 290)), 'Silver')

    def test_catalog_has_series_and_color(self):
        entries = json.loads((ROOT / 'catalog.json').read_text())
        self.assertEqual({e['id'] for e in entries}, set(palettes.SERIES))
        for e in entries:
            self.assertIn(e['color'], palettes.COLOR_FAMILIES)
            self.assertTrue(e['series'])
        by_id = {e['id']: e['series'] for e in entries}
        self.assertEqual(by_id['madara-crimson-eclipse'], 'Naruto')
        self.assertEqual(by_id['gojo-hollow-purple'], 'Jujutsu Kaisen')
        self.assertEqual(by_id['geralt-silver-hunt'], 'The Witcher')
        self.assertEqual(by_id['totoro-rain-shelter'], 'Studio Ghibli')

    def test_palette_values_are_well_formed(self):
        for slug in THEMES:
            c = colors(slug)
            for key, value in c.items():
                if key not in ('mode', 'hyprland_active_border', 'hyprland_inactive_border'):
                    with self.subTest(theme=slug, key=key):
                        self.assertRegex(value, HEX)
            with self.subTest(theme=slug, key='shell'):
                shell = tomllib.loads((ROOT / slug / 'shell.toml').read_text())
                self.assertEqual(shell['bar']['background'], c['background'])
                self.assertEqual(shell['notifications']['countdown'], c['accent'])


if __name__ == '__main__':
    unittest.main()

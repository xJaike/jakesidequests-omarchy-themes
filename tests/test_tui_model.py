import importlib.util
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('tui', ROOT / 'tui.py')
tui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tui)

FIXTURE = [
    ('a', 'Akatsuki Rain', 'Naruto', 'Crimson'),
    ('b', 'Blood Moon', 'Naruto', 'Crimson'),
    ('c', 'Cursed Storm', 'Naruto', 'Violet'),
    ('d', 'Drift Tide', 'One Piece', 'Jade'),
    ('e', 'Emerald Hunt', 'The Witcher', 'Jade'),
    ('f', 'Field Train', 'Persona', 'Gold'),
]


def make_model(**kwargs):
    themes = [tui.Theme(i, n, s, c, {}) for i, n, s, c in FIXTURE]
    return tui.Model(themes=themes, favorites=kwargs.pop('favorites', set()),
                     recent=kwargs.pop('recent', []), current=None, **kwargs)


def ids(themes):
    return [theme.id for theme in themes]


class ModelTests(unittest.TestCase):
    def test_filters_combine(self):
        model = make_model()
        model.set_series('Naruto')
        model.toggle_color('Crimson')
        self.assertEqual(ids(model.filtered()), ['a', 'b'])
        model.toggle_color('Crimson')
        self.assertIsNone(model.color)
        self.assertEqual(ids(model.filtered()), ['a', 'b', 'c'])

    def test_search_matches_name_series_color_all_words(self):
        model = make_model()
        for text, expected in (('naruto crimson', 2), ('jade witcher', 1), ('JADE', 2)):
            model.search = ''
            for ch in text:
                model.type_char(ch)
            self.assertEqual(len(model.filtered()), expected, text)
        model.backspace()
        self.assertEqual(model.search, 'JAD')

    def test_favorites_and_recent_views(self):
        model = make_model(favorites={'e', 'b'}, recent=['c', 'a'])
        model.set_view('recent')
        self.assertEqual(ids(model.filtered()), ['c', 'a'])
        model.set_view('favorites')
        self.assertEqual(ids(model.filtered()), ['b', 'e'])

    def test_selection_kept_or_clamped_after_filter(self):
        model = make_model()
        model.end()
        self.assertEqual(model.selected().id, 'f')
        model.set_series('Persona')
        self.assertEqual(model.selected().id, 'f')
        model.set_series('Naruto')
        self.assertTrue(0 <= model.index < len(model.filtered()))
        self.assertIsNotNone(model.selected())
        model.toggle_color('Gold')
        self.assertEqual(model.filtered(), [])
        self.assertIsNone(model.selected())

    def test_surprise_stays_in_filter_and_moves(self):
        model = make_model()
        model.set_series('Naruto')
        rng = random.Random(1)
        previous = model.selected().id
        for _ in range(20):
            model.surprise(rng)
            self.assertIn(model.selected().id, {'a', 'b', 'c'})
            self.assertNotEqual(model.selected().id, previous)
            previous = model.selected().id

    def test_chips_list(self):
        model = make_model()
        labels = [chip.label for chip in model.chips()]
        self.assertEqual(labels[:4], ['All 6', '★ Favorites', 'Recent', 'Series: any ▾'])
        self.assertEqual([c.value for c in model.chips() if c.kind == 'color'], ['Crimson', 'Gold', 'Jade', 'Violet'])
        model.set_series('Naruto')
        self.assertIn('Series: Naruto ▾', [chip.label for chip in model.chips()])
        self.assertEqual(model.series_options()[0], ('Naruto', 3))

    def test_move_home_end_clamp(self):
        model = make_model()
        model.move(-1)
        self.assertEqual(model.index, 0)
        model.end()
        self.assertEqual(model.selected().id, 'f')
        model.move(5)
        self.assertEqual(model.selected().id, 'f')
        model.home()
        self.assertEqual(model.index, 0)
        self.assertTrue(model.select_id('d'))
        self.assertFalse(model.select_id('zzz'))
        self.assertEqual(model.selected().id, 'd')


if __name__ == '__main__':
    unittest.main()

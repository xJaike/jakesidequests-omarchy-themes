import unittest

from test_tui_model import FIXTURE, tui

KEYS = ('background', 'foreground', 'muted', 'accent', 'second', 'selection', 'lighter_background',
        'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'orange', 'brown',
        'bright_red', 'bright_yellow', 'bright_green', 'bright_cyan', 'bright_blue', 'bright_magenta',
        'light_foreground', 'dark_foreground', 'bright_foreground')


def palette(seed):
    return {key: '#%02x%02x%02x' % (seed * 20 + 10, k * 15 + 5, 200 - seed * 7) for k, key in enumerate(KEYS)}


def make_model(**kwargs):
    themes = [tui.Theme(i, n, s, c, palette(k)) for k, (i, n, s, c) in enumerate(FIXTURE)]
    return tui.Model(themes=themes, favorites=set(), recent=[], current=None, **kwargs)


def code(kind, value):
    r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
    return f'\x1b[{38 if kind == "fg" else 48};2;{r};{g};{b}m'.encode()


def osc(number, value):
    return f'\x1b]{number};rgb:{value[1:3]}/{value[3:5]}/{value[5:7]}\x1b\\'.encode()


class FakeImages:
    def __init__(self, available=()):
        self.available, self.calls = set(available), []

    def get(self, kind, slug, w, h):
        self.calls.append((kind, slug, w, h))
        return f'\x1bPq{kind}-{slug}\x1b\\'.encode() if (kind, slug) in self.available else None


class PaintTests(unittest.TestCase):
    def setUp(self):
        self.layout = tui.compute_layout(160, 48, 10, 20)

    def frame(self, model, images=None, sixel=True, layout=None):
        return tui.paint_frame(model, layout or self.layout, images or FakeImages(), sixel)

    def test_frame_tints_terminal_default_colors_to_selected_theme(self):
        model = make_model()
        out = self.frame(model)
        self.assertIn(osc(11, model.themes[0].palette['background']), out)
        self.assertIn(osc(10, model.themes[0].palette['foreground']), out)
        self.assertIn(code('fg', model.themes[0].palette['accent']), out)
        # Base cells keep the default background so foot's opacity applies to them.
        self.assertIn(b'\x1b[49m', out)
        self.assertNotIn(code('bg', model.themes[0].palette['background']), out)
        model.move(1)
        out = self.frame(model)
        self.assertIn(osc(11, model.themes[1].palette['background']), out)
        self.assertNotIn(osc(11, model.themes[0].palette['background']), out)

    def test_sample_shows_ansi_colors(self):
        model = make_model()
        out = self.frame(model)
        for key in ('red', 'green', 'yellow', 'blue', 'magenta', 'cyan'):
            self.assertIn(code('fg', model.themes[0].palette[key]), out)
        self.assertIn('git:(main)'.encode(), out)

    def test_showroom_names_each_color_in_its_own_color(self):
        p = palette(2)
        segments = [segment for line in tui.sample_segments(p) for segment in line]
        for key in ('red', 'yellow', 'green', 'cyan', 'blue', 'magenta', 'orange', 'brown'):
            self.assertIn((key, p[key], None), [(t.strip(), f, b) for t, f, b in segments])
        for key in ('red', 'yellow', 'green', 'cyan', 'blue', 'magenta'):
            self.assertIn(p['bright_' + key], [f for _, f, _ in segments])
        for key in ('foreground', 'light_foreground', 'dark_foreground', 'bright_foreground', 'muted',
                    'accent', 'second'):
            self.assertIn(p[key], [f for _, f, _ in segments])
        self.assertIn(p['selection'], [b for _, _, b in segments])
        self.assertIn(' selection ', [t for t, _, _ in segments])

    def test_showroom_painted_as_text_when_opaque(self):
        model = make_model()
        out = self.frame(model)
        for key in ('bright_red', 'orange', 'brown', 'light_foreground'):
            self.assertIn(code('fg', model.themes[0].palette[key]), out)
        self.assertIn(b'palette', out)

    def test_cached_thumbs_drawn_placeholders_otherwise(self):
        model = make_model()
        out = self.frame(model, FakeImages({('thumb', 'b')}))
        self.assertEqual(out.count(b'\x1bPqthumb-b'), 1)
        self.assertIn(code('bg', model.themes[2].palette['lighter_background']), out)

    def test_wanted_images_use_current_sizes(self):
        model = make_model()
        model.move(2)
        for cols, rows in ((160, 48), (100, 30)):
            layout = tui.compute_layout(cols, rows, 10, 20)
            jobs = tui.wanted_images(model, layout)
            self.assertEqual(jobs[0], ('stage', 'c', *layout.stage_px))
            self.assertEqual({job[1] for job in jobs if job[0] == 'stage'}, {'b', 'c', 'd'})
            for kind, _, w, h in jobs:
                self.assertEqual((w, h), layout.stage_px if kind == 'stage' else layout.thumb_px)

    def test_stage_painted_only_when_cached(self):
        model = make_model()
        self.assertIsNone(tui.paint_stage(model, self.layout, FakeImages()))
        out = tui.paint_stage(model, self.layout, FakeImages({('stage', 'a')}))
        self.assertIn(b'\x1bPqstage-a', out)

    def test_paint_thumbs_draws_each_cached_thumb_once(self):
        model, drawn = make_model(), set()
        images = FakeImages({('thumb', 'a'), ('thumb', 'b')})
        out = tui.paint_thumbs(model, self.layout, images, drawn)
        self.assertEqual((out.count(b'\x1bPqthumb-'), drawn), (2, {'a', 'b'}))
        self.assertEqual(tui.paint_thumbs(model, self.layout, images, drawn), b'')

    def test_tiny_empty_and_no_sixel_messages(self):
        model = make_model()
        tiny = tui.compute_layout(50, 30, 10, 20)
        self.assertIn(b'Enlarge window to browse themes', self.frame(model, layout=tiny))
        self.assertIn(b'Images need a Sixel terminal such as foot', self.frame(model, sixel=False))
        model.set_series('Persona')
        model.toggle_color('Crimson')
        self.assertIn(b'No themes match', self.frame(model))

    def test_outdated_prompt_text(self):
        model = make_model(prompt='outdated')
        self.assertIn('u update & apply (backup kept) · a apply my copy · Esc cancel'.encode(), self.frame(model))

    def test_message_and_badges(self):
        model = make_model(message='boom', error=True)
        model.favorites.add('a')
        model.installed = {'a'}
        out = self.frame(model)
        self.assertIn(code('fg', model.themes[0].palette['red']) + b'boom', out)
        self.assertIn('★'.encode(), out)

    def test_info_line_fits_and_keeps_left_text(self):
        model = make_model(prompt='outdated')
        for cols in (60, 95, 100, 120, 160):
            left, hints = tui.info_line(model, model.selected(), cols)
            self.assertEqual(left, tui.OUTDATED_PROMPT if cols >= 62 else left)
            used = len(left) + (len(hints) + 2 if hints else 0)
            self.assertLessEqual(used, cols - 2, cols)
        model = make_model(message='x' * 300, error=True)
        left, hints = tui.info_line(model, model.selected(), 100)
        self.assertLessEqual(len(left), 98)

    def test_chips_fit_width(self):
        model = make_model()
        model.themes = [tui.Theme(f't{c}', 'n', 'The Apothecary Diaries', c, palette(1))
                        for c in tui.COLOR_FAMILIES[:7]]
        model.set_series('The Apothecary Diaries')
        for cols in (60, 95, 100, 120, 160):
            layout = tui.compute_layout(cols, 40, 10, 20)
            spans = tui.chip_spans(model, layout)
            self.assertLessEqual(spans[-1][1], cols - 1, cols)
            if cols >= 95:
                self.assertEqual(sum(1 for *_, chip in spans if chip.kind == 'color'), 7, cols)

    def test_series_list_and_centered_film(self):
        layout = tui.compute_layout(60, 20, 10, 20)
        model = make_model(focus='series')
        self.assertIn(b'Naruto (3)', self.frame(model, layout=layout))
        model = make_model(index=3)
        out = self.frame(model, layout=layout)
        for name in ('Cursed Storm', 'Drift Tide', 'Emerald Hunt'):
            self.assertIn(name.encode(), out)
        for name in ('Blood Moon', 'Field Train'):
            self.assertNotIn(name.encode(), out)


if __name__ == '__main__':
    unittest.main()

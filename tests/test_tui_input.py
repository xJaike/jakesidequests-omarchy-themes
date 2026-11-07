import random
import unittest

from test_tui_model import make_model, tui

E = tui.Event


def key(name):
    return E('key', name)


class ParseTests(unittest.TestCase):
    def test_arrows_home_end_enter_tab_esc(self):
        events = tui.parse_input(b'\x1b[D\x1b[C\x1b[A\x1b[B\x1b[H\x1b[F\r\t')
        self.assertEqual(events, [key(k) for k in ('left', 'right', 'up', 'down', 'home', 'end', 'enter', 'tab')])

    def test_many_keys_in_one_read(self):
        self.assertEqual(tui.parse_input(b'\x1b[C\x1b[C\x1b[C'), [key('right')] * 3)

    def test_lone_escape(self):
        self.assertEqual(tui.parse_input(b'\x1b'), [key('esc')])
        self.assertEqual(tui.parse_input(b'\x1bx'), [key('esc'), E('char', 'x')])

    def test_sgr_mouse(self):
        self.assertEqual(tui.parse_input(b'\x1b[<0;12;5M'), [E('click', None, 11, 4)])
        self.assertEqual(tui.parse_input(b'\x1b[<64;1;1M'), [E('wheel', -1)])
        self.assertEqual(tui.parse_input(b'\x1b[<65;1;1M'), [E('wheel', 1)])
        self.assertEqual(tui.parse_input(b'\x1b[<0;12;5m'), [])

    def test_utf8_char_and_backspace_and_ctrl_c(self):
        self.assertEqual(tui.parse_input('é'.encode()), [E('char', 'é')])
        self.assertEqual(tui.parse_input(b'\x7f'), [key('backspace')])
        self.assertEqual(tui.parse_input(b'\x03'), [key('ctrl-c')])
        self.assertEqual(tui.parse_input(b' '), [key('space')])
        self.assertEqual(tui.parse_input(b'\x1b[1~\x1b[4~\x1b[99~'), [key('home'), key('end')])


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.model = make_model()
        self.layout = tui.compute_layout(120, 40, 10, 20)
        self.rng = random.Random(3)

    def send(self, *events):
        return [tui.dispatch(self.model, event, self.layout, self.rng) for event in events]

    def test_letters_are_text_while_searching(self):
        results = self.send(E('char', '/'), *[E('char', c) for c in 'frqhl'])
        self.assertEqual(self.model.search, 'frqhl')
        self.assertEqual(self.model.favorites, set())
        self.assertNotIn('quit', results)

    def test_film_keys(self):
        self.assertEqual(self.send(E('char', 'l'), key('right'), E('wheel', 1)), [None, None, None])
        self.assertEqual(self.model.index, 3)
        self.send(E('char', 'h'), key('home'))
        self.assertEqual(self.model.index, 0)
        self.assertEqual(self.send(E('char', 'f')), ['save'])
        self.assertEqual(self.model.favorites, {'a'})
        self.send(E('char', 'r'))
        self.assertNotEqual(self.model.selected().id, 'a')
        self.assertEqual(self.send(key('enter')), ['apply'])
        self.assertEqual(self.send(E('char', 'q')), ['quit'])
        self.assertEqual(self.send(key('ctrl-c')), ['quit'])

    def test_other_printable_char_starts_search(self):
        self.send(E('char', 'g'))
        self.assertEqual((self.model.focus, self.model.search), ('search', 'g'))

    def test_esc_order(self):
        self.send(E('char', '/'), E('char', 'x'))
        self.assertEqual(self.send(key('esc')), [None])
        self.assertEqual((self.model.search, self.model.focus), ('', 'film'))
        self.send(key('tab'))
        self.assertEqual(self.model.focus, 'chips')
        self.assertEqual(self.send(key('esc')), [None])
        self.assertEqual(self.model.focus, 'film')
        self.assertEqual(self.send(key('esc')), ['quit'])

    def test_chip_and_series_navigation(self):
        self.send(key('tab'), key('right'), key('right'), key('right'), key('enter'))
        self.assertEqual(self.model.focus, 'series')
        self.send(key('down'), key('enter'))
        self.assertEqual((self.model.series, self.model.focus), ('Naruto', 'chips'))
        self.send(key('right'), key('enter'))
        self.assertEqual(self.model.color, 'Crimson')
        self.send(key('left'), key('enter'))
        self.assertEqual(self.model.series_index, 1)  # opens on the current series
        self.send(key('up'), key('enter'))
        self.assertIsNone(self.model.series)

    def test_outdated_prompt_keys(self):
        self.model.prompt = 'outdated'
        self.assertEqual(self.send(E('char', 'f')), [None])
        self.assertEqual(self.model.favorites, set())
        self.assertEqual(self.send(E('char', 'u')), ['update'])
        self.assertEqual(self.send(E('char', 'a')), ['apply-copy'])
        self.send(key('esc'))
        self.assertIsNone(self.model.prompt)

    def test_click_select_then_apply(self):
        card = self.layout.film[2]
        click = E('click', None, card.x + 1, card.y + 1)
        self.assertEqual(self.send(click), [None])
        self.assertEqual(self.model.index, tui.film_start(self.model, self.layout) + 2)
        self.assertEqual(self.send(click), ['apply'])

    def test_click_chip(self):
        spans = tui.chip_spans(self.model, self.layout)
        start, end, chip = next(span for span in spans if span[2].value == 'Jade')
        self.send(E('click', None, start, self.layout.chips.y))
        self.assertEqual(self.model.color, 'Jade')


if __name__ == '__main__':
    unittest.main()

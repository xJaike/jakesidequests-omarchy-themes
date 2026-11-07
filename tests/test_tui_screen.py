import os
import pty
import termios
import time
import unittest

from test_tui_model import make_model, tui


class ScreenTests(unittest.TestCase):
    def test_screen_restores_terminal_on_exception(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        before = termios.tcgetattr(slave)
        with self.assertRaises(ValueError):
            with tui.Screen(slave, slave):
                self.assertNotEqual(termios.tcgetattr(slave), before)
                raise ValueError('boom')
        self.assertEqual(termios.tcgetattr(slave), before)
        written = os.read(master, 4096)
        self.assertIn(b'\x1b[?1049h', written)
        self.assertIn(b'\x1b[?1049l', written)
        self.assertIn(b'\x1b[?25h', written)

    def detect(self, reply):
        reply_r, reply_w = os.pipe()
        query_r, query_w = os.pipe()
        for fd in (reply_r, reply_w, query_r, query_w):
            self.addCleanup(os.close, fd)
        if reply:
            os.write(reply_w, reply)
        result = tui.detect_sixel(reply_r, query_w)
        self.assertEqual(os.read(query_r, 16), b'\x1b[c')
        return result

    def test_detect_sixel(self):
        self.assertTrue(self.detect(b'\x1b[?62;4;22c'))
        self.assertFalse(self.detect(b'\x1b[?62;22c'))
        started = time.monotonic()
        self.assertFalse(self.detect(b''))
        self.assertLess(time.monotonic() - started, 0.3)


class FakeBackend:
    class NeedsDecision(Exception):
        pass

    def __init__(self, state='missing', fail=None):
        self.state, self.fail, self.calls = state, fail, []

    def status(self, slug):
        return self.state

    def install(self, slug, replace=False):
        self.calls.append(('install', slug, replace))
        if self.state == 'outdated' and not replace:
            raise self.NeedsDecision(slug)

    def apply(self, slug):
        self.calls.append(('apply', slug))
        if self.fail:
            raise self.fail


class FakeState:
    def __init__(self):
        self.recent, self.saved = [], 0

    def push_recent(self, slug):
        self.recent.insert(0, slug)

    def save(self):
        self.saved += 1


class PerformTests(unittest.TestCase):
    def run_flow(self, command, backend, model=None):
        model = model or make_model()
        state, frames = FakeState(), []
        done = tui.perform(model, command, backend, state, redraw=lambda: frames.append(model.message))
        return model, state, done, frames

    def test_missing_installs_then_applies(self):
        backend = FakeBackend('missing')
        model, state, done, frames = self.run_flow('apply', backend)
        self.assertTrue(done)
        self.assertEqual(backend.calls, [('install', 'a', False), ('apply', 'a')])
        self.assertEqual((state.recent, state.saved), (['a'], 1))
        self.assertEqual(frames, ['Applying …'])

    def test_current_says_already_applied(self):
        backend = FakeBackend('current')
        model, _, done, _ = self.run_flow('apply', backend)
        self.assertEqual((model.message, done, backend.calls), ('Already applied', False, []))

    def test_outdated_prompts_then_update_or_keep(self):
        model, _, done, _ = self.run_flow('apply', FakeBackend('outdated'))
        self.assertEqual((model.prompt, done), ('outdated', False))
        backend = FakeBackend('outdated')
        model, _, done, _ = self.run_flow('update', backend, model)
        self.assertTrue(done)
        self.assertEqual(backend.calls, [('install', 'a', True), ('apply', 'a')])
        self.assertIsNone(model.prompt)
        backend = FakeBackend('outdated')
        _, _, done, _ = self.run_flow('apply-copy', backend)
        self.assertEqual((done, backend.calls), (True, [('apply', 'a')]))

    def test_failure_shows_error_and_stays_open(self):
        model, state, done, _ = self.run_flow('apply', FakeBackend('installed', RuntimeError('boom')))
        self.assertEqual((model.message, model.error, done, state.recent), ('boom', True, False, []))

    def test_multiline_error_shows_first_line(self):
        model, _, _, _ = self.run_flow('apply', FakeBackend('installed', RuntimeError('first line\nsecond line')))
        self.assertEqual(model.message, 'first line')

    def test_save_command_persists_favorites(self):
        _, state, done, _ = self.run_flow('save', FakeBackend())
        self.assertEqual((state.saved, done), (1, False))


if __name__ == '__main__':
    unittest.main()

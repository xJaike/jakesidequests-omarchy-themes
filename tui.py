"""Full-screen terminal stage + filmstrip browser for the theme collection."""
from dataclasses import dataclass, field
import fcntl
import os
import random
import re
import select
import selectors
import signal
import struct
import termios
import time
import tty

# Same values and order as tools/derive_palettes.COLOR_FAMILIES.
COLOR_FAMILIES = ('Crimson', 'Ember', 'Gold', 'Jade', 'Ocean', 'Violet', 'Rose', 'Silver')


# ---------- model ----------

@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    series: str
    color: str
    palette: dict = field(compare=False, hash=False)


@dataclass
class Chip:
    label: str
    kind: str
    value: str | None
    active: bool


@dataclass
class Model:
    themes: list
    favorites: set
    recent: list
    current: str | None
    view: str = 'all'
    series: str | None = None
    color: str | None = None
    search: str = ''
    index: int = 0
    focus: str = 'film'
    chip_index: int = 0
    series_index: int = 0
    prompt: str | None = None
    message: str | None = None
    error: bool = False
    installed: set = field(default_factory=set)
    alpha: float = 1.0

    def filtered(self):
        if self.view == 'recent':
            by_id = {theme.id: theme for theme in self.themes}
            pool = [by_id[slug] for slug in self.recent if slug in by_id]
        elif self.view == 'favorites':
            pool = [theme for theme in self.themes if theme.id in self.favorites]
        else:
            pool = list(self.themes)
        words = self.search.lower().split()
        return [theme for theme in pool
                if (self.series is None or theme.series == self.series)
                and (self.color is None or theme.color == self.color)
                and all(word in f'{theme.name} {theme.series} {theme.color}'.lower() for word in words)]

    def selected(self):
        themes = self.filtered()
        return themes[self.index] if 0 <= self.index < len(themes) else None

    def move(self, delta):
        self.index = max(0, min(len(self.filtered()) - 1, self.index + delta))

    def home(self):
        self.index = 0

    def end(self):
        self.index = max(0, len(self.filtered()) - 1)

    def select_id(self, slug):
        for position, theme in enumerate(self.filtered()):
            if theme.id == slug:
                self.index = position
                return True
        return False

    def _reselect(self, previous_id):
        if previous_id is None or not self.select_id(previous_id):
            self.index = max(0, min(self.index, len(self.filtered()) - 1))

    def _refilter(self, change):
        previous = self.selected()
        change()
        self._reselect(previous.id if previous else None)

    def set_view(self, view):
        self._refilter(lambda: setattr(self, 'view', view))

    def set_series(self, series):
        self._refilter(lambda: setattr(self, 'series', series))

    def toggle_color(self, color):
        self._refilter(lambda: setattr(self, 'color', None if self.color == color else color))

    def type_char(self, ch):
        self._refilter(lambda: setattr(self, 'search', self.search + ch))

    def backspace(self):
        self._refilter(lambda: setattr(self, 'search', self.search[:-1]))

    def surprise(self, rng):
        themes = self.filtered()
        current = self.selected()
        choices = [theme for theme in themes if len(themes) < 2 or theme != current]
        if choices:
            self.select_id(rng.choice(choices).id)

    def chips(self):
        chips = [
            Chip(f'All {len(self.themes)}', 'view', 'all', self.view == 'all'),
            Chip('★ Favorites', 'view', 'favorites', self.view == 'favorites'),
            Chip('Recent', 'view', 'recent', self.view == 'recent'),
            Chip(f'Series: {self.series or "any"} ▾', 'series', self.series, self.series is not None),
        ]
        present = {theme.color for theme in self.themes}
        chips += [Chip(color, 'color', color, self.color == color) for color in COLOR_FAMILIES if color in present]
        return chips

    def series_options(self):
        counts = {}
        for theme in self.themes:
            counts[theme.series] = counts.get(theme.series, 0) + 1
        return sorted(counts.items())


# ---------- layout ----------

@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Layout:
    mode: str
    header: Rect
    chips: Rect
    stage: Rect | None
    sample: Rect | None
    info: Rect | None
    film: list
    stage_px: tuple
    thumb_px: tuple
    sample_px: tuple = (0, 0)


def compute_layout(cols, rows, cell_w, cell_h):
    """Place header, chips, stage, terminal sample, info line and filmstrip cards (0-based cells)."""
    header, chips = Rect(0, 0, cols, 1), Rect(0, 1, cols, 1)
    if cols < 60 or rows < 20:
        return Layout('tiny', header, chips, None, None, None, [], (0, 0), (0, 0))
    thumb_rows = max(3, rows * 18 // 100)
    film_h = thumb_rows + 2
    stage_y = 3
    stage_h = rows - stage_y - 2 - film_h  # info line + bottom rule
    wide = cols >= 100
    stage = Rect(0, stage_y, cols * 62 // 100 if wide else cols, stage_h)
    sample = Rect(stage.w + 2, stage_y, cols - stage.w - 2, stage_h) if wide else None
    info = Rect(0, stage_y + stage_h, cols, 1)
    card_w = max(18, cols // 7)
    count = max(3, (cols + 1) // (card_w + 1))
    film_y = info.y + 2
    film = [Rect(k * (card_w + 1), film_y, card_w, film_h) for k in range(count)]
    return Layout('wide' if wide else 'narrow', header, chips, stage, sample, info, film,
                  (stage.w * cell_w, stage.h * cell_h), (card_w * cell_w, thumb_rows * cell_h),
                  (sample.w * cell_w, sample.h * cell_h) if sample else (0, 0))


# ---------- input ----------

@dataclass(frozen=True)
class Event:
    kind: str
    value: object = None
    x: int = 0
    y: int = 0


CSI_KEYS = {'A': 'up', 'B': 'down', 'C': 'right', 'D': 'left', 'H': 'home', 'F': 'end'}
TILDE_KEYS = {'1': 'home', '7': 'home', '4': 'end', '8': 'end'}
CONTROL_KEYS = {'\r': 'enter', '\n': 'enter', '\t': 'tab', '\x7f': 'backspace', '\x08': 'backspace',
                '\x03': 'ctrl-c', ' ': 'space'}


def parse_input(data):
    """Split one read from the terminal into key, character and mouse events."""
    text = data.decode('utf-8', errors='ignore')
    events, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == '\x1b':
            if i + 1 < len(text) and text[i + 1] in '[O':
                j = i + 2
                while j < len(text) and not '\x40' <= text[j] <= '\x7e':  # CSI final byte
                    j += 1
                if j >= len(text):
                    break  # truncated sequence: drop it
                body, final = text[i + 2:j], text[j]
                i = j + 1
                if body.startswith('<'):
                    events.extend(_mouse(body[1:], final))
                elif final in CSI_KEYS:
                    events.append(Event('key', CSI_KEYS[final]))
                elif final == '~' and body in TILDE_KEYS:
                    events.append(Event('key', TILDE_KEYS[body]))
                continue
            events.append(Event('key', 'esc'))
        elif ch in CONTROL_KEYS:
            events.append(Event('key', CONTROL_KEYS[ch]))
        elif ch.isprintable():
            events.append(Event('char', ch))
        i += 1
    return events


def _mouse(params, final):
    try:
        button, x, y = (int(part) for part in params.split(';'))
    except ValueError:
        return []
    if final != 'M':
        return []
    if button == 0:
        return [Event('click', None, x - 1, y - 1)]
    if button in (64, 65):
        return [Event('wheel', -1 if button == 64 else 1)]
    return []


def film_start(model, layout):
    """Index of the first theme shown in the filmstrip, keeping the selection centered."""
    total, count = len(model.filtered()), len(layout.film)
    return max(0, min(model.index - count // 2, max(0, total - count)))


def chip_label(chip):
    if chip.kind == 'color':
        return f' ● {chip.label} ' if chip.label else ' ● '
    return f' {chip.label} '


def chip_spans(model, layout):
    """Column range [start, end) of every chip that fits on the chips row, with labels shortened to fit.

    Color chips shrink from full names to three letters to dots only; chips that still do not fit are left out.
    """
    limit = layout.header.w - 1
    chips = model.chips()
    for chip in chips:
        if chip.kind == 'series':
            chip.label = f'Series: {_fit(model.series or "any", 16)} ▾'
    for shorten in (lambda name: name, lambda name: name[:3], lambda name: ''):
        tier = [Chip(shorten(c.label), c.kind, c.value, c.active) if c.kind == 'color' else c for c in chips]
        spans, x = [], 1
        for chip in tier:
            width = len(chip_label(chip))
            spans.append((x, x + width, chip))
            x += width + 1
        if spans[-1][1] <= limit:
            return spans
    return [span for span in spans if span[1] <= limit]


def _activate_chip(model, chip):
    if chip.kind == 'view':
        model.set_view(chip.value)
    elif chip.kind == 'series':
        names = [name for name, _ in model.series_options()]
        model.series_index = names.index(model.series) + 1 if model.series in names else 0
        model.focus = 'series'
    else:
        model.toggle_color(chip.value)


def dispatch(model, event, layout, rng):
    """Apply one event to the model. Returns 'apply', 'update', 'apply-copy', 'save', 'quit' or None."""
    name = event.value if event.kind == 'key' else None
    char = event.value if event.kind == 'char' else None
    if name == 'ctrl-c':
        return 'quit'
    if model.prompt != 'outdated':
        model.message, model.error = None, False
    if model.prompt == 'outdated':
        if char == 'u':
            return 'update'
        if char == 'a':
            return 'apply-copy'
        if name == 'esc':
            model.prompt = None
        return None
    if event.kind == 'wheel':
        model.move(event.value)
        return None
    if event.kind == 'click':
        return _click(model, event, layout)
    if model.focus == 'series':
        options = [None] + [series for series, _ in model.series_options()]
        if name in ('up', 'down'):
            model.series_index = max(0, min(len(options) - 1, model.series_index + (1 if name == 'down' else -1)))
        elif name in ('enter', 'space'):
            model.set_series(options[model.series_index])
            model.focus = 'chips'
        elif name == 'esc':
            model.focus = 'chips'
        return None
    if model.focus == 'search':
        if char is not None or name == 'space':
            model.type_char(char or ' ')
        elif name == 'backspace':
            model.backspace()
        elif name == 'esc':
            model._refilter(lambda: setattr(model, 'search', ''))
            model.focus = 'film'
        elif name in ('left', 'right'):
            model.move(1 if name == 'right' else -1)
        elif name == 'tab':
            model.focus = 'chips'
        elif name == 'enter':
            return 'apply' if model.selected() else None
        return None
    if model.focus == 'chips':
        chips = [chip for _, _, chip in chip_spans(model, layout)]
        if name in ('left', 'right'):
            model.chip_index = max(0, min(len(chips) - 1, model.chip_index + (1 if name == 'right' else -1)))
        elif name in ('enter', 'space'):
            _activate_chip(model, chips[model.chip_index])
        elif name in ('tab', 'esc'):
            model.focus = 'film'
        elif char == 'q':
            return 'quit'
        return None
    # filmstrip focus
    if name in ('left', 'right') or char in ('h', 'l'):
        model.move(1 if name == 'right' or char == 'l' else -1)
    elif name == 'home':
        model.home()
    elif name == 'end':
        model.end()
    elif name == 'enter':
        return 'apply' if model.selected() else None
    elif name == 'tab':
        model.focus = 'chips'
    elif name == 'esc':
        if not model.search:
            return 'quit'
        model._refilter(lambda: setattr(model, 'search', ''))
    elif name == 'backspace':
        if model.search:
            model.backspace()
    elif char == 'q':
        return 'quit'
    elif char == 'f':
        theme = model.selected()
        if theme:
            model._refilter(lambda: model.favorites.symmetric_difference_update({theme.id}))
            return 'save'
    elif char == 'r':
        model.surprise(rng)
    elif char == '/':
        model.focus = 'search'
    elif char is not None:
        model.focus = 'search'
        model.type_char(char)
    return None


def _click(model, event, layout):
    if event.y == layout.chips.y:
        for start, end, chip in chip_spans(model, layout):
            if start <= event.x < end:
                _activate_chip(model, chip)
        return None
    start = film_start(model, layout)
    for k, card in enumerate(layout.film):
        if card.x <= event.x < card.x + card.w and card.y <= event.y < card.y + card.h:
            index = start + k
            if index >= len(model.filtered()):
                return None
            if index == model.index:
                return 'apply'
            model.index = index
    return None


# ---------- painting ----------

FAMILY_SWATCH = {'Crimson': '#ff7c8f', 'Ember': '#ffa070', 'Gold': '#e5bb5a', 'Jade': '#5fd6a8',
                 'Ocean': '#7cb7ff', 'Violet': '#b79cff', 'Rose': '#f59bc8', 'Silver': '#c0c4cc'}
KEY_HINTS = (('←→', 'browse'), ('Enter', 'apply'), ('f', 'favorite'), ('r', 'surprise'),
             ('/', 'search'), ('tab', 'filters'), ('esc', 'quit'))
OUTDATED_PROMPT = 'u update & apply (backup kept) · a apply my copy · Esc cancel'
RESET = '\x1b[0m'


def _rgb(value):
    return ';'.join(str(int(value[i:i + 2], 16)) for i in (1, 3, 5))


def fg(value):
    return f'\x1b[38;2;{_rgb(value)}m'


def bg(value):
    return f'\x1b[48;2;{_rgb(value)}m'


def goto(x, y):
    return f'\x1b[{y + 1};{x + 1}H'


def _fit(text, width):
    return text if len(text) <= width else text[:max(0, width - 1)] + '…'


def _fill(rect, color):
    return ''.join(goto(rect.x, rect.y + row) + bg(color) + ' ' * rect.w for row in range(rect.h))


def _center(rect, text, color):
    text = _fit(text, rect.w)
    return goto(rect.x + max(0, (rect.w - len(text)) // 2), rect.y + rect.h // 2) + fg(color) + text


SHOWROOM_ROWS = (('red', 'yellow', 'green', 'cyan'), ('blue', 'magenta', 'orange', 'brown'))
BRIGHT_ROWS = (('red', 'yellow', 'green', 'cyan'), ('blue', 'magenta'))
SWATCHES = ('red', 'orange', 'yellow', 'green', 'cyan', 'blue', 'magenta', 'brown', 'bright_red',
            'bright_yellow', 'bright_green', 'bright_cyan', 'bright_blue', 'bright_magenta')


def sample_segments(p):
    """Terminal sample + palette showroom as lines of (text, fg hex, bg hex or None)."""
    color = lambda key: p.get(key) or p['foreground']
    seg = lambda text, key, back=None: (text, color(key), color(back) if back else None)
    lines = [
        [seg('❯ ', 'green'), seg('~/projects ', 'blue'), seg('git:(main) ', 'magenta'), seg('ls', 'foreground')],
        [seg('src  ', 'blue'), seg('tests  ', 'blue'), seg('build.sh  ', 'green'), seg('README.md', 'foreground')],
        [seg('❯ ', 'green'), seg('git status -s', 'foreground')],
        [seg(' M ', 'yellow'), seg('theme_picker.py', 'foreground')],
        [seg(' D ', 'red'), seg('old_menu.py', 'foreground')],
        [seg('?? ', 'cyan'), seg('filmstrip.py', 'foreground')],
        [seg('✓ 14 passed ', 'green'), seg('⚠ 1 skipped ', 'yellow'), seg('✗ 0', 'red')],
        [],
        [seg('palette · normal / bright', 'muted')],
    ]
    lines += [[seg(f'{name:<9}', name) for name in row] for row in SHOWROOM_ROWS]
    lines += [[seg(f'{name:<9}', 'bright_' + name) for name in row] for row in BRIGHT_ROWS]
    lines += [[seg('██', key) for key in SWATCHES]]
    lines += [[seg('fg ', 'foreground'), seg('light ', 'light_foreground'), seg('dark ', 'dark_foreground'),
               seg('bright ', 'bright_foreground'), seg('muted', 'muted')],
              [seg('accent ', 'accent'), seg('second ', 'second'), seg(' selection ', 'foreground', 'selection')],
              [seg('❯ ', 'green'), ('█', color('accent'), None)]]
    return lines


def _segments_ansi(line, width, base):
    out, used = [], 0
    for text, color, back in line:
        text = text[:max(0, width - used)]
        if not text:
            break
        out += [bg(back) if back else base, fg(color), text]
        used += len(text)
    return ''.join(out + [base])


def _status_text(model, theme):
    if theme.id == model.current:
        return 'current'
    return 'installed' if theme.id in model.installed else 'not installed'


def paint_frame(model, layout, images, sixel):
    """Every text cell of the screen, painted in the selected theme's palette, plus cached thumbnails."""
    theme = model.selected()
    p = (theme or model.themes[0]).palette
    base = bg(p['background'])
    out = ['\x1b[?2026h', RESET, base, '\x1b[2J']
    cols = layout.header.w
    if layout.mode == 'tiny':
        out.append(_center(Rect(0, 0, cols, max(1, layout.chips.y + 2)), 'Enlarge window to browse themes', p['foreground']))
        out += [RESET, '\x1b[?2026l']
        return _encode(out)
    # header: search + position
    cursor = '_' if model.focus == 'search' else ''
    out += [goto(1, 0), fg(p['muted']), 'search: ', fg(p['foreground']), model.search, cursor]
    total = len(model.filtered())
    position = f'Jake Sidequests · {model.index + 1 if theme else 0}/{total}'
    out += [goto(max(0, cols - len(position) - 1), 0), fg(p['muted']), position]
    # chips
    for k, (start, _, chip) in enumerate(chip_spans(model, layout)):
        focused = model.focus in ('chips', 'series') and k == model.chip_index
        if chip.active:
            style = bg(p['accent']) + fg(p['background'])
        elif focused:
            style = bg(p['selection']) + fg(p['foreground'])
        else:
            style = base + fg(p['foreground'] if chip.kind == 'color' else p['muted'])
        label = chip_label(chip)
        if chip.kind == 'color':
            dot = fg(FAMILY_SWATCH.get(chip.value, p['accent'])) if not chip.active else ''
            label = f' {dot}●{style} {chip.label} ' if chip.label else f' {dot}●{style} '
        out += [goto(start, layout.chips.y), style, label, base]
    out += [goto(0, 2), fg(p['accent']), '─' * cols]
    # stage
    stage = layout.stage
    if theme is None:
        out.append(_center(stage, 'No themes match', p['muted']))
    else:
        out.append(_fill(stage, p['lighter_background']))
        if not sixel:
            out.append(bg(p['lighter_background']) + _center(stage, 'Images need a Sixel terminal such as foot', p['muted']))
        if model.focus == 'series':
            out.append(_series_box(model, stage, p))
        out.append(base)
        if layout.sample:
            sample = layout.sample
            for row, line in enumerate(sample_segments(p)[:max(0, sample.h - 2)]):
                out += [goto(sample.x + 2, sample.y + 1 + row), base, _segments_ansi(line, sample.w - 3, base)]
    # info line
    info = layout.info
    left, hints = info_line(model, theme, cols)
    out.append(goto(1, info.y) + base)
    if model.prompt == 'outdated':
        out += [fg(p['foreground']), left]
    elif model.message:
        out += [fg(p['red'] if model.error else p['foreground']), left]
    elif theme:
        name = left[:len(theme.name)]
        out += [fg(p['accent']), '\x1b[1m', name, '\x1b[22m', fg(p['muted']), left[len(name):]]
    if hints:
        out += [goto(cols - len(hints) - 1, info.y)]
        out += ['  '.join(f'{fg(p["foreground"])}{k} {fg(p["muted"])}{v}' for k, v in hints_pairs(hints))]
    out += [goto(0, info.y + 1), fg(p['lighter_background']), '─' * cols]
    # filmstrip
    themes = model.filtered()
    start = film_start(model, layout)
    thumb_rows = layout.film[0].h - 2 if layout.film else 0
    for k, card in enumerate(layout.film):
        index = start + k
        if index >= len(themes):
            break
        item = themes[index]
        data = images.get('thumb', item.id, *layout.thumb_px) if sixel else None
        if data is None:
            out.append(_fill(Rect(card.x, card.y, card.w, thumb_rows), item.palette['lighter_background']))
            out.append(goto(card.x, card.y) + base)
        badges = ('★' if item.id in model.favorites else '') + ('●' if item.id == model.current else '')
        name = _fit((badges + ' ' if badges else '') + item.name, card.w)
        color = p['accent'] if index == model.index else p['muted']
        out += [goto(card.x, card.y + thumb_rows), base, fg(color), name]
        strip_keys = ('accent', 'second', 'red', 'green', 'blue', 'magenta')
        width = max(1, card.w // len(strip_keys))
        out.append(goto(card.x, card.y + thumb_rows + 1))
        out += [fg(item.palette[key]) + '▀' * width for key in strip_keys]
        if data is not None:
            out += [goto(card.x, card.y), RESET, data, base]
    out += [RESET, '\x1b[?2026l']
    return _encode(out)


def _encode(parts):
    """Join text (UTF-8) and Sixel payloads (already bytes)."""
    return b''.join(part if isinstance(part, bytes) else part.encode('utf-8') for part in parts)


COMPACT_HINTS = (('←→', ''), ('Enter', ''), ('f', ''), ('r', ''), ('/', ''), ('tab', ''), ('esc', ''))


def _hint_text(pairs):
    return '  '.join(f'{k} {v}'.rstrip() for k, v in pairs)


def hints_pairs(text):
    return KEY_HINTS if text == _hint_text(KEY_HINTS) else COMPACT_HINTS


def info_line(model, theme, cols):
    """Left text (prompt, message or name · series · status) fitted to the width, and the key hints that still fit."""
    if model.prompt == 'outdated':
        left = OUTDATED_PROMPT
    elif model.message:
        left = model.message
    elif theme:
        left = f'{theme.name} · {theme.series} · {_status_text(model, theme)}'
    else:
        left = ''
    left = _fit(left, cols - 2)
    for pairs in (KEY_HINTS, COMPACT_HINTS):
        hints = _hint_text(pairs)
        if len(left) + len(hints) + 2 <= cols - 2:
            return left, hints
    return left, None


def _series_box(model, stage, p):
    options = ['any'] + [f'{name} ({count})' for name, count in model.series_options()]
    width = min(stage.w - 4, max(len(option) for option in options) + 4)
    height = min(stage.h - 2, len(options))
    top = max(0, min(model.series_index - height // 2, len(options) - height))
    x, y = stage.x + 2, stage.y + 1
    out = []
    for row in range(height):
        option = options[top + row]
        style = bg(p['selection']) if top + row == model.series_index else bg(p['background'])
        out += [goto(x, y + row), style, fg(p['foreground']), f' {_fit(option, width - 2):<{width - 2}} ']
    return ''.join(out)


def paint_stage(model, layout, images):
    """The stage Sixel at the stage's top-left, or None when it is not cached yet."""
    theme = model.selected()
    if layout.stage is None or theme is None or model.focus == 'series':
        return None
    data = images.get('stage', theme.id, *layout.stage_px)
    if data is None:
        return None
    return goto(layout.stage.x, layout.stage.y).encode() + data


def paint_sample(model, layout, images):
    """The translucent-terminal sample image over the text sample, or None (opaque terminal or not cached)."""
    theme = model.selected()
    if model.alpha >= 1 or layout.sample is None or theme is None:
        return None
    data = images.get('sample', theme.id, *layout.sample_px)
    if data is None:
        return None
    return goto(layout.sample.x, layout.sample.y).encode() + data


def wanted_images(model, layout):
    """Images the screen needs at the current layout's sizes: stages first, then visible thumbnails."""
    themes = model.filtered()
    if layout.stage is None or not themes:
        return []
    jobs = [('stage', themes[i].id, *layout.stage_px)
            for i in (model.index, model.index + 1, model.index - 1) if 0 <= i < len(themes)]
    if model.alpha < 1 and layout.sample:
        jobs.insert(1, ('sample', themes[model.index].id, *layout.sample_px))
    start = film_start(model, layout)
    jobs += [('thumb', theme.id, *layout.thumb_px) for theme in themes[start:start + len(layout.film)]]
    return jobs


def paint_thumbs(model, layout, images, drawn):
    """Thumbnails cached now and not yet in `drawn`, painted over their placeholders; `drawn` is updated."""
    themes, start, out = model.filtered(), film_start(model, layout), []
    for k, card in enumerate(layout.film):
        if start + k < len(themes) and themes[start + k].id not in drawn:
            data = images.get('thumb', themes[start + k].id, *layout.thumb_px)
            if data is not None:
                drawn.add(themes[start + k].id)
                out += [goto(card.x, card.y), RESET, data]
    return _encode(out)


class NoImages:
    """Image source used for the instant repaint on every key: placeholders only."""

    @staticmethod
    def get(kind, slug, w, h):
        return None


# ---------- terminal ----------

ENTER_SCREEN = b'\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h'
LEAVE_SCREEN = b'\x1b[?1006l\x1b[?1000l\x1b[0m\x1b[?25h\x1b[?1049l'


def _raise_exit(signum, frame):
    raise SystemExit(128 + signum)


class Screen:
    """Alternate screen, raw input and mouse reporting; always restored on exit."""

    def __init__(self, fd_in, fd_out):
        self.fd_in, self.fd_out = fd_in, fd_out

    def __enter__(self):
        self.saved = termios.tcgetattr(self.fd_in)
        self.handlers = {sig: signal.signal(sig, _raise_exit) for sig in (signal.SIGTERM, signal.SIGHUP)}
        tty.setraw(self.fd_in)
        os.write(self.fd_out, ENTER_SCREEN)
        return self

    def __exit__(self, *exc):
        try:
            os.write(self.fd_out, LEAVE_SCREEN)
        finally:
            termios.tcsetattr(self.fd_in, termios.TCSADRAIN, self.saved)
            for sig, handler in self.handlers.items():
                signal.signal(sig, handler)
        return False


def detect_sixel(fd_in, fd_out, timeout=0.2):
    """Ask the terminal for its Primary Device Attributes; attribute 4 means Sixel."""
    os.write(fd_out, b'\x1b[c')
    reply, deadline = b'', time.monotonic() + timeout
    while not reply.endswith(b'c'):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd_in], [], [], remaining)[0]:
            break
        chunk = os.read(fd_in, 64)
        if not chunk:
            break
        reply += chunk
    found = re.search(rb'\x1b\[\?([\d;]*)c', reply)
    return bool(found) and b'4' in found.group(1).split(b';')


def cell_size(fd):
    try:
        rows, cols, width, height = struct.unpack('HHHH', fcntl.ioctl(fd, termios.TIOCGWINSZ, bytes(8)))
        if rows and cols and width and height:
            return max(1, width // cols), max(1, height // rows)
    except OSError:
        pass
    return 10, 20


# ---------- apply flow and event loop ----------

def perform(model, command, backend, state, redraw=lambda: None):
    """Carry out a dispatch command. Returns True when the picker should close."""
    theme = model.selected()
    if command == 'save':
        try:
            state.save()
        except OSError as error:
            model.message, model.error = f'Could not save favorites: {error}', True
        return False
    if theme is None:
        return False
    try:
        if command == 'apply':
            current = backend.status(theme.id)
            if current == 'current':
                model.message, model.error = 'Already applied', False
                return False
            if current == 'outdated':
                model.prompt = 'outdated'
                return False
        model.prompt, model.message, model.error = None, 'Applying …', False
        redraw()
        if command == 'update':
            backend.install(theme.id, replace=True)
        elif command == 'apply' and current == 'missing':
            backend.install(theme.id)
        backend.apply(theme.id)
    except backend.NeedsDecision:
        model.prompt, model.message = 'outdated', None
        return False
    except Exception as error:  # surfaced in the info line; the picker stays open
        lines = str(error).strip().splitlines()
        model.prompt, model.message, model.error = None, lines[0] if lines else type(error).__name__, True
        return False
    state.push_recent(theme.id)
    state.save()
    model.message = None
    return True


STAGE_DELAY = 0.1


def run(model, previews, backend, state, fd_in=0, fd_out=1):
    """Run the picker until the user quits or a theme is applied."""
    wake_r, wake_w = os.pipe()
    os.set_blocking(wake_r, False)
    resized = {'flag': True}
    previews.on_ready = lambda: os.write(wake_w, b'.')
    rng = random.Random()
    previous = signal.getsignal(signal.SIGWINCH)

    def on_resize(signum, frame):
        resized['flag'] = True
        os.write(wake_w, b'!')

    signal.signal(signal.SIGWINCH, on_resize)
    previews.start()
    try:
        with Screen(fd_in, fd_out):
            sixel = detect_sixel(fd_in, fd_out)
            selector = selectors.DefaultSelector()
            selector.register(fd_in, selectors.EVENT_READ, 'input')
            selector.register(wake_r, selectors.EVENT_READ, 'wake')
            layout, stage_due, stage_drawn, sample_drawn, thumbs_drawn = None, 0.0, False, False, set()

            def repaint():
                nonlocal stage_due, stage_drawn, sample_drawn
                os.write(fd_out, paint_frame(model, layout, NoImages, sixel))
                if sixel:
                    previews.request(wanted_images(model, layout))
                stage_due, stage_drawn, sample_drawn = time.monotonic() + STAGE_DELAY, False, False
                thumbs_drawn.clear()

            while True:
                if resized['flag']:
                    resized['flag'] = False
                    cols, rows = os.get_terminal_size(fd_out)
                    cell = cell_size(fd_out)
                    layout = compute_layout(cols, rows, *cell)
                    if hasattr(previews, 'sample_settings'):
                        previews.sample_settings(cell=cell)
                    repaint()
                # Before the idle delay: wake when it ends. After it: wait for input or a rendered image.
                now = time.monotonic()
                timeout = stage_due - now if sixel and now < stage_due else None
                ready = selector.select(timeout)
                for key, _ in ready:
                    if key.data == 'wake':
                        try:
                            os.read(wake_r, 4096)
                        except BlockingIOError:
                            pass
                        continue
                    for event in parse_input(os.read(fd_in, 4096)):
                        command = dispatch(model, event, layout, rng)
                        if command == 'quit':
                            return
                        if command and perform(model, command, backend, state,
                                               redraw=lambda: os.write(fd_out, paint_frame(model, layout, NoImages, sixel))):
                            return
                    repaint()
                if resized['flag']:
                    continue
                if sixel and layout.mode != 'tiny' and time.monotonic() >= stage_due:
                    os.write(fd_out, paint_thumbs(model, layout, previews, thumbs_drawn))
                    if not stage_drawn:
                        stage = paint_stage(model, layout, previews)
                        if stage is not None:
                            os.write(fd_out, stage)
                            stage_drawn = True
                    if not sample_drawn:
                        sample = paint_sample(model, layout, previews)
                        if sample is not None:
                            os.write(fd_out, sample)
                            sample_drawn = True
    finally:
        previews.stop()
        signal.signal(signal.SIGWINCH, previous)
        os.close(wake_r)
        os.close(wake_w)

"""Full-screen terminal stage + filmstrip browser for the theme collection."""
from dataclasses import dataclass, field

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
                  (stage.w * cell_w, stage.h * cell_h), (card_w * cell_w, thumb_rows * cell_h))


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
    return f' ● {chip.label} ' if chip.kind == 'color' else f' {chip.label} '


def chip_spans(model, layout):
    """Column range [start, end) of every chip on the chips row."""
    spans, x = [], 1
    for chip in model.chips():
        width = len(chip_label(chip))
        spans.append((x, x + width, chip))
        x += width + 1
    return spans


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
            if model.search:
                model.search = ''
                model._reselect(None)
            model.focus = 'film'
        elif name in ('left', 'right'):
            model.move(1 if name == 'right' else -1)
        elif name == 'tab':
            model.focus = 'chips'
        elif name == 'enter':
            return 'apply' if model.selected() else None
        return None
    if model.focus == 'chips':
        chips = model.chips()
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
        return 'quit'
    elif char == 'q':
        return 'quit'
    elif char == 'f':
        theme = model.selected()
        if theme:
            model.favorites.symmetric_difference_update({theme.id})
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

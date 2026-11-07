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

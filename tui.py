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

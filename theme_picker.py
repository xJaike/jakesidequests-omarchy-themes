#!/usr/bin/env python3
"""Browse, preview and apply the bundled theme collection from the terminal."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent
SLUG = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
DECLARATIVE_FILES = ('colors.toml', 'shell.toml', 'icons.theme', 'README.md', 'wallpaper-prompt.txt')
RASTER_SUFFIXES = ('.png', '.jpg', '.jpeg', '.webp')


class NeedsDecision(Exception):
    """The theme is already installed; the caller must choose to replace it or keep it."""


def catalog():
    items = json.loads((ROOT / 'catalog.json').read_text())
    for item in items:
        slug = item['id']
        if not SLUG.fullmatch(slug):
            raise ValueError('Invalid theme identifier')
        if not item.get('series') or not item.get('color'):
            raise ValueError(f'Missing series/color: {slug}')
        source = ROOT / slug
        if not source.is_dir() or source.is_symlink():
            raise ValueError(f'Missing theme: {slug}')
        for path in source.rglob('*'):
            if path.is_symlink():
                raise ValueError(f'Symlink in theme: {slug}')
        tomllib.loads((source / 'colors.toml').read_text())
    return items


def themes_dir():
    return Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'omarchy/themes'


def state_home():
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state')))


def palette(slug):
    """Theme colors plus 'second', the second color of the active border gradient."""
    colors = tomllib.loads((ROOT / slug / 'colors.toml').read_text())
    border = re.findall(r'rgba\(([0-9a-fA-F]{6})[0-9a-fA-F]{2}\)', colors.get('hyprland_active_border', ''))
    colors['second'] = f'#{border[1].lower()}' if len(border) > 1 else colors.get('accent', '#ffffff')
    return colors


def current_theme():
    """Slug of the active Omarchy theme, or None when it is unknown."""
    try:
        slug = (state_home() / 'omarchy/current/theme.name').read_text().strip()
        if slug:
            return slug
    except OSError:
        pass
    try:
        result = subprocess.run(['omarchy', 'theme', 'current'], capture_output=True, text=True)
    except OSError:
        return None
    name = (result.stdout or '').strip().lower()
    if result.returncode or not name:
        return None
    return next((item['id'] for item in catalog() if item['name'].lower() == name), None)


def status(slug):
    """'current', 'missing', 'outdated' or 'installed' for a bundled theme."""
    if current_theme() == slug:
        return 'current'
    target = themes_dir() / slug
    if not target.is_dir():
        return 'missing'
    for name in ('colors.toml', 'shell.toml'):
        bundled, installed = ROOT / slug / name, target / name
        if bundled.is_file() and (not installed.is_file() or installed.read_bytes() != bundled.read_bytes()):
            return 'outdated'
    return 'installed'


def install(slug, replace=False):
    """Copy a bundled theme's declarative files into the Omarchy themes directory."""
    if slug not in {item['id'] for item in catalog()}:
        raise ValueError('Unknown theme')
    base = themes_dir()
    base.mkdir(parents=True, exist_ok=True)
    target = base / slug
    if (target.exists() or target.is_symlink()) and not replace:
        raise NeedsDecision(slug)
    # Only copy declarative theme files and raster backgrounds, never executable configs.
    with tempfile.TemporaryDirectory(prefix='.jake-theme-stage-', dir=base) as stage:
        staged = Path(stage) / slug
        staged.mkdir()
        for name in DECLARATIVE_FILES:
            source = ROOT / slug / name
            if source.is_file():
                shutil.copy2(source, staged / name)
        backgrounds = staged / 'backgrounds'
        backgrounds.mkdir()
        for source in (ROOT / slug / 'backgrounds').iterdir():
            if source.is_file() and source.suffix.lower() in RASTER_SUFFIXES:
                shutil.copy2(source, backgrounds / source.name)
        backup = None
        if target.exists() or target.is_symlink():
            backup = Path(tempfile.mkdtemp(prefix='.jake-theme-backup-', dir=base)) / slug
            target.rename(backup)
        try:
            staged.rename(target)
        except OSError:
            if backup is not None:
                backup.rename(target)
            raise
    return target


def apply(slug):
    result = subprocess.run(['omarchy', 'theme', 'set', slug], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError((result.stderr or '').strip() or f'omarchy theme set failed ({result.returncode})')


def state_path():
    return state_home() / 'jake-sidequests-themes/state.json'


class State:
    """Favorite and recently applied themes, kept between picker sessions."""
    RECENT_LIMIT = 10

    def __init__(self, path, favorites=(), recent=()):
        self.path = Path(path)
        self.favorites = set(favorites)
        self.recent = list(recent)

    @classmethod
    def load(cls, path, known):
        try:
            data = json.loads(Path(path).read_text())
            favorites = [slug for slug in data.get('favorites', []) if slug in known]
            recent = [slug for slug in data.get('recent', []) if slug in known]
        except (OSError, ValueError, AttributeError, TypeError):
            favorites, recent = [], []
        return cls(path, favorites, recent[:cls.RECENT_LIMIT])

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + '.tmp')
        temp.write_text(json.dumps({'favorites': sorted(self.favorites), 'recent': self.recent}))
        os.replace(temp, self.path)

    def toggle_favorite(self, slug):
        if slug in self.favorites:
            self.favorites.discard(slug)
            return False
        self.favorites.add(slug)
        return True

    def push_recent(self, slug):
        self.recent = [slug] + [item for item in self.recent if item != slug]
        del self.recent[self.RECENT_LIMIT:]


def cache_dir():
    return Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))) / 'jake-sidequests-themes'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='List themes without modifying anything')
    args = parser.parse_args()
    items = catalog()
    if args.list:
        print('\n'.join(item['id'] for item in items))
        return
    if not shutil.which('omarchy'):
        raise SystemExit('Missing dependency: omarchy')
    sys.path.insert(0, str(ROOT))
    import previews
    import tui
    ids = {item['id'] for item in items}
    state = State.load(state_path(), ids)
    installed = {path.name for path in themes_dir().glob('*') if path.is_dir()} & ids
    current = current_theme()
    themes = [tui.Theme(item['id'], item['name'], item['series'], item['color'], palette(item['id'])) for item in items]
    model = tui.Model(themes=themes, favorites=state.favorites, recent=state.recent, current=current,
                      installed=installed)
    if current:
        model.select_id(current)
    tui.run(model, previews.Previews(ROOT, cache_dir(), palette), sys.modules[__name__], state)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:  # printed after the terminal has been restored
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        raise SystemExit(1)

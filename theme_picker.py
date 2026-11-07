#!/usr/bin/env python3
"""Browse, preview and apply the bundled theme collection from the terminal."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='List themes without modifying anything')
    args = parser.parse_args()
    items = catalog()
    if args.list:
        print('\n'.join(item['id'] for item in items))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(str(error))

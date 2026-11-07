#!/usr/bin/env python3
"""Offline picker for the bundled theme catalog. Local theme browsing with wallpaper previews."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys
import struct
import termios
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent


def catalog():
    items = json.loads((ROOT / 'catalog.json').read_text())
    for item in items:
        slug = item['id']
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
            raise ValueError('Invalid theme identifier')
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


def install(slug):
    if slug not in {item['id'] for item in catalog()}:
        raise ValueError('Unknown theme')
    base = themes_dir()
    base.mkdir(parents=True, exist_ok=True)
    target = base / slug
    replacing = target.exists() or target.is_symlink()
    if replacing:
        result = subprocess.run(['gum', 'confirm', f'Replace {slug}? A backup will be kept.', '--default=false'])
        if result.returncode:
            return False
    # Only copy declarative theme files and raster backgrounds, never executable configs.
    with tempfile.TemporaryDirectory(prefix='.jake-theme-stage-', dir=base) as stage:
        staged = Path(stage) / slug
        staged.mkdir()
        for name in ('colors.toml', 'shell.toml', 'icons.theme', 'README.md', 'wallpaper-prompt.txt'):
            source = ROOT / slug / name
            if source.is_file():
                shutil.copy2(source, staged / name)
        backgrounds = staged / 'backgrounds'
        backgrounds.mkdir()
        for source in (ROOT / slug / 'backgrounds').iterdir():
            if source.is_file() and source.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
                shutil.copy2(source, backgrounds / source.name)
        backup = None
        if target.exists() or target.is_symlink():
            backup_root = Path(tempfile.mkdtemp(prefix='.jake-theme-backup-', dir=base))
            backup = backup_root / slug
            target.rename(backup)
        try:
            staged.rename(target)
        except OSError:
            if backup is not None:
                backup.rename(target)
            raise
        if backup is not None:
            print(f'Previous theme backed up to {backup}')
    print(f'Installed {slug}')
    return True


def choose(options, header):
    result = subprocess.run(['gum', 'filter', '--header', header, '--placeholder', 'Type to search…'],
                            input='\n'.join(options), text=True, stdout=subprocess.PIPE)
    return result.stdout.strip() if result.returncode == 0 else None


def preview(slug):
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
        raise ValueError('Invalid theme identifier')
    source = ROOT / slug
    colors = tomllib.loads((source / 'colors.toml').read_text())
    width = max(1, min(120, int(os.environ.get('FZF_PREVIEW_COLUMNS', '60'))))
    height = max(2, min(80, int(os.environ.get('FZF_PREVIEW_LINES', '30')) - 7))
    wallpaper = next(iter(sorted((source / 'backgrounds').glob('*'))), None)
    print(slug.replace('-', ' ').title(), flush=True)
    for name in ('background', 'foreground', 'accent', 'red', 'green', 'blue'):
        value = colors.get(name, '#000000')
        if re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            rgb = ';'.join(str(int(value[i:i + 2], 16)) for i in (1, 3, 5))
            print(f'\033[48;2;{rgb}m  \033[0m {name}: {value}')
    if wallpaper:
        # Use terminal pixel dimensions, rather than one pixel per text cell.
        cell_width, cell_height = terminal_cell_size()
        result = subprocess.run([
            'magick', str(wallpaper), '-thumbnail',
            f'{width * cell_width}x{height * cell_height}',
            '-colors', '256', 'sixel:-',
        ], stdout=subprocess.PIPE, check=True)
        sys.stdout.flush()
        sys.stdout.buffer.write(result.stdout + b'\n')
        sys.stdout.buffer.flush()


def terminal_cell_size():
    try:
        with open('/dev/tty', 'rb') as terminal:
            rows, columns, pixels_x, pixels_y = struct.unpack(
                'HHHH', fcntl.ioctl(terminal, termios.TIOCGWINSZ, bytes(8)))
        if rows and columns and pixels_x and pixels_y:
            return max(1, pixels_x // columns), max(1, pixels_y // rows)
    except OSError:
        pass
    return 10, 20



def choose_theme(items):
    command = f'{shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))} --preview {{1}}'
    env = dict(os.environ, FZF_DEFAULT_OPTS='', FZF_DEFAULT_OPTS_FILE='')
    result = subprocess.run([
        'fzf', '--delimiter', '\t', '--with-nth', '2..', '--layout', 'reverse',
        '--header', f'Jake Sidequests · {len(items)} themes · Enter: actions · Esc: close',
        '--preview', command, '--preview-window', 'right,60%,<100(down,65%)',
    ], input='\n'.join(f"{item['id']}\t{item['name']}" for item in items),
        text=True, stdout=subprocess.PIPE, env=env)
    return result.stdout.strip().split('\t', 1)[0] if result.returncode == 0 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='List themes without modifying anything')
    parser.add_argument('--preview', metavar='THEME', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.preview:
        preview(args.preview)
        return
    items = catalog()
    if args.list:
        print('\n'.join(item['id'] for item in items))
        return
    for command in ('gum', 'omarchy', 'fzf', 'magick'):
        if not shutil.which(command):
            parser.exit(1, f'Missing dependency: {command}\n')
    labels = {item['id']: item['name'] for item in items}
    while True:
        slug = choose_theme(items)
        if slug not in labels:
            return
        while True:
            action = choose(['Preview wallpaper', 'Install and apply', 'Install only', 'Back'], labels[slug])
            if action in (None, 'Back'):
                break
            if action == 'Preview wallpaper':
                wallpaper = next(iter(sorted((ROOT / slug / 'backgrounds').glob('*'))), None)
                if wallpaper:
                    subprocess.run(['xdg-open', str(wallpaper)], check=False)
            elif install(slug) and action == 'Install and apply':
                subprocess.run(['omarchy', 'theme', 'set', slug], check=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))

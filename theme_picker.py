#!/usr/bin/env python3
"""Offline picker for the bundled theme catalog. No shell interpolation."""
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='List themes without modifying anything')
    args = parser.parse_args()
    items = catalog()
    if args.list:
        print('\n'.join(item['id'] for item in items))
        return
    for command in ('gum', 'omarchy'):
        if not shutil.which(command):
            parser.exit(1, f'Missing dependency: {command}\n')
    labels = {f"{item['name']}  [{item['id']}]": item['id'] for item in items}
    while True:
        selected = choose(labels, f'Jake Sidequests · {len(items)} themes · Esc to close')
        if selected not in labels:
            return
        slug = labels[selected]
        while True:
            action = choose(['Preview wallpaper', 'Install and apply', 'Install only', 'Back'], selected)
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

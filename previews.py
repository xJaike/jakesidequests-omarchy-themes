"""Compose mock-desktop stage images and filmstrip thumbnails, cached as Sixel."""
from collections import OrderedDict
import hashlib
import os
from pathlib import Path
import subprocess
import threading
import time

MEMORY_LIMIT = 40


def _fill(wallpaper, w, h):
    return ['magick', str(wallpaper), '-resize', f'{w}x{h}^', '-gravity', 'center', '-extent', f'{w}x{h}',
            '-gravity', 'NorthWest']


def stage_command(wallpaper, palette, w, h):
    """Wallpaper with a mock bar, a gradient-bordered window and a second window, encoded as Sixel."""
    bg, accent = palette['background'], palette['accent']
    second, light = palette.get('second', accent), palette.get('lighter_background', bg)
    bar = max(4, h * 7 // 100)
    dot = max(2, bar // 5)
    border = max(2, w // 300)
    wx, wy, ww, wh = w * 5 // 100, h * 14 // 100, w * 48 // 100, h * 74 // 100
    sx, sw, sh = w - w * 5 // 100 - w * 34 // 100, w * 34 // 100, h * 40 // 100
    argv = _fill(wallpaper, w, h)
    argv += ['-fill', bg, '-draw', f'rectangle 0,0 {w - 1},{bar - 1}', '-fill', accent]
    for k in range(3):
        cx = bar + k * dot * 4
        argv += ['-draw', f'circle {cx},{bar // 2} {cx + dot},{bar // 2}']
    argv += ['(', '-size', f'{ww}x{wh}', '-define', 'gradient:angle=45', f'gradient:{accent}-{second}', ')',
             '-geometry', f'+{wx}+{wy}', '-composite',
             '-fill', bg, '-draw', f'rectangle {wx + border},{wy + border} {wx + ww - 1 - border},{wy + wh - 1 - border}',
             '-stroke', light, '-strokewidth', str(border),
             '-draw', f'rectangle {sx},{wy} {sx + sw - 1},{wy + sh - 1}',
             '+stroke', '-colors', '256', 'sixel:-']
    return argv


def sample_command(wallpaper, palette, segments, w, h, alpha, cell, font):
    """The terminal sample as a translucent terminal would show it over this theme's wallpaper."""
    cw, ch = cell
    argv = _fill(wallpaper, w, h)
    argv += ['(', '-size', f'{w}x{h}', f'xc:{palette["background"]}', '-alpha', 'set', '-channel', 'A',
             '-evaluate', 'set', f'{round(alpha * 100)}%', '+channel', ')', '-composite']
    if font:
        argv += ['-font', font]
    argv += ['+gravity', '-pointsize', str(max(6, round(ch * 0.76)))]
    columns = max(1, w // cw - 3)
    for row, line in enumerate(segments):
        x, y = 2, row + 1
        if (y + 1) * ch > h:
            break
        for text, color, back in line:
            text = text[:max(0, columns - (x - 2))]
            if not text:
                break
            if back:
                argv += ['-fill', back, '-draw',
                         f'rectangle {x * cw},{y * ch} {(x + len(text)) * cw - 1},{(y + 1) * ch - 1}']
            argv += ['-fill', color, '-annotate', f'+{x * cw}+{y * ch + round(ch * 0.78)}', text]
            x += len(text)
    return argv + ['-colors', '256', 'sixel:-']


def thumb_command(wallpaper, w, h):
    return _fill(wallpaper, w, h) + ['-colors', '256', 'sixel:-']


class Previews:
    """Serves cached Sixel previews; a background worker renders what the UI asks for."""

    def __init__(self, root, cache_dir, palette, run=subprocess.run, on_ready=lambda: None):
        self.root, self.cache_dir = Path(root), Path(cache_dir)
        self.palette, self.run, self.on_ready = palette, run, on_ready
        self.memory = OrderedDict()
        self.pending = []
        self.lock = threading.Condition()
        self.thread = None
        self.stopping = False
        self.sample = {'alpha': 1.0, 'cell': (10, 20), 'font': None, 'segments': lambda palette: []}

    def sample_settings(self, **settings):
        """Opacity, cell size, font file and content used for 'sample' images; part of their cache key."""
        self.sample.update(settings)

    def _wallpaper(self, slug):
        return next(iter(sorted((self.root / slug / 'backgrounds').glob('*'))), None)

    def _path(self, kind, slug, w, h):
        wallpaper = self._wallpaper(slug)
        if wallpaper is None:
            return None, None
        extra = ''
        if kind == 'sample':
            extra = repr((self.sample['alpha'], self.sample['cell'], self.sample['font'],
                          self.sample['segments'](self.palette(slug))))
        digest = hashlib.sha1((self.root / slug / 'colors.toml').read_bytes()
                              + str(wallpaper.stat().st_mtime_ns).encode() + extra.encode()).hexdigest()[:10]
        return wallpaper, self.cache_dir / f'{kind}-{slug}-{w}x{h}-{digest}.six'

    def _remember(self, path, data):
        with self.lock:
            self.memory[path] = data
            self.memory.move_to_end(path)
            while len(self.memory) > MEMORY_LIMIT:
                self.memory.popitem(last=False)

    def get(self, kind, slug, w, h):
        """Cached Sixel bytes, or None. Never renders."""
        try:
            _, path = self._path(kind, slug, w, h)
        except OSError:
            return None
        if path is None:
            return None
        with self.lock:
            if path in self.memory:
                self.memory.move_to_end(path)
                return self.memory[path]
        try:
            data = path.read_bytes()
        except OSError:
            return None
        self._remember(path, data)
        return data

    def render(self, kind, slug, w, h):
        cached = self.get(kind, slug, w, h)
        if cached is not None:
            return cached
        try:
            wallpaper, path = self._path(kind, slug, w, h)
            if path is None:
                raise FileNotFoundError(f'no wallpaper for {slug}')
            if kind == 'stage':
                argv = stage_command(wallpaper, self.palette(slug), w, h)
            elif kind == 'sample':
                palette = self.palette(slug)
                argv = sample_command(wallpaper, palette, self.sample['segments'](palette), w, h,
                                      self.sample['alpha'], self.sample['cell'], self.sample['font'])
            else:
                argv = thumb_command(wallpaper, w, h)
            data = self.run(['nice', '-n', '10'] + argv, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=True).stdout
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
            temp.write_bytes(data)
            os.replace(temp, path)
        except (OSError, subprocess.CalledProcessError) as error:
            self._log(f'{kind} {slug} {w}x{h}: {error}')
            return None
        self._remember(path, data)
        return data

    def _log(self, line):
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with open(self.cache_dir / 'picker.log', 'a') as log:
                log.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {line}\n')
        except OSError:
            pass

    def request(self, jobs):
        """Replace the render queue; jobs already cached are skipped."""
        missing = [job for job in jobs if self.get(*job) is None]
        with self.lock:
            self.pending = missing
            self.lock.notify()

    def _work(self):
        while True:
            with self.lock:
                while not self.pending and not self.stopping:
                    self.lock.wait()
                if self.stopping:
                    return
                job = self.pending.pop(0)
            if self.render(*job) is not None:
                self.on_ready()

    def start(self):
        self.thread = threading.Thread(target=self._work, daemon=True)
        self.thread.start()

    def stop(self):
        with self.lock:
            self.stopping = True
            self.lock.notify()
        if self.thread:
            self.thread.join(timeout=1)

#!/usr/bin/env python3
"""Derive each theme's palette from its own wallpaper.

Clusters the wallpaper's pixels in OKLab, then builds:
  * a background tinted by the wallpaper's dark tones,
  * an accent from its most vivid prominent color, plus a contrasting secondary,
  * ANSI colors whose hues lean toward the wallpaper's colors while keeping
    every slot recognisable (red stays red, blue stays blue),
and rewrites colors.toml, shell.toml (from Omarchy's template) and icons.theme.

Usage: python tools/derive_palettes.py [--dry-run] [THEME ...]
Requires ImageMagick (`magick`).
"""
import argparse
import json
import math
from pathlib import Path
import random
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
# Palettes designed by hand; only regenerated when named explicitly.
HAND_TUNED = {'anime-nexus', 'shadow-monarch'}
TEMPLATE = Path('/usr/share/omarchy/default/themed/shell.toml.tpl')


# ---------- color math (OKLab / OKLCH, sRGB gamut) ----------

def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def rgb_to_oklab(r, g, b):
    r, g, b = srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b)
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def oklab_to_linear(L, a, b):
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def lch(L, C, h):
    """OKLCH -> hex, reducing chroma until the color fits in sRGB."""
    for _ in range(40):
        a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
        rgb = oklab_to_linear(L, a, b)
        if all(-1e-4 <= c <= 1 + 1e-4 for c in rgb):
            break
        C *= 0.94
    return '#' + ''.join(f'{round(min(1, max(0, linear_to_srgb(max(0, c)))) * 255):02x}' for c in rgb)


def hex_to_lch(value):
    r, g, b = (int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
    L, a, b2 = rgb_to_oklab(r, g, b)
    return L, math.hypot(a, b2), math.degrees(math.atan2(b2, a)) % 360


def luminance(value):
    r, g, b = (srgb_to_linear(int(value[i:i + 2], 16) / 255) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(x, y):
    a, b = sorted((luminance(x), luminance(y)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def hue_delta(a, b):
    return (b - a + 180) % 360 - 180


def mix_hex(x, y, amount):
    """Mix x toward y by `amount` (0..1) in sRGB, like Omarchy's template `mix`."""
    xs = [int(x[i:i + 2], 16) for i in (1, 3, 5)]
    ys = [int(y[i:i + 2], 16) for i in (1, 3, 5)]
    return '#' + ''.join(f'{round(a + (b - a) * amount):02x}' for a, b in zip(xs, ys))


# ---------- wallpaper analysis ----------

def wallpaper_pixels(path, width=128, height=72):
    raw = subprocess.run(['magick', str(path), '-resize', f'{width}x{height}!', '-depth', '8', 'rgb:-'],
                         stdout=subprocess.PIPE, check=True).stdout
    pixels = []
    for i in range(0, len(raw), 3):
        x = (i // 3) % width
        pixels.append((rgb_to_oklab(raw[i] / 255, raw[i + 1] / 255, raw[i + 2] / 255), x / width))
    return pixels


def kmeans(points, k=12, iterations=14):
    rng = random.Random(7)
    centers = [rng.choice(points)]
    while len(centers) < k:  # k-means++ seeding, deterministic
        weights = [min(sum((p[i] - c[i]) ** 2 for i in range(3)) for c in centers) for p in points]
        total = sum(weights) or 1
        pick, acc = rng.random() * total, 0
        for p, w in zip(points, weights):
            acc += w
            if acc >= pick:
                centers.append(p)
                break
    for _ in range(iterations):
        groups = [[] for _ in centers]
        for p in points:
            best = min(range(len(centers)), key=lambda j: (p[0] - centers[j][0]) ** 2 * 0.5
                       + (p[1] - centers[j][1]) ** 2 + (p[2] - centers[j][2]) ** 2)
            groups[best].append(p)
        centers = [tuple(sum(p[i] for p in g) / len(g) for i in range(3)) if g else c
                   for g, c in zip(groups, centers)]
    clusters = []
    for c, g in zip(centers, groups):
        if g:
            L, a, b = c
            clusters.append({'L': L, 'C': math.hypot(a, b), 'h': math.degrees(math.atan2(b, a)) % 360,
                             'weight': len(g) / len(points)})
    return clusters


def analyse(path):
    samples = wallpaper_pixels(path)
    clusters = kmeans([p for p, _ in samples])
    # The left quarter is composed to sit behind windows: its tone sets the background tint.
    dark = [p for p, x in samples if p[0] < 0.42] or [p for p, _ in samples]
    left = [p for p, x in samples if x < 0.25 and p[0] < 0.5] or dark
    a = sum(p[1] for p in left) / len(left)
    b = sum(p[2] for p in left) / len(left)
    mean_l = sum(p[0] for p, _ in samples) / len(samples)
    vivid = sorted((c['C'] for c in clusters), reverse=True)
    return {
        'pixels': [p for p, _ in samples],
        'clusters': clusters,
        'dark_hue': math.degrees(math.atan2(b, a)) % 360,
        'dark_chroma': math.hypot(a, b),
        'mean_l': mean_l,
        'vividness': sum(vivid[:3]) / 3,
    }


# ---------- palette construction ----------

ANSI_SLOTS = {  # OKLCH hue: canonical, allowed range (ranges keep neighbours apart)
    'red': (22, 10, 30),
    'orange': (56, 48, 66),
    'yellow': (92, 84, 104),
    'green': (145, 130, 158),
    'cyan': (203, 190, 215),
    'blue': (256, 240, 270),
    'magenta': (328, 308, 348),
}


def salience(cluster):
    """Prefer vivid, reasonably bright, reasonably large color regions."""
    lightness_fit = max(0.0, 1 - abs(cluster['L'] - 0.68) / 0.45)
    return cluster['C'] ** 1.6 * math.sqrt(cluster['weight']) * (0.25 + lightness_fit)


def intent_bonus(cluster, hue):
    """Favour colors near the hue the wallpaper was designed around (from its prompt)."""
    if hue is None or cluster['C'] < 0.035:
        return 1.0
    return 1 + 2.5 * max(0.0, 1 - abs(hue_delta(cluster['h'], hue)) / 40)


def rendition(pixels, hue):
    """How the wallpaper actually painted a target hue: vivid pixels within 30 degrees of it."""
    if hue is None:
        return None
    near = [p for p in pixels if 0.3 < p[0] < 0.97 and math.hypot(p[1], p[2]) > 0.045
            and abs(hue_delta(hue, math.degrees(math.atan2(p[2], p[1])))) <= 30]
    if len(near) < len(pixels) * 0.004:
        return None
    chroma = sorted(math.hypot(p[1], p[2]) for p in near)
    a, b = sum(p[1] for p in near), sum(p[2] for p in near)
    return {'L': sum(p[0] for p in near) / len(near), 'C': chroma[int(len(chroma) * 0.75)],
            'h': math.degrees(math.atan2(b, a)) % 360, 'weight': len(near) / len(pixels)}


def pick_accents(info, intent=(None, None)):
    main, complement = intent
    primary = rendition(info['pixels'], main)
    secondary = rendition(info['pixels'], complement)
    if primary and secondary and abs(hue_delta(primary['h'], secondary['h'])) >= 35:
        return primary, secondary
    ranked = sorted(info['clusters'], key=lambda c: salience(c) * intent_bonus(c, main), reverse=True)
    primary = primary or ranked[0]
    others = [c for c in ranked[1:] if abs(hue_delta(primary['h'], c['h'])) >= 55 and c['C'] >= 0.045]
    others.sort(key=lambda c: salience(c) * intent_bonus(c, complement), reverse=True)
    secondary = next((c for c in others if salience(c) >= salience(primary) * 0.06), None)
    return primary, secondary


def prompt_intent(folder):
    """Hues of the 'main light' and 'complementary' colors named in wallpaper-prompt.txt."""
    prompt = folder / 'wallpaper-prompt.txt'
    text = prompt.read_text() if prompt.exists() else ''
    found = re.search(r'(#[0-9a-fA-F]{6}) main light and (#[0-9a-fA-F]{6}) complementary', text)
    return tuple(hex_to_lch(v.lower())[2] for v in found.groups()) if found else (None, None)


def clamp_hue(h, lo, hi):
    if lo <= h <= hi:
        return h
    return lo if abs(hue_delta(h, lo)) < abs(hue_delta(h, hi)) else hi


def build_palette(info, intent=(None, None)):
    primary, secondary = pick_accents(info, intent)
    # Muted wallpapers get calmer terminal colors, vivid ones get punchier colors.
    energy = min(1.15, max(0.78, 0.7 + info['vividness'] * 3))

    accent_c = min(0.17, max(0.075, primary['C'] * 1.15))
    accent = lch(0.80, accent_c, primary['h'])
    if secondary:
        second_h, second_c = secondary['h'], min(0.15, max(0.07, secondary['C'] * 1.1))
    else:  # Single-hue wallpaper: use a gentle analogous companion instead of a clash.
        second_h, second_c = (primary['h'] + 40) % 360, accent_c * 0.75
    accent2 = lch(0.83, second_c, second_h)

    # Background: tinted by the wallpaper's dark tones, never pure grey or oversaturated.
    # Near-neutral shadows borrow the accent's hue so every theme keeps a character.
    own = min(1.0, info['dark_chroma'] / 0.04)
    bg_h = (primary['h'] + hue_delta(primary['h'], info['dark_hue']) * own) % 360
    bg_c = min(0.04, max(0.02, info['dark_chroma'] * 0.6))
    bg_l = 0.205 if info['mean_l'] < 0.45 else 0.215
    tone = lambda L, C=bg_c: lch(L, C, bg_h)

    colors = {
        'mode': 'dark',
        'accent': accent,
        'selection': lch(0.36, min(0.055, accent_c * 0.42), primary['h']),
        'muted': lch(0.60, min(0.03, bg_c * 0.9), bg_h),
        'background': tone(bg_l),
        'dark_background': tone(bg_l - 0.035),
        'darker_background': tone(bg_l - 0.07),
        'lighter_background': tone(bg_l + 0.065, bg_c * 1.1),
        'foreground': lch(0.925, min(0.02, bg_c * 0.5), bg_h),
        'dark_foreground': lch(0.74, min(0.03, bg_c * 0.8), bg_h),
        'light_foreground': lch(0.86, min(0.025, bg_c * 0.6), bg_h),
        'bright_foreground': lch(0.975, 0.008, bg_h),
        'hyprland_active_border': f'rgba({accent[1:]}ee) rgba({accent2[1:]}ee) 45deg',
        'hyprland_inactive_border': lch(0.36, min(0.045, bg_c * 1.3), bg_h),
    }

    # ANSI: lean each slot toward nearby wallpaper hues, anchor the accent's own slot.
    anchors = [(c['h'], c['C'] * math.sqrt(c['weight'])) for c in info['clusters'] if c['C'] > 0.04]
    ansi = {}
    for name, (base, lo, hi) in ANSI_SLOTS.items():
        pull, total = 0.0, 0.0
        for h, w in anchors:
            d = hue_delta(base, h)
            if abs(d) <= 35:
                pull += d * w
                total += w
        hue = base + (pull / total) * 0.5 if total else base
        if abs(hue_delta(base, primary['h'])) <= 22:
            hue = primary['h']
        hue = clamp_hue(hue % 360, lo, hi)
        chroma = {'yellow': 0.13, 'orange': 0.13, 'green': 0.13, 'cyan': 0.11}.get(name, 0.14) * energy
        light = {'yellow': 0.84, 'green': 0.78, 'cyan': 0.80, 'blue': 0.76}.get(name, 0.75)
        ansi[name] = lch(light, chroma, hue)
        if name != 'orange':
            ansi['bright_' + name] = lch(min(0.92, light + 0.08), chroma * 0.82, hue)
    colors.update({k: ansi[k] for k in ('red', 'yellow', 'orange', 'green', 'cyan', 'blue', 'magenta')})
    colors['brown'] = lch(0.64, 0.06, clamp_hue(ansi_hue(ansi['orange']), 45, 70))
    colors.update({k: ansi[k] for k in ('bright_red', 'bright_yellow', 'bright_green',
                                         'bright_cyan', 'bright_blue', 'bright_magenta')})
    return colors, accent2, primary['h'], accent_c


def ansi_hue(value):
    return hex_to_lch(value)[2]


def icon_theme(hue, chroma):
    if chroma < 0.06:
        return 'Yaru'
    for limit, name in ((40, 'Yaru-red'), (68, 'Yaru-wartybrown'), (105, 'Yaru-yellow'),
                        (160, 'Yaru-sage'), (215, 'Yaru-prussiangreen'), (280, 'Yaru-blue'),
                        (318, 'Yaru-purple'), (350, 'Yaru-magenta'), (361, 'Yaru-red')):
        if hue < limit:
            return name


# ---------- writing files ----------

COLOR_ORDER = ['mode', 'accent', 'selection', 'muted', 'background', 'dark_background', 'darker_background',
               'lighter_background', 'foreground', 'dark_foreground', 'light_foreground', 'bright_foreground',
               'hyprland_active_border', 'hyprland_inactive_border', 'red', 'yellow', 'orange', 'green', 'cyan',
               'blue', 'magenta', 'brown', 'bright_red', 'bright_yellow', 'bright_green', 'bright_cyan',
               'bright_blue', 'bright_magenta']


def render_colors(colors):
    return ''.join(f'{key} = "{colors[key]}"\n' for key in COLOR_ORDER)


def render_shell(colors, accent2):
    template = TEMPLATE.read_text()

    def substitute(match):
        expr = match.group(1).split()
        if expr[0] == 'shell_gradient':
            return colors[expr[1]]
        if expr[0] == 'mix':
            return mix_hex(colors[expr[1]], colors[expr[2]], int(expr[3].rstrip('%')) / 100)
        return colors[expr[0]]

    shell = re.sub(r'\{\{\s*(.*?)\s*\}\}', substitute, template)
    # Keep the collection's signature touch: selected rows use the secondary accent.
    return re.sub(r'^(selected-text\s+= )"#[0-9a-f]{6}"', rf'\1"{accent2}"', shell, flags=re.M)


def process(slug, dry_run=False):
    folder = ROOT / slug
    wallpaper = next(iter(sorted((folder / 'backgrounds').glob('*'))))
    info = analyse(wallpaper)
    colors, accent2, hue, chroma = build_palette(info, prompt_intent(folder))
    if not dry_run:
        (folder / 'colors.toml').write_text(render_colors(colors))
        (folder / 'shell.toml').write_text(render_shell(colors, accent2))
        (folder / 'icons.theme').write_text(icon_theme(hue, chroma) + '\n')
    return colors


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('themes', nargs='*')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not TEMPLATE.exists():
        parser.exit(1, f'Missing Omarchy shell template: {TEMPLATE}\n')
    slugs = args.themes or [item['id'] for item in json.loads((ROOT / 'catalog.json').read_text())
                            if item['id'] not in HAND_TUNED]
    for slug in slugs:
        colors = process(slug, args.dry_run)
        print(f"{slug:32} bg {colors['background']}  accent {colors['accent']}  "
              f"{colors['hyprland_active_border'].split()[1][5:11]}", file=sys.stderr)


if __name__ == '__main__':
    main()

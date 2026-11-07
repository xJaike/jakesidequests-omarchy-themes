# Jake Sidequests Themes

132 anime and gaming inspired Omarchy themes with generated wallpapers. A paintbrush button in the Omarchy bar opens a full-screen terminal picker: a large mock-desktop preview of the highlighted theme above a filmstrip of wallpapers, with filters by series, color, favorites and recent themes.

## Install

Requires Omarchy Quattro with Quickshell, Python 3.11+, ImageMagick, and a Sixel-capable terminal (such as Foot). These are local system dependencies; the plugin does not install packages.

```sh
omarchy plugin add https://github.com/xJaike/jakesidequests-omarchy-themes --enable
```

Click the paintbrush. The picker opens on your current theme. The stage shows the highlighted theme as a miniature desktop (wallpaper, bar, window borders). Beside it, a terminal sample shows a short shell session and a palette showroom: every normal and bright terminal color named in its own color, swatches, the foreground tones, accents and selection. The whole picker re-tints to the highlighted theme: while it is open, the terminal's default colors follow that theme, so a translucent terminal keeps its opacity with the theme's background color. Your terminal colors are restored when the picker closes. Browsing never changes your system; only Enter does.

| Key | Action |
|---|---|
| `←` `→` / `h` `l` / mouse wheel | Previous / next theme |
| `Enter` / click the selected card | Apply (installs first if needed) |
| `f` | Favorite / unfavorite |
| `r` | Surprise: jump to a random theme in the current filter |
| `/` or start typing | Search names, series and colors |
| `Tab` | Move to the filter chips (All, ★ Favorites, Recent, Series, colors) |
| `Esc` | Clear search, leave the chips, or quit |

If an installed copy differs from the bundled theme, Enter asks: `u` update & apply (a backup is kept) or `a` apply your copy. Previews are rendered on demand and cached in `$XDG_CACHE_HOME/jake-sidequests-themes`; favorites and recent themes are stored in `$XDG_STATE_HOME/jake-sidequests-themes/state.json`. Without Sixel support the picker still works, showing palettes instead of images. The picker currently uses English; the bar tooltip follows Omarchy's translation fallback.

Run the picker directly from a checkout:

```sh
python theme_picker.py
python theme_picker.py --list
```

## Files and permissions

All 132 themes are bundled. Installation downloads the repository (approximately 308 MB); the picker makes no network requests and runs no background polling. Previews run ImageMagick locally. Applying explicitly runs `omarchy theme set`.

Installation copies declarative colors, shell styling, icon selection and raster wallpapers into `$XDG_CONFIG_HOME/omarchy/themes/<slug>` (default `~/.config/omarchy/themes`). Executable theme configs are never copied. Replacing an existing directory only happens when you choose `u` update & apply, and preserves a backup beside it in `.jake-theme-backup-*/<slug>`. No sudo is needed.

## Remove and update

```sh
omarchy plugin remove io.github.xjaike.theme-collection --yes
omarchy plugin update io.github.xjaike.theme-collection --yes
```

Removing the plugin leaves installed themes and backups in place. Switch to another theme with `omarchy theme set` before deleting an installed theme's directory yourself. Plugin updates do not change installed copies; use the picker to reinstall a theme, with confirmation and backup.

## Contents and licensing

See [catalog.json](catalog.json) for the included themes. Each theme has its palette, generated wallpaper, and generation prompt. Palettes are derived from each theme's own wallpaper by `tools/derive_palettes.py`: the background takes the wallpaper's shadow tones, the accents come from its most prominent colors (guided by the colors named in the prompt), and the terminal colors lean toward the wallpaper while red, green, blue and the rest stay recognisable. Anime Nexus and Shadow Monarch keep their hand-tuned palettes. Rerun it with `python tools/derive_palettes.py [THEME ...]` after changing a wallpaper. The two pre-existing wallpaper-only folders (`cloud-vs-rufus-wallpaper` and `wallhaven-ex136k`) are excluded from the published plugin.

Plugin code is MIT licensed; see [LICENSE](LICENSE). Generated wallpapers and theme names reference existing fictional properties. No ownership of those characters, names, or trademarks is claimed. No license to third-party intellectual property is granted by the code license. Wallpaper prompts are included for provenance.

## Validation

```sh
omarchy plugin validate .
python -m unittest discover -s tests
python theme_picker.py --list
```

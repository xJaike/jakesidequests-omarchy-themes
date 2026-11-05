# Jake Sidequests Themes

132 anime and gaming inspired Omarchy themes with generated wallpapers. A paintbrush button in the Omarchy bar opens a searchable terminal picker. Preview a wallpaper, install a theme, or install and apply it.

## Install

Requires Omarchy Quattro with Quickshell, Python 3.11+, Gum, an installed terminal, and xdg-utils. These are local system dependencies; the plugin does not install packages.

```sh
omarchy plugin add https://github.com/xJaike/jakesidequests-omarchy-themes --enable
```

Click the paintbrush, type to search, and press Enter to choose a theme and action. Escape goes back or closes the picker. Wallpaper previews open in your default image viewer. The picker currently uses English; the bar tooltip follows Omarchy's translation fallback.

Run the picker directly from a checkout:

```sh
python theme_picker.py
python theme_picker.py --list
```

## Files and permissions

All 132 themes are bundled. Installation downloads the repository (approximately 308 MB); the picker makes no network requests and runs no background polling. Previewing starts `xdg-open`. Applying explicitly runs `omarchy theme set`.

Installation copies declarative colors, shell styling, icon selection and raster wallpapers into `$XDG_CONFIG_HOME/omarchy/themes/<slug>` (default `~/.config/omarchy/themes`). Executable theme configs are never copied. Replacing an existing directory requires confirmation, defaults to No, and preserves a backup beside it in `.jake-theme-backup-*/<slug>`. No sudo is needed.

## Remove and update

```sh
omarchy plugin remove io.github.xjaike.theme-collection --yes
omarchy plugin update io.github.xjaike.theme-collection --yes
```

Removing the plugin leaves installed themes and backups in place. Switch to another theme with `omarchy theme set` before deleting an installed theme's directory yourself. Plugin updates do not change installed copies; use the picker to reinstall a theme, with confirmation and backup.

## Contents and licensing

See [catalog.json](catalog.json) for the included themes. Each theme has its palette, generated wallpaper, and generation prompt. The two pre-existing wallpaper-only folders (`cloud-vs-rufus-wallpaper` and `wallhaven-ex136k`) are excluded from the published plugin.

Plugin code is MIT licensed; see [LICENSE](LICENSE). Generated wallpapers and theme names reference existing fictional properties. No ownership of those characters, names, or trademarks is claimed. No license to third-party intellectual property is granted by the code license. Wallpaper prompts are included for provenance.

## Validation

```sh
omarchy plugin validate .
python -m unittest discover -s tests
python theme_picker.py --list
```

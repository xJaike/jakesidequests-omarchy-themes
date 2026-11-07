# Terminal Filmstrip Theme Picker — Design

Date: 2026-11-07 · Status: approved in brainstorming, awaiting spec review

## Intent

Choosing one of 132 themes should feel like browsing a gallery, not operating a menu. Today the paintbrush opens a terminal running fzf (name list + small Sixel preview) followed by a Gum action menu and a Gum confirm. The user named four problems, all in scope:

1. **Feels like a terminal tool** — fzf/Gum chrome, generic colors.
2. **Hard to browse 132** — one alphabetical list; no way to narrow by series or color.
3. **Too many steps** — pick → action menu → confirm.
4. **Can't judge before committing** — a small wallpaper thumbnail says nothing about the bar, borders or terminal colors.

Decisions made with the user:

- Stay a **terminal app** (in foot), laid out as **stage + filmstrip** (option B).
- Preview is a **mock desktop**, never a live apply: nothing on the system changes until Enter.
- Browsing aids: **series filter, color filter, favorites + recent, surprise**.
- Surprise **previews** a random theme; Enter applies it.

Success: a user opens the picker, narrows to e.g. "Naruto" or "Violet" in one or two keystrokes, sees a faithful preview of each theme as they arrow through without stalls, and applies with one key.

## Experience

### Screen layout (≥ 100 columns)

```
 search: _                                              Jake Sidequests · 3/132
 [All 132] ★ Favorites  Recent  Series: any ▾  ●Violet ●Crimson ●Ember ●Gold ●Jade ●Ocean ●Rose ●Silver
 ─────────────────────────────────────────────────────────────────────────────── (accent)
 ┌───────── stage (Sixel) ─────────┐  ┌──── terminal sample (real text) ────┐
 │ wallpaper + mock bar + window    │  │ ❯ ~/projects git:(main) ls          │
 │ with accent→second gradient      │  │ src tests build.sh README.md        │
 │ border + second window           │  │ M theme_picker.py  D old_menu.py …  │
 └──────────────────────────────────┘  └─────────────────────────────────────┘
 Geralt Silver Hunt · The Witcher · installed      ←→ browse Enter apply f favorite r surprise / search tab filters esc quit
 ───────────────────────────────────────────────────────────────────────────────
 [thumb] [thumb] [THUMB] [thumb] [thumb] [thumb] [thumb]     ← filmstrip (Sixel), names + palette strip under each
```

- The entire UI (screen background, text, chips, rules, highlights) is painted in the **highlighted theme's** palette using truecolor ANSI, so the picker itself previews the theme.
- Stage ≈ 62 % of width; terminal sample takes the rest. The sample is real text rendered by foot using the theme's `background`, `foreground`, `muted`, `selection`, `accent` and ANSI colors — it is what the user's terminals will look like.
- Filmstrip shows as many cards as fit (minimum 3), the selected card centered when possible, outlined in the accent; badges: `★` favorite, `●` current theme, `installed`.
- **Narrow** (< 100 columns): the terminal sample is hidden; the stage uses full width. **Tiny** (< 60×20): only the message "Enlarge window to browse themes" is drawn.

### Opening

The bar paintbrush launches `theme_picker.py` in the user's terminal (unchanged mechanism). The picker opens with the **current Omarchy theme** selected if it is in the collection, otherwise the first theme.

### Keys and mouse

| Input | Action |
|---|---|
| `←` `→`, `h` `l`, mouse wheel | previous / next theme in the filtered list |
| `Home` `End` | first / last |
| `Enter` | apply highlighted theme (see Apply) |
| `f` | toggle favorite |
| `r` | surprise: jump to a random theme within the current filter (not the current one when ≥ 2 match); preview only |
| `/` or any printable character other than the bound keys | focus search and type; search matches name, series and color family, case-insensitive, all words must match |
| `Backspace` | edit search |
| `Tab` | move focus to the chip row; `←` `→` move between chips, `Enter`/`Space` toggles; `Tab` returns to the filmstrip |
| `Series ▾` chip activated | vertical list of series (with counts) over the stage; `↑` `↓` choose, `Enter` select, `Esc` back; "any" clears |
| `Esc` | clear search if non-empty → else leave chip focus → else quit |
| `q`, `Ctrl-C` | quit |
| Mouse click on card | select it; click on selected card = apply |
| Mouse click on chip | toggle it |

Filters combine with AND: one of {All, Favorites, Recent} × optional series × optional color family × search text. Favorites/Recent are mutually exclusive with All. Recent is ordered newest first; all other views use catalog order (alphabetical by name). If the filter matches nothing, the stage area shows "No themes match" and the filmstrip is empty; Enter does nothing.

### Apply

`Enter` on a theme:

- **missing** (not in `~/.config/omarchy/themes/<slug>`) → install, then `omarchy theme set <slug>`.
- **installed** and identical to the bundled copy → `omarchy theme set <slug>`.
- **outdated** (installed `colors.toml` or `shell.toml` differs from bundled) → info line asks: `u` update & apply (backup kept) · `a` apply my copy · `Esc` cancel.
- **current** → info line says "Already applied"; nothing runs.

While running, the info line shows "Applying …". On success the theme is pushed to Recent and the picker exits (the window closes). On failure the info line shows the error in the theme's `red` and the picker stays open.

Install safety rules carry over unchanged from today's `install()`: only declarative files (`colors.toml`, `shell.toml`, `icons.theme`, `README.md`, `wallpaper-prompt.txt`) and raster backgrounds are copied; staging happens in a temp dir inside the themes dir; replacement moves the old directory to `.jake-theme-backup-*/<slug>` first and restores it if the final rename fails; symlinks are refused. The Gum confirm is replaced by the in-picker `u`/`a` prompt.

## Architecture

```
ThemeCollection.qml (bar button, unchanged)
  └─ omarchy launch terminal python theme_picker.py
       theme_picker.py   entry point · catalog · install/apply · state  (no UI)
         └─ tui.py       screen model, layout, input → actions, drawing
              └─ previews.py   stage/thumbnail composition with ImageMagick, Sixel cache, prefetch thread
```

### Units

**`theme_picker.py`** — entry point and backend, no terminal drawing.
- `catalog()` — existing validation; now also requires `series` and `color` on every entry.
- `status(slug) -> "missing" | "installed" | "outdated" | "current"`. The current theme slug is read from `$XDG_STATE_HOME/omarchy/current/theme.name` (default `~/.local/state/…`; Omarchy copies the active theme into `current/theme/` and records its slug there). If that file is missing, fall back to `omarchy theme current`, which prints the display name (e.g. "Akatsuki Rainfall"), and match it against catalog names.
- `install(slug, replace: bool)` — existing logic minus Gum; raises `NeedsDecision` when the target exists and `replace` is not set.
- `apply(slug)` — runs `omarchy theme set <slug>`; raises on non-zero exit with stderr in the message.
- `State` — load/save favorites (set of slugs) and recent (list, max 10, newest first) at `$XDG_STATE_HOME/jake-sidequests-themes/state.json` (default `~/.local/state/…`). Unknown slugs are dropped on load; a corrupt or unreadable file yields empty state; saves are atomic (write temp + rename).
- CLI: no args → run the TUI; `--list` → print slugs (unchanged). The hidden `--preview` fzf hook is removed.

**`tui.py`** — the interactive app.
- `Model` (pure, no I/O): themes, filter (view, series, color, search), selected index, focus (filmstrip | chips | series-list | search), pending prompt. Methods return new state for each action; `filtered()` and `surprise(rng)` live here.
- `Layout` (pure): from columns, rows and cell pixel size, computes rectangles for header, chips, stage, sample, info line and filmstrip cards, plus their pixel sizes for images; handles wide / narrow / tiny.
- `parse_input(bytes) -> list[Action]`: keys, SGR (1006) mouse clicks and wheel.
- `Screen`: owns the terminal — alternate screen, hidden cursor, raw mode via `termios`/`tty`, SGR mouse on, `SIGWINCH` → relayout. Restores everything in a `finally` block and on `SIGTERM`/`SIGHUP`.
- Draw loop: on each action redraw text/chrome immediately; draw filmstrip thumbnails from cache (or a palette-colored placeholder block if not yet cached); draw the stage image only after 100 ms without further input, so held arrows never block.

**`previews.py`** — images.
- `stage(slug, width_px, height_px) -> bytes` (Sixel) — ImageMagick composites the theme's first background scaled to fill, a bar strip in `background` with accent workspace dots, a window rectangle with a 45° `accent→second` gradient border filled with `background`, and a second window bordered in `lighter_background`; then encodes Sixel (256 colors).
- `thumb(slug, width_px, height_px) -> bytes` — scaled wallpaper, Sixel.
- Cache: `$XDG_CACHE_HOME/jake-sidequests-themes/<kind>-<slug>-<w>x<h>-<palette-hash>.six`; keyed on size and a hash of `colors.toml` + wallpaper mtime so palette regenerations invalidate it. In-memory LRU (≈ 40 entries) on top.
- Prefetch: one background worker thread renders, in order, the selected stage, its two neighbors' stages, then the visible filmstrip thumbs. Rendering runs `magick` with `nice`. The UI never waits on the worker except to read finished results.
- Errors (missing `magick`, non-zero exit) are logged to `$XDG_CACHE_HOME/jake-sidequests-themes/picker.log`; callers receive `None` and draw the placeholder.

**Sixel detection** — at startup the picker sends a Primary Device Attributes query (`ESC [ c`) and waits up to 200 ms; Sixel is available if the reply contains attribute `4`. Without Sixel the picker runs with placeholders and a one-line hint ("Images need a Sixel terminal such as foot").

### Catalog data

`catalog.json` entries gain two fields:

```json
{"id": "madara-crimson-eclipse", "name": "Madara Crimson Eclipse", "series": "Naruto", "color": "Crimson"}
```

- `series` comes from a hand-maintained table `SERIES` in `tools/derive_palettes.py`, keyed by slug, covering every theme. Themes that mix franchises or are original use `"Crossover"`. The tool fails if any catalog theme is missing from the table.
- `color` is computed from the accent's OKLCH hue/chroma by the same tool: chroma < 0.06 → Silver; hue 350–20 Crimson, 20–60 Ember, 60–110 Gold, 110–190 Jade, 190–265 Ocean, 265–315 Violet, 315–350 Rose.
- The tool rewrites catalog.json (preserving order and existing fields). Hand-tuned themes (Anime Nexus, Shadow Monarch) still get `series`/`color`; their palettes are not touched.
- Color chips shown in the UI are only the families that have at least one theme.

### Removed

- fzf list + `--preview` hook, Gum menus and confirm, the `choose()` helper.
- Runtime dependencies `gum` and `fzf`. Remaining: Python 3.11+, ImageMagick (`magick`), a Sixel terminal (foot), `omarchy`.
- README install/usage text is updated to describe the new picker and dependencies; `xdg-open` "Preview wallpaper" action is dropped (the stage replaces it).

## Error handling

| Situation | Behavior |
|---|---|
| No Sixel reply in 200 ms | run without images; hint line |
| `magick` missing / render fails | placeholder block in palette colors; logged; browsing continues |
| Apply / install fails | error in info line (theme `red`); picker stays open; failed replace restores backup |
| `NeedsDecision` (outdated install) | `u` / `a` / `Esc` prompt in info line |
| State file corrupt | empty state; next save rewrites atomically |
| Window < 60×20 | "Enlarge window to browse themes" only |
| Exception, Ctrl-C, SIGTERM, SIGHUP | terminal restored (raw mode off, main screen, cursor shown, mouse off) before exit; exception text printed after restore |
| Current theme not in collection | start at first theme; no `●` badge |

## Testing

`python -m unittest discover -s tests`, no real terminal required:

- **Model**: each filter alone and combined; search matches name/series/color; Favorites and Recent views; Surprise picks only within the filter and avoids the current theme when possible; empty-filter behavior; selection clamping after filter changes.
- **Layout**: wide, narrow (< 100 cols, sample hidden), tiny (< 60×20) rectangles and pixel sizes; filmstrip card count ≥ 3 and centered selection.
- **Input parsing**: arrows, Home/End, Enter, f, r, /, Tab, Esc, Backspace, printable characters, SGR mouse click and wheel sequences.
- **Drawing**: a fake output buffer receives truecolor sequences in the selected theme's colors; second draw of the same theme reuses cached Sixel bytes (renderer called once); placeholder drawn when the renderer returns `None`.
- **Backend**: existing install tests kept; status detection for missing / installed / outdated / current; `NeedsDecision` path; replace failure restores the backup; apply surfaces `omarchy theme set` stderr.
- **State**: favorite toggle round-trip; recent capped at 10, newest first, deduplicated; corrupt file → empty state; atomic save.
- **Catalog**: every entry has `series` and a `color` from the defined family set.
- **Terminal restore**: an exception inside the loop still leaves raw mode off (tested with a pty).

Manual acceptance before completion: run the picker in a real foot window — browse with held arrows, filter by series and color, search, favorite, surprise, apply a missing theme, apply an outdated one with `u`, resize the window across the narrow and tiny thresholds.

## Out of scope

- A native Quickshell overlay (considered and set aside in favor of staying in the terminal).
- Live try-on / temporary apply.
- New themes or palette changes (done separately).
- Non-Sixel image protocols (kitty graphics).

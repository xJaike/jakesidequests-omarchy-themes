# Terminal Filmstrip Theme Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fzf/Gum theme picker with a full-screen terminal "stage + filmstrip" browser that previews each theme as a mock desktop, filters by series/color/favorites/recent, and applies in one key.

**Architecture:** `theme_picker.py` stays the entry point and becomes a UI-free backend (catalog, status, install, apply, state). `tui.py` holds a pure model, pure layout, input parsing, frame painting and the terminal `Screen`/event loop. `previews.py` composes stage/thumbnail images with ImageMagick and serves cached Sixel bytes, rendered by a background worker.

**Tech Stack:** Python 3.11+ standard library only (`termios`, `tty`, `selectors`, `threading`, `tomllib`, `unittest`), ImageMagick `magick`, Sixel-capable terminal (foot), `omarchy` CLI.

**Spec:** `docs/superpowers/specs/2026-11-07-terminal-filmstrip-picker-design.md`

## Global Constraints

- Python 3.11+, standard library only; no new pip dependencies.
- Runtime dependencies after this change: Python 3.11+, ImageMagick (`magick`), a Sixel terminal (foot), `omarchy`. `gum` and `fzf` are no longer used anywhere.
- Nothing on the system changes until Enter (no live apply, no temp apply).
- Install safety unchanged: copy only `colors.toml`, `shell.toml`, `icons.theme`, `README.md`, `wallpaper-prompt.txt` and raster backgrounds (`.png .jpg .jpeg .webp`); stage in a temp dir inside the themes dir; back up to `.jake-theme-backup-*/<slug>` before replacing; restore backup if the final rename fails; refuse symlinks.
- Paths: themes `$XDG_CONFIG_HOME/omarchy/themes` (default `~/.config/…`); state `$XDG_STATE_HOME/jake-sidequests-themes/state.json`; cache and log `$XDG_CACHE_HOME/jake-sidequests-themes/` (`picker.log`); current theme `$XDG_STATE_HOME/omarchy/current/theme.name`, fallback `omarchy theme current` (prints display name).
- Numbers: Recent max 10 newest first; stage image drawn after 100 ms idle; Sixel DA query timeout 200 ms; narrow below 100 columns; tiny below 60×20; stage ≈ 62 % width in wide mode; filmstrip ≥ 3 cards; in-memory Sixel LRU ≈ 40 entries.
- Color families (accent OKLCH): chroma < 0.06 → Silver; else hue ≥ 350 or < 20 Crimson; 20–60 Ember; 60–110 Gold; 110–190 Jade; 190–265 Ocean; 265–315 Violet; 315–350 Rose (lower bound inclusive).
- UI copy, verbatim: "Enlarge window to browse themes", "No themes match", "Already applied", "Applying …", "Images need a Sixel terminal such as foot", outdated prompt "`u` update & apply (backup kept) · `a` apply my copy · `Esc` cancel".
- Tests run with `python -m unittest discover -s tests` and need no real terminal.

## Review Focus

- **Several keys in one read** (held arrow → `b'\x1b[C\x1b[C\x1b[C'`): must yield three moves, not one or garbage. → Task 6.
- **Lone Esc** (`b'\x1b'` alone, not a sequence prefix): must act as Esc immediately, never wait for more bytes. → Task 6.
- **Bound letters while searching** (`f`, `r`, `q`, `h`, `l` typed after `/`): must be search text, not favorite/surprise/quit. → Task 6.
- **Selection after a filter change**: the selected theme stays selected if still visible, otherwise index clamps to the new list; never out of range. → Task 4.
- **Resize while images are pending**: images rendered for the old pixel size must never be drawn at the new size; the painter only asks for the current layout's sizes. → Task 8.

---

### Task 0: Branch and baseline

**Files:** none created. The working tree holds uncommitted palette work and the user's fzf-preview WIP; they become the baseline this plan builds on.

- [ ] **Step 1:** `git switch -c filmstrip-picker`
- [ ] **Step 2:** Commit the baseline, excluding the two wallpaper-only folders:

```bash
git add .gitignore README.md theme_picker.py tests/ tools/ catalog.json */colors.toml */shell.toml */icons.theme
git commit -m "Derive palettes from wallpapers; Sixel preview picker WIP"
git add docs/superpowers/specs docs/superpowers/plans
git commit -m "Add filmstrip picker design spec and plan"
```

Verify: `git status --short` shows only `?? cloud-vs-rufus-wallpaper/` and `?? wallhaven-ex136k/`.

---

### Task 1: Catalog series and color family

**Files:**
- Modify: `tools/derive_palettes.py` (add `SERIES`, `color_family`, `write_catalog`, `--catalog-only`)
- Modify: `catalog.json` (regenerated)
- Modify: `theme_picker.py` `catalog()` — require `series` and `color`
- Test: `tests/test_palettes.py`

**Interfaces:**
- Produces: `derive_palettes.color_family(hex_accent: str) -> str` (one of `COLOR_FAMILIES`); `derive_palettes.COLOR_FAMILIES = ('Crimson','Ember','Gold','Jade','Ocean','Violet','Rose','Silver')`; `derive_palettes.SERIES: dict[str, str]`; catalog entries `{"id","name","series","color"}`.

- [ ] **Step 1: Write failing tests** in `tests/test_palettes.py`:

```python
def test_color_family_boundaries(self):
    lch = palettes.lch
    self.assertEqual(palettes.color_family(lch(0.8, 0.12, 355)), 'Crimson')
    self.assertEqual(palettes.color_family(lch(0.8, 0.12, 10)), 'Crimson')
    self.assertEqual(palettes.color_family(lch(0.8, 0.12, 40)), 'Ember')
    self.assertEqual(palettes.color_family(lch(0.8, 0.12, 85)), 'Gold')
    self.assertEqual(palettes.color_family(lch(0.8, 0.12, 150)), 'Jade')
    self.assertEqual(palettes.color_family(lch(0.8, 0.12, 230)), 'Ocean')
    self.assertEqual(palettes.color_family(lch(0.8, 0.12, 290)), 'Violet')
    self.assertEqual(palettes.color_family(lch(0.8, 0.12, 330)), 'Rose')
    self.assertEqual(palettes.color_family(lch(0.8, 0.03, 290)), 'Silver')

def test_catalog_has_series_and_color(self):
    entries = json.loads((ROOT / 'catalog.json').read_text())
    self.assertEqual({e['id'] for e in entries}, set(palettes.SERIES))
    for e in entries:
        self.assertIn(e['color'], palettes.COLOR_FAMILIES)
        self.assertTrue(e['series'])
    by_id = {e['id']: e['series'] for e in entries}
    self.assertEqual(by_id['madara-crimson-eclipse'], 'Naruto')
    self.assertEqual(by_id['gojo-hollow-purple'], 'Jujutsu Kaisen')
    self.assertEqual(by_id['geralt-silver-hunt'], 'The Witcher')
    self.assertEqual(by_id['totoro-rain-shelter'], 'Studio Ghibli')
```

- [ ] **Step 2:** Run `python -m unittest tests.test_palettes -v` → FAIL (`color_family` missing).
- [ ] **Step 3: Implement** in `tools/derive_palettes.py`:
  - `SERIES`: one entry per catalog slug. Take the franchise from each theme's `wallpaper-prompt.txt` ("Primary subject: … from X") or the README. Canonical spellings: Naruto, One Piece, Demon Slayer, Jujutsu Kaisen, Bleach, Attack on Titan, Chainsaw Man, Solo Leveling, Final Fantasy, Elden Ring, Dark Souls, Bloodborne, Sekiro, Persona, NieR, The Witcher, Baldur's Gate 3, Mass Effect, Resident Evil, Zelda, Metroid, Hollow Knight, Studio Ghibli (Spirited Away, Totoro, Mononoke, Howl), Frieren, Dragon Ball, Cowboy Bebop, Devil May Cry, Hunter x Hunter, Mob Psycho 100, Fullmetal Alchemist, Evangelion, Cyberpunk 2077, Ghost of Tsushima, God of War, Horizon, Trigun, Samurai Champloo, Akira, Violet Evergarden, The Apothecary Diaries, Doom, League of Legends, Genshin Impact, Spy x Family. Use `Crossover` for mixed or original themes (e.g. `anime-nexus`, `nexus-all-stars`). Add a new canonical name only when none fits.
  - `color_family(hex_accent: str) -> str` using `hex_to_lch` and the Global Constraints table.
  - `write_catalog()`: rewrites `catalog.json` in existing order with `series` from `SERIES` and `color` from the theme's current `colors.toml` accent; raises `SystemExit` naming any slug missing from `SERIES`. JSON format: `indent=2`, trailing newline.
  - `main()`: always call `write_catalog()` after processing; `--catalog-only` skips palette regeneration.
  - `theme_picker.catalog()`: raise `ValueError(f'Missing series/color: {slug}')` when either key is absent.
- [ ] **Step 4:** Run `python tools/derive_palettes.py --catalog-only`, then `python -m unittest discover -s tests` → all PASS (the `InstallTests` fixture catalog gets `"series": "Test", "color": "Violet"` added).
- [ ] **Step 5:** Commit `tools/derive_palettes.py catalog.json theme_picker.py tests/` — "Tag themes with series and color family".

---

### Task 2: Backend — palette, status, install, apply

**Files:**
- Modify: `theme_picker.py` (remove `choose`, `choose_theme`, `preview`, `terminal_cell_size`, gum confirm; add functions below)
- Test: `tests/test_picker.py` (rewrite `InstallTests`; delete `PreviewTests`)

**Interfaces:**
- Produces:
  - `palette(slug: str) -> dict[str, str]` — `colors.toml` values plus `'second'`: the second `rgba(xxxxxxee)` hex in `hyprland_active_border` as `#xxxxxx`, falling back to `accent`.
  - `current_theme() -> str | None` — slug per Global Constraints; display-name fallback matched against `catalog()` names; `None` if unknown.
  - `status(slug: str) -> str` — `'current' | 'missing' | 'outdated' | 'installed'`; outdated when installed `colors.toml` or `shell.toml` bytes differ from bundled.
  - `class NeedsDecision(Exception)`.
  - `install(slug: str, replace: bool = False) -> Path` — raises `NeedsDecision` if target exists and not `replace`; returns installed path.
  - `apply(slug: str) -> None` — `subprocess.run(['omarchy','theme','set',slug], capture_output=True, text=True)`; non-zero → `RuntimeError(stderr.strip() or f'omarchy theme set failed ({code})')`.

- [ ] **Step 1: Write failing tests** (reuse the existing `setUp`; add `shell.toml` to the fixture theme):
  - `test_install_only_declarative_files`: `picker.install('sample')` returns `self.target/'sample'`; `colors.toml` copied; `hyprland.lua` absent.
  - `test_existing_install_needs_decision`: pre-create target with `original`; `assertRaises(picker.NeedsDecision)`; `original` still `'keep'`.
  - `test_replace_keeps_backup`: `install('sample', replace=True)`; exactly one `.jake-theme-backup-*/sample/original`.
  - `test_failed_replace_restores_backup`: patch `Path.rename` so the staged→target rename raises `OSError`; after `assertRaises(OSError)`, target `original` reads `'keep'`.
  - `test_status_values`: missing → `'missing'`; after install → `'installed'`; edit installed `colors.toml` → `'outdated'`; with `current_theme` patched to `'sample'` → `'current'`.
  - `test_current_theme_reads_state_file_then_cli`: `XDG_STATE_HOME` → temp dir with `omarchy/current/theme.name` = `sample\n` → `'sample'`; remove file, patch `subprocess.run` stdout `'Sample\n'` → `'sample'`; stdout `'Other\n'` → `None`.
  - `test_apply_surfaces_stderr`: patched run returncode 1, stderr `'boom\n'` → `RuntimeError('boom')`.
  - `test_palette_second_color`: fixture `hyprland_active_border = "rgba(aabbccee) rgba(112233ee) 45deg"` → `palette('sample')['second'] == '#112233'`.
  - Keep `test_unknown_slug_and_symlink_refused`.
- [ ] **Step 2:** Run `python -m unittest tests.test_picker -v` → FAIL.
- [ ] **Step 3: Implement** the Interfaces above in `theme_picker.py`; keep `catalog()`, `themes_dir()`, `ROOT`, `--list`. `main()` temporarily keeps only `--list` (the TUI is wired in Task 9).
- [ ] **Step 4:** Run `python -m unittest discover -s tests` → PASS.
- [ ] **Step 5:** Commit — "Make picker backend non-interactive".

---

### Task 3: Favorites and recent state

**Files:**
- Modify: `theme_picker.py`
- Test: `tests/test_picker.py` (`StateTests`)

**Interfaces:**
- Produces: `state_path() -> Path`; `class State` with attributes `favorites: set[str]`, `recent: list[str]`, and methods `State.load(path: Path, known: set[str]) -> State` (classmethod), `save() -> None`, `toggle_favorite(slug) -> bool` (returns new is-favorite), `push_recent(slug) -> None`.

- [ ] **Step 1: Write failing tests:**
  - `test_favorite_round_trip`: toggle `'a'` → `True`; save; reload → `{'a'}`; toggle again → `False`.
  - `test_recent_capped_newest_first_deduplicated`: push `t0`…`t11`, then `t5` → `recent[0] == 't5'`, `len == 10`, `recent.count('t5') == 1`.
  - `test_unknown_slugs_dropped_on_load`: file has favorite `'gone'` → not in `favorites` when `known={'a'}`.
  - `test_corrupt_file_gives_empty_state`: file text `'{nope'` → empty favorites and recent, no exception.
  - `test_save_is_atomic`: patch `os.replace` to raise; the original file content is unchanged.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement**. JSON shape `{"favorites": [...sorted], "recent": [...]}`; save writes `state.json.tmp` in the same dir, then `os.replace`; parent dirs created on save.
- [ ] **Step 4:** Run `python -m unittest discover -s tests` → PASS.
- [ ] **Step 5:** Commit — "Store favorites and recent themes".

---

### Task 4: Model (filters, selection, surprise)

**Files:**
- Create: `tui.py`
- Test: `tests/test_tui_model.py`

**Interfaces:**
- Produces in `tui.py`:
  - `@dataclass(frozen=True) class Theme: id: str; name: str; series: str; color: str; palette: dict`
  - `@dataclass class Chip: label: str; kind: str; value: str | None; active: bool` — kinds `'view'`, `'series'`, `'color'`.
  - `@dataclass class Model` with fields `themes: list[Theme]`, `favorites: set[str]`, `recent: list[str]`, `current: str | None`, `view: str = 'all'` (`'all'|'favorites'|'recent'`), `series: str | None = None`, `color: str | None = None`, `search: str = ''`, `index: int = 0`, `focus: str = 'film'` (`'film'|'chips'|'series'|'search'`), `chip_index: int = 0`, `series_index: int = 0`, `prompt: str | None = None`, `message: str | None = None`, `error: bool = False`.
  - Methods: `filtered() -> list[Theme]`; `selected() -> Theme | None`; `move(delta: int)`; `home()`; `end()`; `select_id(slug: str) -> bool`; `set_view(view: str)`; `set_series(series: str | None)`; `toggle_color(color: str)`; `type_char(ch: str)`; `backspace()`; `surprise(rng: random.Random)`; `chips() -> list[Chip]`; `series_options() -> list[tuple[str, int]]` (sorted by name, counts over all themes).

- [ ] **Step 1: Write failing tests** with a 6-theme fixture (two Naruto/Crimson, one Naruto/Violet, one One Piece/Jade, one Witcher/Jade, one Persona/Gold):
  - `test_filters_combine`: `set_series('Naruto')` + `toggle_color('Crimson')` → the two Naruto/Crimson ids; `toggle_color('Crimson')` again clears color.
  - `test_search_matches_name_series_color_all_words`: `'naruto crimson'` → 2; `'jade witcher'` → 1; `'JADE'` → 2.
  - `test_favorites_and_recent_views`: recent `['c','a']` → `[c, a]` order; favorites view in catalog order.
  - `test_selection_kept_or_clamped_after_filter` *(Review Focus)*: select last theme, apply a filter that keeps it → still selected; apply one that removes it → `index` within range and `selected()` not None; filter matching nothing → `selected() is None`.
  - `test_surprise_stays_in_filter_and_moves`: with a 3-match filter and `random.Random(1)`, 20 calls never select outside the filter and never return the same theme twice in a row.
  - `test_chips_list`: labels start `['All 6', '★ Favorites', 'Recent', 'Series: any ▾']`, then only color families present, in `COLOR_FAMILIES` order.
  - `test_move_home_end_clamp`: `move(-1)` at 0 stays 0; `end()` → last.
- [ ] **Step 2:** Run `python -m unittest tests.test_tui_model -v` → FAIL.
- [ ] **Step 3: Implement**. `tui.py` defines its own `COLOR_FAMILIES` tuple (same values as Task 1) to avoid importing tools. Filter changes call one private `_reselect(previous_id)` used by every filter mutator.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit — "Add picker model".

---

### Task 5: Layout

**Files:**
- Modify: `tui.py`
- Test: `tests/test_tui_layout.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class Rect: x: int; y: int; w: int; h: int` (0-based cells); `@dataclass(frozen=True) class Layout: mode: str; header: Rect; chips: Rect; stage: Rect | None; sample: Rect | None; info: Rect | None; film: list[Rect]; stage_px: tuple[int, int]; thumb_px: tuple[int, int]`; `compute_layout(cols: int, rows: int, cell_w: int, cell_h: int) -> Layout`.

Rows top→bottom: header (1), chips (1), rule (1), stage, info (1), rule (1), film (thumbnail rows + 2 rows for name and palette strip). Thumbnail rows = `max(3, rows * 18 // 100)`. Card width = `max(18, cols // 7)` with a 1-column gap; card count = `max(3, (cols + 1) // (card_width + 1))`. Wide: stage width = `cols * 62 // 100`, sample = the remaining width minus a 2-column gap. Pixel sizes = cells × cell size.

- [ ] **Step 1: Write failing tests:**
  - `test_wide_layout`: `(160, 48, 10, 20)` → mode `'wide'`, `stage.w == 99`, `sample` not None, `stage_px == (990, stage.h * 20)`, `len(film) >= 3`, every rect inside 160×48 and non-overlapping vertically between stage/info/film.
  - `test_narrow_hides_sample`: `(99, 40, 10, 20)` → `'narrow'`, `sample is None`, `stage.w == 99`.
  - `test_tiny`: `(59, 30, …)` and `(80, 19, …)` → `'tiny'`, `stage is None`, `film == []`.
  - `test_minimum_three_cards`: `(60, 20, 10, 20)` → `len(film) == 3`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit — "Add picker layout".

---

### Task 6: Input parsing and dispatch

**Files:**
- Modify: `tui.py`
- Test: `tests/test_tui_input.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class Event: kind: str; value: str | int | None = None; x: int = 0; y: int = 0` — kinds `'key'` (values `'left','right','up','down','home','end','enter','tab','esc','backspace','space','ctrl-c'`), `'char'` (printable str), `'click'` (0-based x, y), `'wheel'` (value `-1`/`+1`).
- `parse_input(data: bytes) -> list[Event]`.
- `dispatch(model: Model, event: Event, layout: Layout, rng: random.Random) -> str | None` — returns a command `'apply' | 'update' | 'apply-copy' | 'quit'` or `None` (model mutated in place). Key map per the spec's Keys table; `q` quits only in film/chips focus; with `model.prompt == 'outdated'`, `u` → `'update'`, `a` → `'apply-copy'`, Esc clears the prompt, other keys ignored. Click on a film card selects it; a click on the already-selected card → `'apply'`; click on the chips row toggles the chip under x (chip x-ranges come from `chip_spans(model, layout) -> list[tuple[int, int, Chip]]`, which the painter also uses).

- [ ] **Step 1: Write failing tests:**
  - `test_arrows_home_end_enter_tab_esc`: `b'\x1b[D\x1b[C\x1b[A\x1b[B\x1b[H\x1b[F\r\t'` → the 8 expected key events.
  - `test_many_keys_in_one_read` *(Review Focus)*: `b'\x1b[C\x1b[C\x1b[C'` → three `right`.
  - `test_lone_escape` *(Review Focus)*: `b'\x1b'` → `[Event('key','esc')]`.
  - `test_sgr_mouse`: `b'\x1b[<0;12;5M'` → `click` at `(11, 4)`; `b'\x1b[<64;1;1M'` → `wheel -1`; `b'\x1b[<65;1;1M'` → `wheel +1`; release `...m` ignored.
  - `test_utf8_char_and_backspace_and_ctrl_c`: `'é'.encode()` → `char 'é'`; `b'\x7f'` → backspace; `b'\x03'` → ctrl-c.
  - `test_letters_are_text_while_searching` *(Review Focus)*: after `/`, chars `f r q h l` → `model.search == 'frqhl'`, favorites unchanged, no `'quit'` returned.
  - `test_esc_order`: search non-empty → Esc clears search; then from chips focus → film; then → `'quit'`.
  - `test_outdated_prompt_keys`: `prompt='outdated'`: `u` → `'update'`, `a` → `'apply-copy'`, Esc → `prompt is None`, `f` ignored.
  - `test_click_select_then_apply`: click on film card 2 selects it (returns None); second click → `'apply'`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit — "Parse keys and mouse for the picker".

---

### Task 7: Previews (compose, cache, worker)

**Files:**
- Create: `previews.py`
- Test: `tests/test_previews.py`

**Interfaces:**
- Consumes: `theme_picker.palette(slug)` (passed in as a callable, no import cycle).
- Produces:
  - `stage_command(wallpaper: Path, palette: dict, w: int, h: int) -> list[str]` — `magick` argv: fill-crop the wallpaper to `w×h`; bar strip `h*7//100` high in `background` with three `accent` dots; window at x 5 %, y 14 %, 48 % × 74 % with a 45° `accent→second` gradient border (≈ `max(2, w//300)` px) filled with `background`; second window at right 5 %, y 14 %, 34 % × 40 % filled `background`, bordered `lighter_background`; end with `-colors 256 sixel:-`.
  - `thumb_command(wallpaper: Path, w: int, h: int) -> list[str]` — fill-crop, `-colors 256 sixel:-`.
  - `class Previews(root: Path, cache_dir: Path, palette: Callable[[str], dict], run=subprocess.run, on_ready: Callable[[], None] = lambda: None)` with `get(kind: str, slug: str, w: int, h: int) -> bytes | None` (memory LRU 40 → disk; never renders), `render(kind, slug, w, h) -> bytes | None` (runs `nice -n 10 magick …`, writes the disk cache, returns bytes; logs failures to `cache_dir/'picker.log'` and returns None), `request(jobs: list[tuple[str, str, int, int]])` (replaces the pending queue; jobs already cached are skipped), `start()` / `stop()` for one daemon worker thread that calls `render` then `on_ready()`.
  - Cache file name: `f'{kind}-{slug}-{w}x{h}-{digest}.six'`, `digest = sha1(colors.toml bytes + str(wallpaper.stat().st_mtime_ns).encode()).hexdigest()[:10]`.

- [ ] **Step 1: Write failing tests** (fixture theme in a temp root, fake `run` returning `b'SIXEL'`):
  - `test_stage_command_uses_palette_and_size`: argv contains `'990x560'`-style geometry, the `accent`, `second`, `background`, `lighter_background` hex values, and ends with `'sixel:-'`.
  - `test_render_caches_on_disk_and_memory`: `render` once → fake run called once; `get` returns `b'SIXEL'`; a new `Previews` on the same cache dir → `get` hits disk without calling run.
  - `test_palette_change_invalidates_cache`: rewrite `colors.toml` → `get` returns None.
  - `test_render_failure_logged_returns_none`: fake run raises `FileNotFoundError` → `render` returns None and `picker.log` contains the slug.
  - `test_worker_renders_requested_then_signals`: `request([('thumb','sample',200,112)])`, `start()`, wait ≤ 2 s on an `Event` set by `on_ready`; then `get` returns bytes; `stop()`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit — "Render and cache Sixel previews".

---

### Task 8: Painter

**Files:**
- Modify: `tui.py`
- Test: `tests/test_tui_paint.py`

**Interfaces:**
- Consumes: `Model`, `Layout`, `chip_spans`, `Previews.get`.
- Produces: `paint_frame(model: Model, layout: Layout, images, sixel: bool) -> bytes` (all text, chrome, terminal sample, filmstrip names/strips and thumbnails that `images.get` returns; placeholders otherwise) and `paint_stage(model: Model, layout: Layout, images) -> bytes | None` (cursor-positioned stage Sixel, or None if not cached); `wanted_images(model: Model, layout: Layout) -> list[tuple[str, str, int, int]]` (selected stage, both neighbors' stages, visible thumbs — all at the **current** layout's pixel sizes).

Content rules (from the spec): every cell painted with the selected theme's `background`; text in `foreground`, secondary text in `muted`; active chip as `accent` background with `background` text; rule lines in `accent` (top) and `lighter_background` (bottom); info line `name` in `accent` + ` · series · status` in `muted`, key hints on the right; `model.message` in `red` when `model.error` else `foreground`; outdated prompt text verbatim from Global Constraints; selected card name in `accent`, others `muted`; badges `★` favorite, `●` current, `installed`; terminal sample lines exactly as in the mockup (prompt `❯` green, path blue, `git:(main)` magenta, `M` yellow, `D` red, `??` cyan, `✓ 14 passed` green, `⚠ 1 skipped` yellow, `✗ 0` red, comment muted, a `selection` block, accent cursor). Tiny mode paints only "Enlarge window to browse themes"; an empty filter paints "No themes match" in the stage; `sixel=False` paints the hint "Images need a Sixel terminal such as foot" in the stage. Placeholder = stage/thumb rect filled with `lighter_background` plus a palette strip. Filmstrip window: first visible theme = `clamp(index - len(film)//2, 0, max(0, n - len(film)))`, so the selection is centered except at the ends. With `focus == 'series'`, a box over the stage lists `series_options()` as `any` then `Name (count)`, the highlighted row (`model.series_index`) in `selection` background.

- [ ] **Step 1: Write failing tests** with a fake `images` recording `get` calls:
  - `test_frame_uses_selected_palette`: output contains `48;2;r;g;b` of `background` and `38;2;…` of `accent`; switching selection changes them.
  - `test_sample_shows_ansi_colors`: output contains the truecolor codes of red, green, yellow, blue, magenta, cyan of the selected theme.
  - `test_cached_thumbs_drawn_placeholders_otherwise`: fake returns bytes for one thumb only → those bytes appear once; others produce placeholder fills.
  - `test_wanted_images_use_current_sizes` *(Review Focus)*: compute at `(160,48)` then `(100,30)`; every requested size equals the new layout's `stage_px`/`thumb_px`.
  - `test_tiny_empty_and_no_sixel_messages`: each verbatim string present in its case.
  - `test_outdated_prompt_text`: `prompt='outdated'` → verbatim prompt string present.
  - `test_series_list_and_centered_film`: `focus='series'` → `'Naruto (3)'` present; with 6 themes, 3 cards and `index=3`, the card names painted are themes 2, 3, 4.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit — "Paint picker frames".

---

### Task 9: Screen, event loop, apply flow, wiring

**Files:**
- Modify: `tui.py`, `theme_picker.py` (`main()`)
- Test: `tests/test_tui_screen.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `class Screen(fd_in: int, fd_out: int)` context manager: enter saves termios attrs, sets raw mode, writes `\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h`; exit (also on exception) writes `\x1b[?1006l\x1b[?1000l\x1b[?25h\x1b[?1049l` and restores attrs. Installs `SIGTERM`/`SIGHUP` handlers that raise `SystemExit` so `__exit__` runs.
  - `detect_sixel(fd_in: int, fd_out: int, timeout: float = 0.2) -> bool` — writes `\x1b[c`, reads the reply until `c` or timeout; True if `4` is among the `;`-separated attributes.
  - `cell_size(fd: int) -> tuple[int, int]` — `TIOCGWINSZ` pixel/cell, fallback `(10, 20)` (moved from the old `terminal_cell_size`).
  - `perform(model: Model, command: str, backend, state, redraw: Callable[[], None] = lambda: None) -> bool` — the Apply flow from the spec using `backend.status/install/apply/NeedsDecision`; sets `model.message='Applying …'` and calls `redraw()` before running; on success `state.push_recent`, `state.save()`, returns True (exit); `'current'` → message "Already applied", False; outdated → `model.prompt='outdated'`, False; exceptions → `model.message=str(error)`, `model.error=True`, False.
  - `run(model: Model, previews, backend, state, fd_in=0, fd_out=1) -> None` — `selectors` on `fd_in` and a wake pipe (`previews.on_ready` writes one byte); on input: parse → dispatch → `perform` for commands → repaint frame → `previews.request(wanted_images(...))`; stage image painted once 100 ms pass with no input; `SIGWINCH` → recompute layout and full repaint; `'quit'` or a successful `perform` ends the loop.
  - `theme_picker.main()`: `--list` unchanged; otherwise check `omarchy` and `magick` on PATH (missing `magick` only logs; missing `omarchy` exits with a message), build `Theme`s from `catalog()` + `palette()`, `State.load(state_path(), ids)`, `Model(..., current=current_theme())` with `select_id(current)`, `Previews(...)`, then `tui.run(...)`; any exception escaping `run` is printed to stderr (after `Screen` has restored the terminal) and exits with status 1. Imports `tui`/`previews` from the same directory via `sys.path.insert(0, str(ROOT))`.

- [ ] **Step 1: Write failing tests:**
  - `test_screen_restores_terminal_on_exception`: `pty.openpty()`; record `termios.tcgetattr(slave)`; `with Screen(slave, slave): raise ValueError` inside `assertRaises`; attrs equal the recorded ones; bytes read from master contain `\x1b[?1049l` and `\x1b[?25h`.
  - `test_detect_sixel`: fake fds via `os.pipe()` pre-filled with `b'\x1b[?62;4;22c'` → True; `b'\x1b[?62;22c'` → False; nothing written → False within 0.3 s.
  - `test_perform_flow`: fake backend — missing → install then apply, recent updated, returns True; `'current'` → "Already applied", False; outdated (install raises `NeedsDecision`) → `prompt == 'outdated'`; `'update'` → `install(replace=True)`; `'apply-copy'` → apply only; apply raises `RuntimeError('boom')` → `message == 'boom'`, `error is True`, False.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run `python -m unittest discover -s tests` → all PASS; `python theme_picker.py --list | wc -l` → `132`.
- [ ] **Step 5:** Commit — "Run the filmstrip picker in the terminal".

---

### Task 10: Docs, manifest, cleanup, manual acceptance

**Files:**
- Modify: `README.md` (Install requirements → "Python 3.11+, ImageMagick, a Sixel-capable terminal (such as Foot), and Omarchy Quattro with Quickshell"; replace the picker paragraph with the stage/filmstrip description and the key table; drop the "Preview wallpaper"/xdg-open text and the `xdg-utils` dependency)
- Modify: `manifest.json` (`"version": "1.1.0"`)
- Verify: no references remain — `grep -rn "gum\|fzf\|xdg-open" --include=*.py --include=*.md --include=*.qml .` prints nothing outside `docs/`.

- [ ] **Step 1:** Edit README and manifest as above.
- [ ] **Step 2:** `omarchy plugin validate .` exits 0; `python -m unittest discover -s tests` passes; the grep above is empty.
- [ ] **Step 3: Manual acceptance in a real foot window** (`foot python theme_picker.py`), each item observed:
  - opens on the current theme; holding → scrolls without stalling and the stage catches up when released;
  - `Series ▾` → Naruto, then `Crimson` narrows correctly; `/gojo` finds Gojo; Esc clears search, then quits;
  - `f` adds ★ and it survives a restart; `r` stays inside the filter;
  - apply a not-installed theme → desktop switches, window closes, theme appears first in Recent next time;
  - edit an installed copy's `colors.toml`, apply it → `u`/`a` prompt; `u` replaces with a backup;
  - shrink the window below 100 columns (sample hides) and below 60×20 ("Enlarge window to browse themes"); grow it back.
- [ ] **Step 4:** Commit — "Document the filmstrip picker".

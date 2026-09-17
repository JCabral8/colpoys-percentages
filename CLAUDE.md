# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A phone-first, single-file web app for an annual golf weekend: four friends (Nick, Jay, Justin, Chris) post sports takes, lock in percentages on a spinning drum, and once a year the "Marshal" runs Audit Night to reveal last year's sealed takes with a fire sequence. Read `HANDOFF.md` first; it is the authoritative architecture doc, the Audit Night sequence spec, and the list of decisions not to undo.

## No build, no tests, no tooling

- Everything is in `index.html` (CSS, JS, archive data, WebGL shader, particles). There is no package.json, bundler, linter, or test runner. Do not add one.
- Run it: open `index.html` in a browser, or host it on any static server (`python -m http.server` from the repo root works). Firebase (multi-phone) mode needs a real host because it loads the Firebase compat SDK from gstatic.
- Verify changes by loading the page in a browser (phone-width viewport) and checking the console. Marshal PIN is `1234`.
- The file uses very long lines (one function per line in places). Grep by function name rather than line number; the function map in `HANDOFF.md` §2 is accurate.

## Release checklist

- Bump `APP_VERSION` (near the top of the script) on every publish. Single-phone installs use it to reset `audit`/`audited`/seen-reveals state, so a stale version leaves phones in a broken audit.
- If you touch the `ARCHIVE` array in `index.html`, mirror the change in `archive.json` (and vice versa). They are hand-maintained duplicates of the same 25 items; nothing generates one from the other.

## Architecture in one pass

- **State** is a single plain object (`defaultState()`): `settings`, `takes`, `votes`, `results`, `rulings`, `audit`, `audited`. Every mutation goes through `sync.set(path, value)` (slash-separated path, `null` deletes) or `sync.replace(state)`. Never assign into `state` directly.
- **Sync** has two interchangeable backends chosen at boot from `loadCfg()`: `makeLocalSync` (localStorage + BroadcastChannel across tabs) and `makeFirebaseSync` (Realtime Database at `firepit/<ROOM>`, one `on("value")` listener, last-writer-wins). Both call `render()` after every change; there is no other update path.
- **Render** is a full innerHTML re-render of `#app` on every state change, dispatched by `tab` to `renderFeed/Archive/Board/Admin`. Transient UI (armed two-tap buttons, open dial, filters) lives in the module-level `ui` object, not in `state`. Overlays are appended after the main render; the animated widgets (`initDrum`, `initNav`, `initStack`) are re-initialised by `render()` and keep their own rAF loops.
- **Archive data** (`ARCHIVE`) has four item kinds: `call` (yes/no with `stance` + `outcome`), `pick` (`picks` + `correct[]`/`partial[]`), `num` (`guesses` + `actual`), `lore` (text only). 2025 items carry `sealed:true` and must stay hidden everywhere (archive deck, scorecard, titles) until they appear in `state.audited`; `isSealed`/`visibleArchive`/`liveArchive` are the gates.
- **Scoring** rule is deliberately binary: every take you weighed in on ends W or L, no pushes, no partial credit. `archiveWinners`/`archiveLosers` decide per item (closest number, best Brier for percentages, right side for calls, exact for picks); `lifetime`/`yearWL` aggregate. Don't reintroduce ties-as-pushes.
- **Audit Night** is driven by the Marshal's phone via `state.audit {active, order[], idx, revealed}` and played on every phone by `playAudit`/`renderAudit`. The timings in `HANDOFF.md` §3 (deal, ignite, hold, snuff in `loserOrder`, winner flare, receipts) are the spec; changes to feel should preserve that beat structure.
- **Effects** are all procedural: `SND` is WebAudio synthesis (no audio files), 2D-canvas particles (`sparks`/`burst`/`wisp`), and a full-screen WebGL fragment shader (`GL_FS`) for the torch flames positioned from DOM torch elements. `prefers-reduced-motion` turns the ambient layers off; keep new effects behind the same check.

## Conventions to keep

- No `alert()`/`confirm()`/`prompt()`. Destructive actions use `sure(key, fn)` two-tap arming with `sureLbl` for the button text.
- Escape all interpolated strings with `esc()`; the render path is template-literal HTML.
- Player colours are fixed in `PC` (red/yellow/blue/purple) and referenced everywhere, including the shader colour ramp. Wordmark is COLPOY'S; the compass nav has no icons.
- localStorage keys are prefixed `firepit-`; Firebase config can also arrive via a `#cfg=<base64>` share link and is persisted to `firepit-cfg`.
- `whatsapp-export.txt` is the raw source the archive was mined from; it is reference material, not app input.

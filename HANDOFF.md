# Handoff: Colpoy's Percentages

Everything a Claude Code session (or a Blender/Unreal artist) needs to take this further.

## 1. What the app is

A phone-first web app. Four friends post sports takes on an open board ("the Firepit"); each guy spins a Price-is-Right-style drum to lock in a percentage (or a number); the others' numbers appear once yours is in. Once a year at the cottage the Marshal runs **Audit Night**: last year's sealed takes are dealt to every phone, revealed one at a time with a fire sequence, and the resolved takes flow into an Archive deck and a lifetime golf-style scorecard.

Sections (bottom compass nav): **Firepit · Archive · Scorecard · Marshal**.

## 2. Architecture (all inside `index.html`)

| Layer | Where in the file | Notes |
|---|---|---|
| Config | `FIREBASE_CONFIG`, `ROOM`, `DEFAULT_PIN`, `APP_VERSION` | Firebase config can also be pasted in-app; it's stored in localStorage and carried in a share link as `#cfg=<base64>` |
| Players | `PLAYERS`, `P`, `PC` | `PC` = player colours: Nick `#ff4a4a` red, Jay `#ffd23f` yellow, Justin `#4aa8ff` blue, Chris `#b56bff` purple |
| Archive data | `ARCHIVE`, `SOURCES` | Kinds: `call` (yes/no, `stance` map, `outcome`), `pick` (`picks` map, `correct[]`, `partial[]`), `num` (`guesses` map, `actual`), `lore` (text only). `sealed:true` = hidden until audited (v44: removed from the 2025 items, which aired on Audit Night Sept 2026; a year's items get it when they're baked in ahead of their show) |
| Live take kinds (v37) | `renderAdd`/`addTake`, `renderDialOverlay`, `renderVotesReveal`, `renderResolveCtl`, `auditItem`, `liveArchive` | `pct` (drum, Brier), `num` (closest), `pick` (author lists `options[]`, `multi` = pick any; a vote is an array of option indexes; result `{correct:[idx]}`; **exact set wins**, scored through the archive `pick` rules), yes/no = a `pick` with `options:["Yes","No"]`, `yn:true`, and `text` (v39: free-text answers, result `{winners:[pid]}` ticked by the Marshal, archived as `pick` with `correct=winners`). Retakes: `RETAKE_UNTIL` (Mon Sept 21 2026 4 a.m. ET) lets a player change a locked answer until then (`canRetake`, "Change my …" button); `openDial` prefills the current answer. **Board lock (v43)**: `boardLocked(t)` freezes every take with `year<=YEAR` at the same moment: no first answers either (card shows the others' answers + "Board closed", missing players listed as "Sat out"), not counted in Need me; the Marshal can still resolve. Takes posted after `RETAKE_UNTIL` get `year:YEAR+1`. |
| State | `defaultState()` | `settings{pin}`, `takes{id}`, `votes{takeId}{playerId}{v,t}`, `results{takeId}{outcome|actual,note,at}`, `rulings{archiveId}`, `audit{active,order[],idx,revealed}`, `audited{archiveId:ts}` |
| Sync | `makeLocalSync` / `makeSupabaseSync` / `makeFirebaseSync` | Same interface: `set(path,value)`, `replace(state)`. **Supabase (v25, the one Justin has)**: table `firepit` (room pk, state jsonb), per-path writes via the `firepit_set(room, path[], val)` SQL function (atomic, creates intermediate objects, null deletes), whole-state via `firepit_replace`, Realtime `postgres_changes` on the row + a 20 s pull as backup. `SUPABASE_SQL` in the file is the setup block, shown in the Marshal tab. Config = `{supabaseUrl, supabaseKey}` from a paste (`parseCfg` finds the URL and an `sb_publishable_…`/JWT key), `#cfg=` share link, or the `SUPABASE_CONFIG` constant. Firebase path kept as-is. |
| Render | `render()` + `renderFeed/Add/Archive/Board/Admin` | Vanilla JS, full re-render into `#app` innerHTML on every state change. Overlays (wheel, add sheet, reveal, audit) are appended after |
| Wheel | `initDrum` | Vertical drum, momentum, wraps 100→0, ticks with pitch by speed |
| Nav | `initNav` | Horizontal compass tape with lubber line, flick or tap, wraps |
| Archive deck | `initStack` | Tinder-style card stack, left = next, right = back, ember trail in the thrower's colour |
| Scoring | `archiveWinners/archiveLosers`, `brier`, `lifetime`, `yearWL` | One rule: every take you weighed in on ends W or L. Number = closest wins; percentage = best Brier wins; call = right side; pick = exact |
| Honours | `honours`, `badges`, `completedYears` | **C** = best lifetime net, **A** = second (ties share). **FRAUD** = worst net in the most recent season whose archive items are all audited (so it never spoils a sealed year; it flips on Audit Night). Shown on the Scorecard and the seat picker |
| Sound | `SND` | WebAudio only, no files: wheel ticks, clack, thud, whoosh, crackle, a synthesized loon call on 2 min idle |
| Particles (2D canvas) | `sparks`, `burst`, `smokeOnly`, `wisp`, `sparkStep`, `smokeSprite` | Embers: heat-cooling colour, buoyancy, turbulence, streak + glow. Smoke: procedural fbm sprite, two counter-rotating layers. Ash flakes on snuff |
| Fire (WebGL) | `GL_FS`, `glInit/glStart/glStep` | Full-screen fragment shader; up to 4 flames driven by DOM torch positions; fbm noise body, tip tearing, sway, colour ramp per player, glow. Intensity eases: lit 1.0, win 1.5, snuff gutters for 1.1s then 0.05 |
| Audit Night | `auditItem`, `renderAudit`, `playAudit`, `loserOrder` | See §3 |
| Ambient | `hearth`, `.sky`, `.aurora`, `cineOn` | Rising embers behind the Firepit list; rotating stars; occasional aurora; film grain + vignette during audit |

Everything runs at 60 fps on a 2020-era phone. `prefers-reduced-motion` disables the ambient layers.

## 3. Audit Night sequence (the thing to make cinematic)

Per card, on every phone that has the app open (Firebase keeps them in sync; the Marshal's phone drives):

1. **Deal.** Score strip at top (W–L per player, in colour). Take text is blurred; smoke rises past it; text sharpens (0.7 s).
2. **Ignite.** One torch per player who weighed in, left to right, 380 ms apart: flame eases up from the wick in his colour, ember burst, rising tone. His guess appears beneath.
3. **Hold** until the Marshal calls it (archive items are pre-loaded; app takes need It happened / Didn't / the actual).
4. **Snuff.** Losers, worst-to-first (`loserOrder`), 1.5 s apart: flame gutters (two sputter rhythms) for 1.1 s and collapses to a dull ember; thin smoke thread for 2.5 s; ash flakes fall; the column chars (desaturate, darken, guess struck through); 0.9 s later his L ticks in the strip with a low tone.
5. **Winner.** Last flame flares to 1.5×, big burst in his colour, camera push-in (DOM scale 1.04) with the vignette closing, W ticks in the strip. Ties share.
6. **Receipts.** Result slides up: number counts up over 1.2 s, or HIT/MISS; "what happened" text; "Nick takes the W."
7. Marshal: Next take → repeat. Finish → cards join the Archive and Scorecard.

## 4. What a Blender / Unreal pipeline should produce

The browser can't run a game engine, so the realistic route is **pre-rendered loops + live compositing**:

| Asset | Spec | Used for |
|---|---|---|
| Torch flame loop, burning | 3–4 s seamless loop, 512×1024, alpha (WebM VP9 with alpha, or MP4 + separate alpha matte), rendered **white/neutral** so the app can tint it per player with CSS `hue-rotate`/`filter` or a canvas multiply. Mantaflow fire, no smoke in this layer | Ignited state |
| Torch flame, ignition | 1.5 s, from wick to full burn, same format | Step 2 |
| Torch flame, snuff | 2.5 s: gutter → collapse → ember at wick, same format | Step 4 |
| Torch flame, flare | 2 s: 1× → 1.5× and back, same format | Step 5 |
| Smoke wisp | 3 s, alpha, grey | After snuff |
| Take reveal smoke | 2 s, wide plume rising, alpha | Step 1 |
| Campfire bed | 6 s loop, 1920×1080 (portrait crop safe), the fire ring seen from a seated eye line, embers only, very dark | Background behind the whole audit stage; the four torches composite over it |
| Stage plate | still, 1080×1920, dark clearing, four stakes at x = 12.5 / 37.5 / 62.5 / 87.5 % of width, wick tops at ~42 % of height | The torches must land on these stakes; the DOM labels sit under them |
| Title sequence | 8–10 s, "Colpoy's Percentages · Audit Night · 2026" | On Start audit |
| Sound | fire loop, ignition whoosh, snuff hiss, flare, stamp/thud, a sting for the winner | Replaces the WebAudio synths |

Constraints: single HTML file hosted on Netlify/Firebase can load these from relative paths. Keep the whole asset set under ~25 MB so phones on cottage wifi load it. Every clip must loop or hold on its last frame. Alpha matters more than resolution: 720p clips with clean alpha beat 4K without.

**If instead you want it real-time (no pre-renders):** Three.js from cdnjs is loadable in the hosted version. The plan was: 3D clearing, four stakes with point lights, ~350 additive sprite particles per flame with a noise-torn alpha and colour ramp, smoke sprites, embers, a custom bloom pass (bright-pass + separable blur + additive composite), camera dolly on deal and push-in on the winner, torches positioned by unprojecting the DOM column centres. The current WebGL shader (`GL_FS`) is the fallback and stays.

## 5. Things a new session should not undo

- Only what you put on record counts; no partial credit. Pushes were removed on purpose.
- 2025 items stay `sealed` until audited; the scorecard must not spoil them.
- No browser `confirm()`/`alert()` — the artifact viewer blocks them; use `sure()` two-tap.
- Bump `APP_VERSION` on every release.
- Nav has no icons; wordmark is COLPOY'S; player colours are red/yellow/blue/purple.
- The FRAUD tag is the worst score of the last completed season, decided by the group; keep it computed, never hand-assigned.

## 6. The Firepit Hour (radio booth) — in progress, Sept 2026

A parody sportscast that calls each take: **Hayes** (play-by-play, captain) and **O'Dog** (colour, assistant captain) from TSN's OverDrive, framed as a cottage edition of their *Gerry's Percentages* segment (the app's name is a nod to it).

| Piece | Where | State |
|---|---|---|
| Booth sample | `booth-sample.html` (also published as a private artifact) | Working: photo-cutout heads from the OverDrive promo shot (`ref/*-head.png`, cut with rembg, mouth/eye regions protected from the colour key), hinged-jaw lip flap, VU meters, scope, captions, take card. Plays the real clips: `<audio>` + `audio/<id>.json`; captions/speaker switch on the per-line timings, jaws and meters follow the baked `env` loudness envelope (AnalyserNode fallback if a JSON has no env, phone speech only if the clip is missing). Segment picker carries only the three unsealed clips (open, 2024 Celebrini, close). Layout rule (Justin, Sept 17): heads + the whole take card must fit one phone screen; scope removed, VU dials sit on the desk inside the scene, big display-font nameplates, one small two-line caption under the card. Mouth boxes are baked; the tuning panel is gone. |
| Mouth calibration | removed | Boxes are baked into `HOST.photo.mouth` / `COLR.photo.mouth`; a `firepit-booth-mouths` localStorage override from the old panel still wins if present. |
| Scripts | `tools/script.json` | Cold open, 2024 Celebrini sample, all ten sealed 2025 items, sign-off. Written for Eleven v3: `[tags]` for delivery, `...` for beats, CAPS for one emphasised word, hard names respelled. Cue fields per line: `hl` (player ids to light), `reveal`, `final`. |
| Audio bake + timing | `tools/tts.py` | ElevenLabs text-to-dialogue **with timestamps** → `audio/<id>.mp3` + `audio/<id>.json` (per-line start/end, tag-stripped caption text, cue fields). Needs `ELEVENLABS_API_KEY` (Creator plan) and the two custom voices Justin designed in ElevenLabs; `--pick hayes=<name> odog=<name>` saves their ids. No cloning of the real hosts. |

**Integrated into `index.html` (Sept 17 2026, APP_VERSION 23):**
- `BOOTH` module (IIFE near the end of the script) + `BOOTH_CLIPS` (the ids that have a clip). Heads load from `booth/hayes.png` / `booth/odog.png`; clips from `audio/<id>.mp3` + `.json`. **Deploy the folder, not just the file**: `index.html`, `audio/`, `booth/`.
- **Audit Night (v24, Justin's call on Sept 17: "the Firepit Hour is the show")**: any deck card whose archive id is in `BOOTH_CLIPS` renders `renderAuditBooth` instead of the torch stage: strip, question, booth, four `.pk` pick cells, caption, `.bres` result row, "what happened" note. The tape drives it: `hl` lights a cell, the `reveal` line counts the number up, the `final` line stamps W/L (`auditBoothFinal`), bumps the strip, and on the Marshal's phone (local mode + isAdmin) calls `auditReveal({})` so the item goes on the record; Reveal is gone, only a ghost **Skip** remains. Cards without a clip (takes made in the app) still use the torch/snuff stage, which is why `playAudit`/`renderAudit` keep both paths. Mouth boxes are Justin's calibrated numbers (hayes {x:87,y:199,w:36,h:37,a:4}, odog {x:96,y:180,w:35,h:38,a:2}) in both files.
- Audit Night cue: `state.audit.show = {clip, at, idx}` is the shared cue. The Marshal's row has **Cold open** (idx 0), **▶ Play the call** (archive items with a clip) and **Sign-off** (last card, after reveal); `boothCue()` sets it. Every phone renders the booth between the question and the torches and follows the shared start time (`at`, Firebase `.info/serverTimeOffset` applied); only the phone that cued it voices the clip, other phones get a 🔊 button in the caption to join (`ui.boothSound`). `hl` cues light the matching torch. Reveal/snuff run as before while the hosts keep talking; **Next take** clears `show` and stops the booth.
- Programming (v40): `SHOWS` lists shows the Marshal runs outside Audit Night (first one: the Saturday night edition, `sat-*` clips). The Marshal tab's Programming card cues a segment via `state.show={clip,at}`; every phone renders `renderShowOverlay` (booth + caption + the live takes named by `seg.takes` substrings, via `renderVotesReveal`), with Back / Replay / Next / End for the Marshal and × to hide for viewers. Same sound rule as the audit: the cueing phone voices it, others tap 🔊.
- Sealed results (v42): a resolved live take that a show segment lists (`showLists`) is hidden from `liveArchive` (so Archive + scorecard) and shows a 🔒 card in the feed until `state.aired[id]` is set: automatically ~2.5 s after the segment's `final` cue on the Marshal's phone, on End the show, or via the Marshal's Unseal button. Same idea as `audited` for the envelope.
- Full-show replay (v43): `REPLAYS` lists the Friday night (Audit Night: cold open, the ten 2025 calls, sign-off) and Saturday night edition clip runs. The Archive tab shows **▶ Friday show** / **▶ Saturday show** side by side under the deck (`renderReplayRow`); a night appears only when none of its archive items is sealed (`replayOpen`). `openReplay` plays the segments back to back on this phone only (`ui.pl`, no shared cue), rolling to the next 1.5 s after one ends, with Back / Replay / Next. Friday segments show the archive card; Saturday segments show the listed takes (archive card once resolved and aired, else the answers).
- Archive (v44): the per-card **▶ Watch the call** button and its overlay (`openBooth`/`renderBooth`) are gone; the full-show replay covers it and the cards need the room. `fitCards` zooms a deck card's sections down (to 62% at most) until the whole take fits without scrolling. The footer sync line and the "N takes sealed" line are gone too.
- (Before v44) Archive: audited cards with a clip get **▶ Watch the call** (`openBooth`), a full-screen `.bov` overlay with the booth, caption and the card, auto-playing on this phone. Sealed items never get the button (`isSealed`), and the caption/booth markup only exists while a show is cued.
- Hosting: GitHub Pages from the `main` branch of JCabral8/colpoys-percentages (https://jcabral8.github.io/colpoys-percentages/), Supabase baked in (`SUPABASE_CONFIG`). Every change: bump `APP_VERSION`, `cp index.html dist/` (Netlify fallback), commit, push; Pages redeploys in ~1 min. The "Adjust mouths" panel is back in the sample; new numbers get baked into both files by hand.
- Timing pipeline (v30): a bake now runs `align()` automatically: ElevenLabs speech-to-text (`scribe_v1`, cached as `audio/<id>.stt.json`) gives word timestamps; `difflib` matches them to the script's spoken words, so each line gets exact `start`/`end` and a per-caption-word `wt` array. Hand-overs snap to the last silence in the gap (from `env`). `--align` re-runs it (free once cached), `--captions` rewrites caption text (`caption` overrides in script.json, respellings undone, number words to digits), `--snap` is the offline pitch-based fallback (later-only moves). The API key lives in `~/.elevenlabs-key` on Justin's machine (not in the repo).
- Booth captions: words are `<span>`s; `karaoke()` lights them from `wt` (or by loudness share when a clip has no `wt`) and scrolls the two-row caption. Audit Night pick cells start `veil`ed and get `rev` (slide-up + colour sweep) on the `hl` cue; `rev still` when rendered already-revealed.
- Script v3 (Sept 17 2026, baked): every take opens with Hayes teeing up what was happening the night it went down (dates from `whatsapp-export.txt`: the board was May 6 2025 6:29 p.m.; the cottage takes Sept 26 2025, 10:06 to 11:32 p.m.; Robertson Sept 29 11:01 a.m.), conversational and addressed to "Dog"; O'Dog answers the line before his. OverDrive bits woven in (list in `script.json` `_notes`). `tools/hayes-draft.md` was the interim staccato draft; superseded.

**Original integration plan (for reference):**
- Audit Night: the Marshal's phone plays the clip for the current item during the Hold step, before the snuff sequence; every phone plays its own local copy, cued by `state.audit` (idx + a `show` flag) so they stay in sync.
- Replay: once an item is in `state.audited`, the Archive card gets a "Watch the call" action that opens the booth for that item at any time. Sealed items must never expose their clip, script or timings before audit.
- Playback (done in the sample, to port): `<audio>` element; the timing JSON picks the speaker and caption, and its `env` array (50 Hz loudness, from `tts.py --env`) drives the jaw and meters from `currentTime`, so no WebAudio is needed on the phone. AnalyserNode is the fallback when `env` is absent; phone speech only when the clip is missing. Create/resume any AudioContext inside the tap.
- Assets: 13 clips baked Sept 17 2026 (voices HB/OD), 96 kbps, 10.1 min, 7.0 MB in `audio/`; ship next to `index.html`, or embed as data URIs for a self-contained build.

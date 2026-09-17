# Colpoy's Percentages

Firepit sports-takes app for the annual golf weekend (Colpoy's Bay, Sept). Four players: Nick, Jay, Justin, Chris.

## Files

| File | What |
|---|---|
| `index.html` | The entire app. Single self-contained file: CSS, JS, archive data, WebGL fire shader, particle systems. No build step. Open it in a browser or drop it on any static host (Netlify Drop, GitHub Pages). |
| `archive.json` | The audited history (2021–2025) as plain JSON: players, colours, every take, guesses, results, sources. Same data that is embedded in `index.html` as `ARCHIVE`. |
| `whatsapp-export.txt` | The raw group-chat export the archive was mined from. |
| `HANDOFF.md` | Architecture, data model, the Audit Night sequence spec, and what a Blender/Unreal pipeline should produce. Read this first. |

## Running it

- **Single phone:** open `index.html`. State lives in localStorage.
- **All phones:** host `index.html`, create a free Firebase project with a Realtime Database (rules `{"rules":{".read":true,".write":true}}`), paste the `firebaseConfig` block into Marshal → "All phones at once" → Connect, then copy the link it generates into the group chat. Setup steps are inside the app under Marshal.
- Marshal PIN: `1234` (change in Marshal → Setup).

## Publishing changes

`APP_VERSION` near the top of `index.html` must be bumped on every release: single-phone installs reset the audit state when they see a new version.

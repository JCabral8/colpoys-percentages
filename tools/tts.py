"""Render the Firepit Hour scripts to MP3 clips with ElevenLabs, plus timing JSON for lip sync.

Usage (from the repo root):
    $env:ELEVENLABS_API_KEY="sk_..."           (PowerShell)
    python tools/tts.py --voices                list the voices on your account (custom ones first)
    python tools/tts.py --pick hayes="Hayes" odog="O'Dog"   save those voices (by name or id) into script.json
    python tools/tts.py --dry-run               character counts per clip, no API calls
    python tools/tts.py --only a24-celebrini    render one item
    python tools/tts.py                         render every item in tools/script.json
    python tools/tts.py --env                   (re)compute the amplitude envelopes for existing clips, no API calls

Outputs, per item:
    audio/<id>.mp3    the clip, both voices trading lines
    audio/<id>.json   {"lines":[{"i":0,"speaker":"hayes","text":"...","start":0.0,"end":3.2,"hl":[...]}, ...], "duration": 41.7}
                      start/end come from ElevenLabs' per-line voice_segments, so the app can switch
                      captions, light the right announcer and drive his jaw from the real audio.
                      text has the [delivery tags] stripped (caption-ready); hl/reveal/final cues are carried over.
                      "env" is a 50 Hz loudness envelope (0..1) of the whole clip, from ffmpeg + numpy when they are
                      installed, so the booth can move the jaws from currentTime alone, without WebAudio.

Nothing runs at app time; this is a one-off bake. Only python stdlib is used.
"""
import argparse, base64, json, os, re, shutil, subprocess, sys, time, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "script.json"
OUT = ROOT / "audio"
API = "https://api.elevenlabs.io/v1"
MAX_CHARS = 2000  # text-to-dialogue guideline per request; longer items get chunked


def key():
    k = os.environ.get("ELEVENLABS_API_KEY")
    if not k:
        sys.exit("Set ELEVENLABS_API_KEY first: https://elevenlabs.io/app/developers/api-keys")
    return k


def call(path, body=None, query=""):
    req = urllib.request.Request(API + path + query, method="POST" if body is not None else "GET")
    req.add_header("xi-api-key", key())
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, data, timeout=300) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"ElevenLabs {e.code} on {path}: {e.read().decode(errors='replace')[:800]}")


TAG = re.compile(r"\s*\[[^\]]*\]\s*")


def caption(text):
    """Strip [delivery tags] and tidy spacing so the line can be shown as a caption."""
    return re.sub(r"\s{2,}", " ", TAG.sub(" ", text)).strip()


ENV_HZ = 50


def envelope(mp3):
    """50 Hz RMS loudness of the clip, normalised so the 98th percentile is 1.0. None if ffmpeg/numpy are missing."""
    if not shutil.which("ffmpeg"):
        return None
    try:
        import numpy as np
    except ImportError:
        return None
    sr = 8000
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(pcm, dtype=np.float32)
    hop = sr // ENV_HZ
    n = len(x) // hop
    if n == 0:
        return None
    e = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(axis=1))
    top = float(np.percentile(e, 98)) or 1.0
    e = np.clip(e / top, 0, 1)
    return [round(float(v), 2) for v in e]


def add_envelope(item_id):
    mp3, js = OUT / f"{item_id}.mp3", OUT / f"{item_id}.json"
    if not (mp3.exists() and js.exists()):
        return False
    env = envelope(mp3)
    if env is None:
        return False
    d = json.loads(js.read_text(encoding="utf-8"))
    d["env_hz"], d["env"] = ENV_HZ, env
    js.write_text(json.dumps(d, indent=1), encoding="utf-8")
    return True


def voices_on_account():
    return json.loads(call("/voices"))["voices"]


def list_voices():
    v = voices_on_account()
    # your own voices (designed / cloned) first, stock premade ones after
    v.sort(key=lambda x: (x.get("category") == "premade", x["name"].lower()))
    for x in v:
        labels = ", ".join(f"{k}={val}" for k, val in (x.get("labels") or {}).items())
        print(f"{x['voice_id']}  {x['name']:<22} {x.get('category', ''):<10} {labels}")


def pick_voices(spec, pairs):
    """--pick hayes=<name or id> odog=<name or id>: resolve against the account and save to script.json."""
    v = voices_on_account()
    for pair in pairs:
        if "=" not in pair:
            sys.exit(f"--pick expects speaker=name, got {pair!r}")
        speaker, want = pair.split("=", 1)
        hit = [x for x in v if x["voice_id"] == want or x["name"].lower() == want.lower()]
        if not hit:
            sys.exit(f"No voice named {want!r} on this account. Run --voices to see them.")
        spec["voices"][speaker] = hit[0]["voice_id"]
        print(f"{speaker} -> {hit[0]['name']} ({hit[0]['voice_id']})")
    SCRIPT.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"saved to {SCRIPT.relative_to(ROOT)}")


def chunks(lines):
    group, n = [], 0
    for ln in lines:
        if group and n + len(ln["text"]) > MAX_CHARS:
            yield group
            group, n = [], 0
        group.append(ln)
        n += len(ln["text"])
    if group:
        yield group


def render(item, voices, settings, fmt):
    audio, timing, offset, base = b"", [], 0.0, 0
    for grp in chunks(item["lines"]):
        body = {
            "inputs": [{"text": ln["text"], "voice_id": voices[ln["speaker"]]} for ln in grp],
            "model_id": settings.get("model_id", "eleven_v3"),
            "settings": {"stability": settings.get("stability", 0.5)},
            "apply_text_normalization": settings.get("apply_text_normalization", "auto"),
        }
        if settings.get("seed") is not None:
            body["seed"] = int(settings["seed"])
        if settings.get("language_code"):
            body["language_code"] = settings["language_code"]
        res = json.loads(call("/text-to-dialogue/with-timestamps", body, f"?output_format={fmt}"))
        audio += base64.b64decode(res["audio_base64"])
        segs = res.get("voice_segments") or []
        # one entry per dialogue input, merged if the API split a line into several segments
        per = {}
        for sg in segs:
            i = sg["dialogue_input_index"]
            s0, e0 = per.get(i, (sg["start_time_seconds"], sg["end_time_seconds"]))
            per[i] = (min(s0, sg["start_time_seconds"]), max(e0, sg["end_time_seconds"]))
        ends = (res.get("alignment") or {}).get("character_end_times_seconds") or []
        chunk_len = max([e for _, e in per.values()] + (ends[-1:] or [0.0]))
        for j, ln in enumerate(grp):
            s0, e0 = per.get(j, (None, None))
            entry = {"i": base + j, "speaker": ln["speaker"], "text": caption(ln["text"]),
                     "start": None if s0 is None else round(offset + s0, 3),
                     "end": None if e0 is None else round(offset + e0, 3)}
            for cue in ("hl", "reveal", "final"):
                if cue in ln:
                    entry[cue] = ln[cue]
            timing.append(entry)
        offset += chunk_len
        base += len(grp)
        time.sleep(0.5)
    OUT.mkdir(exist_ok=True)
    (OUT / f"{item['id']}.mp3").write_bytes(audio)
    (OUT / f"{item['id']}.json").write_text(json.dumps({"lines": timing, "duration": round(offset, 3)}, indent=1), encoding="utf-8")
    add_envelope(item["id"])
    return OUT / f"{item['id']}.mp3"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voices", action="store_true", help="list account voices and exit")
    ap.add_argument("--pick", nargs="+", metavar="SPEAKER=NAME", help="save voices into script.json by name or id, e.g. --pick hayes=Hayes odog=\"O'Dog\"")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="render a single item id")
    ap.add_argument("--force", action="store_true", help="re-render clips that already exist")
    ap.add_argument("--env", action="store_true", help="only (re)compute amplitude envelopes for existing clips; no API calls")
    a = ap.parse_args()

    if a.voices:
        list_voices()
        return

    spec = json.loads(SCRIPT.read_text(encoding="utf-8"))
    if a.pick:
        pick_voices(spec, a.pick)
        return
    voices, settings = spec["voices"], spec.get("settings", {})
    fmt = settings.get("output_format", "mp3_44100_128")
    items = [it for it in spec["items"] if not a.only or it["id"] == a.only]
    if not items:
        sys.exit(f"No item named {a.only} in {SCRIPT}")

    total = 0
    for it in items:
        n = sum(len(ln["text"]) for ln in it["lines"])
        total += n
        missing = sorted({ln["speaker"] for ln in it["lines"] if ln["speaker"] not in voices})
        if missing:
            sys.exit(f"{it['id']}: no voice_id for speaker(s) {missing}")
        print(f"{it['id']:<18} {len(it['lines']):>2} lines  {n:>5} chars")
    print(f"{'total':<18} {'':>2}        {total:>5} chars")
    if a.dry_run:
        return
    if a.env:
        for it in items:
            ok = add_envelope(it["id"])
            print(f"{'env' if ok else 'skip'}  {it['id']}" + ("" if ok else "  (no clip, or ffmpeg/numpy missing)"))
        return
    if any(v.startswith("PASTE") for v in voices.values()):
        sys.exit("Fill in the voice ids in tools/script.json first (python tools/tts.py --voices).")

    for it in items:
        out = OUT / f"{it['id']}.mp3"
        if out.exists() and not a.force:
            print(f"skip {out.name} (exists; --force to redo)")
            continue
        p = render(it, voices, settings, fmt)
        print(f"wrote {p.relative_to(ROOT)} ({p.stat().st_size // 1024} KB) + {p.with_suffix('.json').name}")


if __name__ == "__main__":
    main()

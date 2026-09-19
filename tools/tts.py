"""Render the Firepit Hour scripts to MP3 clips with ElevenLabs, plus timing JSON for lip sync.

Usage (from the repo root):
    $env:ELEVENLABS_API_KEY="sk_..."           (PowerShell)
    python tools/tts.py --voices                list the voices on your account (custom ones first)
    python tools/tts.py --pick hayes="Hayes" odog="O'Dog"   save those voices (by name or id) into script.json
    python tools/tts.py --dry-run               character counts per clip, no API calls
    python tools/tts.py --only a24-celebrini    render one item
    python tools/tts.py                         render every item in tools/script.json
    python tools/tts.py --env                   (re)compute the amplitude envelopes for existing clips, no API calls
    python tools/tts.py --captions              rewrite the caption text in existing JSONs from the script (names, digits)
    python tools/tts.py --snap                  re-find the speaker switches from the audio itself (ElevenLabs' segment
                                                times run early); keeps the API times as seg_start/seg_end
    python tools/tts.py --align                 the real fix: ElevenLabs speech-to-text on each clip gives exact word
                                                timestamps -> exact line boundaries + per-word caption timing ("wt").
                                                Needs ELEVENLABS_API_KEY; a few credits per clip.

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
import argparse, base64, difflib, json, os, re, shutil, subprocess, sys, time, urllib.request, urllib.error, uuid
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


# Respellings that exist only to coax the right pronunciation out of the voice; captions show the real thing.
CAPTION_FIX = [("Dry-sightle", "Draisaitl"), ("Eye-kel", "Eichel"), ("Elliott?", "Elliotte?"), ("M C L", "MCL"),
               ("G, E, double R, Y.", "G-E-R-R-Y."), ("Four p.m.!", "4 p.m.!"), ("fifty-fifty", "50/50"), ("one oh one", "101"),
               ("eleven-oh-one in the morning", "11:01 a.m."), ("twenty-thirty", "2030")]
_ONES = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_NUM = re.compile(r"\b(?:(?:(?:a|one) hundred)|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:-(?:one|two|three|four|five|six|seven|eight|nine))?|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)\b", re.I)


def _num(m):
    w = m.group(0).lower()
    if "hundred" in w:
        return "100"
    if "-" in w:
        a, b = w.split("-")
        return str(_TENS[a] + _ONES[b])
    return str(_TENS.get(w, _ONES.get(w, 0)))


def caption(text, override=None):
    """The on-screen version of a line: delivery tags stripped, pronunciation respellings undone, numbers as digits."""
    if override:
        return override
    t = re.sub(r"\s{2,}", " ", TAG.sub(" ", text)).strip()
    for a, b in CAPTION_FIX:
        t = t.replace(a, b)
    t = _NUM.sub(_num, t)
    t = re.sub(r"\b20 (\d\d)\b", r"20\1", t)          # "twenty twenty-five" -> "2025"
    return t


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


def rewrite_captions(item):
    js = OUT / f"{item['id']}.json"
    if not js.exists():
        return False
    d = json.loads(js.read_text(encoding="utf-8"))
    for e, ln in zip(d["lines"], item["lines"]):
        e["text"] = caption(ln["text"], ln.get("caption"))
    js.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    return True


def snap(item_id, win=4.5, min_chunk=0.5):
    """Move each speaker switch to where the voice actually changes, using a spectral fingerprint per speech chunk."""
    mp3, js = OUT / f"{item_id}.mp3", OUT / f"{item_id}.json"
    if not (mp3.exists() and js.exists()) or not shutil.which("ffmpeg"):
        return None
    import numpy as np
    sr = 16000
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(pcm, dtype=np.float32)
    hop = 0.02; h = int(sr * hop); n = len(x) // h
    e = np.sqrt((x[:n * h].reshape(n, h) ** 2).mean(1)); e = e / (np.percentile(e, 98) or 1)
    sp = e >= 0.05; look = int(0.22 / hop); chunks = []; i = 0
    while i < n:
        if sp[i]:
            j = i
            while j < n and (sp[j] or (j + look < n and sp[j:j + look].any())):
                j += 1
            a, b = i * hop, j * hop
            while b - a > 2.0:                      # long runs can hold both voices: judge them in ~1 s pieces
                chunks.append((a, a + 1.0)); a += 1.0
            chunks.append((a, b)); i = j
        else:
            i += 1

    def feat(a, b):
        seg = x[int(a * sr):int(b * sr)]
        if len(seg) < sr * 0.15:
            return None
        win_, hp, f = 1024, 256, []
        w = np.hanning(win_)
        for s0 in range(0, len(seg) - win_, hp):
            pw = np.abs(np.fft.rfft(seg[s0:s0 + win_] * w)) ** 2
            if pw.sum() < 1e-6:
                continue
            ed = np.linspace(0, len(pw), 25).astype(int)
            f.append(np.log([pw[ed[k]:ed[k + 1]].mean() + 1e-9 for k in range(24)]))
        if not f:
            return None
        v = np.mean(f, 0); return v - v.mean()

    def f0(a, b):
        """Median pitch in Hz over [a,b] by autocorrelation, and how many voiced frames backed it."""
        seg = x[int(a * sr):int(b * sr)]; out = []
        w, hp = int(0.04 * sr), int(0.01 * sr); lo, hi = int(sr / 300), int(sr / 70)
        for s0 in range(0, len(seg) - w, hp):
            fr = seg[s0:s0 + w]; fr = fr - fr.mean()
            if np.sqrt((fr ** 2).mean()) < 0.02:
                continue
            ac = np.correlate(fr, fr, "full")[w - 1:]; ac = ac / (ac[0] + 1e-9)
            k = lo + int(np.argmax(ac[lo:hi]))
            if ac[k] > 0.5:
                out.append(sr / k)
        return (float(np.median(out)) if out else None), len(out)

    d = json.loads(js.read_text(encoding="utf-8")); L = d["lines"]; moves = []
    for ln in L:
        ln.setdefault("seg_start", ln["start"]); ln.setdefault("seg_end", ln["end"])
    for k in range(len(L) - 1):
        A, B = L[k], L[k + 1]
        if A["speaker"] == B["speaker"]:
            continue
        bnd = A["seg_end"]
        # the two voices sit a good octave apart in pitch, so pitch is the judge; the spectral fingerprint is the fallback
        fa, na = f0(A["seg_start"] + 0.3, max(A["seg_start"] + 0.8, bnd - 1.0)); fb, nb_ = f0(min(B["seg_end"] - 0.8, bnd + 1.0), B["seg_end"] - 0.3)
        use_pitch = fa and fb and na >= 15 and nb_ >= 15 and abs(np.log(fa / fb)) >= 0.2
        ra = feat(A["seg_start"], max(A["seg_start"] + 0.3, bnd - win)); rb = feat(min(B["seg_end"] - 0.3, bnd + win), B["seg_end"])
        if not use_pitch and (ra is None or rb is None):
            continue
        lab = []
        for c in chunks:
            if c[1] <= bnd - win or c[0] >= bnd + win:
                continue
            api_side = "A" if c[0] < bnd else "B"
            if c[1] - c[0] < min_chunk:          # too short to judge: trust the API side
                lab.append((c, api_side)); continue
            if use_pitch:
                f, nf = f0(*c)
                if not f or nf < 8:
                    lab.append((c, api_side)); continue
                lab.append((c, "A" if abs(np.log(f / fa)) < abs(np.log(f / fb)) else "B")); continue
            fc = feat(*c)
            if fc is None:
                continue
            da, db = np.linalg.norm(fc - ra), np.linalg.norm(fc - rb)
            decisive = max(da, db) / max(1e-6, min(da, db)) >= 1.25
            lab.append((c, ("A" if da < db else "B") if decisive else api_side))
        # best split: the cut between pieces that leaves the most A-pieces before it and B-pieces after it; ties go to the API time
        lab.sort(key=lambda t: t[0][0])
        if not any(l == "A" for _, l in lab) or not any(l == "B" for _, l in lab):
            continue
        best, nb = -1, bnd
        for m in range(1, len(lab)):
            score = sum(1 for _, l in lab[:m] if l == "A") + sum(1 for _, l in lab[m:] if l == "B")
            cand = round((lab[m - 1][0][1] + lab[m][0][0]) / 2, 3)
            if score > best or (score == best and abs(cand - bnd) < abs(nb - bnd)):
                best, nb = score, cand
        # sanity: nobody talks faster than ~20 characters a second, so a move can't leave either line shorter than that
        if nb - A["start"] < len(A["text"]) / 20 or B["seg_end"] - nb < len(B["text"]) / 20:
            nb = bnd
        if nb < bnd:                             # the API only ever ends lines early, so never move a switch earlier
            nb = bnd
        if abs(nb - bnd) > 0.25:
            moves.append((k, bnd, nb))
        A["end"] = nb; B["start"] = nb
    js.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    return moves


def stt(mp3):
    """ElevenLabs Scribe: words with start/end seconds for a clip. Cached next to the clip so re-runs cost nothing."""
    cache = mp3.with_suffix(".stt.json")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    boundary = "----firepit" + uuid.uuid4().hex
    fields = {"model_id": "scribe_v1", "timestamps_granularity": "word", "diarize": "false", "tag_audio_events": "false", "language_code": "eng"}
    body = b""
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{mp3.name}\"\r\nContent-Type: audio/mpeg\r\n\r\n".encode() + mp3.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(API + "/speech-to-text", data=body, method="POST")
    req.add_header("xi-api-key", key()); req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"ElevenLabs {e.code} on /speech-to-text: {e.read().decode(errors='replace')[:800]}")
    words = [w for w in res.get("words", []) if w.get("type", "word") == "word" and w.get("start") is not None]
    cache.write_text(json.dumps(words), encoding="utf-8")
    return words


_WORDNUM = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_WORDNUM.update({"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100})


def _norm(w):
    """Comparable token: lowercase letters/digits only; simple number words become digits so 'ninety' ~ '90'."""
    t = re.sub(r"[^a-z0-9]", "", w.lower().replace("'", ""))
    return str(_WORDNUM[t]) if t in _WORDNUM else t


def align(item):
    """Line boundaries and per-word times from speech-to-text, matched to the caption words of each line."""
    mp3, js = OUT / f"{item['id']}.mp3", OUT / f"{item['id']}.json"
    if not (mp3.exists() and js.exists()):
        return None
    d = json.loads(js.read_text(encoding="utf-8")); L = d["lines"]
    asr = stt(mp3)
    if not asr:
        return None
    a_tok = [_norm(w["text"]) for w in asr]
    # the script as spoken (TTS text, tags stripped) is what the recogniser heard; captions may differ (digits, names)
    spoken, owner = [], []          # spoken tokens, and which (line, caption-word) each belongs to
    for li, (e, ln) in enumerate(zip(L, item["lines"])):
        cap_words = e["text"].split(" ")
        tts_words = re.sub(r"\s{2,}", " ", TAG.sub(" ", ln["text"])).strip().split(" ")
        # map spoken words onto caption words by position share (they mostly line up 1:1; respellings/numbers stretch a little)
        for wi, w in enumerate(tts_words):
            ci = min(len(cap_words) - 1, int(wi * len(cap_words) / max(1, len(tts_words))))
            for piece in re.split(r"[-\s]+", w):        # "Dry-sightle" -> two tokens like the recogniser might hear
                t = _norm(piece)
                if t:
                    spoken.append(t); owner.append((li, ci))
    sm = difflib.SequenceMatcher(a=a_tok, b=spoken, autojunk=False)
    hit = {}                                   # spoken index -> asr word
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                hit[j1 + k] = asr[i1 + k]
    ratio = len(hit) / max(1, len(spoken))
    if ratio < 0.5:
        return ("low match", round(ratio, 2))
    # per caption word: earliest start / latest end of its matched spoken tokens
    wt = {}
    for si, (li, ci) in enumerate(owner):
        if si in hit:
            w = hit[si]; cur = wt.get((li, ci))
            wt[(li, ci)] = (min(cur[0], w["start"]) if cur else w["start"], max(cur[1], w["end"]) if cur else w["end"])
    moves = []
    for li, e in enumerate(L):
        n = len(e["text"].split(" "))
        times = [wt.get((li, ci)) for ci in range(n)]
        known = [(ci, t) for ci, t in enumerate(times) if t]
        if not known:
            continue
        # fill gaps by interpolation between known neighbours
        for ci in range(n):
            if times[ci]:
                continue
            prev = max([k for k in known if k[0] < ci], key=lambda k: k[0], default=None); nxt = min([k for k in known if k[0] > ci], key=lambda k: k[0], default=None)
            if prev and nxt:
                f0_, f1_ = prev[1][1], nxt[1][0]; span = max(0, nxt[0] - prev[0]); k = ci - prev[0]
                times[ci] = (f0_ + (f1_ - f0_) * (k - 1) / span, f0_ + (f1_ - f0_) * k / span)
            elif prev:
                times[ci] = (prev[1][1], prev[1][1] + 0.25)
            else:
                times[ci] = (max(0, nxt[1][0] - 0.25), nxt[1][0])
        e["wt"] = [[round(t0, 3), round(t1, 3)] for t0, t1 in times]
        e.setdefault("seg_start", e["start"]); e.setdefault("seg_end", e["end"])
        s0, e0 = times[0][0], times[-1][1]
        if abs(s0 - e["start"]) > 0.25 or abs(e0 - e["end"]) > 0.25:
            moves.append((li, round(e["start"], 2), round(s0, 2), round(e["end"], 2), round(e0, 2)))
        e["start"], e["end"] = round(s0, 3), round(e0, 3)
    # hand-overs: a line starts where the previous one ended. Put the cut at the end of the last silence in the gap,
    # so unmatched opening words (spelled letters, respellings) still belong to the right voice.
    env, hz = d.get("env"), d.get("env_hz", 50)
    for k in range(1, len(L)):
        a, b = L[k - 1]["end"], L[k]["start"]
        if b <= a:
            continue
        cut = round((a + b) / 2, 3)
        if env:
            i0, i1 = int(a * hz), int(b * hz); quiet = [i for i in range(i0, min(i1, len(env))) if env[i] < 0.05]
            if quiet:
                # last run of quiet frames of >= 0.2 s inside the gap
                runs, start = [], quiet[0]
                for prev, cur in zip(quiet, quiet[1:] + [None]):
                    if cur != prev + 1:
                        runs.append((start, prev)); start = cur
                runs = [r for r in runs if (r[1] - r[0] + 1) / hz >= 0.2]
                if runs:
                    cut = round((runs[-1][1] + 1) / hz, 3)
        L[k - 1]["end"] = cut; L[k]["start"] = cut
        if L[k].get("wt") and L[k]["wt"][0][0] > cut:
            L[k]["wt"][0][0] = cut
    d["aligned"] = True
    js.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    return ("ok", round(ratio, 2), moves)


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
            entry = {"i": base + j, "speaker": ln["speaker"], "text": caption(ln["text"], ln.get("caption")),
                     "start": None if s0 is None else round(offset + s0, 3),
                     "end": None if e0 is None else round(offset + e0, 3)}
            for cue in ("hl", "reveal", "final", "take"):
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
    try:
        align(item)
    except SystemExit as e:
        print(f"  (alignment skipped: {e})"); snap(item["id"])
    return OUT / f"{item['id']}.mp3"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voices", action="store_true", help="list account voices and exit")
    ap.add_argument("--pick", nargs="+", metavar="SPEAKER=NAME", help="save voices into script.json by name or id, e.g. --pick hayes=Hayes odog=\"O'Dog\"")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="render a single item id")
    ap.add_argument("--force", action="store_true", help="re-render clips that already exist")
    ap.add_argument("--env", action="store_true", help="only (re)compute amplitude envelopes for existing clips; no API calls")
    ap.add_argument("--captions", action="store_true", help="rewrite caption text in existing JSONs from the script; no API calls")
    ap.add_argument("--snap", action="store_true", help="re-find speaker switches from the audio; no API calls")
    ap.add_argument("--align", action="store_true", help="speech-to-text alignment: exact boundaries + word timings (uses the API)")
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
    if a.captions:
        for it in items:
            print(f"{'captions' if rewrite_captions(it) else 'skip'}  {it['id']}")
        return
    if a.snap:
        for it in items:
            mv = snap(it["id"])
            print(f"snap  {it['id']:<16} " + ("no clip" if mv is None else (", ".join(f"line{k}: {b:.2f}->{nb:.2f}" for k, b, nb in mv) or "no change")))
        return
    if a.align:
        for it in items:
            r = align(it)
            if r is None:
                print(f"align {it['id']:<16} no clip"); continue
            if r[0] != "ok":
                print(f"align {it['id']:<16} SKIPPED: {r[0]} (match {r[1]})"); continue
            print(f"align {it['id']:<16} match {r[1]}  " + (", ".join(f"line{li}: {s0:.1f}-{e0:.1f} -> {s1:.1f}-{e1:.1f}" for li, s0, s1, e0, e1 in r[2]) or "no change"))
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

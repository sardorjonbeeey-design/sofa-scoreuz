#!/usr/bin/env python3
"""Turn a brief into a render spec: caption timings from the voiceover's own
word timestamps, page colour sampled from the illustration itself.

Usage:
    python3 reels/make_spec.py 02_ortiqcha_yuk
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_alignment(path: str):
    """Return (chars, starts, ends) from whatever shape the provider used."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):               # provider returns one block per chunk
        chars, starts, ends = [], [], []
        for block in data:
            chars += block["characters"]
            starts += block["character_start_times_seconds"]
            ends += block["character_end_times_seconds"]
        return chars, starts, ends
    for node in (data, data.get("alignment"), data.get("normalized_alignment")):
        if isinstance(node, dict) and "characters" in node:
            return (node["characters"],
                    node["character_start_times_seconds"],
                    node["character_end_times_seconds"])
    if "words" in data:                      # word-level fallback
        chars, starts, ends = [], [], []
        for w in data["words"]:
            text = w.get("text", "")
            if not text:
                continue
            n = len(text)
            s, e = float(w.get("start", 0.0)), float(w.get("end", 0.0))
            for k, ch in enumerate(text):
                chars.append(ch)
                starts.append(s + (e - s) * k / n)
                ends.append(s + (e - s) * (k + 1) / n)
        return chars, starts, ends
    raise SystemExit("unrecognised timestamps format: " + path)


def audio_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def paper_colour(path: str) -> str:
    arr = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    corners = np.concatenate([arr[:24, :24].reshape(-1, 3), arr[:24, -24:].reshape(-1, 3),
                              arr[-24:, :24].reshape(-1, 3), arr[-24:, -24:].reshape(-1, 3)])
    r, g, b = np.median(corners, axis=0).astype(int)
    return "#%02X%02X%02X" % (r, g, b)


def build(brief_id: str) -> str:
    briefs = json.load(open(os.path.join(ROOT, "briefs", "briefs.json"), encoding="utf-8"))
    common = briefs["common"]
    brief = next(v for v in briefs["videos"] if v["id"] == brief_id)

    assets = os.path.join(ROOT, "assets", brief_id)
    audio = os.path.join(assets, "voice.mp3")
    illus = os.path.join(assets, "illustration.png")
    chars, starts, ends = load_alignment(os.path.join(assets, "timestamps.json"))

    phrases = brief["phrases"]
    spoken = " ".join(p.replace("\n", " ") for p in phrases)
    joined = "".join(chars)
    if joined.strip() != spoken.strip():
        # the provider may normalise punctuation; fall back to offsets in `joined`
        print("note: alignment text differs from the script, using alignment text")

    captions, cursor = [], 0
    for phrase in phrases:
        flat = phrase.replace("\n", " ")
        a = joined.find(flat, cursor)
        if a < 0:                                   # normalised punctuation
            a = joined.find(flat.strip("«».,:?"), cursor)
        if a < 0:
            raise SystemExit("phrase not found in alignment: " + flat[:40])
        b = a + len(flat)
        cursor = b
        captions.append({
            "start": round(float(starts[a]), 2),
            "end": round(float(ends[min(b, len(ends)) - 1]), 2),
            "text": phrase,
        })

    # verse marker lands with the recited verse — phrase index 3 in every brief
    verse_cap = captions[3]
    duration = round(audio_duration(audio) + 0.4, 2)

    spec = {
        "id": brief_id,
        "topic": brief.get("topic", brief_id),
        "duration": duration,
        "output": "out/%s.mp4" % brief_id,
        "audio": "assets/%s/voice.mp3" % brief_id,
        "illustration": "assets/%s/illustration.png" % brief_id,
        "illustration_box": common["illustration_box"],
        "zoom": [1.0, 1.06],
        "caption_y": common["caption_y"],
        "footer": "",
        "palette": {
            "bg": paper_colour(illus),
            "ink": "#3B352C",
            "muted": "#7A7265",
            "faint": "#A79E90",
            "highlight": brief["palette"]["highlight"],
            "gold": "#C9A227",
        },
        "glow_color": brief["palette"]["highlight"],
        "header": {
            "y": common["header_y"],
            "arabic": brief["arabic"],
            "arabic_highlight": brief["arabic_highlight"],
            "arabic_size": 48,
            "highlight_at": round(verse_cap["start"] + 0.25, 2),
            "highlight_duration": 0.5,
            "translation": brief["translation"],
            "translation_size": 21,
            "reference": brief["reference"],
        },
        "captions": captions,
    }
    for cap in spec["captions"]:
        marks = brief.get("highlight", {}).get(cap["text"], [])
        if marks:
            cap["highlight"] = marks

    out = os.path.join(ROOT, "videos", brief_id + ".json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=2)
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: make_spec.py <brief-id>")
    print(build(sys.argv[1]))

#!/usr/bin/env python3
"""Render an Uzbek Islamic reel (9:16, re.mind.ai-style) from a JSON spec.

Pipeline: cream canvas -> static header (Arabic verse + Uzbek translation +
surah reference) -> centred flat illustration with a slow push-in -> narration
subtitles revealed phrase by phrase in sync with the voiceover -> H.264 MP4.

Usage:
    python3 reels/render_reel.py reels/videos/01_yolgizlik.json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))

W, H = 720, 1280
FPS = 30

INTER = "/usr/share/fonts/opentype/inter/Inter-{}.otf"
AMIRI = os.path.join(ROOT, "fonts", "Amiri-{}.ttf")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def hex2rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def inter(style: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(INTER.format(style), size)


def amiri(style: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(AMIRI.format(style), size)


def ease_out(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return 1.0 - (1.0 - t) ** 3


def ease_in_out(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return 3 * t * t - 2 * t * t * t


def ar_len(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> float:
    return draw.textlength(text, font=font, direction="rtl", language="ar")


def rounded(draw: ImageDraw.ImageDraw, box, radius: int, fill) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


# --------------------------------------------------------------------------- #
# spec
# --------------------------------------------------------------------------- #
@dataclass
class Palette:
    bg: tuple[int, int, int]
    ink: tuple[int, int, int]
    muted: tuple[int, int, int]
    faint: tuple[int, int, int]
    highlight: tuple[int, int, int]
    gold: tuple[int, int, int]


def load_palette(spec: dict) -> Palette:
    p = spec.get("palette", {})
    return Palette(
        bg=hex2rgb(p.get("bg", "#F5EBDB")),
        ink=hex2rgb(p.get("ink", "#3B352C")),
        muted=hex2rgb(p.get("muted", "#7A7265")),
        faint=hex2rgb(p.get("faint", "#A79E90")),
        highlight=hex2rgb(p.get("highlight", "#F2D98B")),
        gold=hex2rgb(p.get("gold", "#C9A227")),
    )


# --------------------------------------------------------------------------- #
# layers
# --------------------------------------------------------------------------- #
def make_background(pal: Palette) -> Image.Image:
    """Flat cream paper. Grain is added last, over the whole frame."""
    return Image.new("RGB", (W, H), pal.bg)


def make_grain() -> Image.Image:
    """Soft monochrome noise, blended over the finished frame so the
    illustration and the page share exactly one paper texture."""
    noise = Image.effect_noise((W, H), 11).convert("L")
    noise = noise.filter(ImageFilter.GaussianBlur(0.4))
    return Image.merge("RGB", (noise, noise, noise))


def make_header(spec: dict, pal: Palette, with_highlight: bool) -> Image.Image:
    """Arabic verse + ornaments + Uzbek translation + surah reference."""
    head = spec["header"]
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = W // 2

    verse = head["arabic"]
    keyword = head.get("arabic_highlight", "")
    f_verse = amiri("Bold", head.get("arabic_size", 50))
    f_orn = amiri("Regular", head.get("arabic_size", 50) + 6)

    y_verse = head.get("y", 150)
    total = ar_len(d, verse, f_verse)
    left = cx - total / 2

    # highlight sits behind the final (logical) word, which renders left-most
    if with_highlight and keyword:
        kw = ar_len(d, keyword, f_verse)
        rounded(
            d,
            (left - 9, y_verse - 30, left + kw + 9, y_verse + 24),
            10,
            pal.highlight + (235,),
        )

    d.text(
        (cx, y_verse),
        verse,
        font=f_verse,
        fill=pal.ink + (255,),
        anchor="mm",
        direction="rtl",
        language="ar",
    )

    # ornamental verse brackets
    gap = total / 2 + 26
    for ch, x in (("﴿", cx - gap), ("﴾", cx + gap)):
        d.text((x, y_verse), ch, font=f_orn, fill=pal.faint + (255,), anchor="mm")

    # Uzbek translation
    f_tr = inter("Italic", head.get("translation_size", 23))
    d.text(
        (cx, y_verse + 52),
        head["translation"],
        font=f_tr,
        fill=pal.muted + (255,),
        anchor="mm",
    )

    # surah reference
    f_ref = inter("Medium", 16)
    d.text(
        (cx, y_verse + 84),
        head["reference"].upper(),
        font=f_ref,
        fill=pal.faint + (255,),
        anchor="mm",
    )
    return layer


def make_illustration(spec: dict, pal: Palette) -> Image.Image:
    """Lift the drawing off its own paper so it sits directly on the page.

    The generated art comes on a cream field with a soft vignette. Pixels close
    to that field become transparent on a soft ramp, which drops the vignette
    with it; what is left is the line work, trimmed and centred in the box.
    """
    import numpy as np

    src = Image.open(os.path.join(ROOT, spec["illustration"])).convert("RGB")
    arr = np.asarray(src).astype(np.int16)

    # the source's own paper colour, from its corners
    corners = np.concatenate(
        [arr[:24, :24].reshape(-1, 3), arr[:24, -24:].reshape(-1, 3),
         arr[-24:, :24].reshape(-1, 3), arr[-24:, -24:].reshape(-1, 3)]
    )
    paper = np.median(corners, axis=0)

    delta = np.abs(arr - paper).max(axis=2).astype(np.float32)
    lo, hi = spec.get("cutout_ramp", [12.0, 28.0])
    alpha = np.clip((delta - lo) / (hi - lo), 0.0, 1.0)

    cut = Image.fromarray(np.dstack([np.asarray(src), (alpha * 255).astype(np.uint8)]), "RGBA")
    cut.putalpha(cut.getchannel("A").filter(ImageFilter.GaussianBlur(0.6)))

    bbox = cut.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    if bbox:
        cut = cut.crop(bbox)

    box = spec.get("illustration_box", [40, 300, 680, 940])
    bw, bh = box[2] - box[0], box[3] - box[1]
    k = min(bw / cut.width, bh / cut.height)
    cut = cut.resize((max(1, int(cut.width * k)), max(1, int(cut.height * k))), Image.LANCZOS)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.paste(cut, (box[0] + (bw - cut.width) // 2, box[1] + (bh - cut.height) // 2), cut)
    return layer


def make_caption(line: dict, pal: Palette, spec: dict) -> Image.Image:
    """One narration phrase, centred, with optional yellow keyword marker."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = W // 2
    y0 = spec.get("caption_y", 1046)

    size = line.get("size", 34)
    f = inter("SemiBold", size)
    f_ar = amiri("Regular", size + 6)
    lead = size + 14
    marks = set(line.get("highlight", []))

    rows = line["text"].split("\n")
    block_h = lead * len(rows)
    y = y0 - block_h / 2 + lead / 2

    for row in rows:
        if line.get("script") == "ar":
            d.text(
                (cx, y),
                row,
                font=f_ar,
                fill=pal.ink + (255,),
                anchor="mm",
                direction="rtl",
                language="ar",
            )
            y += lead
            continue

        words = row.split(" ")
        advances = [d.textlength(w + " ", font=f) for w in words]
        inks = [d.textlength(w, font=f) for w in words]
        x0 = cx - sum(advances) / 2

        flags = [w.strip("\u00ab\u00bb.,:;\u2014?!\u2026") in marks for w in words]
        xs, x = [], x0
        for a in advances:
            xs.append(x)
            x += a

        # one marker stroke per run of adjacent highlighted words
        i = 0
        while i < len(words):
            if not flags[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(words) and flags[j + 1]:
                j += 1
            rounded(
                d,
                (xs[i] - 6, y - size * 0.64, xs[j] + inks[j] + 6, y + size * 0.54),
                8,
                pal.highlight + (225,),
            )
            i = j + 1

        for word, x in zip(words, xs):
            d.text((x, y), word, font=f, fill=pal.ink + (255,), anchor="lm")
        y += lead
    return layer


def make_footer(spec: dict, pal: Palette) -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    text = spec.get("footer", "").strip()
    if not text:
        return layer
    d = ImageDraw.Draw(layer)
    d.text(
        (W // 2, 1196),
        text,
        font=inter("Medium", 17),
        fill=pal.faint + (150,),
        anchor="mm",
    )
    return layer


# --------------------------------------------------------------------------- #
# compositing
# --------------------------------------------------------------------------- #
def fade_alpha(layer: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 0.999:
        return layer
    out = layer.copy()
    a = out.getchannel("A").point(lambda v: int(v * alpha))
    out.putalpha(a)
    return out


def segment_alpha(t: float, start: float, end: float, fade: float = 0.22) -> float:
    if t < start - fade or t > end + fade:
        return 0.0
    if t < start:
        return ease_out((t - (start - fade)) / fade)
    if t > end:
        return 1.0 - ease_out((t - end) / fade)
    return 1.0


def render(spec_path: str) -> str:
    with open(spec_path, encoding="utf-8") as fh:
        spec = json.load(fh)

    pal = load_palette(spec)
    duration = float(spec["duration"])
    frames = int(round(duration * FPS))

    bg = make_background(pal)
    grain = make_grain()
    grain_mix = float(spec.get("grain", 0.03))
    blank = Image.blend(bg, grain, grain_mix) if grain_mix > 0 else bg.copy()
    header_plain = make_header(spec, pal, with_highlight=False)
    header_hl = make_header(spec, pal, with_highlight=True)
    illu = make_illustration(spec, pal)
    footer = make_footer(spec, pal)
    captions = [(c, make_caption(c, pal, spec)) for c in spec["captions"]]

    box = spec.get("illustration_box", [40, 300, 680, 940])
    zoom_from = spec.get("zoom", [1.0, 1.055])[0]
    zoom_to = spec.get("zoom", [1.0, 1.055])[1]
    hl_at = spec["header"].get("highlight_at", 6.3)
    hl_dur = spec["header"].get("highlight_duration", 0.5)

    out_path = os.path.join(ROOT, spec["output"])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    audio = os.path.join(ROOT, spec["audio"])

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", audio,
        "-filter_complex", f"[1:a]apad,atrim=0:{duration},afade=t=out:st={duration-0.45}:d=0.45[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-profile:v", "high", "-preset", "slow", "-crf", "19",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart", "-shortest",
        out_path,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None

    bw, bh = box[2] - box[0], box[3] - box[1]
    for i in range(frames):
        t = i / FPS
        frame = bg.copy()

        # illustration: slow push-in, fades up first
        k = zoom_from + (zoom_to - zoom_from) * ease_in_out(t / duration)
        nw, nh = int(bw * k), int(bh * k)
        scaled = illu.crop((box[0], box[1], box[2], box[3])).resize((nw, nh), Image.LANCZOS)
        shifted = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        shifted.paste(scaled, (box[0] - (nw - bw) // 2, box[1] - (nh - bh) // 2))
        frame.paste(
            fade_alpha(shifted, ease_out(t / 0.9)).convert("RGB"),
            (0, 0),
            fade_alpha(shifted, ease_out(t / 0.9)).getchannel("A"),
        )

        # header
        head_a = ease_out((t - 0.15) / 0.9)
        if head_a > 0:
            layer = header_hl if t >= hl_at + hl_dur else header_plain
            if hl_at <= t < hl_at + hl_dur:
                mix = ease_out((t - hl_at) / hl_dur)
                layer = Image.alpha_composite(header_plain, fade_alpha(header_hl, mix))
            layer = fade_alpha(layer, head_a)
            frame.paste(layer.convert("RGB"), (0, 0), layer.getchannel("A"))

        # footer
        f_a = ease_out((t - 0.6) / 1.2)
        if f_a > 0:
            layer = fade_alpha(footer, f_a)
            frame.paste(layer.convert("RGB"), (0, 0), layer.getchannel("A"))

        # captions
        for cap, layer in captions:
            a = segment_alpha(t, cap["start"], cap["end"])
            if a <= 0.003:
                continue
            faded = fade_alpha(layer, a)
            frame.paste(faded.convert("RGB"), (0, 0), faded.getchannel("A"))

        # one shared paper grain over everything
        if grain_mix > 0:
            frame = Image.blend(frame, grain, grain_mix)

        # open from / close to cream
        if t < 0.35:
            frame = Image.blend(blank, frame, ease_out(t / 0.35))
        if t > duration - 0.5:
            frame = Image.blend(frame, blank, ease_in_out((t - (duration - 0.5)) / 0.5))

        proc.stdin.write(frame.tobytes())

    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg failed")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: render_reel.py <spec.json>")
    print(render(sys.argv[1]))

#!/usr/bin/env python3
"""Render an Uzbek Islamic reel (9:16, re.mind.ai-style) from a JSON spec.

The illustration is not treated as a flat picture. It is taken apart by colour
into a base plate plus sprites (moon, stars, lit windows), so the scene can
actually move: the drawing is laid down stroke-wise, the moon drifts, stars
twinkle, windows switch on and off through the night, and the camera pushes in
with the sky parallaxing against the room. Text behaves the same way -- the
verse is written on right-to-left, the marker stroke is swiped across the
keyword, and captions arrive word by word in time with the voiceover.

Usage:
    python3 reels/render_reel.py reels/videos/01_yolgizlik.json
"""

from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy import ndimage

ROOT = os.path.dirname(os.path.abspath(__file__))

DESIGN_W, DESIGN_H = 720, 1280     # the layout is authored at this size
SC = 1.0                           # output scale; 1.5 gives a 1080x1920 master
W, H = DESIGN_W, DESIGN_H
FPS = 30


def set_scale(scale: float) -> None:
    """Scale the whole layout. Everything geometric goes through px()."""
    global SC, W, H
    SC = float(scale)
    W, H = int(round(DESIGN_W * SC)), int(round(DESIGN_H * SC))


def px(v: float) -> float:
    """A design-space length in output pixels."""
    return v * SC

INTER = "/usr/share/fonts/opentype/inter/Inter-{}.otf"
AMIRI = os.path.join(ROOT, "fonts", "Amiri-{}.ttf")


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def hex2rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def inter(style: str, size: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(INTER.format(style), max(1, int(round(px(size)))))


def amiri(style: str, size: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(AMIRI.format(style), max(1, int(round(px(size)))))


def clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def ease_out(t: float) -> float:
    t = clamp01(t)
    return 1.0 - (1.0 - t) ** 3


def ease_in_out(t: float) -> float:
    t = clamp01(t)
    return 3 * t * t - 2 * t * t * t


def rounded(draw: ImageDraw.ImageDraw, box, radius: int, fill) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def scale_alpha(layer: Image.Image, alpha: float) -> Image.Image:
    """Return a copy of an RGBA layer with its alpha scaled."""
    if alpha >= 0.999:
        return layer
    out = layer.copy()
    out.putalpha(out.getchannel("A").point(lambda v: int(v * alpha)))
    return out


def paste_rgba(dst: Image.Image, layer: Image.Image, pos=(0, 0)) -> None:
    dst.paste(layer.convert("RGB"), pos, layer.getchannel("A"))


# --------------------------------------------------------------------------- #
# palette
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
# illustration: cut out, take apart, animate
# --------------------------------------------------------------------------- #
@dataclass
class Sprite:
    img: Image.Image          # RGBA patch
    x: int                    # position in plate coordinates
    y: int
    kind: str                 # moon | star | light
    phase: float = 0.0
    schedule: list = field(default_factory=list)   # for lights: (t_off, t_on)


@dataclass
class Scene:
    plate: Image.Image        # base drawing, sprites removed
    sprites: list
    glow: Image.Image         # warm halo over the window (may be None)
    sky_box: tuple
    size: tuple


def cutout(path: str, ramp) -> Image.Image:
    """Lift the drawing off the cream field it was generated on."""
    src = Image.open(path).convert("RGB")
    arr = np.asarray(src).astype(np.int16)
    corners = np.concatenate(
        [arr[:24, :24].reshape(-1, 3), arr[:24, -24:].reshape(-1, 3),
         arr[-24:, :24].reshape(-1, 3), arr[-24:, -24:].reshape(-1, 3)]
    )
    paper = np.median(corners, axis=0)
    delta = np.abs(arr - paper).max(axis=2).astype(np.float32)
    lo, hi = ramp
    alpha = np.clip((delta - lo) / (hi - lo), 0.0, 1.0)
    out = Image.fromarray(np.dstack([np.asarray(src), (alpha * 255).astype(np.uint8)]), "RGBA")
    out.putalpha(out.getchannel("A").filter(ImageFilter.GaussianBlur(0.6)))
    bbox = out.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    return out.crop(bbox) if bbox else out


def build_scene(spec: dict) -> Scene:
    """Split the drawing into a plate plus animatable light sprites."""
    art = cutout(os.path.join(ROOT, spec["illustration"]), spec.get("cutout_ramp", [12.0, 28.0]))

    box = [px(v) for v in spec.get("illustration_box", [60, 310, 660, 950])]
    bw, bh = box[2] - box[0], box[3] - box[1]
    over = spec.get("zoom", [1.0, 1.06])[1]          # render at full push-in size
    k = min(bw * over / art.width, bh * over / art.height)
    art = art.resize((max(1, int(art.width * k)), max(1, int(art.height * k))), Image.LANCZOS)

    rgb = np.asarray(art.convert("RGB")).astype(np.int16)
    alpha = np.asarray(art.getchannel("A"))
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b

    sky = (b > r + 10) & (lum < 150) & (alpha > 120)
    warm = (r > 190) & (g > 150) & (b < 170) & ((r - b) > 55) & (alpha > 120)

    sky_box = (0, 0, art.width, art.height)
    if sky.any():
        ys, xs = np.where(sky)
        sky_box = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))

    plate_px = np.array(art)
    sprites = []

    labels, count = ndimage.label(warm)
    blobs = ndimage.find_objects(labels)
    areas = [int((labels[sl] == i + 1).sum()) for i, sl in enumerate(blobs)]
    # thresholds are relative to the plate, so they survive any output size
    plate_area = art.width * art.height
    min_area = max(10, int(plate_area * 3e-5))
    ranked = sorted(areas, reverse=True)
    runner_up = ranked[1] if len(ranked) > 1 else 0
    moon_idx = int(np.argmax(areas)) if areas and ranked[0] > 2.5 * runner_up else -1

    rng = random.Random(spec.get("seed", 7))

    for i, sl in enumerate(blobs):
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        h, w = y1 - y0, x1 - x0
        area = areas[i]
        if area < min_area:
            continue

        if i == moon_idx:
            kind = "moon"
        elif 0.75 < w / max(h, 1) < 1.35:
            kind = "star"
        else:
            kind = "light"

        pad = 6
        px0, py0 = max(0, x0 - pad), max(0, y0 - pad)
        px1, py1 = min(art.width, x1 + pad), min(art.height, y1 + pad)

        blob = (labels[py0:py1, px0:px1] == i + 1)
        patch = np.array(art)[py0:py1, px0:px1].copy()
        patch_a = patch[..., 3].astype(np.float32)
        patch_a *= ndimage.gaussian_filter(blob.astype(np.float32), 1.1)
        patch[..., 3] = np.clip(patch_a, 0, 255).astype(np.uint8)

        # heal the plate: fill the blob with the colour ringing it
        ring = ndimage.binary_dilation(blob, iterations=4) & ~blob
        region = plate_px[py0:py1, px0:px1]
        if ring.any():
            fill = np.median(region[ring], axis=0).astype(np.uint8)
            region[blob] = fill
            plate_px[py0:py1, px0:px1] = region

        sprite = Sprite(
            img=Image.fromarray(patch, "RGBA"),
            x=px0,
            y=py0,
            kind=kind,
            phase=rng.random(),
        )
        if kind == "light":
            # most windows stay lit; a few go dark and come back during the clip
            if rng.random() < 0.5:
                off = rng.uniform(1.8, float(spec["duration"]) - 5.5)
                sprite.schedule = [(off, off + rng.uniform(1.6, 3.4))]
        sprites.append(sprite)

    plate = Image.fromarray(plate_px, "RGBA")

    # warm halo over the window, for the breathing night glow
    glow = None
    if sky.any():
        gx0, gy0, gx1, gy1 = sky_box
        glow = Image.new("RGBA", art.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse(
            (gx0 - px(40), gy0 - px(40), gx1 + px(40), gy1 + px(40)),
            fill=hex2rgb(spec.get("glow_color", "#E8C675")) + (70,),
        )
        glow = glow.filter(ImageFilter.GaussianBlur(px(38)))

    return Scene(plate=plate, sprites=sprites, glow=glow, sky_box=sky_box, size=art.size)


def sprite_state(sp: Sprite, t: float):
    """alpha, dx, dy for one sprite at time t."""
    if sp.kind == "star":
        tw = math.sin(2 * math.pi * (t / (2.1 + 1.4 * sp.phase) + sp.phase))
        return 0.22 + 0.78 * clamp01(0.5 + 0.5 * tw), 0, 0
    if sp.kind == "moon":
        bob = math.sin(2 * math.pi * (t / 11.0 + sp.phase)) * px(3.0)
        return 1.0, 0, int(round(-bob))
    a = 1.0
    for off, on in sp.schedule:
        if off <= t < on:
            a = 1.0 - ease_in_out(min((t - off) / 0.35, 1.0))
        elif on <= t < on + 0.5:
            a = ease_in_out((t - on) / 0.5)
    flicker = 1.0 + 0.04 * math.sin(2 * math.pi * (t / 1.7 + sp.phase))
    return clamp01(a * flicker), 0, 0


def render_scene(scene: Scene, t: float, reveal: float, parallax: float,
                 glow_amt: float) -> Image.Image:
    """One frame of the illustration, before the camera move."""
    # the glow sits behind the drawing, so it spills onto the wall around the
    # window instead of fogging the night sky
    if scene.glow is not None and glow_amt > 0:
        frame = Image.alpha_composite(scale_alpha(scene.glow, glow_amt), scene.plate)
    else:
        frame = scene.plate.copy()

    cx = (scene.sky_box[0] + scene.sky_box[2]) / 2
    cy = (scene.sky_box[1] + scene.sky_box[3]) / 2

    for sp in scene.sprites:
        a, dx, dy = sprite_state(sp, t)
        if a <= 0.01:
            continue
        # sky objects sit deeper, so they drift against the room as we push in
        ox = int(round(sp.x + dx + (sp.x + sp.img.width / 2 - cx) * parallax))
        oy = int(round(sp.y + dy + (sp.y + sp.img.height / 2 - cy) * parallax))
        patch = scale_alpha(sp.img, a)
        frame.paste(patch.convert("RGB"), (ox, oy), patch.getchannel("A"))

    if reveal < 0.999:
        h, w = frame.height, frame.width
        edge = reveal * (h + px(150)) - px(75)
        rows = np.clip((edge - np.arange(h, dtype=np.float32)[:, None]) / px(95.0), 0.0, 1.0)
        # a slight slant, so the drawing reads as being laid down by hand
        mask = np.clip(rows - np.linspace(0.0, 0.14, w, dtype=np.float32)[None, :], 0.0, 1.0)
        a = (np.asarray(frame.getchannel("A")).astype(np.float32) * mask).astype(np.uint8)
        frame.putalpha(Image.fromarray(a, "L"))

    return frame


# --------------------------------------------------------------------------- #
# text layers
# --------------------------------------------------------------------------- #
def ink_span(layer: Image.Image):
    a = np.asarray(layer.getchannel("A"))
    cols = np.where((a > 16).any(axis=0))[0]
    return (int(cols.min()), int(cols.max())) if len(cols) else (0, 0)


def wipe(layer: Image.Image, frac: float, direction: str, feather: float = 46.0) -> Image.Image:
    """Reveal a layer across its own ink, left-to-right or right-to-left."""
    if frac >= 0.999:
        return layer
    if frac <= 0.001:
        return Image.new("RGBA", layer.size, (0, 0, 0, 0))
    feather = px(feather)
    x0, x1 = ink_span(layer)
    span = (x1 - x0) + 2 * feather
    xs = np.arange(layer.width, dtype=np.float32)
    if direction == "rtl":
        edge = (x1 + feather) - frac * span
        mask = np.clip((xs - edge) / feather, 0.0, 1.0)
    else:
        edge = (x0 - feather) + frac * span
        mask = np.clip((edge - xs) / feather, 0.0, 1.0)
    out = layer.copy()
    a = (np.asarray(out.getchannel("A")).astype(np.float32) * mask[None, :]).astype(np.uint8)
    out.putalpha(Image.fromarray(a, "L"))
    return out


def make_header(spec: dict, pal: Palette):
    head = spec["header"]
    cx = W // 2
    y_verse = px(head.get("y", 152))
    size = head.get("arabic_size", 50)
    f_verse = amiri("Bold", size)
    f_orn = amiri("Regular", size + 6)

    probe = ImageDraw.Draw(Image.new("RGBA", (W, H)))
    verse = head["arabic"]
    total = probe.textlength(verse, font=f_verse, direction="rtl", language="ar")
    left = cx - total / 2

    marker = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    kw = head.get("arabic_highlight", "")
    if kw and kw in verse:
        # words that follow the keyword logically are drawn to its left, so the
        # keyword's left edge is the line's left edge plus the width of that tail
        tail = verse[verse.index(kw) + len(kw):]
        tail_w = probe.textlength(tail, font=f_verse, direction="rtl", language="ar")
        kwl = probe.textlength(kw, font=f_verse, direction="rtl", language="ar")
        x_a = left + tail_w
        rounded(
            ImageDraw.Draw(marker),
            (x_a - px(9), y_verse - px(30), x_a + kwl + px(9), y_verse + px(24)),
            px(10),
            pal.highlight + (235,),
        )

    text = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(text).text(
        (cx, y_verse), verse, font=f_verse, fill=pal.ink + (255,),
        anchor="mm", direction="rtl", language="ar",
    )

    orn = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    do = ImageDraw.Draw(orn)
    gap = total / 2 + px(26)
    for ch, x in (("﴿", cx - gap), ("﴾", cx + gap)):
        do.text((x, y_verse), ch, font=f_orn, fill=pal.faint + (255,), anchor="mm")

    trans = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(trans).text(
        (cx, y_verse + px(52)), head["translation"],
        font=inter("Italic", head.get("translation_size", 22)),
        fill=pal.muted + (255,), anchor="mm",
    )

    ref = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(ref).text(
        (cx, y_verse + px(84)), head["reference"].upper(),
        font=inter("Medium", 16), fill=pal.faint + (255,), anchor="mm",
    )

    return {"marker": marker, "verse": text, "orn": orn, "trans": trans, "ref": ref}


def draw_caption(frame: Image.Image, line: dict, pal: Palette, spec: dict,
                 t: float, alpha: float) -> None:
    """Captions arrive word by word, each one rising into place."""
    size = line.get("size", 34)
    f = inter("SemiBold", size)
    f_ar = amiri("Regular", size + 6)
    lead = px(size + 14)
    y0 = px(spec.get("caption_y", 1046))
    marks = set(line.get("highlight", []))
    stagger = line.get("stagger", 0.055)

    rows = line["text"].split("\n")
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = W // 2
    y = y0 - lead * len(rows) / 2 + lead / 2

    index = 0
    for row in rows:
        if line.get("script") == "ar":
            d.text((cx, y), row, font=f_ar, fill=pal.ink + (255,),
                   anchor="mm", direction="rtl", language="ar")
            y += lead
            continue

        words = row.split(" ")
        advances = [d.textlength(w + " ", font=f) for w in words]
        inks = [d.textlength(w, font=f) for w in words]
        xs, x = [], cx - sum(advances) / 2
        for adv in advances:
            xs.append(x)
            x += adv

        flags = [w.strip("«».,:;—?!…") in marks for w in words]
        appear = [ease_out((t - line["start"] - n * stagger) / 0.26)
                  for n in range(index, index + len(words))]

        # marker strokes swipe in under their run of words
        i = 0
        while i < len(words):
            if not flags[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(words) and flags[j + 1]:
                j += 1
            swipe = ease_out((t - line["start"] - (index + j) * stagger - 0.16) / 0.30)
            if swipe > 0.01:
                x_a, x_b = xs[i] - px(6), xs[j] + inks[j] + px(6)
                rounded(d, (x_a, y - px(size * 0.64), x_a + (x_b - x_a) * swipe,
                            y + px(size * 0.54)), px(8), pal.highlight + (225,))
            i = j + 1

        for n, (word, x) in enumerate(zip(words, xs)):
            a = appear[n]
            if a <= 0.01:
                continue
            rise = (1.0 - a) * px(9)
            d.text((x, y + rise), word, font=f, fill=pal.ink + (int(255 * a),), anchor="lm")
        index += len(words)
        y += lead

    paste_rgba(frame, scale_alpha(layer, alpha))


def make_footer(spec: dict, pal: Palette) -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    text = spec.get("footer", "").strip()
    if text:
        ImageDraw.Draw(layer).text(
            (W // 2, px(1196)), text, font=inter("Medium", 17),
            fill=pal.faint + (150,), anchor="mm",
        )
    return layer


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #
def segment_alpha(t: float, start: float, end: float, fade: float = 0.22) -> float:
    if t < start or t > end + fade:
        return 0.0
    if t > end:
        return 1.0 - ease_out((t - end) / fade)
    return 1.0


def render(spec_path: str, scale: float = 1.0, crf: int = 19, suffix: str = "") -> str:
    set_scale(scale)
    with open(spec_path, encoding="utf-8") as fh:
        spec = json.load(fh)

    pal = load_palette(spec)
    duration = float(spec["duration"])
    frames = int(round(duration * FPS))

    bg = Image.new("RGB", (W, H), pal.bg)
    noise = Image.effect_noise((W, H), 11).convert("L").filter(ImageFilter.GaussianBlur(0.4))
    grain = Image.merge("RGB", (noise, noise, noise))
    grain_mix = float(spec.get("grain", 0.03))
    blank = Image.blend(bg, grain, grain_mix) if grain_mix > 0 else bg.copy()

    scene = build_scene(spec)
    header = make_header(spec, pal)
    footer = make_footer(spec, pal)

    box = [int(round(px(v))) for v in spec.get("illustration_box", [60, 310, 660, 950])]
    bw, bh = box[2] - box[0], box[3] - box[1]
    z0, z1 = spec.get("zoom", [1.0, 1.06])
    hl_at = spec["header"].get("highlight_at", 6.3)
    hl_dur = spec["header"].get("highlight_duration", 0.5)
    reveal_dur = float(spec.get("reveal_duration", 1.5))

    out_path = os.path.join(ROOT, spec["output"])
    if suffix:
        stem, ext = os.path.splitext(out_path)
        out_path = stem + suffix + ext
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    audio = os.path.join(ROOT, spec["audio"])

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H), "-r", str(FPS), "-i", "-",
        "-i", audio,
        "-filter_complex",
        "[1:a]apad,atrim=0:%s,afade=t=out:st=%s:d=0.45[a]" % (duration, duration - 0.45),
        "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-profile:v", "high", "-preset", "slow", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart", "-shortest",
        out_path,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    for i in range(frames):
        t = i / FPS
        frame = bg.copy()

        # --- illustration -------------------------------------------------- #
        reveal = ease_in_out(t / reveal_dur)
        glow_amt = max(ease_out((t - 0.8) / 1.6), 0.0) * (0.78 + 0.22 * math.sin(2 * math.pi * t / 6.5))
        parallax = -0.05 * ease_in_out(t / duration)
        art = render_scene(scene, t, reveal, parallax, max(glow_amt, 0.0))

        k = z0 + (z1 - z0) * ease_in_out(t / duration)
        tw, th = max(1, int(bw * k)), max(1, int(bh * k))
        drift = math.sin(2 * math.pi * t / 17.0) * px(3.0)
        art = art.resize((tw, th), Image.LANCZOS)
        paste_rgba(frame, art,
                   (box[0] + (bw - tw) // 2 + int(round(drift)), box[1] + (bh - th) // 2))

        # --- header -------------------------------------------------------- #
        verse_w = ease_in_out((t - 0.25) / 1.15)
        if verse_w > 0.001:
            if t >= hl_at:
                paste_rgba(frame, wipe(header["marker"], ease_out((t - hl_at) / hl_dur), "ltr", 28.0))
            paste_rgba(frame, wipe(header["verse"], verse_w, "rtl"))
            a_orn = ease_out((t - 1.0) / 0.7)
            if a_orn > 0.004:
                paste_rgba(frame, scale_alpha(header["orn"], a_orn))
        a_tr = ease_out((t - 1.15) / 0.8)
        if a_tr > 0.004:
            paste_rgba(frame, scale_alpha(header["trans"], a_tr))
        a_rf = ease_out((t - 1.45) / 0.8)
        if a_rf > 0.004:
            paste_rgba(frame, scale_alpha(header["ref"], a_rf))

        a_ft = ease_out((t - 1.8) / 1.2)
        if a_ft > 0.004:
            paste_rgba(frame, scale_alpha(footer, a_ft))

        # --- captions ------------------------------------------------------ #
        for cap in spec["captions"]:
            a = segment_alpha(t, cap["start"], cap["end"])
            if a > 0.004:
                draw_caption(frame, cap, pal, spec, t, a)

        # --- paper + open/close -------------------------------------------- #
        if grain_mix > 0:
            frame = Image.blend(frame, grain, grain_mix)
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
    import argparse

    ap = argparse.ArgumentParser(description="Render a reel from a JSON spec.")
    ap.add_argument("spec")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="1.0 = 720x1280 (default), 1.5 = 1080x1920 master")
    ap.add_argument("--crf", type=int, default=19, help="x264 quality, lower is better")
    ap.add_argument("--suffix", default="", help="appended to the output file name")
    args = ap.parse_args()
    print(render(args.spec, scale=args.scale, crf=args.crf, suffix=args.suffix))

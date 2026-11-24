#!/usr/bin/env python3
"""Render the pinned "about me" carousel: 1080x1350 slides in the reel palette.

    python3 reels/carousel/render_carousel.py
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from render_reel import cutout, hex2rgb          # noqa: E402

INTER = "/usr/share/fonts/opentype/inter/Inter-{}.otf"
EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"

INK = (59, 53, 44)
MUTED = (122, 114, 101)
FAINT = (167, 158, 144)


def inter(style: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(INTER.format(style), size)


def wrapped(draw, text, font, x, y, fill, lead, anchor="mm"):
    for line in text.split("\n"):
        draw.text((x, y), line, font=font, fill=fill, anchor=anchor)
        y += lead
    return y


def render(slide: dict, size, out_dir: str, total: int) -> str:
    W, H = size
    bg = hex2rgb(slide["bg"])
    accent = hex2rgb(slide["accent"])

    page = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(page)
    cx = W // 2

    # headline
    f_head = inter("SemiBold", 62)
    y = 150
    y_after = wrapped(d, slide["headline"], f_head, cx, y, INK, 76)

    # body
    f_body = inter("Regular", 30)
    body_end = wrapped(d, slide["body"], f_body, cx, y_after + 18, MUTED, 44)

    # illustration, lifted off its generated paper and centred in what is left
    art = cutout(os.path.join(HERE, "assets", slide["illustration"]), [12.0, 28.0])
    band_top = body_end + 16
    band_bot = H - (252 if slide.get("cta") else 128)
    box_w, box_h = 800, band_bot - band_top
    k = min(box_w / art.width, box_h / art.height)
    art = art.resize((int(art.width * k), int(art.height * k)), Image.LANCZOS)
    top = band_top + (box_h - art.height) // 2
    page.paste(art.convert("RGB"), (cx - art.width // 2, top), art.getchannel("A"))

    # call to action chips on the last slide
    if slide.get("cta"):
        f_chip = inter("SemiBold", 30)
        chips = slide["cta"]
        widths = [d.textlength(c, font=f_chip) + 54 for c in chips]
        gap = 18
        x = cx - (sum(widths) + gap * (len(chips) - 1)) / 2
        y_chip = H - 196
        for c, w in zip(chips, widths):
            d.rounded_rectangle((x, y_chip - 30, x + w, y_chip + 30), radius=30, fill=accent)
            d.text((x + w / 2, y_chip), c, font=f_chip, fill=INK, anchor="mm")
            x += w + gap

    if slide.get("footer"):
        d.text((cx, H - 112), slide["footer"], font=inter("Medium", 28),
               fill=MUTED, anchor="mm")

    # slide counter
    d.text((W - 72, H - 64), "%d/%d" % (slide["n"], total), font=inter("Medium", 26),
           fill=FAINT, anchor="rm")

    # shared paper grain
    noise = Image.effect_noise((W, H), 11).convert("L").filter(ImageFilter.GaussianBlur(0.4))
    page = Image.blend(page, Image.merge("RGB", (noise, noise, noise)), 0.028)

    out = os.path.join(out_dir, slide["file"])
    page.save(out)
    return out


def main() -> None:
    spec = json.load(open(os.path.join(HERE, "slides.json"), encoding="utf-8"))
    out_dir = os.path.join(HERE, "out")
    os.makedirs(out_dir, exist_ok=True)
    total = len(spec["slides"])
    for slide in spec["slides"]:
        print(render(slide, spec["size"], out_dir, total))


if __name__ == "__main__":
    main()

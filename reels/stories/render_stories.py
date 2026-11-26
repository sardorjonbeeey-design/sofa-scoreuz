#!/usr/bin/env python3
"""Render Instagram stories (1080x1920) in the Sakinat visual language.

Everything sits inside the story safe area: the top 260 px (profile row) and
the bottom 300 px (reply bar) are left clear, and slides that expect a poll or
countdown sticker keep an empty band for it.

    python3 reels/stories/render_stories.py
"""

from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from render_reel import cutout, hex2rgb          # noqa: E402

INTER = "/usr/share/fonts/opentype/inter/Inter-{}.otf"
AMIRI = os.path.join(os.path.dirname(HERE), "fonts", "Amiri-{}.ttf")

INK = (59, 53, 44)
MUTED = (122, 114, 101)
FAINT = (167, 158, 144)

SAFE_TOP = 260
SAFE_BOTTOM = 300


def inter(style: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(INTER.format(style), size)


def amiri(style: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(AMIRI.format(style), size)


def lines(draw, text, font, x, y, fill, lead, **kw):
    for line in text.split("\n"):
        draw.text((x, y), line, font=font, fill=fill, anchor="mm", **kw)
        y += lead
    return y


def render(st: dict, size, out_dir: str) -> str:
    W, H = size
    page = Image.new("RGB", (W, H), hex2rgb(st["bg"]))
    d = ImageDraw.Draw(page)
    cx = W // 2
    y = SAFE_TOP + 60

    if not st.get("illustration"):
        # nothing to fill the lower half, so centre the type block instead
        block = (210 if st.get("word") else 0) + (150 if st.get("arabic") else 0)
        block += 50 + (st["headline"].count("\n") + 1) * 92
        block += 20 + (st["body"].count("\n") + 1) * 52
        band = 300 if st.get("sticker_band") else 170
        free = (H - SAFE_BOTTOM - band) - SAFE_TOP
        y = SAFE_TOP + max(60, (free - block) // 2)

    # the brand word, on the launch story
    if st.get("word"):
        d.text((cx, y + 70), st["word"], font=amiri("Bold", 150), fill=INK,
               anchor="mm", direction="rtl", language="ar")
        y += 210

    # the verse, on a verse story
    if st.get("arabic"):
        d.text((cx, y + 50), st["arabic"], font=amiri("Bold", 62), fill=INK,
               anchor="mm", direction="rtl", language="ar")
        y += 150

    y = lines(d, st["headline"], inter("SemiBold", 72), cx, y + 50, INK, 92)
    y = lines(d, st["body"], inter("Regular", 36), cx, y + 20, MUTED, 52)

    # illustration fills what is left above the sticker band
    band = 300 if st.get("sticker_band") else 170
    bottom = H - SAFE_BOTTOM - band
    if st.get("illustration"):
        art = cutout(os.path.join(HERE, st["illustration"]), [12.0, 28.0])
        box_w, box_h = 820, max(80, bottom - (y + 40))
        k = min(box_w / art.width, box_h / art.height)
        art = art.resize((int(art.width * k), int(art.height * k)), Image.LANCZOS)
        top = (y + 40) + (box_h - art.height) // 2
        page.paste(art.convert("RGB"), (cx - art.width // 2, top), art.getchannel("A"))

    # where the interactive sticker goes — a guide, not decoration
    if st.get("sticker_hint"):
        hint_y = H - SAFE_BOTTOM - band // 2
        if st.get("sticker_band"):
            d.rounded_rectangle((110, hint_y - 96, W - 110, hint_y + 96), radius=28,
                                outline=FAINT, width=3)
        d.text((cx, hint_y), st["sticker_hint"], font=inter("Medium", 28),
               fill=FAINT, anchor="mm")

    d.text((cx, H - SAFE_BOTTOM + 40), st["footer"], font=inter("Medium", 30),
           fill=MUTED, anchor="mm")

    noise = Image.effect_noise((W, H), 11).convert("L").filter(ImageFilter.GaussianBlur(0.4))
    page = Image.blend(page, Image.merge("RGB", (noise, noise, noise)), 0.028)

    out = os.path.join(out_dir, st["file"])
    page.save(out)
    return out


def main() -> None:
    spec = json.load(open(os.path.join(HERE, "stories.json"), encoding="utf-8"))
    out_dir = os.path.join(HERE, "out")
    os.makedirs(out_dir, exist_ok=True)
    for st in spec["stories"]:
        print(render(st, spec["size"], out_dir))


if __name__ == "__main__":
    main()

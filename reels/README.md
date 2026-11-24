# Uzbek Islamic Reels

Faceless 9:16 reels in the `re.mind.ai` visual language: one object, one verse,
cream paper, calm pacing. Arabic verse on top, Uzbek translation under it,
flat illustration in the middle, narration subtitles at the bottom.

## Render

```bash
pip install pillow fonttools numpy scipy
python3 reels/render_reel.py reels/videos/01_yolgizlik.json
```

Output: `reels/out/<id>.mp4` — 720x1280, 30 fps, H.264 + AAC.

The layout is authored at 720x1280 and every length goes through `px()`, so
any scale renders natively — text and line work are redrawn at the output
size, never upscaled. For the Instagram master:

```bash
python3 reels/render_reel.py reels/videos/01_yolgizlik.json \
    --scale 1.5 --crf 16 --suffix _1080
```

| File | Size | Use |
|------|------|-----|
| `<id>.mp4` | 720x1280, CRF 19 | quick check, messaging |
| `<id>_1080.mp4` | 1080x1920, CRF 16 | **upload this** — Instagram's native reel size |

## Motion

The illustration is split by colour into a base plate plus sprites, so the
scene animates rather than just zooming:

- the drawing is laid down top-to-bottom on a slanted soft edge (`reveal_duration`)
- stars twinkle on their own periods, lit windows flicker and a few switch
  off and back on during the clip
- the moon drifts; sky objects parallax against the room as the camera pushes in
- a warm glow behind the drawing breathes onto the wall around the window
- the verse is written on right-to-left, the marker stroke swipes across the
  keyword at `highlight_at`
- captions arrive word by word with a `stagger`, each word rising into place

## Spec format

```jsonc
{
  "duration": 20.0,                       // seconds; must cover the voiceover
  "output": "out/01_yolgizlik.mp4",
  "audio": "assets/01/voice.mp3",         // ElevenLabs Adam voiceover
  "illustration": "assets/01/illustration.png",
  "illustration_box": [60, 310, 660, 950],// where the art is fitted
  "zoom": [1.0, 1.06],                    // slow push-in over the whole clip
  "caption_y": 1046,
  "header": {
    "arabic": "...",                      // the verse
    "arabic_highlight": "...",            // last word of the verse, marked in yellow
    "highlight_at": 6.3,                  // when the marker appears (sync to the recitation)
    "translation": "...",                 // Uzbek, in « »
    "reference": "Inshiroh surasi · 94:5-6"
  },
  "captions": [                           // narration, one phrase per entry
    { "start": 2.47, "end": 3.95, "text": "Yolgʻiz his qilyapsanmi?",
      "highlight": ["Yolgʻiz"] }          // yellow marker words
  ]
}
```

`text` may contain `\n` for a second line. `"script": "ar"` renders a caption in
Arabic (RTL, Amiri).

## Caption timing

Timings are taken from the voiceover itself, not guessed:

```bash
ffmpeg -i reels/assets/01/voice.mp3 -af silencedetect=noise=-35dB:d=0.22 -f null - 2>&1 \
  | grep silence_
```

Each `silence_end → next silence_start` pair is one spoken phrase.

## Illustration sourcing

Generated with Poyo (`gpt-image-2.6-fixed`, 1:1, 2K) and prompted with no text,
no people and no watermark — the renderer lifts the drawing off its generated
paper and places it straight on the page, so the art must be line work on a
flat cream field.

Prompt skeleton:

> Minimalist flat hand-drawn line illustration … thin uniform charcoal-brown
> outlines, warm cream background (#F3EFE7), soft muted mustard-yellow accents
> only, lots of negative space. STRICTLY: no text, no letters, no Arabic, no
> numbers, no watermark, no signature, no people, no faces.

## Voice

ElevenLabs Adam via Poyo — stability 0.4, similarity_boost 0.8,
`language_code` `uz`, `mp3_44100_128`.

## Fonts

- Arabic: Amiri (OFL), vendored in `reels/fonts/`
- Latin: Inter (OFL), from the system

Arabic shaping and RTL come from Pillow's Raqm/HarfBuzz layout engine.

## Instagram framing

The layout is authored inside the reel safe area, so nothing is covered by
Instagram's own interface:

| Reserved | 1080x1920 | design space |
|----------|-----------|--------------|
| top bar | 0-220 | 0-147 |
| caption, username, audio | 1500-1920 | 1000-1280 |
| action buttons | x > 900, y > 900 | x > 600 |

Videos 02 onward use `header_y` 175, `illustration_box` [110, 320, 610, 820]
and `caption_y` 930, which clears all three.

## Captions from the voiceover

The TTS call sets `timestamps: true`; `make_spec.py` reads the returned
character-level alignment and gives every phrase its exact start and end:

```bash
python3 reels/make_spec.py 02_ortiqcha_yuk     # brief -> spec
python3 reels/render_reel.py reels/videos/02_ortiqcha_yuk.json \
    --scale 1.5 --crf 16 --suffix _1080
```

`make_spec.py` also samples the illustration's own paper colour into
`palette.bg`, so the page and the drawing always match exactly.

Briefs (script, verse, palette, marker words) live in `reels/briefs/briefs.json`.

## Videos

| # | Topic | Verse | Page | Status |
|---|-------|-------|------|--------|
| 01 | Yolgʻizlik | 94:5-6 | cream | done |
| 02 | Ortiqcha yuk | 2:286 | sand | done |
| 03 | Qalb tinchligi | 13:28 | sage | done |
| 04 | Tavakkul | 65:3 | mist blue | done |
| 05 | Zikr | 2:152 | dusty rose | done |
| 06 | Duo | 40:60 | lavender | done |
| 07 | Umidsizlik | 39:53 | cream | done |

#!/usr/bin/env python3
"""Render a caption card PNG for demo videos — the house popup style.

Full-frame transparent PNG meant to be ffmpeg-overlaid on a freeze-frame
(see REFERENCE.md "Caption cards"). Style matches the ShipMaker editor:
near-black panel, green border, Visitor pixel-font title, optional keycap
chip, DejaVu body. First used in the part-picker demo (2026-08-08); reuse
this script for future videos rather than restyling per take.

Usage:
  make-caption-card.py OUT.png "PIPETTE" --key Q \
      --line "Q over empty space drops the hand." \
      --line "Q over a placed part copies it straight into the hand."
"""
import argparse
import os

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ---------------------------------------------------------------- style tokens
# Fonts: title/keycap use the game's own Visitor TT1 (pixel font — render at
# multiples of 10 px for crispness); body is a plain readable sans.
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

# The title face is the game's own, which ships with the game and not with this
# repo, so it is resolved rather than assumed. The body face is any DejaVu Sans.
VISITOR = os.environ.get("BSF_VISITOR_TTF") or os.path.join(
    _REPO, "_local", "mockups", "visitor1.ttf")
_BODY_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",       # Debian/Ubuntu
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",                # Fedora/Arch
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/Library/Fonts/DejaVuSans.ttf",                         # macOS
]
BODYFONT = next((f for f in _BODY_CANDIDATES if os.path.exists(f)),
                _BODY_CANDIDATES[0])


def _font(path, size, what):
    """Load a face, or say which one is missing and how to supply it."""
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        raise SystemExit(
            "%s font not found at %s\n"
            "The Visitor face comes with the game, not with this repo -- point "
            "BSF_VISITOR_TTF at it, or install DejaVu for the body face."
            % (what, path))

GREEN = (0, 170, 0, 255)        # panel + keycap border
DKGREEN = (0, 70, 0, 255)       # inner hairline
TITLE_C = (140, 255, 140, 255)  # title + keycap letter
BODY_C = (208, 216, 208, 255)   # body text
PANEL_BG = (6, 12, 6, 238)      # near-opaque near-black, slight green cast

TITLE_PX = 40                   # visitor1 @ 4x its 10px native
KEY_PX = 30                     # keycap letter
BODY_PX = 27
LINE_H = 37                     # body line pitch
PAD_X = 48                      # panel inner padding
RADIUS = 10


def make_card(out, title, key, lines, size, cy):
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    tfont = _font(VISITOR, TITLE_PX, "title")
    kfont = _font(VISITOR, KEY_PX, "keycap")
    bfont = _font(BODYFONT, BODY_PX, "body")

    tw = d.textlength(title, font=tfont) + (64 if key else 0)
    bw = max(d.textlength(l, font=bfont) for l in lines)
    pw = int(max(tw, bw)) + 2 * PAD_X
    ph = 66 + len(lines) * LINE_H + 46
    px, py = (w - pw) // 2, cy - ph // 2

    # soft drop shadow, then the panel with border + inner hairline
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle(
        [px + 4, py + 8, px + pw + 4, py + ph + 8], radius=RADIUS + 2, fill=(0, 0, 0, 110))
    img = Image.alpha_composite(sh.filter(ImageFilter.GaussianBlur(7)), img)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=RADIUS,
                        fill=PANEL_BG, outline=GREEN, width=2)
    d.rounded_rectangle([px + 4, py + 4, px + pw - 4, py + ph - 4],
                        radius=RADIUS - 3, outline=DKGREEN, width=1)

    tx, ty = px + PAD_X, py + 30
    if key:
        d.rounded_rectangle([tx, ty - 6, tx + 44, ty + 38], radius=6,
                            fill=(10, 30, 10, 255), outline=GREEN, width=2)
        kw = d.textlength(key, font=kfont)
        d.text((tx + 22 - kw / 2, ty + 1), key, font=kfont, fill=TITLE_C)
        tx += 64
    d.text((tx, ty), title, font=tfont, fill=TITLE_C)
    for j, l in enumerate(lines):
        d.text((px + PAD_X, py + 66 + 18 + j * LINE_H), l, font=bfont, fill=BODY_C)
    img.save(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    ap.add_argument("title")
    ap.add_argument("--key", help="optional keycap letter shown left of the title")
    ap.add_argument("--line", action="append", required=True,
                    help="body line (repeat; keep to 1-2 lines, ~60 chars)")
    ap.add_argument("--geometry", default="1920x1080")
    ap.add_argument("--cy", type=int, default=400,
                    help="panel center y (400 clears the bottom quickbar)")
    a = ap.parse_args()
    make_card(a.out, a.title, a.key, a.line,
              tuple(int(v) for v in a.geometry.split("x")), a.cy)

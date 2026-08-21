#!/usr/bin/env python3
"""Draw the startup banner and write it into the exe's settings block.

The splash Battleships Forever shows while it boots is not a room and not a
sprite. It belongs to the GM 7.0 runner, which puts it up before room 1 exists
and while it is still inflating the resource tree -- so no GML runs, and there
is no runtime API that can change it. What there is, is a settings block
appended after the PE image, holding a custom loading image as a zlib-compressed
24 bpp BMP plus the handful of ints that govern how it is shown.

This module draws that BMP and writes it back.

    splash.py read                     what the exe says today
    splash.py build                    compose the banner to build/splash/
    splash.py build --preview 4        ...and a 4x PNG to look at
    splash.py patch                    compose it and write it into the exe
    splash.py patch --alpha 232        ...at a lower uniform window alpha
    splash.py revert                   put the saved original back
    splash.py plate                    redraw the checked-in plate (design changes)

--------------------------------------------------------------- the design
"Drydock": an opaque HUD plate with its four corners chamfered off, the wordmark
stacked at the left over a faint drydock grid, and an Athena-class cruiser
holding station at the right. The version line sits under the wordmark, and
beneath it a recessed channel crosses the plate exactly where the runner draws
its progress bar. The plate stands 18 rows taller than the stock banner for
that one reason: the runner anchors its bar 32 rows above the window's foot,
so the window grew until that band cleared the type and landed where the
mockup always had it.

Only the four corner triangles are keyed away -- about 1% of the frame. That is
deliberate. Transparency here is a colour key, not an alpha channel: the runner
calls SetLayeredWindowAttributes with LWA_COLORKEY, which erases pixels matching
one exact RGB and leaves every other pixel fully opaque. Anti-aliased edges are
blends of the artwork *with the key colour*, so they are not the key and they
stay -- as a fringe of it. Keeping the plate opaque means the hull art keeps its
own soft edges and only two straight 45-degree cuts per corner have to be exact.

The key is #FF00E6, chosen because the artwork never uses it, and it is checked
rather than assumed: `_check_key` fails the build if a keyed pixel appears
anywhere outside the chamfers. The stock banner is the cautionary tale -- its
bottom-left pixel is a dark olive that is part of the picture, so switching the
flag on without redrawing would have punched holes through the artwork.

------------------------------------------------------------- the byte work
The block is found by scanning for GM's own header rather than by a remembered
address, because the fields after the image move whenever the image's compressed
length changes and an address that was right once is a trap afterwards:

    [u32 1234321][u32 700] ... [i32 load_bar_mode]
    if load_bar_mode != 0:  2 slots (back bar, front bar), each either
                            [i32 -1]  or  [i32 1][u32 len][len bytes zlib -> BMP]
    [i32 show_custom_load_image][u32 complen][complen bytes zlib -> BMP]
        (that is the same slot shape again: the show flag sits where a bar
        slot's marker sits and does both jobs, so the length+image pair exists
        only while it is positive -- write 0 and keep the pair, and the stream
        desyncs)
    [i32 image_partially_transparent][i32 load_image_alpha][i32 scale_progress_bar]
    [i32 display_errors][i32 write_to_log][i32 abort_on_error][i32 uninit_as_zero]

Everything after those seven ints is copied through untouched, so an exe that
has already been through `patch_bsf.py` stays patched: the resource tree lives
further down the file and is never rewritten here.

--------------------------------------------------------------- the load bar
**Mode 2 is the working mode, and the wire format was the whole problem.** The
2026-08-20 measurements stopped one int short of the answer; re-measured on
2026-08-21 against this build, frames read off an Xvfb display:

  * A non-zero `load_bar_mode` is followed by two image *slots*, back bar then
    front bar. An absent slot is the single int `-1`; a present one is
    `[i32 1][u32 len][len bytes of zlib -> 24 bpp BMP file]`. The earlier
    attempts sat either side of that: a bare `[len][zlib]` pair feeds the
    length in as the marker and the zlib magic in as a length (desync), and
    `1, -1, -1` parses cleanly while promising no images.
  * Mode 1 -- GM's own red-on-grey bar -- draws nothing on this runner. Not
    over a custom loading image, keyed or opaque, and not without one either:
    set `show_custom_load_image = 0` (dropping the image pair with it) and
    there is no loading window at all, only the busy cursor. The default bar
    is dead code here; own images are not.
  * With `scale_progress_bar = 0` both images draw at native size, top-left
    anchored in a fixed rect -- (24, H-32), sized (W-48) x 16, measured at
    both H=150 (y 118..133) and H=168 (y 136..151), so the anchor tracks the
    window height -- and are cropped to it. The front image is further cropped
    to `progress x its own width`, so a rect-sized front fills the recess
    exactly at 100%. The runner sizes and centres the window to whatever image
    it is given, which is what lets the plate grow to move the bar. LWA_COLORKEY
    keys the chamfers away with the bar drawing happily inside them.

So the shipping configuration is mode 2 with both images supplied, drawn at
patch time from the plate's own palette -- no fonts touched, so the
patch-needs-nothing rule holds. The plate's recessed channel sits exactly under
the runner's rect and the back image repaints it pixel for pixel, which is what
makes the handoff invisible. `--bar 0` restores the historical dormant
configuration; `--bar 1` still writes the absent markers, in case a later
runner grows a default bar.

------------------------------------------------------- what this needs to run
The banner arrives in two halves, split along the only line that matters: what
may be checked in, and what may not.

  * **The plate** -- `splash-plate.png`, 550x168 and about 5 KB. Ground, grid,
    chamfers, rules, channel and every line of type. None of it is the game's,
    so it is tracked, and it arrives as pixels: patching needs no fonts, which
    is what lets the version line be set in a mono nobody has to install.
  * **The hull** -- the game's, and therefore never checked in. Rendered at
    patch time from the player's own exe: `stockship.source` reads the Athena's
    Create event out of the resource tree when no GML dump is present, and the
    sprites come from `Custom sprites/`, which ships with v0.90d.

So a patching machine needs the game and nothing else. Only redrawing the plate
needs fonts, and only on the machine making the design change -- Visitor TT1/TT2
are in `tools/fonts/`, the mono is whatever `_FACES` names.

That split is also why the plate can be tracked at all: `.gitignore` bars what is
extracted from the game or generated from its source, and the plate is neither.
The rule this repo actually applies is the one beside `mods/act2m1.gml` -- what
gets shipped belongs in the repo, wherever it was drawn.

The output belongs in `build/`, which is not tracked.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import struct
import sys
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / 'bsf'))
import model      # noqa: E402
import paths      # noqa: E402
import render     # noqa: E402
import scene      # noqa: E402
import stockship  # noqa: E402

from PIL import Image, ImageChops, ImageDraw, ImageFont   # noqa: E402


# --------------------------------------------------------------------------
# the banner
# --------------------------------------------------------------------------

W, H = 550, 168                 #: stock width; 18 rows taller than the stock
                                #: banner so the runner's bar band (anchored at
                                #: H-32) clears the version line
CHAMFER = 14                    #: corner cut, in pixels along each edge

KEY     = (0xFF, 0x00, 0xE6)    #: transparency key -- absent from the artwork
PLATE   = (0x07, 0x0B, 0x0A)    #: near-black, biased green
CHANNEL = (0x0A, 0x11, 0x0E)    #: the bar's recess
RULE    = (0x1C, 0x2A, 0x24)    #: hairlines
GREEN   = (0x6F, 0xFE, 0x27)    #: sampled off the game's own logo
EMBER   = (0xF3, 0x54, 0x00)    #: ...and its FOREVER
CYAN    = (0x40, 0xF0, 0xF0)    #: ...and the LEGACY! swash on the main menu
STAMP   = (0x6B, 0x83, 0x79)    #: the version line, deliberately quiet

GRID_INK, GRID_A, GRID_STEP = (111, 254, 39), 0.055, 25

#: The runner's bar rect, measured off this build (see "the load bar"): both
#: bar images land top-left anchored at (BAR_X, BAR_TOP) and are cropped to
#: BAR_W x BAR_H. The plate's recess sits exactly here so plate and bar agree.
BAR_X, BAR_TOP = 24, H - 32
BAR_W, BAR_H = W - 2 * BAR_X, 16

#: (text, face, size, x, top, tracking-in-em, colour). `top` is the CSS box top
#: the mockup was laid out against; `_baseline` converts it.
WORDMARK = [
    ('BATTLESHIPS', 'tt1', 30, 22, 10, 0.02, GREEN),
    ('FOREVER',     'tt1', 30, 22, 42, 0.02, EMBER),
    ('LEGACY',      'tt2', 22, 24, 78, 0.30, CYAN),
]

#: The version line, and the one place a face is a choice rather than a given.
#: `tt2` is the game's own smaller interface face and is already in the
#: checkout, so it costs nothing and needs nothing installed; `mono` is the
#: mockup's texture but resolves to whatever mono the machine happens to have,
#: which on Windows is not the one this was drawn against.
STAMP_TEXT = 'V0.90D · MOD FRAMEWORK'
STAMP_LINE = {                          # face -> (size, x, top, tracking-in-em)
    'tt2':  (12, 24, 112, 0.34),
    'mono': (12, 24, 112, 0.16),
}

RULE_BOX    = (24, 106)                 #: x, y -- the rule under the wordmark. Its
                                        #: width is measured from the line below it
                                        #: rather than fixed, so the two stay flush
                                        #: whichever face draws the line.
DIVIDER_BOX = (284, 12, 114)            #: x, y, height -- wordmark | hull
HULL        = ('Athena', 308, 18)      #: hull, and where it holds station


def _plate_polygon() -> list[tuple[int, int]]:
    """The chamfered plate, in pixel coordinates (so W-1, not W)."""
    c = CHAMFER
    return [(c, 0), (W - 1 - c, 0), (W - 1, c), (W - 1, H - 1 - c),
            (W - 1 - c, H - 1), (c, H - 1), (0, H - 1 - c), (0, c)]


def _blend(bg: tuple[int, int, int], fg: tuple[int, int, int],
           a: float) -> tuple[int, int, int]:
    return tuple(round(fg[i] * a + bg[i] * (1 - a)) for i in range(3))


def _grid(img: Image.Image) -> None:
    """The drydock mesh: 25 px cells, fading out towards the lower right.

    The mockup masks the mesh with an ellipse anchored at 30%/40% of the plate;
    the same falloff is reproduced here so the hull sits against clean ground
    rather than through a uniform lattice.
    """
    d = ImageDraw.Draw(img)
    cx, cy, rx, ry = 0.30 * W, 0.40 * H, 1.20 * W, 1.50 * H
    solid, gone = 0.25, 0.78

    def alpha(x: float, y: float) -> float:
        r = (((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2) ** 0.5
        if r <= solid:
            return GRID_A
        if r >= gone:
            return 0.0
        return GRID_A * (gone - r) / (gone - solid)

    for x in range(0, W, GRID_STEP):
        for y in range(H):
            a = alpha(x, y)
            if a > 0:
                d.point((x, y), _blend(PLATE, GRID_INK, a))
    for y in range(H - 1, -1, -GRID_STEP):
        for x in range(W):
            a = alpha(x, y)
            if a > 0:
                d.point((x, y), _blend(PLATE, GRID_INK, a))


def _baseline(font: ImageFont.FreeTypeFont, top: float, size: float) -> float:
    """CSS `top` with `line-height: 1` -> the baseline PIL wants.

    The mockup positions every line by the top of a box exactly one em tall, and
    CSS centres the font's ascent+descent inside that box (half-leading). Get
    this wrong and the whole stack drifts a few pixels off the layout that was
    signed off.
    """
    ascent, descent = font.getmetrics()
    return top + (size - (ascent + descent)) / 2 + ascent


def _tracked_width(font: ImageFont.FreeTypeFont, text: str, tracking: float) -> int:
    """How wide the drawn line actually is, to the right edge of its last glyph.

    Not the same as the advance total: `_tracked` adds tracking after the final
    character, as CSS does, and that trailing gap is not ink. The rule above the
    version line is sized from this so the two finish together -- at 12 px the
    two faces on offer differ by ~7 px, which a fixed width would show as an
    overhang under one of them.
    """
    if not text:
        return 0
    return round(sum(font.getlength(c) for c in text) + tracking * (len(text) - 1))


def _tracked(d: ImageDraw.ImageDraw, xy: tuple[float, float], text: str,
             font: ImageFont.FreeTypeFont, fill, tracking: float) -> None:
    """Draw with CSS letter-spacing, which PIL has no notion of.

    Spacing is added after every character including the last, as CSS does --
    it matters for the version line, whose right edge is meant to finish flush
    with the rule above it.
    """
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill, anchor='ls')
        x += font.getlength(ch) + tracking


def _hull() -> Image.Image:
    """The Athena, drawn offline from the stock definition and cropped tight.

    The definition comes through `stockship.source`, which reads it out of the
    player's own exe when no GML dump is present -- so this runs against a fresh
    install with nothing but the game and this toolchain. The sprites come from
    `Custom sprites/`, which ships with v0.90d.

    Returned as it comes out of the renderer -- composited against near-black,
    which is what the plate is, so pasting it through a coverage mask needs no
    un-premultiply and leaves no seam.
    """
    name, _x, _y = HULL
    img, _ids, _info = render.render(scene.build(stockship.ship(name)), scale=1)
    img = img.convert('RGB')
    return img.crop(_ink(img).getbbox())


#: Anything above this is artwork; the renderer's own ground is (5, 7, 10).
INK_CUT = 26


def _ink(img: Image.Image) -> Image.Image:
    """One-bit coverage from the brightest channel.

    Not `convert('L')`: that is luminance-weighted, and the core marker is a
    saturated blue whose luminance reads as background.
    """
    r, g, b = img.convert('RGB').split()
    top = ImageChops.lighter(ImageChops.lighter(r, g), b)
    return top.point(lambda v: 255 if v > INK_CUT else 0)


def _plate_mask() -> Image.Image:
    """255 inside the chamfered plate, 0 in the four corners the key erases."""
    mask = Image.new('L', (W, H), 0)
    ImageDraw.Draw(mask).polygon(_plate_polygon(), fill=255)
    return mask


def draw_bar(fill: tuple[int, int, int]) -> Image.Image:
    """One bar image: a flat field under the hairline that caps the recess.

    Back and front differ only in that fill -- CHANNEL for the empty recess,
    GREEN for what has loaded -- so they are one function. Drawing them the
    same way is what keeps the front from creeping a pixel off the back as
    the design changes.
    """
    img = Image.new('RGB', (BAR_W, BAR_H), fill)
    ImageDraw.Draw(img).rectangle([0, 0, BAR_W - 1, 0], fill=RULE)
    return img


def _paint_recess(img: Image.Image) -> None:
    """Stamp the empty recess onto the plate, at the runner's own bar rect.

    The same pixels the runner will lay down as the back bar -- literally the
    same image, so the handoff is invisible by construction rather than by two
    code paths agreeing. `banner` re-asserts it after the hull lands, because
    the runner draws the bar over the hull too and the preview should not
    disagree.
    """
    img.paste(draw_bar(CHANNEL), (BAR_X, BAR_TOP))


def draw_plate(stamp_face: str = 'mono') -> Image.Image:
    """Everything except the hull -- and everything that needs a font.

    This is the half of the banner that is ours: plate, grid, chamfers, rules,
    channel and all four lines of type. It is drawn once, by whoever changes the
    design, and checked in as `splash-plate.png`. Patch time never runs it, which
    is what frees the version line to be set in a mono nobody has to install.
    """
    size, sx, stop, strack = STAMP_LINE[stamp_face]
    if stop + size > BAR_TOP:
        raise SystemExit(
            f'the {stamp_face} version line runs to y={stop + size} but the '
            f'runner puts its bar band at y={BAR_TOP}. H is 18 rows taller '
            f'than the stock banner for exactly this clearance -- raise H '
            f'(the band follows it at H-32) or lift STAMP_LINE.')
    lines = WORDMARK + [(STAMP_TEXT, stamp_face, size, sx, stop, strack, STAMP)]
    rule_w = _tracked_width(load_font(stamp_face, size), STAMP_TEXT, strack * size)
    layer = Image.new('RGB', (W, H), PLATE)
    _grid(layer)
    d = ImageDraw.Draw(layer)

    x, y = RULE_BOX
    d.rectangle([x, y, x + rule_w - 1, y], fill=RULE)
    x, y, h = DIVIDER_BOX
    d.rectangle([x, y, x, y + h - 1], fill=RULE)

    for text, face, size, tx, top, track, ink in lines:
        font = load_font(face, size)
        _tracked(d, (tx, _baseline(font, top, size)), text, font, ink,
                 track * size)

    _paint_recess(layer)        # last, as `banner` does it -- the band is the
                                # runner's, and nothing may sit in it
    out = Image.new('RGB', (W, H), KEY)
    out.paste(layer, (0, 0), _plate_mask())
    return out


def banner(stamp_face: str = 'mono', *, from_fonts: bool = False) -> Image.Image:
    """The finished frame: the checked-in plate with this install's hull on it.

    The hull is the one piece that cannot be checked in -- it is the game's, and
    it is rendered here from the player's own exe. Everything else arrives as
    pixels, so the only thing a patching machine needs is the game.
    """
    if from_fonts or not PLATE_FILE.exists():
        base = draw_plate(stamp_face)
    else:
        base = Image.open(PLATE_FILE).convert('RGB')
        if base.size != (W, H):
            raise SystemExit(f'{PLATE_FILE.name} is {base.size[0]}x{base.size[1]}, '
                             f'expected {W}x{H}')

    out = base.copy()
    hull = _hull()
    _name, hx, hy = HULL
    out.paste(hull, (hx, hy), _ink(hull))
    _paint_recess(out)
    _check_key(out, _plate_mask())
    return out


def _check_key(img: Image.Image, mask: Image.Image) -> None:
    """Refuse to ship a banner whose key colour leaks into the artwork.

    Two ways this goes wrong and neither is visible in a preview: a keyed pixel
    inside the plate punches a hole at runtime, and a bottom-left pixel that is
    not the key makes the runner key some *other* colour out of the picture.
    """
    if img.getpixel((0, H - 1)) != KEY:
        raise SystemExit(
            f'bottom-left pixel is {img.getpixel((0, H - 1))}, not the key '
            f'{KEY} -- the runner keys on that pixel, so this would erase the '
            'wrong colour')
    px, mk = img.load(), mask.load()
    for yy in range(H):
        for xx in range(W):
            if mk[xx, yy] and px[xx, yy] == KEY:
                raise SystemExit(
                    f'key colour {KEY} appears inside the plate at '
                    f'({xx}, {yy}) -- it would be punched out at runtime')


# --------------------------------------------------------------------------
# fonts
# --------------------------------------------------------------------------

#: The faces the game itself names in its resource tree: MainMenuFont and
#: TextFontLarge are Visitor TT1 BRK, TextFont is Visitor TT2 BRK. Drawing the
#: banner in them is what makes it read as the same product as the menu behind
#: it. Brian Kent's originals are freeware; they are not redistributed here.
_FACES = {
    'tt1':  ('visitor1.ttf', 'visitor tt1 brk'),
    'tt2':  ('visitor2.ttf', 'visitor tt2 brk'),
    'mono': ('DejaVuSansMono.ttf', 'dejavu sans mono'),
}
_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
_OVERRIDE: dict[str, str] = {}


#: The faces that travel with this checkout, because nothing else can supply them.
BUNDLED = pathlib.Path(__file__).resolve().parent / 'fonts'

#: The pre-drawn half of the banner. Tracked, because it carries no game content
#: -- and because shipping it is what removes the font dependency from patching.
PLATE_FILE = pathlib.Path(__file__).resolve().parent / 'splash-plate.png'


def _font_dirs() -> list[pathlib.Path]:
    """Where to look, most specific first. No path is written down."""
    out = []
    env = os.environ.get('BSF_FONTS')
    if env:
        out.append(pathlib.Path(env).expanduser())
    out.append(BUNDLED)
    # A wine prefix kept beside the install may have the game's faces installed,
    # which is what makes the game's own text render in them rather than a
    # substitute. Searched after the bundled copies, never instead of them.
    for base in (paths.GAME.parent, paths.GAME):
        out.append(base / 'wineprefix' / 'drive_c' / 'windows' / 'Fonts')
    out += [pathlib.Path.home() / '.local' / 'share' / 'fonts',
            pathlib.Path.home() / '.fonts',
            pathlib.Path('/usr/share/fonts'),
            pathlib.Path('/usr/local/share/fonts')]
    return [d for d in out if d.is_dir()]


def _find_face(filename: str) -> pathlib.Path | None:
    stem = filename.lower()
    for d in _font_dirs():
        hit = next((p for p in d.rglob('*.ttf') if p.name.lower() == stem), None)
        if hit:
            return hit
    return None


def load_font(face: str, size: int) -> ImageFont.FreeTypeFont:
    key = (face, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    override = _OVERRIDE.get(face)
    path = pathlib.Path(override) if override else _find_face(_FACES[face][0])
    if path is None or not path.exists():
        filename, human = _FACES[face]
        raise SystemExit(
            f'font not found: {human} ({filename})\n'
            f'  Install it, put it in a directory named by $BSF_FONTS, or pass '
            f'--font {face}=/path/to/{filename}\n'
            f'  Visitor TT1 and TT2 BRK are Brian Kent freeware faces. They are '
            f'not in the game package -- GM 7.0 stores a face NAME, not glyphs, '
            f'which is also why the game\'s own menus fall back without them.')
    _FONT_CACHE[key] = ImageFont.truetype(str(path), size)
    return _FONT_CACHE[key]


# --------------------------------------------------------------------------
# the settings block
# --------------------------------------------------------------------------

_HEADER = struct.pack('<II', 1234321, 700)      #: GM's magic, then its version

#: Offset of `load_bar_mode` from the header, established by reading this build
#: and cross-checked against enigma-dev's GMK `LoadSettings` reader. An earlier
#: reading of this comment said the compiled exe *omits* the `!= -1` image-present
#: marker that the .gmk format carries in front of the load image. It does not:
#: `show_custom_load_image` sits in the marker's position and does both jobs at
#: once (see `_slot`). Measured -- write 0 and keep the length+blob and the
#: stream desyncs; write 0 and drop them and the exe boots with no splash.
#: Everything past here is walked, not remembered, because a non-zero bar mode
#: inserts two more slots.
_BAR = 0x68
_BAR_SLOTS = 2                  #: image slots a non-zero mode inserts, always two
_TAIL_FIELDS = ('image_partially_transparent', 'load_image_alpha',
                'scale_progress_bar', 'display_errors', 'write_to_log',
                'abort_on_error', 'treat_uninit_as_zero')


def _slot(raw: bytes | None) -> bytes:
    """One optional-blob slot: a marker, then the deflated payload if present.

    The settings stream spells an optional image this way in three places --
    the two bar slots, and the loading image, whose `show_custom_load_image`
    int *is* its marker. `-1` is absent, and the reader consumes the marker
    either way, which is why a slot can never simply be left out.
    """
    if raw is None:
        return struct.pack('<i', -1)
    z = zlib.compress(raw, 9)
    return struct.pack('<iI', 1, len(z)) + z


def _read_slot(buf: bytes, off: int) -> tuple[int, int]:
    """Walk one slot. Returns its deflated length (-1 if absent) and the offset
    just past it -- the payload is skipped rather than copied, so walking an
    8 MB buffer costs nothing."""
    marker = struct.unpack_from('<i', buf, off)[0]
    off += 4
    if marker == -1:
        return -1, off
    n = struct.unpack_from('<I', buf, off)[0]
    return n, off + 4 + n


class Settings:
    """A located settings block. Every offset is derived, never remembered."""

    def __init__(self, buf: bytes):
        self.buf = buf
        first = buf.find(_HEADER)
        if first < 0:
            raise SystemExit('no GM 7.0 settings header in this file -- is it '
                             'the v0.90d BattleshipsForever.exe?')
        if buf.find(_HEADER, first + 1) >= 0:
            raise SystemExit('more than one GM 7.0 settings header found; '
                             'refusing to guess which one is real')
        self.base = first
        off = self.base + _BAR
        self._bar = struct.unpack_from('<i', buf, off)[0]
        off += 4
        self.bar_slots = []     #: per slot: -1 (absent) or the zlib length
        if self._bar:
            for _ in range(_BAR_SLOTS):
                n, off = _read_slot(buf, off)
                self.bar_slots.append(n)
        self._show_at = off
        self.complen = struct.unpack_from('<I', buf, off + 4)[0]
        self.image_at = off + 8
        self.tail = self.image_at + self.complen

    def bar_mode(self) -> int:
        return self._bar

    def show_image(self) -> int:
        return struct.unpack_from('<i', self.buf, self._show_at)[0]

    def field(self, name: str) -> int:
        off = self.tail + 4 * _TAIL_FIELDS.index(name)
        return struct.unpack_from('<i', self.buf, off)[0]

    def image(self) -> bytes:
        return zlib.decompress(self.buf[self.image_at:self.tail])

    def describe(self) -> str:
        bmp = self.image()
        w, h = struct.unpack_from('<ii', bmp, 18)
        bpp = struct.unpack_from('<H', bmp, 28)[0]
        slots = ', '.join('absent' if n < 0 else f'{n} B zlib'
                          for n in self.bar_slots)
        rows = [f'settings block   0x{self.base:x}  (image at 0x{self.image_at:x}, '
                f'tail at 0x{self.tail:x})',
                f'load_bar_mode              {self.bar_mode()}'
                + (f'  ({slots})' if slots else ''),
                f'show_custom_load_image     {self.show_image()}',
                f'loading image              {w}x{h} {bpp}bpp, '
                f'{len(bmp)} B -> {self.complen} B deflated']
        rows += [f'{name:<26} {self.field(name)}' for name in _TAIL_FIELDS]
        return '\n'.join(rows)


def write_settings(buf: bytes, bmp: bytes, *, bar_mode: int, transparent: int,
                   alpha: int, bar_back: bytes | None = None,
                   bar_front: bytes | None = None) -> bytes:
    """Return `buf` with a new loading image and the three flags that show it.

    The image is replaced first and the flags are addressed afterwards, off the
    *new* tail, because swapping the image moves them. The two bar images are
    named rather than passed as a sequence because the stream distinguishes
    them only by position -- handing them over in the wrong order yields an exe
    that boots happily and draws the recess over the fill.
    """
    if (bar_back is None) != (bar_front is None):
        raise SystemExit('supply both bar images or neither: a half-filled '
                         'pair draws a fill with no ground under it')
    if (bar_mode == 2) != (bar_back is not None):
        raise SystemExit(f'load_bar_mode {bar_mode} with '
                         f'{"images" if bar_back else "no images"}. 2 is the '
                         f'mode that draws own bar images, and the only mode '
                         f'with any use for them -- mode 2 without them is the '
                         f'configuration that parses cleanly and draws nothing.')
    s = Settings(buf)
    head = bytearray(buf[:s.base + _BAR])
    head += struct.pack('<i', bar_mode)
    if bar_mode:
        for raw in (bar_back, bar_front):
            head += _slot(raw)
    head += _slot(bmp)          # this slot's marker is show_custom_load_image
    tail = bytearray(buf[s.tail:])
    struct.pack_into('<ii', tail, 0, transparent, alpha)
    return bytes(head + tail)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

BACKUP_SUFFIX = '.splashbak'


def _exe(arg: str | None) -> pathlib.Path:
    if arg:
        return pathlib.Path(arg).expanduser()
    return paths.require(paths.GAME / 'BattleshipsForever.exe', 'the game exe')


def _outdir() -> pathlib.Path:
    d = paths.REPO / 'build' / 'splash'
    d.mkdir(parents=True, exist_ok=True)
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='splash.py', description=__doc__.split('\n')[0])
    ap.add_argument('--font', action='append', default=[], metavar='FACE=PATH',
                    help='override a face: tt1, tt2 or mono')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('read', help='show the exe\'s current splash settings')\
       .add_argument('exe', nargs='?')

    pl = sub.add_parser('plate', help='redraw the checked-in plate (needs the fonts)')
    pl.add_argument('-o', '--out')
    pl.add_argument('--stamp', choices=tuple(STAMP_LINE), default='mono',
                    help='face for the version line, baked into the plate')

    b = sub.add_parser('build', help='draw the banner to build/splash/')
    b.add_argument('-o', '--out')
    b.add_argument('--from-fonts', action='store_true',
                   help='redraw the plate instead of using the checked-in one')
    b.add_argument('--stamp', choices=tuple(STAMP_LINE), default='mono',
                   help='face for the version line, with --from-fonts')
    b.add_argument('--preview', type=int, metavar='N',
                   help='also write an Nx PNG to look at')

    p = sub.add_parser('patch', help='draw the banner and write it into the exe')
    p.add_argument('exe', nargs='?')
    p.add_argument('--alpha', type=int, default=255,
                   help='load_image_alpha, 0-255, uniform over the whole window')
    p.add_argument('--bar', type=int, default=2, choices=(0, 1, 2),
                   help='load_bar_mode. 2 is the shipping value: own bar '
                        'images drawn from the plate palette, filling the '
                        'recess. 1 is dead code on this runner and 0 is the '
                        'historical dormant value.')
    p.add_argument('--opaque', action='store_true',
                   help='leave image_partially_transparent off (square corners)')
    p.add_argument('--from-fonts', action='store_true',
                   help='redraw the plate instead of using the checked-in one')
    p.add_argument('--stamp', choices=tuple(STAMP_LINE), default='mono',
                   help='face for the version line, with --from-fonts')
    p.add_argument('--no-backup', action='store_true')

    sub.add_parser('revert', help=f'restore the saved {BACKUP_SUFFIX}')\
       .add_argument('exe', nargs='?')

    args = ap.parse_args(argv)
    for spec in args.font:
        face, _, path = spec.partition('=')
        if face not in _FACES:
            raise SystemExit(f'unknown face {face!r}; expected one of '
                             f'{", ".join(_FACES)}')
        _OVERRIDE[face] = path

    if args.cmd == 'read':
        print(Settings(_exe(args.exe).read_bytes()).describe())
        return 0

    if args.cmd == 'plate':
        img = draw_plate(args.stamp)
        out = pathlib.Path(args.out) if args.out else PLATE_FILE
        img.save(out)
        print(f'plate ({args.stamp} version line, no hull) -> {out}  '
              f'({out.stat().st_size} B)')
        return 0

    if args.cmd == 'build':
        img = banner(args.stamp, from_fonts=args.from_fonts)
        out = pathlib.Path(args.out) if args.out else _outdir() / 'drydock.bmp'
        img.save(out)
        print(f'{img.width}x{img.height} -> {out}  ({out.stat().st_size} B)')
        if args.preview:
            png = out.with_suffix('.png')
            img.resize((W * args.preview, H * args.preview),
                       Image.NEAREST).save(png)
            print(f'{args.preview}x preview -> {png}')
        return 0

    if args.cmd == 'revert':
        exe = _exe(args.exe)
        bak = exe.with_suffix(exe.suffix + BACKUP_SUFFIX)
        if not bak.exists():
            raise SystemExit(f'no backup at {bak}')
        shutil.copy2(bak, exe)
        print(f'restored {exe.name} from {bak.name}')
        return 0

    exe = _exe(args.exe)
    if not 0 <= args.alpha <= 255:
        raise SystemExit('--alpha must be 0-255')
    buf = exe.read_bytes()
    before = Settings(buf)
    if not before.show_image():
        raise SystemExit('show_custom_load_image is 0 in this exe; it would not '
                         'display a custom image however we write one')

    if args.bar == 1:
        print('note: measured on this build -- mode 1 draws nothing, with or '
              'without a custom loading image. 2 is the mode with a bar.')

    img = banner(args.stamp, from_fonts=args.from_fonts)
    bmp = _outdir() / 'drydock.bmp'
    img.save(bmp)

    bars = {}
    if args.bar == 2:
        for role, fill in (('back', CHANNEL), ('front', GREEN)):
            path = _outdir() / f'bar-{role}.bmp'
            draw_bar(fill).save(path)
            bars[f'bar_{role}'] = path.read_bytes()

    bak = exe.with_suffix(exe.suffix + BACKUP_SUFFIX)
    if not args.no_backup and not bak.exists():
        shutil.copy2(exe, bak)
        print(f'backed up -> {bak.name}')

    patched = write_settings(buf, bmp.read_bytes(), bar_mode=args.bar,
                             transparent=0 if args.opaque else 1,
                             alpha=args.alpha, **bars)
    exe.write_bytes(patched)

    after = Settings(exe.read_bytes())
    if after.image() != bmp.read_bytes():
        raise SystemExit('read-back mismatch: the image did not survive the '
                         'write. Restore from the backup before launching.')
    print(f'patched {exe.name}  ({len(buf)} -> {len(patched)} B)')
    print(after.describe())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

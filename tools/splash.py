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
holding station at the right. A recessed channel runs along the foot for the
progress bar.

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
    if load_bar_mode != 0:  [i32 back_bar][i32 front_bar]
    [i32 show_custom_load_image][u32 complen][complen bytes zlib -> BMP]
    [i32 image_partially_transparent][i32 load_image_alpha][i32 scale_progress_bar]
    [i32 display_errors][i32 write_to_log][i32 abort_on_error][i32 uninit_as_zero]

Everything after those seven ints is copied through untouched, so an exe that
has already been through `patch_bsf.py` stays patched: the resource tree lives
further down the file and is never rewritten here.

--------------------------------------------------------------- the load bar
**The two ints after a non-zero `load_bar_mode` are not optional, and there is
no bar at the end of it anyway.** Both halves of that were measured against this
build on 2026-08-20, by launching the patched exe and watching the frames:

  * Write `load_bar_mode = 1` on its own and the gamedata stream desyncs from
    that point on. The loader dies before any window appears -- silently, since
    this is a loader failure and not a GML one, so `display_errors` has nothing
    to say about it. Mode 2 with the two bar images written as bare
    `[len][zlib]` pairs, with or without a present-marker in front, gets as far
    as "Failed to load the game data. File seems corrupted."
  * Write `1, -1, -1` and the game loads perfectly -- so the reader consumes
    exactly two ints for any non-zero mode, and `-1` (absent) satisfies it.
  * But no bar is ever drawn. Seven seconds of splash at 20 fps, and the only
    lit pixels on screen are the 550x150 loading image: this runner draws no
    progress bar over a *custom* loading image.

So the shipping configuration leaves the mode at 0, which is what the game has
always had, and the recessed channel along the foot of the plate is a design
element rather than a promise. `--bar 1` still works and writes the markers, in
case a later build behaves differently.

------------------------------------------------------- what this needs to run
The banner arrives in two halves, split along the only line that matters: what
may be checked in, and what may not.

  * **The plate** -- `splash-plate.png`, 550x150 and about 5 KB. Ground, grid,
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

W, H = 550, 150                 #: what the runner has always shown, unchanged
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
CHANNEL_H = 14

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


def draw_plate(stamp_face: str = 'mono') -> Image.Image:
    """Everything except the hull -- and everything that needs a font.

    This is the half of the banner that is ours: plate, grid, chamfers, rules,
    channel and all four lines of type. It is drawn once, by whoever changes the
    design, and checked in as `splash-plate.png`. Patch time never runs it, which
    is what frees the version line to be set in a mono nobody has to install.
    """
    size, sx, stop, strack = STAMP_LINE[stamp_face]
    lines = WORDMARK + [(STAMP_TEXT, stamp_face, size, sx, stop, strack, STAMP)]
    rule_w = _tracked_width(load_font(stamp_face, size), STAMP_TEXT, strack * size)
    layer = Image.new('RGB', (W, H), PLATE)
    _grid(layer)
    d = ImageDraw.Draw(layer)

    x, y = RULE_BOX
    d.rectangle([x, y, x + rule_w - 1, y], fill=RULE)
    x, y, h = DIVIDER_BOX
    d.rectangle([x, y, x, y + h - 1], fill=RULE)

    d.rectangle([0, H - CHANNEL_H, W - 1, H - 1], fill=CHANNEL)
    d.rectangle([0, H - CHANNEL_H, W - 1, H - CHANNEL_H], fill=RULE)

    for text, face, size, tx, top, track, ink in lines:
        font = load_font(face, size)
        _tracked(d, (tx, _baseline(font, top, size)), text, font, ink,
                 track * size)

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
#: and cross-checked against enigma-dev's GMK `LoadSettings` reader. The compiled
#: exe omits the `!= -1` image-present marker the .gmk format carries in front of
#: the *load image*, which is what makes the int right before the length the
#: *show* flag rather than a second mode. Everything past here is walked, not
#: remembered, because a non-zero bar mode inserts two ints.
_BAR = 0x68
_BAR_MARKERS = 2                #: ints the reader eats when the mode is non-zero
_TAIL_FIELDS = ('image_partially_transparent', 'load_image_alpha',
                'scale_progress_bar', 'display_errors', 'write_to_log',
                'abort_on_error', 'treat_uninit_as_zero')


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
        if self._bar:
            off += 4 * _BAR_MARKERS
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
        rows = [f'settings block   0x{self.base:x}  (image at 0x{self.image_at:x}, '
                f'tail at 0x{self.tail:x})',
                f'load_bar_mode              {self.bar_mode()}',
                f'show_custom_load_image     {self.show_image()}',
                f'loading image              {w}x{h} {bpp}bpp, '
                f'{len(bmp)} B -> {self.complen} B deflated']
        rows += [f'{name:<26} {self.field(name)}' for name in _TAIL_FIELDS]
        return '\n'.join(rows)


def write_settings(buf: bytes, bmp: bytes, *, bar_mode: int, transparent: int,
                   alpha: int) -> bytes:
    """Return `buf` with a new loading image and the three flags that show it.

    The image is replaced first and the flags are addressed afterwards, off the
    *new* tail, because swapping the image moves them.
    """
    s = Settings(buf)
    blob = zlib.compress(bmp, 9)
    head = bytearray(buf[:s.base + _BAR])
    head += struct.pack('<i', bar_mode)
    if bar_mode:
        # The reader eats these whether or not it wants them. -1 is "absent",
        # which is the only value that leaves the stream aligned without also
        # supplying two bar images.
        head += struct.pack('<i', -1) * _BAR_MARKERS
    head += struct.pack('<i', 1)                          # show_custom_load_image
    head += struct.pack('<I', len(blob)) + blob
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
    p.add_argument('--bar', type=int, default=0, choices=(0, 1),
                   help='load_bar_mode. 0 is the shipping value: this runner '
                        'draws no bar over a custom loading image, so 1 costs '
                        'two stream ints and buys nothing (see the module docs)')
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

    if args.bar:
        print('note: measured on this build -- no bar is drawn over a custom '
              'loading image, whatever the mode says')

    img = banner(args.stamp, from_fonts=args.from_fonts)
    bmp = _outdir() / 'drydock.bmp'
    img.save(bmp)

    bak = exe.with_suffix(exe.suffix + BACKUP_SUFFIX)
    if not args.no_backup and not bak.exists():
        shutil.copy2(exe, bak)
        print(f'backed up -> {bak.name}')

    patched = write_settings(buf, bmp.read_bytes(), bar_mode=args.bar,
                             transparent=0 if args.opaque else 1,
                             alpha=args.alpha)
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

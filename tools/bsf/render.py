#!/usr/bin/env python3
"""Blit a scene to a PNG, and record which part won each pixel.

Two buffers come out of one pass: the colour image, and an **id buffer** holding
the op index that painted each pixel. The id buffer is what makes visibility,
occlusion, overlap pairs and connectivity answerable without a second traversal
-- so `ship check` is a query over a render rather than a separate geometry
engine. (That analysis is v2; the buffer is produced here so it exists when it
is needed.)

Rotation happens about the op's own origin, which for a turret is the base of
its barrel. The sprite is first placed on a padded square with its origin at the
centre, then rotated about that centre -- so the origin is a fixed point of the
transform and the paste position needs no correction.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image

#: Sections are two-tone masks multiplied by a team colour. That multiply is the
#: entire vector look; converting a mask naively to RGBA yields black squares.
RESAMPLE = Image.BICUBIC


def _tinted(frame: np.ndarray, blend: str, mask: bool) -> Image.Image:
    im = Image.fromarray(frame, 'RGBA')
    if not mask or blend == '#FFFFFF':
        return im
    r = int(blend[1:3], 16) / 255
    g = int(blend[3:5], 16) / 255
    b = int(blend[5:7], 16) / 255
    a = np.array(im, dtype=np.float32)
    a[..., 0] *= r
    a[..., 1] *= g
    a[..., 2] *= b
    return Image.fromarray(a.clip(0, 255).astype(np.uint8), 'RGBA')


def _transform(op: dict, frame: np.ndarray) -> tuple[Image.Image, float, float]:
    """Return (image, ox, oy) with the rotation origin at the image centre."""
    im = _tinted(frame, op['blend'], op['mask'])

    xs, ys = op['xs'], op['ys']
    if xs < 0:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    if ys < 0:
        im = im.transpose(Image.FLIP_TOP_BOTTOM)

    ox, oy = op['ox'], op['oy']
    if xs < 0:
        ox = op['w'] - ox
    if ys < 0:
        oy = op['h'] - oy

    sx, sy = abs(xs), abs(ys)
    if (sx, sy) != (1.0, 1.0):
        nw, nh = max(1, round(op['w'] * sx)), max(1, round(op['h'] * sy))
        im = im.resize((nw, nh), RESAMPLE)
        ox, oy = ox * sx, oy * sy

    # Pad so the rotation origin sits at the exact centre of a square, which
    # makes it a fixed point of the rotation and removes any offset bookkeeping.
    w, h = im.size
    half = math.ceil(math.hypot(w, h)) + 2
    pad = Image.new('RGBA', (half * 2, half * 2), (0, 0, 0, 0))
    pad.paste(im, (round(half - ox), round(half - oy)))

    if op['ang']:
        pad = pad.rotate(op['ang'], resample=RESAMPLE, expand=False)
    return pad, half, half


def render(sc: dict, *, scale: int = 4, pad: int = 8,
           background: tuple[int, int, int, int] = (5, 7, 10, 255),
           highlight: set[int] | None = None,   # op indices, not part ids
           dim_others: bool = False,
           want_masks: bool = False):
    """Draw the scene. Returns (PIL image, id buffer, transform info).

    `scale` is integer supersampling: the scene is drawn at 1 BSF pixel = 1
    image pixel and then enlarged, so geometry stays exact and only the final
    presentation is scaled.

    With `want_masks` the info dict gains a `masks` entry: one canvas-sized
    boolean array per op, holding the coverage that op *would* have if nothing
    were drawn over it. Producing it here rather than in a second pass is what
    keeps it comparable with the id buffer -- both apply the same transform and
    the same `alpha > 127` cut, so `mask.sum()` and `(ids == i).sum()` are the
    same measurement before and after occlusion.
    """
    x0, y0, x1, y1 = sc['bbox']
    w = max(1, int(math.ceil(x1 - x0)) + pad * 2)
    h = max(1, int(math.ceil(y1 - y0)) + pad * 2)
    cx, cy = -x0 + pad, -y0 + pad

    canvas = Image.new('RGBA', (w, h), background)
    ids = np.full((h, w), -1, dtype=np.int32)
    masks: list[np.ndarray] = []

    import sprites as _sprites
    for idx, op in enumerate(sc['ops']):
        sp = _sprites.load_any(op['spr'], op['mask'], op['kind'] in ('weapon', 'module'))
        img, ox, oy = _transform(op, sp.frames[0])

        alpha = op.get('alpha', 1.0)
        # Op index, not part id: a section and a weapon can both be id 0, so an
        # id-keyed highlight would light up whichever happened to match.
        lit = highlight is None or idx in highlight
        if dim_others and not lit:
            alpha *= 0.22
        if alpha < 1.0:
            a = np.array(img, dtype=np.float32)
            a[..., 3] *= max(0.0, min(1.0, alpha))
            img = Image.fromarray(a.clip(0, 255).astype(np.uint8), 'RGBA')

        px, py = round(cx + op['x'] - ox), round(cy + op['y'] - oy)
        canvas.alpha_composite(img, (px, py)) if _in_bounds(px, py, img, canvas) \
            else _safe_composite(canvas, img, px, py)

        if want_masks:
            m = np.zeros((h, w), dtype=bool)
            _stamp(m, img, px, py, True)
            masks.append(m)
        _stamp(ids, img, px, py, idx)

    if scale != 1:
        canvas = canvas.resize((w * scale, h * scale), Image.NEAREST)
    info = {'w': w, 'h': h, 'cx': cx, 'cy': cy, 'scale': scale}
    if want_masks:
        info['masks'] = masks
    return canvas, ids, info


def _in_bounds(px, py, img, canvas) -> bool:
    return px >= 0 and py >= 0 and px + img.width <= canvas.width \
        and py + img.height <= canvas.height


def _safe_composite(canvas: Image.Image, img: Image.Image, px: int, py: int) -> None:
    """alpha_composite refuses out-of-bounds offsets; crop to the overlap."""
    cx0, cy0 = max(0, px), max(0, py)
    cx1, cy1 = min(canvas.width, px + img.width), min(canvas.height, py + img.height)
    if cx0 >= cx1 or cy0 >= cy1:
        return
    canvas.alpha_composite(img.crop((cx0 - px, cy0 - py, cx1 - px, cy1 - py)), (cx0, cy0))


def _stamp(ids: np.ndarray, img: Image.Image, px: int, py: int, idx) -> None:
    """Record this op as the owner of every pixel it painted opaquely."""
    h, w = ids.shape
    cx0, cy0 = max(0, px), max(0, py)
    cx1, cy1 = min(w, px + img.width), min(h, py + img.height)
    if cx0 >= cx1 or cy0 >= cy1:
        return
    a = np.array(img)[cy0 - py:cy1 - py, cx0 - px:cx1 - px, 3]
    ids[cy0:cy1, cx0:cx1] = np.where(a > 127, idx, ids[cy0:cy1, cx0:cx1])


def save(sc: dict, path: str, **kw) -> dict:
    img, ids, info = render(sc, **kw)
    img.convert('RGB').save(path)
    info['path'] = path
    # Keyed by kind and id together: part ids are only unique within a kind.
    info['visible'] = {f'{op["kind"]} {op["id"]}': int((ids == idx).sum())
                       for idx, op in enumerate(sc['ops'])}
    return info

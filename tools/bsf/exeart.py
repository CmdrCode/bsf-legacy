#!/usr/bin/env python3
"""Recover sprites from the game's own resource tree, straight out of the exe.

The gamedata is not locked. GM 7.0 encrypts its resource tree with the stock
"gmkrypt" scheme and `tools/gm7.py` already inverts it byte-exactly -- that is
how the mod patcher writes into the tree in the first place. So every sprite the
game has, including the ones that were never exported to `Custom sprites/`, is
readable without wine, ptrace or memory scanning.

Two things come out of this that nothing on disk can provide:

  * **the exe-only art** -- the core shapes beyond frame 0, and the weapons
    (`Tesla`, `Dieterling`, `Pulse`, `ThrusterEx`) that had to be drawn as
    stand-ins;
  * **the true sprite origins**. Game Maker keeps the origin in the resource
    tree, which is exactly why `barrel_pivot()` had to infer a turret's pivot
    from the shape of its base. The real number is a field in this record.

A GM 7.0 sprite record, read off this build's own tree rather than taken from a
reference implementation (the frame stamp here is 540, not the 800 later
versions use, and the pixels are deflated, not raw):

    [u32 name_len][name][u32 version == 542]
    [u32 w][u32 h][i32 bbox l,r,b,t][u32 transparent][u32 smooth][u32 preload]
    [u32 bbox_mode][u32 precise][i32 origin_x][i32 origin_y][u32 frame_count]
    per frame:  [u32 540][u32 1][u32 w][u32 h][u32 len][zlib -> w*h*4 BGRA]

Rather than walk every section of the tree to reach the sprite list, the records
are located directly and the format is made to verify itself -- the same tactic
`gm7tree.py` uses for rooms. A plausible identifier, then exactly 542, then a
frame stamped 540 whose zlib stream inflates to exactly w*h*4: nothing
accidental survives all of that.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import struct
import sys
import zlib

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import paths    # noqa: E402
import gm7  # noqa: E402

SPRITE_VERSION = 542
#: Frame records in this build stamp 540, not the 800 that later GM versions use
#: -- read off the real tree rather than taken from a reference implementation.
FRAME_VERSION = 540

#: Field order after the version word, confirmed against known sprites:
#: spr_core is 80x80 with origin (40,40) and 8 frames; spr_bridge is 15x15 with
#: origin (7,7), which is its exact centre.
#:   w, h, bbox_left, bbox_right, bbox_bottom, bbox_top,
#:   transparent, smooth_edges, preload, bounding_box_mode, precise_collision,
#:   origin_x, origin_y, frame_count
F_W, F_H, F_ORIGIN_X, F_ORIGIN_Y, F_COUNT = 0, 1, 11, 12, 13
HEADER_WORDS = 14
NAME_RE = re.compile(rb'^[A-Za-z_][A-Za-z0-9_ ]{0,63}$')

CACHE = pathlib.Path(__file__).resolve().parent / '.cache' / 'exeart'
DEFAULT_EXE = paths.SHIPMAKER_EXE


def u32(buf: bytes, pos: int) -> int:
    return struct.unpack_from('<I', buf, pos)[0]


def i32(buf: bytes, pos: int) -> int:
    return struct.unpack_from('<i', buf, pos)[0]


def parse_sprite(plain: bytes, pos: int) -> dict | None:
    """Parse a sprite whose name-length field starts at `pos`, or None."""
    n = u32(plain, pos)
    if n == 0 or n > 64 or pos + 4 + n + 16 > len(plain):
        return None
    name = plain[pos + 4:pos + 4 + n]
    if not NAME_RE.match(name):
        return None
    p = pos + 4 + n
    if u32(plain, p) != SPRITE_VERSION:
        return None
    p += 4

    if p + HEADER_WORDS * 4 > len(plain):
        return None
    hdr = [i32(plain, p + 4 * k) for k in range(HEADER_WORDS)]
    sw, sh = hdr[F_W], hdr[F_H]
    ox, oy = hdr[F_ORIGIN_X], hdr[F_ORIGIN_Y]
    count = hdr[F_COUNT]
    p += HEADER_WORDS * 4
    if not (0 <= count <= 4096) or sw < 0 or sh < 0:
        return None

    frames = []
    for _ in range(count):
        if p + 20 > len(plain):
            return None
        if u32(plain, p) != FRAME_VERSION:
            return None
        w, h, ln = u32(plain, p + 8), u32(plain, p + 12), u32(plain, p + 16)
        p += 20
        if ln == 0:                       # an empty frame is legal
            frames.append((w, h, b''))
            continue
        if w == 0 or h == 0 or p + ln > len(plain):
            return None
        # The self-check that makes this scan safe: the pixels are zlib-compressed
        # BGRA, so the stream must inflate to exactly w*h*4. Nothing accidental
        # gets past that.
        try:
            raw = zlib.decompress(plain[p:p + ln])
        except zlib.error:
            return None
        if len(raw) != w * h * 4:
            return None
        frames.append((w, h, raw))
        p += ln

    return {'name': name.decode('latin1'), 'origin': (ox, oy),
            'size': (sw, sh), 'frames': frames, 'end': p, 'start': pos}


def scan(plain: bytes) -> list[dict]:
    """Every sprite record in the tree, in file order."""
    out: list[dict] = []
    marker = struct.pack('<I', SPRITE_VERSION)
    pos = 0
    while True:
        hit = plain.find(marker, pos)
        if hit < 0:
            break
        pos = hit + 1
        # The version field sits just past [len][name]; step back over plausible
        # name lengths to find where the record actually begins.
        for nlen in range(1, 65):
            start = hit - nlen - 4
            if start < 0:
                break
            if u32(plain, start) != nlen:
                continue
            rec = parse_sprite(plain, start)
            if rec:
                out.append(rec)
                pos = max(pos, rec['end'])
                break
    return out


def to_image(w: int, h: int, data: bytes) -> Image.Image:
    """A frame's BGRA bytes as RGBA."""
    a = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 4)
    return Image.fromarray(a[..., [2, 1, 0, 3]].copy(), 'RGBA')


def extract(exe: pathlib.Path, out: pathlib.Path,
            only: str | None = None, write: bool = True) -> dict:
    _raw, (_pos, _clen, blob) = gm7.load(str(exe))
    plain, seed, _swap_start, swap_offset = gm7.gmkrypt_decrypt(blob)
    print(f'{exe.name}: tree {len(plain):,} B  seed={seed} swap_offset={swap_offset}')

    sprites = scan(plain)
    print(f'{len(sprites)} sprite records')

    index: dict[str, dict] = {}
    written = 0
    if write:
        out.mkdir(parents=True, exist_ok=True)
    for s in sprites:
        if only and only.lower() not in s['name'].lower():
            continue
        real = [f for f in s['frames'] if f[2]]
        index[s['name']] = {
            'origin': list(s['origin']),
            'frames': len(s['frames']),
            'size': list(s['size']),
        }
        if not write:
            continue
        for i, (w, h, data) in enumerate(s['frames']):
            if not data:
                continue
            p = out / (f'{s["name"]}.png' if len(real) == 1
                       else f'{s["name"]}_{i:02d}.png')
            to_image(w, h, data).save(p)
            written += 1
    if write:
        (out / 'index.json').write_text(json.dumps(index, indent=1, sort_keys=True))
        print(f'wrote {written} frames for {len(index)} sprites -> {out}')
    return index


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--exe', default=str(DEFAULT_EXE))
    ap.add_argument('-o', '--out', default=str(CACHE))
    ap.add_argument('--only', help='substring filter on the sprite name')
    ap.add_argument('--list', action='store_true', help='report only, write nothing')
    a = ap.parse_args()
    idx = extract(pathlib.Path(a.exe), pathlib.Path(a.out), a.only, write=not a.list)
    if a.list:
        for name in sorted(idx):
            d = idx[name]
            print(f'  {name:<28} {d["size"][0]:>4}x{d["size"][1]:<4} '
                  f'frames={d["frames"]:<3} origin={d["origin"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

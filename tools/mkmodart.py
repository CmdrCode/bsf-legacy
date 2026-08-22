#!/usr/bin/env python3
"""Draw the mod-provided turret art into `mods/`, from code rather than by hand.

One sprite so far: `spr_UmbraCloak.png`, the Umbra Cloak's mount. It is original
art -- nothing here is extracted from the game or derived from its source -- but
it has to sit inside the game's own visual grammar to read as a module at all,
and that grammar is measured off the stock set:

  * **small**: `spr_Deflecctor` is 10x10, `spr_NanoMatrix` 15x15, `spr_Impeder`
    17x17. A module is a bead on a hull, not a turret.
  * **a 1px white rim over a mid-grey body**, which is what every one of them is.
  * **keyed, not alpha**. The game's loader calls `sprite_add(..., transparent=1)`
    and GM keys on the *bottom-left pixel's colour*; the stock turret sheets use
    `(0,128,64)` for it, so this does too. Writing an alpha channel instead would
    load as an opaque rectangle.

Shape: a nested diamond aperture with nothing in the middle. Distinctive on
purpose -- the stock modules are a circle with a bite, a spiked ring, a square
frame, an I-beam, a capsule and a snowflake, and not one of them is a diamond,
so the silhouette is unambiguous at 15px. The void at the centre is the whole
idea of the device.

    python3 tools/mkmodart.py            # writes mods/spr_UmbraCloak.png
    python3 tools/mkmodart.py --show     # ... and prints it as ASCII
"""
from __future__ import annotations

import argparse
import pathlib

import numpy as np
from PIL import Image

#: GM keys transparency on the bottom-left pixel; the stock turret sheets put
#: this colour there, so the whole set keys the same way.
KEY = (0, 128, 64)
RIM = (255, 255, 255)
BODY = (128, 128, 128)

#: Odd, so there is a true centre pixel to build the aperture around.
N = 15
C = N // 2

#: Chebyshev would give a square and Euclid a circle; the L1 (taxicab) metric is
#: what makes a diamond, and it lands exactly on pixel centres at every radius.
RIM_R, BODY_R, EYE_R = 7, (4, 6), 3


def draw() -> np.ndarray:
    a = np.zeros((N, N, 3), np.uint8)
    a[:, :] = KEY
    for y in range(N):
        for x in range(N):
            d = abs(x - C) + abs(y - C)
            if BODY_R[0] <= d <= BODY_R[1]:
                a[y, x] = BODY
            elif d == RIM_R or d == EYE_R:
                a[y, x] = RIM
    return a


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', '--out')
    ap.add_argument('--show', action='store_true')
    args = ap.parse_args()

    out = pathlib.Path(args.out) if args.out else (
        pathlib.Path(__file__).resolve().parent.parent / 'mods' / 'spr_UmbraCloak.png')
    a = draw()
    Image.fromarray(a).save(out)
    print(f'{out}  {N}x{N}  origin ({C},{C})')
    if args.show:
        for row in a:
            print(''.join('#' if tuple(p) == RIM else
                          '+' if tuple(p) == BODY else '.' for p in row))


if __name__ == '__main__':
    main()

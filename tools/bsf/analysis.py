#!/usr/bin/env python3
"""Pixel-level facts about a ship, all derived from one render.

`ship check` is a query over a picture, not a second geometry engine. One pass
writes an id buffer (which part won each pixel) and a coverage mask per part
(which pixels that part *would* have won alone), and everything else -- what is
visible, what is buried, what touches what, what floats, what encloses a hole --
falls out of comparing those two.

Doing it this way is what makes the answers agree with the render the user is
looking at. A geometric occlusion test over rotated bounding boxes would call
plates "overlapping" that visibly are not, because BSF section art is mostly
transparent inside its own bounding box.

Two things this deliberately does not do:

**It does not have an opinion about overlap.** Overlap is how BSF hulls are
built -- deliberately stacked 80x80 plates -- so listing intersecting pairs
would flag nearly every pair on every ship. Only `check` gets an opinion, and
only about duplicates, floats and holes (D23).

**It is not cached to disk.** A full scene build and render is 5-10 ms on real
ships, so a revision-keyed disk cache would cost more in staleness risk than it
saves. One render per process, memoised, *is* the per-revision cache -- a
command reads the file once.
"""
from __future__ import annotations

import math

import numpy as np

import render as _render

#: Everything is measured at 1 BSF pixel = 1 image pixel. Supersampling would
#: change every count reported here for no gain in fidelity.
SCALE = 1


class Analysis:
    """One render, plus the questions answerable from it.

    Indices throughout are **op indices** into `scene['ops']`, not part ids --
    a section and a weapon can share id 0, and only the op index is unique.
    """

    def __init__(self, sc: dict, pad: int = 8):
        self.sc = sc
        self.ops = sc['ops']
        _img, ids, info = _render.render(sc, scale=SCALE, pad=pad, want_masks=True)
        self.ids: np.ndarray = ids
        self.masks: list[np.ndarray] = info['masks']
        self.w, self.h = info['w'], info['h']
        self.cx, self.cy = info['cx'], info['cy']

        self.area = [int(m.sum()) for m in self.masks]
        self.visible = [int((ids == i).sum()) for i in range(len(self.ops))]
        self._boxes = [_bbox(m) for m in self.masks]
        self._adj: dict[int, set[int]] | None = None

    # -- per part ----------------------------------------------------------
    def occluded(self, i: int) -> float:
        """Fraction of a part's own pixels that something else won.

        Reported as data, never as a defect: buried plate is armour. Sections
        carry 196-375 HP each against a hull `maxhp` of 300, so a 96%-hidden
        plate is still a quarter-tonne of armour an enemy has to chew through.
        """
        a = self.area[i]
        return 0.0 if a == 0 else round(1.0 - self.visible[i] / a, 4)

    def index_of(self, kind: str, part_id: int) -> int | None:
        for i, o in enumerate(self.ops):
            if o['kind'] == kind and o['id'] == part_id:
                return i
        return None

    # -- between parts -----------------------------------------------------
    def within(self, i: int, dist: float) -> set[int]:
        """Op indices whose coverage comes within `dist` pixels of part `i`.

        Chebyshev distance, computed by box-dilating one mask -- exact, one pass
        over the canvas, and no dependency on scipy. `dist = 0` is plain
        overlap; `dist = 1` is overlap-or-adjacent, which is what "touching"
        means for pixel art on an integer grid.
        """
        if not (0 <= i < len(self.masks)):
            return set()
        grown = _dilate(self.masks[i], int(math.ceil(dist)))
        gb = _bbox(grown)
        out = set()
        for j, m in enumerate(self.masks):
            if j == i or not _overlap(gb, self._boxes[j]):
                continue
            if (grown & m).any():
                out.add(j)
        return out

    def touching(self, i: int) -> set[int]:
        return self.within(i, 1)

    @property
    def adjacency(self) -> dict[int, set[int]]:
        """The full touch graph, built once."""
        if self._adj is None:
            adj: dict[int, set[int]] = {i: set() for i in range(len(self.masks))}
            for i in range(len(self.masks)):
                for j in self.touching(i):
                    adj[i].add(j)
                    adj[j].add(i)
            self._adj = adj
        return self._adj

    # -- whole ship --------------------------------------------------------
    def islands(self) -> list[list[int]]:
        """Connected groups of parts, largest first.

        More than one means something is physically detached from the hull. The
        group holding the core is the ship; the rest are floating.
        """
        adj = self.adjacency
        seen: set[int] = set()
        out: list[list[int]] = []
        for start in range(len(self.masks)):
            if start in seen:
                continue
            comp, stack = [], [start]
            seen.add(start)
            while stack:
                cur = stack.pop()
                comp.append(cur)
                for nxt in adj[cur]:
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            out.append(sorted(comp))
        out.sort(key=len, reverse=True)
        return out

    @property
    def silhouette(self) -> np.ndarray:
        return self.ids >= 0

    def holes(self, min_size: int = 4) -> list[dict]:
        """Enclosed pockets of background inside the hull outline.

        A hole is a connected region of background that cannot reach the edge of
        the canvas. One labelling pass answers it: every background region that
        does not touch the border is a hole, and its size and centroid come out
        of the same labels.
        """
        labels, n = _label(~self.silhouette)
        if n == 0:
            return []
        outside = set(labels[0].tolist()) | set(labels[-1].tolist()) \
            | set(labels[:, 0].tolist()) | set(labels[:, -1].tolist())
        sizes = np.bincount(labels.ravel(), minlength=n + 1)

        out = []
        for lab in range(1, n + 1):
            if lab in outside or sizes[lab] < min_size:
                continue
            py, px = np.nonzero(labels == lab)
            out.append({
                'pixels': int(sizes[lab]),
                'x': round(float(px.mean()) - self.cx, 1),
                'y': round(float(py.mean()) - self.cy, 1),
                'parts': self._surrounds(labels == lab),
            })
        out.sort(key=lambda d: -d['pixels'])
        return out

    def _surrounds(self, hole: np.ndarray) -> list[int]:
        """Which parts form the rim of a pocket.

        This is what separates a gap from a window. Section art is full of
        interior transparency -- vents, canopies, cut-outs -- and every one of
        those is background fully enclosed by the outline, so a naive hole test
        reports the artwork. A pocket rimmed by a *single* part is that part's
        own art; a pocket rimmed by two or more is a place where plates failed
        to meet, which is the thing worth saying.
        """
        ys, xs = np.nonzero(hole)
        y0, y1 = max(0, ys.min() - 2), min(self.h, ys.max() + 3)
        x0, x1 = max(0, xs.min() - 2), min(self.w, xs.max() + 3)
        sub = hole[y0:y1, x0:x1]
        ring = _dilate(sub, 1) & ~sub
        owners = self.ids[y0:y1, x0:x1][ring]
        return sorted({int(v) for v in np.unique(owners) if v >= 0})


# --------------------------------------------------------------------------
# small array helpers
# --------------------------------------------------------------------------

def _bbox(m: np.ndarray) -> tuple[int, int, int, int] | None:
    """(x0, y0, x1, y1) half-open, or None for an empty mask."""
    ys, xs = np.nonzero(m)
    if len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _overlap(a, b) -> bool:
    if a is None or b is None:
        return False
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _label(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Label 4-connected True regions, 1..n. Returns (labels, n).

    A scanline fill: claim the whole horizontal run in one slice assignment and
    only push the *start* of each new run in the rows above and below. That
    keeps the Python loop proportional to the number of runs rather than the
    number of pixels, which matters because the background of a ship canvas is
    a hundred thousand pixels and a per-pixel fill takes minutes.
    """
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    n = 0
    for sy in range(h):
        for sx in np.nonzero(mask[sy] & (labels[sy] == 0))[0]:
            if labels[sy, sx]:
                continue
            n += 1
            stack = [(sy, int(sx))]
            while stack:
                y, x = stack.pop()
                if labels[y, x] or not mask[y, x]:
                    continue
                x0 = x
                while x0 > 0 and mask[y, x0 - 1] and not labels[y, x0 - 1]:
                    x0 -= 1
                x1 = x
                while x1 < w - 1 and mask[y, x1 + 1] and not labels[y, x1 + 1]:
                    x1 += 1
                labels[y, x0:x1 + 1] = n
                for ny in (y - 1, y + 1):
                    if not (0 <= ny < h):
                        continue
                    seg = mask[ny, x0:x1 + 1] & (labels[ny, x0:x1 + 1] == 0)
                    if not seg.any():
                        continue
                    starts = np.nonzero(np.diff(seg.astype(np.int8), prepend=0) == 1)[0]
                    stack += [(ny, x0 + int(o)) for o in starts]
    return labels, n


def _dilate(m: np.ndarray, r: int) -> np.ndarray:
    """Box-dilate by `r` pixels: a max filter, done as shifted ORs.

    Separable, so 2r shifts rather than (2r+1)^2 -- fast enough that the query
    layer can afford to call it per predicate rather than precomputing an n^2
    distance matrix that most queries would never read.
    """
    if r <= 0:
        return m.copy()
    out = m.copy()
    for _ in range(r):
        out[:, :-1] |= out[:, 1:].copy()
        out[:, 1:] |= out[:, :-1].copy()
    for _ in range(r):
        out[:-1, :] |= out[1:, :].copy()
        out[1:, :] |= out[:-1, :].copy()
    return out

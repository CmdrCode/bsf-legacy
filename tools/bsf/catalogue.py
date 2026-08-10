#!/usr/bin/env python3
"""The parts catalogue: what a sprite looks like, and what ships put next to it.

There are hundreds of section sprites on disk and picking one by filename is not
viable, but rendering all of them for every decision is not viable either. So
two indexes, both derived and neither hand-authored (D21):

**Shape metrics.** Bounding box, fill, centroid, symmetry and per-edge
straightness for every sprite, cached to the gitignored directory and rebuilt
when the install changes. Filter down to a handful, then look at a contact sheet.

**Co-occurrence.** What real ships actually place beside what, mined from every
ship file on disk. No invented taxonomy and no manual tagging -- if authors put
`BSF_Stock17` next to `BSF_Stock22` two hundred times, that is a fact about the
part, and if they never did, that is a fact too.

**Every metric is continuous, and that is the point.** An earlier pass tested
symmetry as exact array equality and flat edges at 80% solid; the first fired on
1 of 14 stock parts and the second on 6 of 14, because hand-drawn masks are
*near*-symmetric, not symmetric. Reporting scores and letting the query pick the
threshold is the fix -- `symh > 0.9` finds what `symmetric` missed.

**Sample size is honest or it is nothing.** `parts near` prints the number of
placements its answer rests on. Stock Sections are well covered; the Kae and Dan
packs are thin, and a co-occurrence built on four placements says so.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import paths    # noqa: E402
import model      # noqa: E402
import sprites    # noqa: E402

CACHE = pathlib.Path(__file__).resolve().parent / '.cache' / 'catalogue'
PARTS = CACHE / 'parts.json'
NEAR = CACHE / 'cooccurrence.json'

#: Where the corpus lives. Same roots the round-trip gate walks.
SHIP_ROOTS = [paths.SHIPS, paths.GAME.parent]

#: Folders whose sprites are hull sections. Others are catalogued too -- the
#: `folder` field is queryable -- but these are what `parts` defaults to.
SECTION_FOLDERS = ('Stock Sections', 'Sections', 'Old Sections', 'Kae_stock',
                   'Kae_generic', 'Kae_detail', 'Kae_small', 'Kae_misc',
                   'Kae_alien')

FIELDS = {'name', 'folder', 'w', 'h', 'bw', 'bh', 'px', 'fill', 'aspect',
          'cx', 'cy', 'symh', 'symv', 'flat_n', 'flat_e', 'flat_s', 'flat_w',
          'radius'}


# --------------------------------------------------------------------------
# shape metrics
# --------------------------------------------------------------------------

def measure(mask: np.ndarray) -> dict:
    """Shape facts about one sprite's opaque coverage.

    `symh` is the fraction of pixels that agree with their reflection about the
    vertical axis -- 1.0 is perfectly symmetric left-to-right. `flat_n` and
    friends are how solid the outermost row or column of the bounding box is,
    which is what decides whether a plate can butt cleanly against another.
    """
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return {}
    h, w = mask.shape
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
    box = mask[y0:y1, x0:x1]
    bh, bw = box.shape
    px = int(box.sum())

    def agree(a, b):
        return round(float((a == b).sum()) / a.size, 4) if a.size else 0.0

    return {
        'w': w, 'h': h, 'bw': bw, 'bh': bh, 'px': px,
        'fill': round(px / (bw * bh), 4),
        'aspect': round(bw / bh, 4) if bh else 0.0,
        # centroid, as an offset from the box centre in units of the box size:
        # 0 is centred, +0.5 is hard against the right or bottom edge.
        'cx': round(float(xs.mean() - (x0 + x1) / 2) / bw, 4),
        'cy': round(float(ys.mean() - (y0 + y1) / 2) / bh, 4),
        'symh': agree(box, box[:, ::-1]),
        'symv': agree(box, box[::-1, :]),
        'flat_n': round(float(box[0].mean()), 4),
        'flat_s': round(float(box[-1].mean()), 4),
        'flat_w': round(float(box[:, 0].mean()), 4),
        'flat_e': round(float(box[:, -1].mean()), 4),
        # half-diagonal of the filled box: the radius used to decide whether
        # two placements in a real ship are neighbours.
        'radius': round(float(np.hypot(bw, bh)) / 2, 2),
    }


def _install_stamp() -> float:
    """Newest mtime under the sprite tree, so the cache dies with an install."""
    newest = 0.0
    if sprites.SPRITES.exists():
        for p in sprites.SPRITES.rglob('*'):
            if p.is_file():
                newest = max(newest, p.stat().st_mtime)
    return round(newest, 3)


def build_parts(force: bool = False) -> dict:
    """Measure every sprite on disk. Cached; rebuilt when the install changes."""
    stamp = _install_stamp()
    if PARTS.exists() and not force:
        try:
            got = json.loads(PARTS.read_text())
            if got.get('stamp') == stamp:
                return got
        except ValueError:
            pass

    out: dict[str, dict] = {}
    for folder in sorted({p.name for p in sprites.SPRITES.iterdir() if p.is_dir()}
                         if sprites.SPRITES.exists() else []):
        for f in sorted((sprites.SPRITES / folder).iterdir()):
            if f.suffix.lower() not in ('.png', '.gif'):
                continue
            try:
                sp = sprites.load(str(f), mask=True, pivot=False)
            except Exception:
                continue
            m = measure(sp.frames[0][..., 3] > 127)
            if not m:
                continue
            m['name'] = f.stem
            m['folder'] = folder
            m['ref'] = f'{folder}\\{f.name}'
            out[m['ref']] = m

    CACHE.mkdir(parents=True, exist_ok=True)
    data = {'stamp': stamp, 'parts': out}
    PARTS.write_text(json.dumps(data))
    return data


# --------------------------------------------------------------------------
# corpus mining
# --------------------------------------------------------------------------

#: sh1 is raw GML: a creation call, then the sprite on a following line. The
#: object is `ShipSection` on player hulls and `EShipSection` on enemy ones --
#: same geometry, and skipping the enemy variant would drop two thirds of the
#: corpus, since most shipped .shp files are campaign opponents.
SH1_CREATE = re.compile(r'instance_create\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*'
                        r'[A-Za-z_]*ShipSection\s*\)')
SH1_SPRITE = re.compile(r'sprite_index\s*=\s*([A-Za-z_]\w*)')
#: sh2 packs the same thing into one call.
SH2_SEC = re.compile(r'\bnSec\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*([A-Za-z_]\w*)')


def placements(path: pathlib.Path) -> list[tuple[str, float, float]]:
    """(sprite ref, x, y) for one ship, core-relative, whatever generation.

    Four formats say the same thing four ways, and all four are mined -- an
    earlier pass could only read sh2/sh3/sb4 and reported a corpus of ~69 ships,
    because the 161 sh1 files are raw Game Maker source rather than records. They
    are perfectly regular source, though, so a two-line regex recovers them and
    roughly triples the sample.
    """
    try:
        text, _ = model.decode(path.read_bytes())
    except OSError:
        return []
    out: list[tuple[str, float, float]] = []

    if '//sb4' in text[:64]:
        ship = model.load(path)
        for s in ship.sections:
            out.append((s.sprite, s.x, s.y))
        return out

    if '//sh3' in text[:64]:
        for line in text.splitlines():
            if not line.startswith('nSec2a,'):
                continue
            t = line[len('nSec2a,'):].split(',')
            if len(t) < 3:
                continue
            try:
                out.append((t[2].strip().strip('"'), float(t[0]), float(t[1])))
            except ValueError:
                continue
        return out

    for m in SH2_SEC.finditer(text):
        out.append((m.group(3), float(m.group(1)), float(m.group(2))))
    if out:
        return out

    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = SH1_CREATE.search(line)
        if not m:
            continue
        for nxt in lines[i + 1:i + 4]:
            s = SH1_SPRITE.search(nxt)
            if s:
                out.append((s.group(1), float(m.group(1)), float(m.group(2))))
                break
    return out


def corpus_files() -> list[pathlib.Path]:
    seen: dict[str, pathlib.Path] = {}
    for root in SHIP_ROOTS:
        if not root.exists():
            continue
        for p in sorted(root.rglob('*')):
            if p.is_file() and p.suffix.lower() in ('.shp', '.sb4'):
                seen.setdefault(p.name.lower(), p)
    return sorted(seen.values())


def _canonical(ref: str, parts: dict) -> str | None:
    """Map any generation's way of naming a sprite onto one catalogue key."""
    p = sprites.resolve(ref)
    if p is None:
        return None
    key = f'{p.parent.name}\\{p.name}'
    return key if key in parts else None


def build_cooccurrence(force: bool = False) -> dict:
    """Which sprites real ships place beside which.

    Two placements are neighbours when their centres are closer than the sum of
    the sprites' radii -- size-aware rather than a flat threshold, so a 12 px
    detail piece is not called a neighbour of everything within 40 px of it.
    """
    cat = build_parts()
    parts, stamp = cat['parts'], cat['stamp']
    if NEAR.exists() and not force:
        try:
            got = json.loads(NEAR.read_text())
            if got.get('stamp') == stamp:
                return got
        except ValueError:
            pass

    pair: dict[str, dict[str, int]] = {}
    count: dict[str, int] = {}
    ships = used = 0
    total = 0
    for f in corpus_files():
        pl = placements(f)
        ships += 1
        rows = []
        for ref, x, y in pl:
            key = _canonical(ref, parts)
            if key is None:
                continue
            rows.append((key, x, y, parts[key]['radius']))
        if not rows:
            continue
        used += 1
        total += len(rows)
        for k, _x, _y, _r in rows:
            count[k] = count.get(k, 0) + 1
        for i in range(len(rows)):
            ka, xa, ya, ra = rows[i]
            for j in range(i + 1, len(rows)):
                kb, xb, yb, rb = rows[j]
                if (xa - xb) ** 2 + (ya - yb) ** 2 > (ra + rb) ** 2:
                    continue
                pair.setdefault(ka, {})[kb] = pair.setdefault(ka, {}).get(kb, 0) + 1
                pair.setdefault(kb, {})[ka] = pair.setdefault(kb, {}).get(ka, 0) + 1

    CACHE.mkdir(parents=True, exist_ok=True)
    data = {'stamp': stamp, 'files': ships, 'parsed': used,
            'placements': total, 'count': count, 'pairs': pair}
    NEAR.write_text(json.dumps(data))
    return data


# --------------------------------------------------------------------------
# queries and output
# --------------------------------------------------------------------------

class Sprite:
    """A catalogue row, in the shape the query grammar expects."""

    __slots__ = ('d',)

    def __init__(self, d: dict):
        self.d = d

    def field(self, name: str):
        if name not in self.d:
            raise KeyError(name)
        return self.d[name]

    def __getattr__(self, name):
        return self.d[name]


def search(where: str | None, folders=SECTION_FOLDERS, limit: int = 40):
    import query
    rows = [Sprite(d) for d in build_parts()['parts'].values()
            if folders is None or d['folder'] in folders]
    if where:
        words = {'all': lambda p, c: True}
        pred = query.Parser(where, fields=FIELDS, words=words).parse()
        rows = [r for r in rows if pred(r, None)]
    rows.sort(key=lambda r: (r.folder, r.name))
    return rows[:limit], len(rows)


def sheet(rows, out: str, cell: int = 96, cols: int = 8,
          tint=(120, 235, 130)) -> str:
    """A contact sheet: the shortlist, drawn, with names under each.

    The point of the metrics is to get from hundreds of parts to a dozen; the
    point of this is to then actually look at the dozen.
    """
    from PIL import ImageDraw, ImageFont
    try:
        font = ImageFont.load_default()
    except OSError:
        font = None
    rows = list(rows)
    cols = max(1, min(cols, len(rows) or 1))
    n = len(rows)
    grid_h = (n + cols - 1) // cols
    label = 12
    img = Image.new('RGB', (cols * cell, grid_h * (cell + label)), (5, 7, 10))
    draw = ImageDraw.Draw(img)

    for i, r in enumerate(rows):
        path = sprites.SPRITES / r.d['ref'].replace('\\', '/')
        try:
            sp = sprites.load(str(path), mask=True, pivot=False)
        except Exception:
            continue
        a = sp.frames[0].astype(np.float32)
        a[..., 0] *= tint[0] / 255
        a[..., 1] *= tint[1] / 255
        a[..., 2] *= tint[2] / 255
        tile = Image.fromarray(a.clip(0, 255).astype(np.uint8), 'RGBA')
        if max(tile.size) > cell - 6:
            k = (cell - 6) / max(tile.size)
            tile = tile.resize((max(1, int(tile.width * k)),
                               max(1, int(tile.height * k))), Image.NEAREST)
        cx = (i % cols) * cell + (cell - tile.width) // 2
        cy = (i // cols) * (cell + label) + (cell - tile.height) // 2
        img.paste(tile, (cx, cy), tile)
        draw.text(((i % cols) * cell + 2,
                   (i // cols) * (cell + label) + cell), r.name[:16],
                  fill=(150, 170, 150), font=font)
    img.save(out)
    return f'{n} part(s), {cols}x{grid_h}, {img.width}x{img.height}'


def neighbours(ref: str, limit: int = 15):
    """(rows, support, corpus) -- what gets placed next to this part, and how sure."""
    data = build_cooccurrence()
    parts = build_parts()['parts']
    key = _canonical(ref, parts)
    if key is None:
        for k in parts:
            if k.rsplit('\\', 1)[-1].lower().startswith(ref.lower()):
                key = k
                break
    if key is None:
        return None, 0, data
    pairs = data['pairs'].get(key, {})
    rows = sorted(pairs.items(), key=lambda kv: -kv[1])[:limit]
    return (key, rows), data['count'].get(key, 0), data

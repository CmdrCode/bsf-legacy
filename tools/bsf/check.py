#!/usr/bin/env python3
"""`ship check` -- an opinionated linter, and `ship visibility` -- plain data.

The split between them is the whole design (D23). Occlusion is **reported, never
warned about**: buried plate is armour. Every section on station_bolthole carries
between 196 and 375 HP against a hull `maxhp` of 300, and its twenty sections
total 5,269 HP, so a plate that is 96% hidden is still a quarter-tonne an enemy
has to chew through before the hull takes a scratch. An earlier draft of this
tool offered `remove --where 'occluded > 0.99'` as a cleanup; that would strip a
ship's armour, and it is withdrawn.

So `check` has an opinion about exactly five things, all of which are mistakes
rather than choices:

    duplicate    two parts at the same place with the same art and transform
    floating     a part not physically connected to the hull
    hole         background fully enclosed by the outline
    mirror       a pair that does not reflect, with the exact deviation
    dangling     a tier-2 record naming a part that is not there
    missing      a sprite that does not resolve

**A baseline, not a tolerance** (D20). There is no natural cutoff for mirror
drift: measured on a real hull, every angle is exactly right and every
positional offset is exactly 1.00 or 2.00 px -- whole-pixel nudges an author
made on purpose, not noise. A tolerance of 0.5 flags seven pairs, 1.0 flags one,
2.01 flags none; tuning it only moves an arbitrary line. So every deviation is
reported with its magnitude, `--accept` records the current set as known, and
later runs show only what is new. A finding whose magnitude *changes* is new
again, which is the point -- accepting 1 px of drift is not accepting 3.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import edits      # noqa: E402
import history    # noqa: E402
import model      # noqa: E402
import scene      # noqa: E402

#: Below this, an enclosed pocket is an artefact of two plates not quite meeting
#: rather than a gap anyone would see. Four pixels is two-by-two at 1:1.
MIN_HOLE = 4

#: Coordinates in a `.sb4` are written at two decimals, so anything under half a
#: unit in the last place is the same number written twice.
EPS = 0.005


class Finding:
    """One thing worth saying, with a key stable enough to accept.

    The key deliberately includes the magnitude: accepting `sections 5/6 drift
    dy 1.00` should not silently also accept `dy 12.00` later.
    """

    __slots__ = ('code', 'subject', 'detail')

    def __init__(self, code: str, subject: str, detail: str = ''):
        self.code = code
        self.subject = subject
        self.detail = detail

    @property
    def key(self) -> str:
        return f'{self.code}|{self.subject}|{self.detail}'

    def __str__(self) -> str:
        return f'{self.code:<9} {self.subject:<22} {self.detail}'


# --------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------

def duplicates(ship: model.Ship) -> list[Finding]:
    """Parts sitting exactly on top of each other with identical art.

    Not the same thing as overlap -- overlap is how BSF hulls are built. This is
    the double-paste: the same plate placed twice at the same coordinates with
    the same transform, which is invisible in the editor and does nothing but
    inflate the file.
    """
    seen: dict[tuple, list[str]] = {}
    for p in [('section', s) for s in ship.sections] + \
             [(m.kind, m) for m in ship.mounts]:
        kind, o = p
        k = (kind, o.sprite, round(o.x, 2), round(o.y, 2), round(o.angle, 2),
             round(o.xscale, 2), round(o.yscale, 2))
        seen.setdefault(k, []).append(f'{kind} {o.id}')
    out = []
    for k, who in sorted(seen.items(), key=lambda kv: kv[1]):
        if len(who) > 1:
            out.append(Finding('duplicate', ', '.join(who),
                               f'{k[1]} at {k[2]:+g},{k[3]:+g}'))
    return out


def mirror_pairs(ship: model.Ship) -> list[Finding]:
    """Every way a linked pair fails to be each other's reflection.

    Reflection across the core's horizontal centreline means `y -> -y` and
    `angle -> -angle` for everything, with x and xscale unchanged. `yscale` is
    the field that is **not** uniform: a section negates it, and so does a
    `Sidewinder` -- whose sprite is not symmetric about its barrel -- but an
    ordinary weapon, a module and a doodad all keep theirs, because ShipMaker's
    own mirror routine only touches their angle. Expecting a flip everywhere
    would report every correctly mirrored turret on every ship.

    Each axis is reported separately and with its magnitude, because they mean
    different things -- a y offset is a nudge, a wrong angle is a broken part.
    """
    out = []
    for kind in ('section', 'weapon', 'module', 'doodad'):
        pool = {s.id: s for s in ship.sections} if kind == 'section' else \
               {m.id: m for m in ship.mounts if m.kind == kind}
        for a, b in sorted(ship.mirror_map(kind).items()):
            if b <= a or a not in pool or b not in pool:
                continue                       # each pair once; missing = dangling
            p, q = pool[a], pool[b]
            who = f'{kind}s {a}/{b}'
            flips_y = kind == 'section' or p.name == 'Sidewinder'
            dys = q.yscale + p.yscale if flips_y else q.yscale - p.yscale
            for label, got in (
                ('dx', round(q.x - p.x, 2)),
                ('dy', round(q.y + p.y, 2)),
                ('dangle', round(_wrap(q.angle + p.angle), 2)),
                ('dxscale', round(q.xscale - p.xscale, 2)),
                ('dyscale', round(dys, 2)),
            ):
                if abs(got) > EPS:
                    out.append(Finding('mirror', who, f'{label} {got:+g}'))
            if p.sprite != q.sprite:
                out.append(Finding('mirror', who,
                                   f'different art: {p.name} vs {q.name}'))
    return out


def _wrap(a: float) -> float:
    """Fold an angle sum into (-180, 180]; -180 and +180 are the same heading."""
    a = (a + 180) % 360 - 180
    return a


def lone_offcentre(ship: model.Ship) -> list[Finding]:
    """Sections off the centreline with no partner.

    Deliberate on an asymmetric design and a slip on a symmetric one, so it is
    reported as its own code -- `check --accept` can retire the whole class in
    one go on a ship that means it.
    """
    out = []
    for s in ship.sections:
        if abs(s.y) < 1:
            continue
        if ship.mirrors.get(s.id, model.UNMIRRORED) < 0:
            out.append(Finding('unpaired', f'section {s.id}',
                               f'{s.name} at {s.x:+g},{s.y:+g}, no nSecMir'))
    return out


def pixel_findings(ship: model.Ship, sc: dict) -> tuple[list[Finding], object]:
    """Floats and holes -- the two that need to know what the ship looks like."""
    import analysis
    an = analysis.Analysis(sc)
    out: list[Finding] = []

    core = an.index_of('core', 0)
    groups = an.islands()
    hull: set[int] = set()
    for g in groups:
        if core is None or core in g:
            hull = set(g)
            break
    if not hull and groups:
        hull = set(groups[0])
    for g in groups:
        if set(g) == hull:
            continue
        who = ', '.join(f'{an.ops[i]["kind"]} {an.ops[i]["id"]}' for i in sorted(g))
        out.append(Finding('floating', who[:60],
                           f'{len(g)} part(s) not touching the hull'))

    for h in an.holes(MIN_HOLE):
        if len(h['parts']) < 2:
            continue                       # a window in one part's own art
        who = ', '.join(f'{an.ops[i]["kind"]} {an.ops[i]["id"]}'
                        for i in h['parts'][:4])
        out.append(Finding('hole', f'at {h["x"]:+g},{h["y"]:+g}',
                           f'{h["pixels"]} px between {who}'))
    return out, an


def run(ship: model.Ship) -> tuple[list[Finding], object]:
    """Every check, in the order a reader wants them: art, then structure."""
    sc = scene.build(ship)
    out: list[Finding] = []
    for name in sorted(sc['missing']):
        out.append(Finding('missing', name, 'no sprite file resolves'))
    out += duplicates(ship)
    pix, an = pixel_findings(ship, sc)
    out += pix
    out += mirror_pairs(ship)
    out += lone_offcentre(ship)
    out += [Finding('dangling', d, '') for d in edits.dangling(ship)]
    return out, an


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def report(path: pathlib.Path, ship: model.Ship, *, accept: bool = False,
           show_all: bool = False) -> int:
    found, _an = run(ship)
    known = set(history.read_baseline(path))
    fresh = [f for f in found if f.key not in known]

    if accept:
        history.write_baseline(path, [f.key for f in found], f'on {path.name}')
        print(f'{path.name}: {len(found)} finding(s) accepted as the baseline')
        for f in found:
            print(f'  {f}')
        return 0

    shown = found if show_all else fresh
    if not found:
        print(f'{path.name}: clean')
        return 0
    if not shown:
        print(f'{path.name}: clean  ({len(found)} accepted, --all to list)')
        return 0

    tail = f'  ({len(found) - len(fresh)} accepted)' if known and not show_all else ''
    print(f'{path.name}: {len(shown)} finding(s){tail}')
    for f in shown:
        mark = ' ' if f.key in known else '!'
        print(f' {mark} {f}')
    return 1


def visibility(path: pathlib.Path, ship: model.Ship, as_json: bool = False) -> int:
    """What each part contributes to the picture. Data, not judgement.

    `own` is the pixels a part would paint alone, `shown` is what it actually
    won, and `hidden` is the difference as a fraction. A high figure is a
    statement about layering, not a defect -- see this module's docstring.
    """
    import analysis
    sc = scene.build(ship)
    an = analysis.Analysis(sc)
    rows = []
    for i, op in enumerate(an.ops):
        rows.append({'kind': op['kind'], 'id': op['id'], 'name': op['name'],
                     'own': an.area[i], 'shown': an.visible[i],
                     'hidden': an.occluded(i)})
    rows.sort(key=lambda r: -r['hidden'])

    if as_json:
        import json
        print(json.dumps(rows, indent=2))
        return 0

    total = int((an.ids >= 0).sum())
    print(f'{ship.name}  {an.w}x{an.h}px  {total} px of ship  '
          f'{len(rows)} parts')
    print(f'  {"part":<20}{"own":>7}{"shown":>7}{"hidden":>8}')
    for r in rows:
        bar = '#' * int(r['hidden'] * 20)
        print(f'  {r["kind"] + " " + str(r["id"]):<20}{r["own"]:>7}'
              f'{r["shown"]:>7}{r["hidden"] * 100:>7.1f}%  {bar}')
    return 0

#!/usr/bin/env python3
"""Moor one of the game's own ships inside a `.sb4`, as scenery.

A station wants ships docked at it, and the game already has sixty-three of
them -- but they live as Game Maker source (`sh1`), not as records, so nothing
could read them into the editor. This turns that source into real `nSecA` and
`nWepA/B` records in a target ship file.

Three things have to survive the trip or the result is not usable:

**The hierarchy.** sh1 declares attachment the other way round from `.sb4` --
`l_section[j].l_child[...] = l_section[j-1]` means *j owns j-1*, so the parent
link runs backwards from what the file format wants. Get it wrong and a hull
that should come apart in one piece comes apart in twelve. A ship also has
several sections attached to its own core rather than to each other, which have
nowhere to hang once the core is gone; they are re-hung on the first of them, so
the whole hull has exactly one root and `remove <root>` takes all of it.

**The weapons.** A warship without its turrets does not read as a warship. The
`nWepB` layout past `parent.secid` was never recovered, so it is cloned from a
real weapon on a real ship rather than invented -- the same donor argument as
D16, for the same reason.

**Damage.** Knocking a section out has to take everything hanging off it, which
is what `remove_section`'s cascade already does. Orphaning the children instead
leaves parts floating in space where the hull used to be.
"""
from __future__ import annotations

import functools
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import paths    # noqa: E402
import edits     # noqa: E402
import gm7       # noqa: E402
import gmobj     # noqa: E402
import model     # noqa: E402
import sprites   # noqa: E402

GML = paths.GML

#: A real weapon, to clone the unrecovered tail of `nWepB` from.
DONOR_SHIP = paths.PENDULUM

#: Game Maker's `make_color_rgb`: red in the low byte, blue in the high one.
#: (A `$RRGGBB`-looking hex literal in GML source is therefore BGR.)
def gm_rgb(r: int, g: int, b: int) -> int:
    return int(r) + int(g) * 256 + int(b) * 65536


#: Scorched hull, for ships shown as wrecks.
DAMAGE_TINT = gm_rgb(214, 84, 52)

#: The core hull every ship draws under its plating. Only frame 0 exists on
#: disk (the other seven live in the exe), so all moored ships share one core
#: shape rather than their own -- visible only if you know to look for it.
CORE_SPRITE = 'Stock Misc\\spr_Core.gif'

@functools.lru_cache(maxsize=1)
def _hulls_in_exe() -> dict[str, str]:
    """Every stock hull's Create event, read straight out of the install.

    `paths.GML` is a dump scraped from a *running* game (`tools/dump_game.py`
    reads /proc/<pid>/mem under wine), so it exists on the machine that made it
    and nowhere else. Anyone patching their own copy has the game and this
    toolchain, nothing more -- and that is enough, because the definitions were
    in the exe all along: each hull is a Game Maker object whose Create event
    builds the sections, and the resource tree is plaintext once `gm7.py` undoes
    gmkrypt. Same trick `exeart.py` uses to recover the sprites.

    Costs one inflate + decrypt of a ~7 MB tree, so it is cached for the process.
    """
    exe = paths.require(paths.GAME / 'BattleshipsForever.exe', 'the game exe')
    _raw, (_pos, _clen, blob) = gm7.load(str(exe))
    plain, *_rest = gm7.gmkrypt_decrypt(blob)
    out: dict[str, str] = {}
    for pos in gmobj.candidates(plain):
        try:
            rec = gmobj.parse_object(plain, pos)
        except Exception:
            continue
        if not rec or rec[0]['name'] in out:
            continue
        obj = rec[0]
        for chunks in obj['events'].values():
            src = '\n'.join(chunks)
            if 'l_section[' in src:
                out[obj['name']] = src
                break
    return out


def source(name: str) -> str:
    """A stock hull's Game Maker source: the dump if there is one, else the exe.

    The dump wins when present only because it is already on disk; the two carry
    the same text, and the exe is the one that travels.
    """
    f = (next(GML.glob(f'{name}.player.gml'), None)
         or next(GML.glob(f'{name}.*.gml'), None))
    if f is not None:
        text, _ = model.decode(f.read_bytes())
        return text
    src = _hulls_in_exe().get(name)
    if src is None:
        raise FileNotFoundError(
            f'no source for ship {name!r}: not under {GML}, and not among the '
            f'{len(_hulls_in_exe())} hulls in {paths.GAME.name}')
    return src


def ship(name: str) -> model.Ship:
    """A stock hull as a `Ship`, ready for `scene.build()`."""
    return model.Ship(pathlib.Path(f'{name}.gml'), source(name), False)


def read(name: str) -> dict:
    """Parse a stock ship's Game Maker source into sections and weapons.

    The parsing itself lives in `model.parse_gml`: sh1 is a ship file format
    like any other, the model reads `.shp` files written in it, and two copies
    of a regex that has to know `l_child` runs backwards is one too many.
    """
    return model.parse_gml(source(name))


def _weapon_template() -> dict[str, list[str]]:
    """Token lists for a real weapon's records, to clone the unknown tail from."""
    out: dict[str, list[str]] = {}
    if not DONOR_SHIP.exists():
        return out
    donor = model.load(DONOR_SHIP)
    wid = None
    for r in donor.of_kind('nWepA'):
        wid = int(r.num(0))
        break
    if wid is None:
        return out
    for r in donor.records:
        if r.kind.startswith('nWep') and r.kind != 'nWepMir' and int(r.num(0)) == wid:
            out.setdefault(r.kind, list(r.tokens))
    return out


def dock(sh: model.Ship, name: str, x: float, y: float, *,
         tint: int | None = None, weapons: bool = True) -> tuple[int, list[int]]:
    """Moor a stock ship at a core-relative position. Returns (root, section ids).

    Sections keep the ship's own attachment tree, so removing any one of them
    takes its children with it. The tree's several roots are re-hung on the
    first, giving the hull a single handle.
    """
    spec = read(name)
    secs, parent = spec['sections'], spec['parent']
    order = sorted(secs)

    # Every BSF ship draws a core hull that its sections bolt onto; without one
    # the plates read as loose debris rather than a ship. A `.sb4` has room for
    # exactly one `nCor`, which the host station already owns, so a moored ship
    # gets its core as an ordinary section wearing the core sprite. It doubles
    # as the hull's single root: the ship's own core-attached sections hang off
    # it, so `remove <core>` takes the whole wreck and damage cascades properly.
    anchor, _n = edits.add_section(sh, CORE_SPRITE, round(x, 2), round(y, 2),
                                   parent=0, angle=0.0)
    if tint is not None:
        sh.section(anchor).rec.set_num(model.Section.IMAGE_BLEND, tint)

    made: dict[int, int] = {}            # ship index -> new secid
    todo = list(order)
    emitted = set()
    while todo:
        progress = False
        for i in list(todo):
            p = parent.get(i)
            if p is not None and p not in emitted:
                continue
            rec = secs[i]
            path = sprites.resolve(rec['obj'])
            if path is None:
                todo.remove(i)
                emitted.add(i)
                continue
            ref = f'{path.parent.name}\\{path.name}'
            par = made[p] if p is not None else anchor
            sid, _n = edits.add_section(
                sh, ref, round(x + rec['x'], 2), round(y + rec['y'], 2),
                parent=par, angle=rec['ang'], xscale=rec['xs'], yscale=rec['ys'])
            if tint is not None:
                sh.section(sid).rec.set_num(model.Section.IMAGE_BLEND, tint)
            made[i] = sid
            emitted.add(i)
            todo.remove(i)
            progress = True
        if not progress:                 # a cycle in the declared tree
            break

    if weapons:
        _add_weapons(sh, spec, made, x, y, tint, anchor)
    return anchor, sorted([anchor] + list(made.values()))


def _add_weapons(sh: model.Ship, spec: dict, made: dict[int, int],
                 x: float, y: float, tint: int | None, anchor: int) -> None:
    tpl = _weapon_template()
    if 'nWepA' not in tpl:
        return
    nxt = edits.next_mount_id(sh, 'weapon')
    after = edits._last_record(sh, ('nWepA', 'nWepB', 'nWepC', 'nWepD', 'nWepTr'))
    for i, w in sorted(spec['weapons'].items()):
        sp, path, _note = sprites.best(w['obj'], mask=False, pivot=True)
        if sp is None:
            continue
        host = made.get(spec['wparent'].get(i, -1), anchor)
        a = list(tpl['nWepA'])
        a[0] = str(nxt)
        a[1] = model.gmstr(sh.core_x + x + w['x'])
        a[2] = model.gmstr(sh.core_y + y + w['y'])
        a[3] = w['obj']
        a[4] = model.gmstr(w['xs'])
        a[5] = model.gmstr(w['ys'])
        a[6] = model.gmstr(w['ang'])
        if tint is not None and len(a) > 9:
            a[9] = str(tint)
        after = sh.add_record('nWepA', a, after)
        if 'nWepB' in tpl:
            b = list(tpl['nWepB'])
            b[0] = str(nxt)
            b[1] = str(host if host is not None else 0)
            if 'arc' in w and len(b) > 2:
                b[2] = model.gmstr(w['arc'])
            after = sh.add_record('nWepB', b, after)
        for kind in ('nWepC', 'nWepD', 'nWepTr'):
            if kind in tpl:
                t = list(tpl[kind])
                t[0] = str(nxt)
                after = sh.add_record(kind, t, after)
        nxt += 1


def damage(sh: model.Ship, root: int, fraction: float = 0.34,
           side: str = '+y') -> list[str]:
    """Blow a bite out of a moored hull, from one quarter of it.

    Removal cascades, so a section takes everything hanging off it -- which is
    the point. Anything else leaves a wing floating where the hull used to be.
    The root is spared so the wreck keeps a single handle.
    """
    ids = [i for i in _subtree(sh, root) if i != root]
    if not ids:
        return []
    pos = {i: (sh.section(i).x, sh.section(i).y) for i in ids if sh.section(i)}
    if not pos:
        return []
    cx = sum(p[0] for p in pos.values()) / len(pos)
    cy = sum(p[1] for p in pos.values()) / len(pos)
    key = {'+y': lambda p: p[1] - cy, '-y': lambda p: cy - p[1],
           '+x': lambda p: p[0] - cx, '-x': lambda p: cx - p[0]}[side]
    order = sorted(pos, key=lambda i: -key(pos[i]))
    gone: list[str] = []
    for i in order[:max(1, round(len(pos) * fraction))]:
        if sh.section(i) is not None:
            g, _w = edits.remove_section(sh, i, orphan=False, mirror=False)
            gone += g
    return gone


def _subtree(sh: model.Ship, root: int) -> list[int]:
    out = [root]
    changed = True
    while changed:
        changed = False
        for s in sh.sections:
            if s.parent in out and s.id not in out:
                out.append(s.id)
                changed = True
    return out

#!/usr/bin/env python3
"""ship -- read, edit and see Battleships Forever ships.

    ship tree     Pendulum.sb4
    ship render   Pendulum.sb4 -o out.png --scale 6
    ship move  5  --by +4,-2      Pendulum.sb4
    ship rotate 5 --by 15         Pendulum.sb4 --with-children
    ship flip  5  --axis y        Pendulum.sb4
    ship log / diff / undo        Pendulum.sb4
    ship serve    Pendulum.sb4

Coordinates are **core-relative with y down**, matching the file, ShipMaker and
Game Maker itself; `-15` is up. Edits follow a part's `nSecMir` partner by
default -- BSF hulls are almost universally symmetric and the pairing is already
recorded in the file -- and `--no-mirror` opts out.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import history   # noqa: E402
import model     # noqa: E402
import render    # noqa: E402
import scene     # noqa: E402


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------

def subtree(ship: model.Ship, sid: int) -> list[int]:
    """A section and every descendant, by parent link."""
    out, stack = [], [sid]
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.append(cur)
        stack += [s.id for s in ship.sections if s.parent == cur]
    return out


def groups(ship: model.Ship, sid: int, with_children: bool,
           mirror: bool) -> list[tuple[float, float, list[int], float]]:
    """The sets an edit applies to, as (pivot_x, pivot_y, member ids, sign).

    An edit touches at most two groups: the requested subtree, and -- unless
    mirroring is off -- the subtree hanging off its `nSecMir` partner. The sign
    is +1 for the first and -1 for the second, because reflection across the
    centreline negates y and angle.

    Two details that are easy to get wrong, and both were:

    **Sign is per group, not per part.** Testing each part against the original
    id looks right on a lone mirrored pair and is wrong for everything deeper --
    in a subtree the grandchildren are mirrors of each other too, and a per-part
    test sees no pairing and turns them the wrong way.

    **The mirrored group pivots about the reflection of the primary pivot**, not
    about the partner's own position. Real hulls carry a pixel or two of drift,
    so those two points are usually not the same; pivoting about the partner
    makes every rotation amplify the existing asymmetry instead of preserving
    it. Reflecting the pivot means a symmetric ship stays exactly symmetric and
    a drifted one keeps the drift it already had.
    """
    primary = subtree(ship, sid) if with_children else [sid]
    root = ship.section(sid)
    out = [(root.x, root.y, primary, 1.0)]
    if not mirror:
        return out
    partner = ship.mirrors.get(sid)
    if not partner or partner <= 0 or partner == sid or ship.section(partner) is None:
        return out
    secondary = [i for i in (subtree(ship, partner) if with_children else [partner])
                 if i not in set(primary)]
    if secondary:
        out.append((root.x, -root.y, secondary, -1.0))
    return out


def _rotate_offset(dx: float, dy: float, deg: float) -> tuple[float, float]:
    """Rotate an offset by a GM image_angle.

    GM's angle increases counterclockwise while screen y points down, so a
    positive angle takes (1,0) to (0,-1) -- up the screen. That is the y-down
    form of a CCW rotation, and it has to match how the sprite itself turns or
    a rotated subtree comes apart.
    """
    import math
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    return dx * ca + dy * sa, -dx * sa + dy * ca


# --------------------------------------------------------------------------
# edits
# --------------------------------------------------------------------------
# Reflection across the horizontal centreline, which is what nSecMir records:
#     y -> -y      yscale -> -yscale      angle -> -angle
# Verified against station_bolthole.sb4, whose mirror pair 1/2 sits at
# angle -180/+180 with yscale -1/+1.

def do_move(ship: model.Ship, sid: int, dx: float, dy: float,
            with_children: bool, mirror: bool) -> list[str]:
    done = []
    for _px, _py, ids, sign in groups(ship, sid, with_children, mirror):
        for t in ids:
            sec = ship.section(t)
            if sec is None:
                continue
            sec.set_pos(round(sec.x + dx, 2), round(sec.y + dy * sign, 2))
            done.append(f'{t} -> {sec.x:+g},{sec.y:+g}')
    return done


def do_rotate(ship: model.Ship, sid: int, by: float,
              with_children: bool, mirror: bool) -> list[str]:
    """Rotate a section, carrying its subtree round with it as a rigid body.

    With `--with-children` the children must *orbit* the pivot as well as turn
    on the spot; spinning each one in place would scramble a wing rather than
    rotate it.
    """
    done = []
    for px, py, ids, sign in groups(ship, sid, with_children, mirror):
        turn = by * sign
        for t in ids:
            sec = ship.section(t)
            if sec is None:
                continue
            if with_children:
                nx, ny = _rotate_offset(sec.x - px, sec.y - py, turn)
                sec.set_pos(round(px + nx, 2), round(py + ny, 2))
            sec.angle = round((sec.angle + turn) % 360, 2)
            done.append(f'{t} -> {sec.angle:g}deg at {sec.x:+g},{sec.y:+g}')
    return done


def do_flip(ship: model.Ship, sid: int, axis: str,
            with_children: bool, mirror: bool) -> list[str]:
    done = []
    for _px, _py, ids, _sign in groups(ship, sid, with_children, mirror):
        for t in ids:
            sec = ship.section(t)
            if sec is None:
                continue
            if axis == 'x':
                sec.xscale = -sec.xscale
            else:
                sec.yscale = -sec.yscale
            done.append(f'{t} -> xs={sec.xscale:g} ys={sec.yscale:g}')
    return done


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------

def print_tree(ship: model.Ship, as_json: bool = False) -> None:
    secs = {s.id: s for s in ship.sections}
    kids: dict[int, list[int]] = {}
    for s in ship.sections:
        kids.setdefault(s.parent, []).append(s.id)

    if as_json:
        print(json.dumps({
            'name': ship.name, 'generation': ship.generation, 'version': ship.version,
            'core': [ship.core_x, ship.core_y],
            'sections': [{'id': s.id, 'sprite': s.sprite, 'name': s.name,
                          'x': s.x, 'y': s.y, 'angle': s.angle,
                          'xscale': s.xscale, 'yscale': s.yscale,
                          'depth': s.depth, 'parent': s.parent,
                          'mirror': s.mirror, 'hp': s.hp, 'defhp': s.defhp}
                         for s in ship.sections],
        }, indent=2))
        return

    print(f'{ship.name}   [{ship.generation} {ship.version}]   '
          f'{len(ship.sections)} sections   core at {ship.core_x:g},{ship.core_y:g}')
    print(f'{"":24}{"x":>8} {"y":>8} {"ang":>7}  flip  {"z":>4}  mirror')

    seen: set[int] = set()

    def walk(pid: int, prefix: str) -> None:
        ids = kids.get(pid, [])
        for n, sid in enumerate(ids):
            if sid in seen:
                continue
            seen.add(sid)
            s = secs[sid]
            last = n == len(ids) - 1
            stem = '└─ ' if last else '├─ '
            label = f'{prefix}{stem}{sid} {s.name}'
            fl = ('X' if s.xscale < 0 else '-') + ('Y' if s.yscale < 0 else '-')
            mir = f'↔{s.mirror}' if s.mirror and s.mirror > 0 else ''
            print(f'{label:<24}{s.x:>8.2f} {s.y:>8.2f} {s.angle:>7.2f}   {fl}  '
                  f'{s.depth:>4.0f}  {mir}')
            walk(sid, prefix + ('   ' if last else '│  '))

    print(f'core{"":20}{0.0:>8.2f} {0.0:>8.2f}')
    walk(0, '')
    orphans = [s for s in ship.sections if s.id not in seen]
    if orphans:
        print(f'\n⚠ {len(orphans)} section(s) unreachable from the core:',
              ', '.join(str(s.id) for s in orphans))


# --------------------------------------------------------------------------
# entry
# --------------------------------------------------------------------------

def parse_pair(s: str) -> tuple[float, float]:
    a, _, b = s.partition(',')
    return float(a), float(b)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog='ship', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    def with_file(p):
        p.add_argument('file', help='.sb4 ship file')
        return p

    def with_edit(p):
        p.add_argument('id', type=int, help='section id')
        with_file(p)
        p.add_argument('--with-children', action='store_true',
                       help='apply to the section and its whole subtree')
        p.add_argument('--no-mirror', action='store_true',
                       help='do not follow the nSecMir partner')
        return p

    with_file(sub.add_parser('tree', help='part hierarchy')).add_argument(
        '--json', action='store_true')
    p = with_file(sub.add_parser('render', help='draw to PNG'))
    p.add_argument('-o', '--out', default='ship.png')
    p.add_argument('--scale', type=int, default=4)
    p.add_argument('--no-bridge', action='store_true')
    with_file(sub.add_parser('scene', help='the draw list as JSON'))

    p = with_edit(sub.add_parser('move', help='translate a section'))
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--by', help='dx,dy')
    g.add_argument('--to', help='x,y (core-relative)')

    p = with_edit(sub.add_parser('rotate', help='rotate a section'))
    p.add_argument('--by', type=float, required=True, help='degrees')

    p = with_edit(sub.add_parser('flip', help='mirror a section on an axis'))
    p.add_argument('--axis', choices=['x', 'y'], required=True)

    with_file(sub.add_parser('log', help='version history'))
    p = with_file(sub.add_parser('diff', help='changes since a revision'))
    p.add_argument('rev')
    with_file(sub.add_parser('undo', help='restore the previous version'))

    p = with_file(sub.add_parser('serve', help='live preview in a browser'))
    p.add_argument('--port', type=int, default=8771)
    p.add_argument('--bind', default='127.0.0.1')

    args = ap.parse_args(argv)
    path = pathlib.Path(args.file).expanduser()
    if not path.exists():
        print(f'no such file: {path}', file=sys.stderr)
        return 2

    # -- read-only ---------------------------------------------------------
    if args.cmd == 'tree':
        print_tree(model.load(path), args.json)
        return 0

    if args.cmd == 'render':
        sc = scene.build(model.load(path), bridge=not args.no_bridge)
        info = render.save(sc, args.out, scale=args.scale)
        print(f'{sc["name"]}  {info["w"]}x{info["h"]} @ x{info["scale"]}  -> {args.out}')
        for n in sc['notes']:
            print(f'  note: {n}')
        if sc['missing']:
            print(f'  ⚠ unresolved sprites: {", ".join(sc["missing"])}')
        return 0

    if args.cmd == 'scene':
        print(json.dumps(scene.build(model.load(path)), indent=2))
        return 0

    if args.cmd == 'log':
        rows = history.log(path)
        if not rows:
            print('no history yet')
            return 0
        for sha, when, msg in rows:
            print(f'  {sha}  {when}  {msg}')
        return 0

    if args.cmd == 'diff':
        d = history.diff(path, args.rev)
        print(d if d.strip() else 'no differences')
        return 0

    if args.cmd == 'serve':
        import serve
        return serve.run(path, args.bind, args.port)

    # -- mutating ----------------------------------------------------------
    try:
        guard = history.Guarded(path)
    except history.Conflict as e:
        print(f'✗ {e}', file=sys.stderr)
        return 3

    if args.cmd == 'undo':
        rows = history.log(path, limit=2)
        if len(rows) < 2:
            print('nothing to undo')
            return 1
        prev = history.show(path, rows[1][0])
        if prev is None:
            print('previous version not retrievable', file=sys.stderr)
            return 1
        guard.write(prev, f'undo to {rows[1][0]}')
        print(f'restored {rows[1][0]}  ({rows[1][2]})')
        return 0

    ship = model.load(path)
    if ship.section(args.id) is None:
        print(f'no section {args.id} in {path.name}', file=sys.stderr)
        return 2
    mirror = not args.no_mirror

    if args.cmd == 'move':
        if args.by:
            dx, dy = parse_pair(args.by)
        else:
            tx, ty = parse_pair(args.to)
            cur = ship.section(args.id)
            dx, dy = tx - cur.x, ty - cur.y
        changed = do_move(ship, args.id, dx, dy, args.with_children, mirror)
        msg = f'move {args.id} by {dx:+g},{dy:+g}'
    elif args.cmd == 'rotate':
        changed = do_rotate(ship, args.id, args.by, args.with_children, mirror)
        msg = f'rotate {args.id} by {args.by:+g}'
    else:
        changed = do_flip(ship, args.id, args.axis, args.with_children, mirror)
        msg = f'flip {args.id} on {args.axis}'

    if not ship.dirty:
        print('no change')
        return 0

    try:
        sha = guard.write(ship.to_bytes(), msg)
    except history.Conflict as e:
        print(f'✗ {e}', file=sys.stderr)
        return 3

    print(f'{msg}   [{sha or "unchanged"}]')
    for c in changed:
        print(f'  {c}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

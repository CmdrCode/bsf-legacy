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
    """Translate a section and everything rigidly attached to it.

    Mounts move unconditionally (D18). They store absolute canvas coordinates
    alongside a `parent.secid`, so a section edit that touches only `nSecA`
    leaves every turret, module and doodad hanging in the space the section used
    to occupy -- silently, until something renders it.
    """
    done = []
    for _px, _py, ids, sign in groups(ship, sid, with_children, mirror):
        for t in ids:
            sec = ship.section(t)
            if sec is None:
                continue
            sec.set_pos(round(sec.x + dx, 2), round(sec.y + dy * sign, 2))
            done.append(f'{t} -> {sec.x:+g},{sec.y:+g}')
            for m in ship.mounts_of(t):
                m.set_pos(round(m.x + dx, 2), round(m.y + dy * sign, 2))
                done.append(f'  {m.kind} {m.id} -> {m.x:+g},{m.y:+g}')
    return done


def do_rotate(ship: model.Ship, sid: int, by: float,
              with_children: bool, mirror: bool) -> list[str]:
    """Rotate a section, carrying its subtree round with it as a rigid body.

    With `--with-children` the children must *orbit* the pivot as well as turn
    on the spot; spinning each one in place would scramble a wing rather than
    rotate it.

    Mounts orbit the same pivot and turn by the same amount, in both cases. That
    falls out uniformly: without `--with-children` the pivot *is* the rotated
    section's own origin, so its turrets swing round it exactly as they should.
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
            for m in ship.mounts_of(t):
                nx, ny = _rotate_offset(m.x - px, m.y - py, turn)
                m.set_pos(round(px + nx, 2), round(py + ny, 2))
                m.angle = round((m.angle + turn) % 360, 2)
                done.append(f'  {m.kind} {m.id} -> {m.angle:g}deg '
                            f'at {m.x:+g},{m.y:+g}')
    return done


def do_flip(ship: model.Ship, sid: int, axis: str,
            with_children: bool, mirror: bool) -> list[str]:
    """Negate a section's scale on one axis.

    Mounts deliberately do *not* move here, unlike move and rotate. Flipping is
    a sprite-space operation -- it changes how the plate is drawn about its own
    origin and leaves the origin itself where it was -- so a turret bolted to
    the plate is still at the same point on the canvas. ShipMaker's X and Y keys
    behave the same way.
    """
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
            'mounts': [{'kind': m.kind, 'id': m.id, 'sprite': m.sprite,
                        'name': m.name, 'x': m.x, 'y': m.y, 'angle': m.angle,
                        'xscale': m.xscale, 'yscale': m.yscale,
                        'parent': m.parent, 'mirror': m.mirror}
                       for m in ship.mounts],
        }, indent=2))
        return

    print(f'{ship.name}   [{ship.generation} {ship.version}]   '
          f'{len(ship.sections)} sections   core at {ship.core_x:g},{ship.core_y:g}')
    print(f'{"":24}{"x":>8} {"y":>8} {"ang":>7}  flip  {"z":>4}  mirror')

    seen: set[int] = set()
    #: Mounts hang off a section rather than nesting, so they are listed under
    #: their host with a marker rather than as another level of the tree.
    MARK = {'weapon': '•', 'module': '◦', 'doodad': '·'}

    def show_mounts(sid: int, prefix: str) -> None:
        for m in ship.mounts_of(sid):
            label = f'{prefix}{MARK.get(m.kind, "?")} {m.kind[:3]} {m.id} {m.name}'
            # `is not None`, not truthiness: mount ids start at 0, so partner 0
            # is a real part rather than "no partner".
            mir = f'↔{m.mirror}' if m.mirror is not None and m.mirror >= 0 else ''
            print(f'{label:<24}{m.x:>8.2f} {m.y:>8.2f} {m.angle:>7.2f}   {"":2}  '
                  f'{"":>4}  {mir}')

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
            inner = prefix + ('   ' if last else '│  ')
            show_mounts(sid, inner)
            walk(sid, inner)

    print(f'core{"":20}{0.0:>8.2f} {0.0:>8.2f}')
    show_mounts(0, '')
    walk(0, '')
    orphans = [s for s in ship.sections if s.id not in seen]
    if orphans:
        print(f'\n⚠ {len(orphans)} section(s) unreachable from the core:',
              ', '.join(str(s.id) for s in orphans))


def do_structural(ship: model.Ship, edits, args) -> tuple[list[str], str]:
    """Dispatch the record-creating and record-destroying verbs.

    They are grouped apart from move/rotate/flip because they are the ones that
    can leave a tier-2 record pointing at something that is gone, so every one
    of them ends by reporting what `dangling()` can still see (D19).
    """
    mirror = not getattr(args, 'no_mirror', False)

    if args.cmd == 'add':
        x, y = parse_pair(args.at)
        xs, ys = parse_pair(args.scale)
        sid, notes = edits.add_section(
            ship, args.sprite, x, y, parent=args.parent, angle=args.angle,
            xscale=xs, yscale=ys, depth=args.depth, donor=args.donor)
        done = [f'section {sid} added at {x:+g},{y:+g}'] + [f'  {n}' for n in notes]
        if args.mirror:
            made, mnotes = edits.mirror_section(ship, sid)
            done += [f'  mirrored as {m}' for m in made] + [f'  {n}' for n in mnotes]
        return done, f'add {args.sprite} at {x:+g},{y:+g}'

    if args.cmd == 'mirror':
        if ship.section(args.id) is None:
            raise edits.EditError(f'no section {args.id}')
        made, notes = edits.mirror_section(
            ship, args.id, with_children=args.with_children)
        done = [f'section {m} created' for m in made] + [f'  {n}' for n in notes]
        return done, f'mirror {args.id}'

    if args.cmd == 'remove':
        if ship.section(args.id) is None:
            raise edits.EditError(f'no section {args.id}')
        gone, warn = edits.remove_section(
            ship, args.id, orphan=args.orphan, mirror=mirror)
        return gone + [f'⚠ {w}' for w in warn], f'remove {args.id}'

    done = edits.reparent(ship, args.id, args.to, mirror=mirror)
    return done, f'reparent {args.id} to {args.to}'


def print_selection(ship: model.Ship, matches, rendered: bool,
                    as_json: bool = False) -> None:
    if as_json:
        print(json.dumps([{'kind': p.kind, 'id': p.obj.id, 'name': p.obj.name,
                           'x': p.obj.x, 'y': p.obj.y, 'angle': p.obj.angle,
                           'parent': p.obj.parent, 'mirror': p.obj.mirror}
                          for p in matches], indent=2))
        return
    if not matches:
        print('no matches')
        return
    print(f'{len(matches)} match(es)'
          + ('   [one render]' if rendered else '   [file only]'))
    for p in matches:
        o = p.obj
        print(f'  {p.ref:<12} {o.name:<18} {o.x:>8.2f} {o.y:>8.2f} '
              f'{o.angle:>7.2f}')


def shoot_selection(ship: model.Ship, matches, out: str, scale: int) -> str:
    """Render with the matches lit and everything else dimmed.

    D6's reason for this existing: a selector is a claim about which parts you
    mean, and a picture is the only cheap way to check the claim before it
    mutates anything.
    """
    sc = scene.build(ship)
    want = {(p.kind, p.obj.id) for p in matches}
    lit = {i for i, o in enumerate(sc['ops']) if (o['kind'], o['id']) in want}
    img, _ids, info = render.render(sc, scale=scale, highlight=lit, dim_others=True)
    img.convert('RGB').save(out)
    return f'{info["w"]}x{info["h"]} @ x{scale}'


def do_parts(args) -> int:
    """The catalogue: filter by shape, look at a sheet, ask what goes with what."""
    import catalogue
    import query

    if args.sub == 'build':
        c = catalogue.build_parts(force=True)
        n = catalogue.build_cooccurrence(force=True)
        print(f'{len(c["parts"])} sprites measured')
        print(f'{n["parsed"]}/{n["files"]} ship files parsed, '
              f'{n["placements"]} section placements')
        return 0

    if args.sub == 'near':
        got, support, data = catalogue.neighbours(args.sprite, args.limit)
        if got is None:
            print(f'no catalogue entry matches {args.sprite!r}', file=sys.stderr)
            return 2
        key, rows = got
        print(f'{key}   placed {support} time(s) across '
              f'{data["parsed"]} ships ({data["placements"]} placements)')
        if support < 10:
            print('  ⚠ thin support — treat this as anecdote, not convention')
        if not rows:
            print('  never placed beside anything in the corpus')
        for name, n in rows:
            print(f'  {n:>4}x  {name}')
        return 0

    folders = None if args.all_folders else catalogue.SECTION_FOLDERS
    try:
        rows, total = catalogue.search(args.where, folders, args.limit)
    except query.QueryError as e:
        print(f'✗ {e}', file=sys.stderr)
        return 2

    if args.sub == 'sheet':
        if not rows:
            print('no parts match')
            return 1
        print(catalogue.sheet(rows, args.out) + f'  -> {args.out}')
        return 0

    if getattr(args, 'json', False):
        print(json.dumps([r.d for r in rows], indent=2))
        return 0
    if not rows:
        print('no parts match')
        return 1
    print(f'{len(rows)} of {total} shown')
    print(f'  {"part":<22}{"box":>9}{"fill":>7}{"symh":>7}{"symv":>7}'
          f'{"N":>6}{"E":>6}{"S":>6}{"W":>6}')
    for r in rows:
        d = r.d
        print(f'  {d["name"]:<22}{d["bw"]}x{d["bh"]:<5}{d["fill"]:>7.2f}'
              f'{d["symh"]:>7.2f}{d["symv"]:>7.2f}'
              f'{d["flat_n"]:>6.2f}{d["flat_e"]:>6.2f}'
              f'{d["flat_s"]:>6.2f}{d["flat_w"]:>6.2f}')
    return 0


# --------------------------------------------------------------------------
# entry
# --------------------------------------------------------------------------

#: Options whose value is an `x,y` pair and so may legitimately start with `-`.
PAIR_OPTS = ('--to', '--by', '--at', '--scale')
PAIR_RE = __import__('re').compile(r'^[-+]?\d*\.?\d+,[-+]?\d*\.?\d+$')


def glue_pairs(argv: list[str]) -> list[str]:
    """Let `--at -60,0` work as well as `--at=-60,0`.

    argparse treats any token starting with `-` as an option unless it looks
    like a plain negative number, and `-60,0` does not. Coordinates are half the
    arguments this tool takes and half of those are negative -- y is down, so
    anything above the centreline is -- which makes the bare form the one people
    reach for first. Joining the pair back onto its flag here is narrower than
    it looks: it only fires when the flag is one of the coordinate options and
    the very next token is exactly a number pair.
    """
    out: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in PAIR_OPTS and i + 1 < len(argv) and PAIR_RE.match(argv[i + 1]):
            out.append(f'{a}={argv[i + 1]}')
            i += 2
            continue
        out.append(a)
        i += 1
    return out


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

    p = sub.add_parser('select', help='find parts by description')
    p.add_argument('query', help="e.g. 'weapon and x > 60', 'occluded > 0.9'")
    with_file(p)
    p.add_argument('--shot', metavar='PNG',
                   help='render with the matches lit and the rest dimmed')
    p.add_argument('--scale', type=int, default=4)
    p.add_argument('--json', action='store_true')

    p = with_edit(sub.add_parser('move', help='translate a section'))
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--by', help='dx,dy')
    g.add_argument('--to', help='x,y (core-relative)')

    p = with_edit(sub.add_parser('rotate', help='rotate a section'))
    p.add_argument('--by', type=float, required=True, help='degrees')

    p = with_edit(sub.add_parser('flip', help='mirror a section on an axis'))
    p.add_argument('--axis', choices=['x', 'y'], required=True)

    p = sub.add_parser('add', help='create a section')
    p.add_argument('sprite', help=r'path under Custom sprites/, '
                                  r'e.g. "Stock Sections\BSF_Stock17.png"')
    with_file(p)
    p.add_argument('--at', required=True, metavar='X,Y',
                   help='core-relative position (y is down)')
    p.add_argument('--parent', type=int, default=0)
    p.add_argument('--angle', type=float, default=0.0)
    p.add_argument('--scale', metavar='XS,YS', default='1,1')
    p.add_argument('--depth', type=float)
    p.add_argument('--donor', type=int,
                   help='section to copy rotator/effect/trigger records from')
    p.add_argument('--mirror', action='store_true',
                   help='also create the reflected partner')

    p = sub.add_parser('mirror', help='create a section\'s reflected partner')
    p.add_argument('id', type=int)
    with_file(p)
    p.add_argument('--with-children', action='store_true')

    p = sub.add_parser('remove', help='delete a section and what hangs off it')
    p.add_argument('id', type=int)
    with_file(p)
    p.add_argument('--orphan', action='store_true',
                   help='reparent the children instead of deleting them')
    p.add_argument('--no-mirror', action='store_true')

    p = sub.add_parser('reparent', help='re-hang a section')
    p.add_argument('id', type=int)
    with_file(p)
    p.add_argument('--to', type=int, required=True, help='new parent, 0 for core')
    p.add_argument('--no-mirror', action='store_true')

    p = sub.add_parser('name', help="show or set the ship's display name")
    with_file(p)
    p.add_argument('to', nargs='?', help='the new name; omit to just show it')

    p = with_file(sub.add_parser('check', help='lint the ship'))
    p.add_argument('--accept', action='store_true',
                   help='record the current findings as the known baseline')
    p.add_argument('--all', action='store_true',
                   help='list accepted findings too')

    p = with_file(sub.add_parser(
        'visibility', help='how much of each part the render actually shows'))
    p.add_argument('--json', action='store_true')

    p = sub.add_parser('parts', help='browse the sprite catalogue')
    ps = p.add_subparsers(dest='sub', required=True)
    q = ps.add_parser('list', help='filter parts by shape')
    q.add_argument('--where', help="e.g. 'symh > 0.95 and flat_e > 0.7'")
    q.add_argument('--limit', type=int, default=40)
    q.add_argument('--all-folders', action='store_true')
    q.add_argument('--json', action='store_true')
    q = ps.add_parser('sheet', help='render a shortlist as a contact sheet')
    q.add_argument('-o', '--out', default='parts.png')
    q.add_argument('--where')
    q.add_argument('--limit', type=int, default=40)
    q.add_argument('--all-folders', action='store_true')
    q = ps.add_parser('near', help='what real ships place beside a part')
    q.add_argument('sprite')
    q.add_argument('--limit', type=int, default=15)
    ps.add_parser('build', help='rebuild both caches from scratch')

    with_file(sub.add_parser('log', help='version history'))
    p = with_file(sub.add_parser('diff', help='changes since a revision'))
    p.add_argument('rev')
    with_file(sub.add_parser('undo', help='restore the previous version'))

    p = with_file(sub.add_parser('serve', help='live preview in a browser'))
    p.add_argument('--port', type=int, default=8771)
    p.add_argument('--bind', default='127.0.0.1')

    args = ap.parse_args(glue_pairs(sys.argv[1:] if argv is None else argv))
    if args.cmd == 'parts':
        return do_parts(args)

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

    if args.cmd == 'select':
        import query
        ship = model.load(path)
        try:
            matches, _ctx, rendered = query.select(ship, args.query)
        except query.QueryError as e:
            print(f'✗ {e}', file=sys.stderr)
            return 2
        print_selection(ship, matches, rendered, args.json)
        if args.shot:
            print(f'  shot: {shoot_selection(ship, matches, args.shot, args.scale)}'
                  f'  -> {args.shot}')
        return 0

    if args.cmd == 'name' and not args.to:
        print(model.load(path).name)
        return 0

    if args.cmd == 'check':
        import check
        return check.report(path, model.load(path),
                            accept=args.accept, show_all=args.all)

    if args.cmd == 'visibility':
        import check
        return check.visibility(path, model.load(path), args.json)

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
    mirror = not getattr(args, 'no_mirror', False)

    if args.cmd == 'name':
        was = ship.name
        try:
            ship.name = args.to
        except ValueError as e:
            print(f'✗ {e}', file=sys.stderr)
            return 2
        changed, msg = [f'{was!r} -> {ship.name!r}'], f'name to {args.to}'
    elif args.cmd in ('add', 'mirror', 'remove', 'reparent'):
        import edits
        try:
            changed, msg = do_structural(ship, edits, args)
        except edits.EditError as e:
            print(f'✗ {e}', file=sys.stderr)
            return 2
    elif ship.section(args.id) is None:
        print(f'no section {args.id} in {path.name}', file=sys.stderr)
        return 2
    elif args.cmd == 'move':
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

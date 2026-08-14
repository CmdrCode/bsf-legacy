#!/usr/bin/env python3
"""Compile a ship into a flat draw list.

This is the contract between the two renderers. Everything error-prone --
core-relative conversion, depth ordering, colour resolution, turret pivots,
sprite resolution and substitution -- happens exactly once, here. The PIL
blitter and the browser canvas then consume the identical list, so they cannot
disagree about anything except how they rasterise a rotated bitmap.

An op is deliberately dumb:

    {id, kind, spr, x, y, xs, ys, ang, blend, alpha, mode, z, ox, oy, w, h}

`x, y` are core-relative with y **down**, matching the file, ShipMaker and Game
Maker itself. `ox, oy` is the point the sprite rotates about, which for a turret
is the base of its barrel rather than the sprite centre.

Draw order is sections by descending depth (Game Maker draws larger depth first,
i.e. furthest back), then modules, then weapons, then the bridge bead at the
origin. The relative order of those four groups is an assumption about the
editor's own draw order and is one of the things `ship verify` exists to check.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import model      # noqa: E402
import sprites    # noqa: E402

#: Group ordering. Lower sorts earlier, i.e. further back. The core really does
#: sit behind everything -- ShipMaker gives it `depth = 99999` against sections
#: in the 1..20 range -- so the hull plates lie over it.
LAYER_CORE, LAYER_SECTION, LAYER_MODULE, LAYER_WEAPON, LAYER_BRIDGE = -1, 0, 1, 2, 3

#: nCor,image_index,l_colourtype,l_colour,image_xscale,image_yscale,
#:      l_fadecol,x,y,l_formrank
COR_INDEX, COR_COLTYPE, COR_COLOUR, COR_XS, COR_YS = 0, 1, 2, 3, 4

#: The bridge bead is suppressed for two core shapes. From the editor's own
#: draw event:  if obj_core.image_index != 3 && != 5 && global.renderbridge == 1
BRIDGELESS_CORES = {3, 5}


def _hex(rgb: tuple[int, int, int]) -> str:
    return '#%02X%02X%02X' % rgb


class Op(dict):
    """A single draw call. A dict so it serialises straight to JSON."""


def _doodad_sprite(name: str):
    """(sprite, path, note) for a doodad's `lname`.

    ShipMaker's own loader branches on the string's length: anything longer than
    four characters is a file under `Custom sprites/` (`.png` or `.gif`, and it
    strips either extension to derive the resource name), and anything shorter
    is a bare sprite index into the game's own resources. Only the first case is
    resolvable from here -- the exe index is keyed by name, and the tree's
    ordering is not preserved in it -- so a numeric `lname` is reported missing
    rather than guessed at.
    """
    if '\\' in name or '/' in name or name.lower().endswith(('.png', '.gif')):
        path = sprites.resolve(name)
        if path is None:
            return None, None, None
        return sprites.load(str(path), mask=True, pivot=False), path, None
    return sprites.best(name, mask=True, pivot=False)


def _mount_ops(ship: model.Ship, kind: str, layer: int,
               notes: list[str], missing: list[str]) -> list[Op]:
    """Draw ops for one family of mounted parts.

    Weapons and modules sit on fixed layers in front of the hull. Doodads do
    not: ShipMaker recomputes every doodad's depth as `parent.depth - 0.0001`
    after a load, which puts each one immediately in front of the section it is
    attached to rather than in front of the whole ship. That is a real mechanism
    read out of the editor's own code, so it is modelled rather than approximated
    -- doodads join the section layer and sort among the plates.

    The same code also re-depths a weapon or module *if* its `ts_depthed` flag
    is set, which the fixed layers here do not model. No ship on disk sets it,
    and settling layer order is what `ship verify` exists for (D12).
    """
    ops: list[Op] = []
    for m in ship.mounts:
        if m.kind != kind:
            continue
        name = m.sprite
        if not name:
            continue
        if kind == 'doodad':
            sp, path, note = _doodad_sprite(name)
        else:
            sp, path, note = sprites.best(name, mask=False, pivot=True)
        if sp is None:
            missing.append(name)
            continue
        if note and note not in notes:
            notes.append(note)

        z, lay = 0.0, layer
        if kind == 'doodad':
            host = ship.section(m.parent)
            z = (host.depth - 0.0001) if host is not None else m.depth
            lay = LAYER_SECTION
        ops.append(Op(
            id=m.id, kind=kind, spr=str(path), name=m.name,
            x=m.x, y=m.y, xs=m.xscale, ys=m.yscale, ang=m.angle,
            blend=_hex(sprites.gm_colour(m.colour)) if kind == 'doodad' else '#FFFFFF',
            alpha=m.alpha,
            mode='normal', layer=lay, z=z,
            ox=sp.ox, oy=sp.oy, w=sp.w, h=sp.h, mask=kind == 'doodad',
            parent=m.parent, mirror=m.mirror,
            glow=name in sprites.MODULES,
        ))
    return ops


def build(ship: model.Ship, *, bridge: bool = True) -> dict:
    """Everything needed to draw the ship, in draw order."""
    ops: list[Op] = []
    notes: list[str] = []
    missing: list[str] = []

    core_index = ship.core_shape

    # The core is a tinted 80x80 sprite at the origin, not just the bridge bead.
    # Its shape is chosen by image_index, but only one core frame exists on disk
    # -- the rest live in the encrypted gamedata -- so anything other than frame
    # 0 is drawn as frame 0 and flagged.
    #
    # Asking the ship rather than for an `nCor` record is what lets a `.shp`
    # draw its core at all: only `.sb4` uses a record, and every other
    # generation writes `sprite_index` as a plain setting. Reading just the
    # record meant all 173 of them rendered coreless -- and the linter, seeing
    # nothing at the origin, reported a hole and a floating bridge.
    if ship.has_core:
        sp = sprites.get_exe('spr_core', core_index, mask=True)
        if sp is None:                       # no exe cache: fall back to disk
            dp = sprites.resolve('spr_Core')
            if dp is not None:
                sp = sprites.load(str(dp), mask=True, pivot=False)
                if core_index != 0:
                    notes.append(f'core shape {core_index}: exe art not extracted — '
                                 f'drawn as the single on-disk frame '
                                 f'(run exeart.py)')
        if sp is None:
            missing.append('spr_core')
        else:
            p = sp.path
            xs, ys = ship.core_scale
            colour = ship.core_colour
            # An unstated colour means the team's, so it is drawn in the same
            # palette base a shade-0 section would take.
            if colour is not None:
                blend = _hex(sprites.gm_colour(colour))
            else:
                pal = sprites.teams().get('player') or [(0, 255, 0)]
                blend = _hex(pal[0])
            ops.append(Op(
                id=0, kind='core', spr=str(p), name='spr_core',
                x=0.0, y=0.0,
                xs=xs, ys=ys, ang=0.0,
                blend=blend,
                alpha=1.0, mode='normal', layer=LAYER_CORE, z=99999.0,
                ox=sp.ox, oy=sp.oy, w=sp.w, h=sp.h, mask=True,
                parent=None, mirror=None, glow=False, frame=core_index,
            ))

    for sec in ship.sections:
        path = sprites.resolve(sec.sprite)
        if path is None:
            missing.append(sec.sprite)
            continue
        sp = sprites.load(str(path), mask=True, pivot=False)
        ops.append(Op(
            id=sec.id, kind='section', spr=str(path), name=sec.name,
            x=sec.x, y=sec.y, xs=sec.xscale, ys=sec.yscale, ang=sec.angle,
            blend=_hex(sprites.gm_colour(sec.colour)), alpha=sec.alpha,
            mode='normal', layer=LAYER_SECTION, z=sec.depth,
            ox=sp.ox, oy=sp.oy, w=sp.w, h=sp.h, mask=True,
            parent=sec.parent, mirror=sec.mirror, glow=False,
        ))

    ops += _mount_ops(ship, 'doodad', LAYER_SECTION, notes, missing)
    ops += _mount_ops(ship, 'module', LAYER_MODULE, notes, missing)
    ops += _mount_ops(ship, 'weapon', LAYER_WEAPON, notes, missing)

    if bridge and core_index not in BRIDGELESS_CORES:
        sp = sprites.get_exe('spr_bridge', 0, mask=False)
        if sp is None:
            dp = sprites.resolve(sprites.BRIDGE)
            sp = sprites.load(str(dp), mask=False, pivot=False) if dp else None
        if sp is not None:
            p = sp.path
            ops.append(Op(
                id=-1, kind='bridge', spr=str(p), name=sprites.BRIDGE,
                x=0.0, y=0.0, xs=1.0, ys=1.0, ang=0.0,
                blend='#FFFFFF', alpha=1.0, mode='normal',
                layer=LAYER_BRIDGE, z=0.0,
                ox=sp.ox, oy=sp.oy, w=sp.w, h=sp.h, mask=False, glow=False,
            ))

    # Game Maker draws larger depth first, so within the section layer the
    # highest depth is furthest back.
    ops.sort(key=lambda o: (o['layer'], -o['z']))

    return {
        'name': ship.name,
        'file': str(ship.path),
        'generation': ship.generation,
        'version': ship.version,
        'bbox': bbox(ops),
        'counts': {k: sum(1 for o in ops if o['kind'] == k)
                   for k in ('core', 'section', 'doodad', 'weapon', 'module', 'bridge')},
        'notes': notes,
        'missing': sorted(set(missing)),
        'ops': ops,
    }


def bbox(ops: list[Op]) -> list[float]:
    """Axis-aligned bounds in core-relative space, accounting for rotation.

    Uses each sprite's rotated corner extents rather than its alpha, so this is
    an upper bound on the true silhouette -- adequate for framing a render, and
    deliberately not what `ship check` will use for occlusion.
    """
    import math
    if not ops:
        return [0.0, 0.0, 0.0, 0.0]
    xs, ys = [], []
    for o in ops:
        w, h = o['w'] * abs(o['xs']), o['h'] * abs(o['ys'])
        a = math.radians(o['ang'])
        ca, sa = abs(math.cos(a)), abs(math.sin(a))
        hw, hh = (w * ca + h * sa) / 2, (w * sa + h * ca) / 2
        xs += [o['x'] - hw, o['x'] + hw]
        ys += [o['y'] - hh, o['y'] + hh]
    return [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)]


def for_web(sc: dict) -> dict:
    """The same scene with sprite pixels inlined, for the browser."""
    out = dict(sc)
    seen: dict[str, str] = {}
    for o in sc['ops']:
        if o['spr'] not in seen:
            sp = sprites.load_any(o['spr'], o['mask'], o['kind'] in ('weapon', 'module'))
            seen[o['spr']] = sprites.data_uri(sp)
    out['sprites'] = seen
    return out

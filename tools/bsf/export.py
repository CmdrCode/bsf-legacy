"""Write the `.shp` generation the game loads, from the `.sb4` ShipMaker edits.

ShipMaker is the only thing that writes `.shp`, which made "export the design"
a manual step in the middle of an otherwise scripted pipeline. This module
removes it.

**This is a transcription, not a reconstruction.** ShipMaker is a Game Maker 7
game, so its resource tree decrypts and its script bodies decode the same way
the game's do, and it carries a script named `saveShipSHP` -- the writer itself.
The game carries the matching readers (`nSec2a`, `nSec2b`, ...) and ShipMaker
carries the `.sb4` ones (`nSecA`, `nSecB`, ...). Every field mapping below was
read off those three sources rather than inferred by aligning files, which is
why the animation records are handled at all: they are inert in every ship we
have, so no amount of comparing examples would have named their fields.

An earlier attempt did try comparing, and recorded the format as unrecoverable.
The lesson worth keeping is not about ships: **the decompiled source was
available the whole time.**

Field-order note, since it is the one thing a reader will not guess: the two
generations agree on *what* a part stores and disagree on *order*, and `.sb4`
splits across `nSecB/C/D` what `.shp` splits across `nSec2b/2c/2M`. The seams do
not line up -- `ef_fade` is written by `nSecD` and read back by `nSec2c` -- so
the mapping is per field, never per record.

Gated by `roundtrip.py --export`, which re-exports the one design that exists in
both generations on disk and compares against ShipMaker's own output.
"""
from __future__ import annotations

import math
import pathlib

import model
import sprites

#: Cores that need an `nCor2a` line after `sprite_index` (`saveShipSHP`). These
#: are also exactly `scene.BRIDGELESS_CORES` -- the two cores that carry no
#: bridge bead are the two that need the extra line.
CORE_NEEDS_2A = {'spr_Civilian', 'spr_Platform'}

#: `ThrusterEx` keeps its plume settings on the object, not in the `.sb4`, so a
#: freshly loaded one exports the object's own defaults. Read off Pendulum's
#: export, which is the only one on disk.
THRUSTER_DEFAULTS = ('"-1"', '90', '1', '1', '0.30', '10', '10')

EOL = '\r\n'


class ExportError(Exception):
    pass


# --------------------------------------------------------------------------
# reading the .sb4 side
# --------------------------------------------------------------------------

def _by_id(ship: model.Ship, kind: str) -> dict[int, model.Record]:
    """`{id: record}` for a `.sb4` family whose token 0 is the part id."""
    return {int(r.num(0)): r for r in ship.of_kind(kind)}


def _tok(r: model.Record | None, i: int, default: str = '0') -> str:
    """A field as its *original text*.

    Copied rather than re-formatted so an untouched value cannot drift: `0.70`
    stays `0.70` and `1.10` stays `1.10`, which is what makes a byte-for-byte
    comparison against ShipMaker's own output mean anything.
    """
    if r is None:
        return default
    return r.txt(i, default) or default


def _num(r: model.Record | None, i: int, default: float = 0.0) -> float:
    return default if r is None else r.num(i, default)


def gm_mod(a: float, b: float) -> float:
    """Game Maker's `mod`, which keeps the sign of the dividend.

    `-75 mod 360` is `-75` in GML and `285` in Python. Turret facings are stored
    signed, so using Python's `%` silently mirrors every port-side turret.
    """
    return math.fmod(a, b)


# --------------------------------------------------------------------------
# l_size
# --------------------------------------------------------------------------

def _sprite_box(ref: str) -> tuple[float, float, float, float] | None:
    """A sprite's opaque extent relative to its origin, as GM's bbox sees it.

    Game Maker's automatic bounding box is the *opaque* region, not the image
    rectangle, and ship art is stored without alpha -- the empty area is
    whatever colour the bottom-left pixel is. Measuring the full rectangle
    instead overstates every section and inflates `l_size` by about a tenth.
    """
    spr = sprites.get(ref, mask=False)
    if spr is None:
        return None
    f = spr.frames[0]
    h, w = f.shape[:2]
    key = f[h - 1, 0]
    solid = (f != key).any(axis=2)
    ys, xs = solid.nonzero()
    if not len(xs):
        return None
    # GM's bbox bounds are inclusive pixel indices, not a half-open range.
    return (xs.min() - spr.ox, ys.min() - spr.oy,
            xs.max() - spr.ox, ys.max() - spr.oy)


def _extent(ref: str, xs: float, ys: float, angle: float,
            dx: float, dy: float) -> float:
    """Farthest corner of one section's axis-aligned box from the core.

    `saveShipSHP` walks every section's `bbox_*` and keeps the largest distance
    to the core, floored at 20. GM's bbox is axis-aligned *after* the transform,
    so the corners are rotated and then re-squared.
    """
    box = _sprite_box(ref)
    if box is None:
        return 0.0
    x0, y0, x1, y1 = box
    a = math.radians(-angle)                 # GM angles run counter-clockwise
    ca, sa = math.cos(a), math.sin(a)
    px, py = [], []
    for cx, cy in ((x0 * xs, y0 * ys), (x1 * xs, y0 * ys),
                   (x0 * xs, y1 * ys), (x1 * xs, y1 * ys)):
        px.append(cx * ca - cy * sa)
        py.append(cx * sa + cy * ca)
    return max(math.hypot(x + dx, y + dy)
               for x in (min(px), max(px)) for y in (min(py), max(py)))


def _l_size(secs: list[model.Record], cx: float, cy: float) -> float:
    r = 20.0
    for s in secs:
        try:
            r = max(r, _extent(s.txt(3), s.num(4, 1), s.num(5, 1), s.num(6),
                               s.num(1) - cx, s.num(2) - cy))
        except Exception:
            continue
    return r


# --------------------------------------------------------------------------
# triggers
# --------------------------------------------------------------------------

#: Trigger types at or above this need a partner part, named by an `nTrigS` /
#: `nTrigW` record: `tr_checkTriggers` splits 11-16 (partner is a weapon) from
#: 17-19 (partner is a section). Below 11 the type stands on its own.
TRIGGER_NEEDS_PARTNER = 11


def _trigger_types(rec: model.Record | None, has_partner: bool) -> list[str]:
    """The nine trigger fields, with dangling partner-triggers dropped.

    A partner-typed trigger whose partner record is absent points at GML's
    "no instance" sentinel, and ShipMaker exports it as no trigger at all.
    Pendulum settles both directions: its sections 6 and 8 store type 17 *and*
    carry `nTrigS` records, and export keeps the 17; its first weapon stores 17
    with no `nTrigW` and exports 0.
    """
    out = [_tok(rec, i) for i in range(1, 10)]
    if not has_partner:
        for i in range(4):                   # ontype1, offtype1, ontype2, offtype2
            if float(out[i] or 0) >= TRIGGER_NEEDS_PARTNER:
                out[i] = '0'
    return out


def _is_toggle(types: list[str]) -> bool:
    """ShipMaker's `tr_checkToggle`, for parts with no partner.

    On/off are the same trigger, so the part toggles rather than latching. With
    no partners the test reduces to the four types agreeing and being non-zero.
    """
    on1, off1, on2, off2 = (float(t or 0) for t in types[:4])
    return on1 == off1 == on2 == off2 and on1 != 0


# --------------------------------------------------------------------------
# the writer
# --------------------------------------------------------------------------

def sb4_to_sh3(ship: model.Ship, *, size: float | None = None,
               warn=None) -> str:
    """Render a parsed `.sb4` as `.shp` (`sh3 ver2`) text.

    `size` overrides the computed `l_size`, which feeds AI range and formation
    spacing rather than geometry. `warn` is called with a message wherever this
    knowingly departs from what ShipMaker's own export would produce.
    """
    if ship.generation != 'sb4':
        raise ExportError(f'{ship.path.name} is {ship.generation}, not sb4')

    shp, cor = ship.first('nShp'), ship.first('nCor')
    if shp is None or cor is None:
        raise ExportError(f'{ship.path.name} has no nShp/nCor header')

    secA = ship.of_kind('nSecA')
    B, C, D, T = (_by_id(ship, k) for k in ('nSecB', 'nSecC', 'nSecD', 'nSecTr'))
    cx, cy = cor.num(6), cor.num(7)

    # Depth is not stored in the `.shp`: record order *is* depth, descending.
    #
    # ShipMaker builds that order with `ds_map_add(objs, deep, id)` and drains
    # it by key, so sections sharing a depth collide and all but one are lost --
    # the station has five at depth 200 and would export as 126 of its 130.
    # Sorting is stable on file order instead, which keeps every section; ties
    # have no defined order in the editor either, so nothing is being decided
    # here that the `.sb4` had an opinion about.
    depths = [s.num(12) for s in secA]
    if warn and len(set(depths)) != len(depths):
        lost = len(depths) - len(set(depths))
        warn('%d section(s) share a depth with another; ShipMaker would drop '
             'them on export. All %d are kept here.' % (lost, len(depths)))
    order = sorted(range(len(secA)), key=lambda i: -secA[i].num(12))
    slot = {int(secA[i].num(0)): j for j, i in enumerate(order)}

    out: list[str] = ['//sh3 ver2']
    # A station is a ship that cannot move, and the tag is how the game knows.
    out.append('//battlestation' if shp.num(0) == 0 else '')

    core_spr = model.CORE_SPRITES.get(int(cor.num(0)), 'spr_Core')
    out += ['//STARTING!', 'sprite_index,' + core_spr]
    if core_spr in CORE_NEEDS_2A:
        out.append('nCor2a')
    out += ['event_inherited', '//COLOR SETTINGS']
    # `nCor` pins l_colourtype to 0 and takes the palette's own colour, so the
    # `nCor2b` and `l_colour` lines saveShipSHP can emit here are unreachable
    # for anything loaded from a `.sb4`.
    if _num(cor, 3, 1) != 1:
        out.append('image_xscale,' + _tok(cor, 3, '1'))
    if _num(cor, 4, 1) != 1:
        out.append('image_yscale,' + _tok(cor, 4, '1'))
    out += ['l_fadecol,' + _tok(cor, 5), '//PROPERTIES',
            '//Movement Properties', 'l_thrust,' + _tok(shp, 0)]

    r = _l_size(secA, cx, cy) if size is None else size
    out.append('nShp2,' + ','.join([
        _tok(shp, 1), _tok(shp, 2), _tok(shp, 3), _tok(shp, 4), _tok(shp, 5),
        _tok(cor, 8),                                  # l_formrank
        '"%s"' % _tok(shp, 6, '').strip('"'),
        '"%s"' % _tok(shp, 7, ' ').strip('"'),
        model.gmstr(r),
    ]))
    out += ['', '//SHIP SYSTEMS\\\\', '//SECTIONS']

    # A partner-typed trigger is only real if a record names its partner.
    sec_partners = {int(r.num(0)) for r in ship.of_kind('nTrigS')}
    wep_partners = {int(r.num(0)) for r in ship.of_kind('nTrigW')}

    sec_types: list[list[str]] = []
    for i in order:
        a = secA[i]
        sid = int(a.num(0))
        out += _section(a, B.get(sid), C.get(sid), D.get(sid), T.get(sid),
                        cx, cy, sid in sec_partners)
        sec_types.append(_trigger_types(T.get(sid), sid in sec_partners))

    out += ['l_sectionnum=j-1', 'l_maxsyshp=0', 'initSections',
            '//WEAPONS/MODULES']
    mounts, allround, wep_types, wslot = _mounts(ship, cx, cy, slot, wep_partners)
    out += mounts

    out.append('//Parents')
    for i in order:
        a = secA[i]
        p = int(a.num(13))
        if p and p in slot:
            out.append('nPar2,%d,%d' % (slot[p], slot[int(a.num(0))]))

    out += _triggers(ship, sec_types, wep_types, slot, wslot)

    out += ['//Weapon init', 'l_weaponnum=wj-1', 'initWeapons']
    # An all-round ship has no blind arc, so its AI is allowed to hold station
    # instead of turning to bring guns to bear.
    if allround:
        out.append('l_ailevel=1')
    out += ['initOwners', '//ENDING']
    # No trailing newline: ShipMaker returns the string and writes it as-is, so
    # a real `.shp` ends at the final `G`.
    return EOL.join(out)


def _section(a, b, c, d, t, cx: float, cy: float,
             has_partner: bool = False) -> list[str]:
    """The six records one section becomes, in the order the loader expects.

    `nSec2d` is last for a reason: its handler ends with `j += 1`, so it is what
    commits the section and starts the next one.
    """
    colourmod = _tok(b, 12)
    a2 = 'nSec2a,' + ','.join([
        model.gmstr(a.num(1) - cx), model.gmstr(a.num(2) - cy),
        '"%s"' % a.txt(3),
        _tok(a, 4, '1'), _tok(a, 5, '1'), _tok(a, 6), _tok(a, 7),
        _tok(a, 9), _tok(a, 10), colourmod,
    ])
    # A section takes its colour from the team palette by class; only an
    # explicit override carries a resolved colour, and only then.
    if colourmod == '-1':
        a2 += ',' + _tok(b, 13)

    b2 = 'nSec2b,' + ','.join([
        _tok(b, 1), _tok(b, 3), _tok(b, 4), _tok(b, 2),
        _tok(b, 7), _tok(b, 8), _tok(b, 5), _tok(b, 6), _tok(b, 9), _tok(b, 10),
    ])

    # The `.sb4` stores fade as a frame count and the `.shp` as a per-step
    # speed; `resetFade` is where ShipMaker converts, dividing the border range.
    span = _num(c, 6, 1) - _num(c, 7)
    fin, fout = _num(d, 2), _num(d, 3)
    c2 = 'nSec2c,' + ','.join([
        _tok(c, 1), _tok(c, 2), _tok(d, 1),
        model.gmstr(span / fin if fin else 0),
        model.gmstr(span / fout if fout else 0),
        _tok(c, 4), _tok(c, 5), _tok(c, 6), _tok(c, 7),
        _tok(d, 4), _tok(c, 8), _tok(c, 9),
    ])
    # Effect 5 reuses the tail for something else, and the loader switches on
    # the same value, so the short form is not optional.
    if _tok(c, 1) == '5':
        c2 += ',' + ','.join([_tok(c, 10), _tok(c, 11)])
    else:
        c2 += ',' + ','.join([_tok(c, 12), _tok(c, 13),
                              _tok(c, 14, '1'), _tok(c, 15, '1')])

    m2 = 'nSec2M,' + ','.join([
        _tok(d, 6), _tok(d, 7), _tok(d, 8, '1'), _tok(d, 9, '1'),
        _tok(d, 10), _tok(d, 11), _tok(d, 12), _tok(d, 13), _tok(d, 5),
    ])
    t2 = 'nSecT,' + ','.join(_trigger_types(t, has_partner))
    d2 = 'nSec2d,' + ','.join([_tok(b, 14), _tok(b, 15)])
    return [a2, b2, c2, m2, t2, d2]


def _mounts(ship: model.Ship, cx: float, cy: float, slot: dict[int, int],
            partners: set[int]
            ) -> tuple[list[str], bool, list[list[str]], dict[int, int]]:
    """Weapons then modules: they share `nTur2` and differ only in the tail.

    Returns the lines, whether the ship is all-round, each mount's trigger
    fields, and the weapon-id-to-`wj` map the trigger block needs.
    """
    wA, wB, wC, wD, wT = (_by_id(ship, k) for k in
                          ('nWepA', 'nWepB', 'nWepC', 'nWepD', 'nWepTr'))
    mA, mB = (_by_id(ship, k) for k in ('nModA', 'nModB'))
    out: list[str] = []
    types: list[list[str]] = []
    wslot: dict[int, int] = {}
    allround = True

    for wid in sorted(wA):
        # A module in the weapon table is not a thing to write out and warn
        # about later: the file it produces loads as a ship with *no weapons*,
        # because the loader's nWep2a handler reads `l_bullet` off the mount and
        # a module has none, which throws inside the ship's Create event and
        # abandons the rest of it. Refusing here is the difference between an
        # error message and an evening -- `ship check` reports the same thing as
        # `unloadable`, and this is the backstop for anyone who skipped it.
        if wA[wid].txt(3) in sprites.MODULES:
            raise ValueError(
                f'weapon {wid} is {wA[wid].txt(3)}, which is a module: the game '
                f'reads l_bullet off every weapon mount and a module has none, '
                f'so this would export a ship that loads with no weapons at '
                f'all. Re-mount it as a module (ship arm places one correctly).')
        wslot[wid] = len(types)
        a, b, c, d = wA[wid], wB.get(wid), wC.get(wid), wD.get(wid)
        if _num(b, 2) < 180:                            # arcrange
            allround = False
        out.append(_tur2(a, a.txt(3), _num(b, 1), _num(b, 2), _tok(c, 7),
                         cx, cy, slot))
        out.append('nWep2a,' + ','.join([
            _tok(b, 4), _tok(b, 6), _tok(b, 5), _tok(b, 7), _tok(b, 11),
            '"%s"' % _tok(d, 3, '').strip('"'),
            _tok(b, 10), _tok(b, 8), _tok(b, 9), _tok(b, 13), _tok(b, 12),
            _tok(c, 1), _tok(c, 2), _tok(c, 3), _tok(c, 4), _tok(c, 5),
        ]))
        out.append('nWep2b,' + ','.join([
            _tok(a, 4, '1'), _tok(a, 5, '1'), _tok(a, 11), _tok(a, 8, '1'),
            _tok(c, 6), _tok(c, 10),
            '"%s"' % _tok(c, 8, '-1').strip('"'),
            '"%s"' % _tok(c, 11, '-1').strip('"'),
            _tok(c, 12),
            '"%s"' % _tok(c, 13, '-1').strip('"'),
            _tok(c, 14), _tok(c, 15), _tok(d, 1), _tok(d, 2), _tok(d, 4), '0',
        ]))
        t = _trigger_types(wT.get(wid), wid in partners)
        out.append('nWepT,' + ','.join(t))
        types.append(t)
        out.append('wj+=1')

    for mid in sorted(mA):
        a, b = mA[mid], mB.get(mid)
        out.append(_tur2(a, a.txt(3), _num(b, 1), 0, '0', cx, cy, slot))
        out.append('nMod2,' + ','.join([
            _tok(a, 15), _tok(a, 13), _tok(a, 14),
            '""',                                    # a module carries no name
            _tok(a, 10), _tok(a, 11),
            _tok(b, 2), _tok(b, 3), _tok(b, 4), _tok(b, 5),
            _tok(b, 6), _tok(b, 7), _tok(b, 8), _tok(b, 9),
            _tok(b, 10, '1'), _tok(a, 6), '0',
        ]))
        if a.txt(3) == 'ThrusterEx':
            out.append('nThrEx2,' + ','.join(THRUSTER_DEFAULTS))
        if abs(_num(a, 5, 1)) != 1:
            out.append('l_weap_img_yscale,' + _tok(a, 5, '1'))
        if abs(_num(a, 4, 1)) != 1:
            out.append('l_weap_img_xscale,' + _tok(a, 4, '1'))
        if _num(b, 11) > 0:
            out.append('l_weap_color,' + _tok(b, 11))
        out.append('wj+=1')

    return out, allround, types, wslot


def _tur2(a: model.Record, spr: str, parent: float, arcrange: float,
          depthed: str, cx: float, cy: float, slot: dict[int, int]) -> str:
    p = int(parent)
    return 'nTur2,' + ','.join([
        model.gmstr(a.num(1) - cx), model.gmstr(a.num(2) - cy), spr,
        model.gmstr(gm_mod(a.num(6), 360)),
        model.gmstr(arcrange), depthed,
        str(slot[p]) if p in slot else '-1',
    ])


def _triggers(ship: model.Ship, sec_types: list[list[str]],
              wep_types: list[list[str]], slot: dict[int, int],
              wslot: dict[int, int]) -> list[str]:
    """`saveMLDTSHP`: the partner links, then the parts that toggle.

    A `.sb4` names parts by id and a `.shp` by emitted position, so both the
    part and its partner are renumbered here. Partner kind 1 is a section and 2
    is a weapon, which is what decides which map to renumber through.

    Links and drivers (`nLink2`, `nDriver2`) are not emitted: they hang off
    `ts_linkpar`/`ts_drivensec`, which no `.sb4` record populates.
    """
    def renumber(rec: model.Record, own: dict[int, int]) -> str | None:
        me = own.get(int(rec.num(0)))
        partner_map = slot if int(rec.num(2)) == 1 else wslot
        partner = partner_map.get(int(rec.num(3)))
        if me is None or partner is None:
            return None
        return '%d,%s,%s,%d' % (me, _tok(rec, 1), _tok(rec, 2), partner)

    out = ['//Weapon links, drivers and triggers']
    for r in ship.of_kind('nTrigW'):
        line = renumber(r, wslot)
        if line:
            out.append('nTrigW,' + line)
    for i, t in enumerate(wep_types):
        if _is_toggle(t):
            out.append('nTrigW,%d,9,0,0' % i)
    out += ['', '//Section triggers', '']
    for r in ship.of_kind('nTrigS'):
        line = renumber(r, slot)
        if line:
            out.append('nTrigS,' + line)
    for i, t in enumerate(sec_types):
        if _is_toggle(t):
            out.append('nTrigS,%d,9,0,0' % i)
    out.append('')
    return out


def export(src: pathlib.Path, dst: pathlib.Path | None = None) -> pathlib.Path:
    """Read a `.sb4` and write its `.shp` beside it."""
    text = sb4_to_sh3(model.load(src))
    dst = dst or src.with_suffix('.shp')
    dst.write_bytes(model.encode(text, obfuscated=False))
    return dst

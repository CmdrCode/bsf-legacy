#!/usr/bin/env python3
"""Structural edits: add a section, mirror one, remove one, reparent one.

These are the edits that create or destroy records, which puts them in direct
tension with D7 -- a brand-new section has no verbatim tier-2 text to preserve,
because it never existed on disk. The resolution (D16) is to **clone a donor**:
copy a real section's `nSecB/C/D/Tr` and rewrite only the fields that track that
section's own state. A default template would silently turn a mirrored rotating
hangar door into a static one, which is the exact loss D7 exists to prevent.
Measured on the corpus, 26 of 28 `nSecD` payloads and most `nSecC` payloads are
already identical between sections, so a donor is nearly always a faithful
source.

The mirror transform is not a coordinate flip and is not guessed at. It is
transcribed from ShipMaker's own auto-mirror routine, which reflects y about the
core, negates `image_yscale` and `image_angle`, **swaps** the clockwise and
counter-clockwise rotator settings rather than negating them, flips the
directional trigger types, and remaps the parent through the partner. Getting
any one of those wrong produces a ship that looks symmetric and behaves
asymmetrically.

One thing the editor does that this deliberately does not: ShipMaker's routine
writes `rs_startcounter = +/-1` on the copy and then calls `resetRotation`,
which is why no ship on disk contains `+1` -- every real mirror pair carries
`-1` on one side and `0` on the other. The observed convention is reproduced
rather than the pre-reset intermediate.
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import paths    # noqa: E402
import model     # noqa: E402
import sprites   # noqa: E402

#: Written as one consecutive block per section, in this order.
SECTION_TIER2 = ('nSecB', 'nSecC', 'nSecD', 'nSecTr')

#: Record families. `prefix` catches every record of the family including the
#: ones whose layout was never recovered (`nWepD`, `nWepTr`), because they all
#: key on the part id in field 0. `extra` are the outliers that do the same
#: without sharing the prefix.
FAMILY = {
    'section': dict(prefix='nSec', mir='nSecMir', extra=('nTrigS',)),
    'weapon':  dict(prefix='nWep', mir='nWepMir', extra=('nDriver',)),
    'module':  dict(prefix='nMod', mir='nModMir', extra=('nThrEx',)),
    'doodad':  dict(prefix='nDoo', mir='nDooMir', extra=()),
}

# -- the mirror transform, field by field ----------------------------------
#: `nSecB` rotator settings. Clockwise and counter-clockwise trade places; the
#: borders trade places *and* negate, because a border is a signed angle.
SECB_SIDE = 9                       # rs_startcounter, used as the side marker
SECB_SWAP = ((3, 4), (5, 6))        # rot frames, delays
SECB_NEGSWAP = ((7, 8),)            # cw/ccw borders
SECB_NEG = (10,)                    # rs_startrotang
SECC_NEG = (13, 15)                 # ef_offy, eff_yscale
SECTR_TYPES = (1, 2, 3, 4)          # tr_ontype1/2, tr_offtype1/2

#: Directional trigger types. 5/6 and 11/12 are the two handed pairs; every
#: other type means the same thing on both sides of the hull.
TRIGGER_FLIP = {5: 6, 6: 5, 11: 12, 12: 11}

#: Used only when a ship has no section to copy from at all -- an empty hull.
#: `l_defhp` is the awkward one: it is **not** derivable from the art. Measured
#: on station_bolthole, four sections share one sprite, one scale and full
#: visibility and still carry 197.12, 196.79, 243.28 and 242.27. So there is no
#: formula to apply, and this is the corpus median of the 28 sections on disk,
#: reported out loud whenever it is used.
DEFAULT_DEFHP = 275.19
DEFAULT_BLEND = 8454016             # GM's BGR for (128,255,128), the stock green


class EditError(ValueError):
    """An edit that cannot be carried out on this ship."""


# --------------------------------------------------------------------------
# record surgery
# --------------------------------------------------------------------------

def owned_records(ship: model.Ship, kind: str, pid: int) -> list[model.Record]:
    """Every record that belongs to one part, including its mirror back-link.

    Matching on the family prefix rather than an enumerated list is deliberate:
    `nWepC`, `nWepD` and `nWepTr` are tier-2 records whose layouts were never
    recovered, and a delete that left them behind would leave the file
    referencing a weapon that no longer exists.
    """
    fam = FAMILY[kind]
    out = []
    for r in ship.records:
        if r.kind.startswith(fam['prefix']) or r.kind in fam['extra']:
            try:
                if int(r.num(0)) == pid:
                    out.append(r)
                    continue
            except ValueError:
                pass
        # the partner's half of the mirror link, and weapon-to-weapon links
        if r.kind == fam['mir'] and _int(r, 1) == pid:
            out.append(r)
        elif r.kind == 'nLink' and kind == 'weapon' and pid in (_int(r, 0), _int(r, 1)):
            out.append(r)
    return out


def _int(rec: model.Record, i: int, default: int = -999999) -> int:
    try:
        return int(rec.num(i))
    except (ValueError, TypeError):
        return default


def dangling(ship: model.Ship) -> list[str]:
    """References from tier-2 records to parts that are not there.

    D19's standing caveat. `nTrigS` names a target section or weapon,
    `nDriver` names a driven section and `nLink` names another weapon -- all of
    them tier-2, so the CLI will not rewrite them and a delete can strand one.
    Reporting is the whole mitigation; the other half is that new sections take
    `max(secid) + 1` and never reuse a gap, so a stale trigger stays visibly
    broken rather than silently re-binding to an unrelated new part.
    """
    secs = {s.id for s in ship.sections} | {0}
    weps = {m.id for m in ship.weapons}
    out = []
    for r in ship.of_kind('nTrigS'):
        owner, target_kind, target = _int(r, 0), _int(r, 2), _int(r, 3)
        pool, what = (secs, 'section') if target_kind == 1 else (weps, 'weapon')
        if target not in pool:
            out.append(f'nTrigS on section {owner} targets missing {what} {target}')
    for r in ship.of_kind('nDriver'):
        if _int(r, 0) not in weps:
            out.append(f'nDriver names missing weapon {_int(r, 0)}')
        if _int(r, 1) not in secs:
            out.append(f'nDriver on weapon {_int(r, 0)} drives missing '
                       f'section {_int(r, 1)}')
    for r in ship.of_kind('nLink'):
        for i in (0, 1):
            if _int(r, i) not in weps:
                out.append(f'nLink names missing weapon {_int(r, i)}')
    for kind in ('section', 'weapon', 'module', 'doodad'):
        pool = secs if kind == 'section' else {m.id for m in ship.mounts
                                              if m.kind == kind}
        for r in ship.of_kind(FAMILY[kind]['mir']):
            if _int(r, 1) != model.UNMIRRORED and _int(r, 1) not in pool:
                out.append(f'{FAMILY[kind]["mir"]} pairs {kind} {_int(r, 0)} '
                           f'with missing {kind} {_int(r, 1)}')
    return out


def _last_record(ship: model.Ship, kinds) -> model.Record | None:
    """The final record of any of these kinds, for insert-after placement."""
    found = None
    for r in ship.records:
        if r.kind in kinds:
            found = r
    return found


def next_secid(ship: model.Ship) -> int:
    """One past the highest, never filling a gap (D19)."""
    return max((s.id for s in ship.sections), default=0) + 1


def next_mount_id(ship: model.Ship, kind: str) -> int:
    return max((m.id for m in ship.mounts if m.kind == kind), default=-1) + 1


def next_depth(ship: model.Ship) -> float:
    """Behind everything currently drawn.

    ShipMaker assigns depth from an incrementing counter, so a later part sits
    at a larger depth, which in Game Maker means further back. Adding in front
    of existing work would be the surprising choice.
    """
    return max((s.depth for s in ship.sections), default=0.0) + 1


# --------------------------------------------------------------------------
# colour
# --------------------------------------------------------------------------

#: `nSecB` is where a section records *where its colour comes from*.
#: `l_colourmod` indexes the team's three-shade palette, and `-1` means custom
#: -- in which case `l_colour` beside it is the literal GM colour to draw.
SECB_COLOURMOD, SECB_COLOUR = 12, 13

#: `nCor`'s `l_colourtype` picks the palette, in the game's own index order.
COLOUR_TYPES = ('player', 'allied', 'pirate', 'alien', 'razor')


def _tier2(ship: model.Ship, kind: str, sid: int) -> model.Record | None:
    for r in ship.of_kind(kind):
        if _int(r, 0) == sid:
            return r
    return None


def set_colour(ship: model.Ship, sid: int, colour: int | None,
               shade: int = 0) -> str:
    """Fix a section's colour, or hand it back to the team palette.

    D7 says never to hand-edit `nSecB`, and this is the documented exception
    rather than a hole in it: the two fields written here are the ones every
    layer of the toolchain has been read on. ShipMaker offers them in its own
    section menu ("1. Default colour | 2. Custom Color") and its `nSecB` reader
    branches on exactly this value; `export.py` carries the pair across as
    `nSec2a`'s optional eleventh field; and the game's own `nSec2a` closes with
    `if argument10 = 0 then l_colour = global.colour[...] else l_colour =
    argument10`. Nothing here is inferred. The rest of `nSecB` is still
    untouchable for the reason D7 gives.

    **Both halves or neither.** `image_blend` on `nSecA` is what ShipMaker and
    this renderer draw; `l_colourmod`/`l_colour` on `nSecB` is what reaches the
    game. Writing only the first -- the obvious edit, and the one `stockship`
    made for its wreck tint -- produces a design that is the right colour in
    every picture and the team's colour in the only place that counts.
    """
    sec = ship.section(sid)
    if sec is None:
        raise EditError(f'no section {sid}')
    b = _tier2(ship, 'nSecB', sid)
    if b is None:
        raise EditError(
            f'section {sid} has no nSecB record, so a colour has nowhere to '
            f'live in the .shp -- it was added with no donor to clone from')
    if colour is None:
        if not 0 <= shade <= 2:
            raise EditError(f'team shade {shade} is out of range 0..2')
        colour = team_colour(ship, shade)
        b.set_num(SECB_COLOURMOD, shade)
        b.set_num(SECB_COLOUR, colour)
        how = f'team shade {shade}'
    else:
        b.set_num(SECB_COLOURMOD, -1)
        b.set_num(SECB_COLOUR, colour)
        how = 'custom'
    sec.rec.set_num(model.Section.IMAGE_BLEND, colour)
    r, g, bl = sprites.gm_colour(colour)
    return f'section {sid}: {how} #{r:02X}{g:02X}{bl:02X}'


def team_colour(ship: model.Ship, shade: int) -> int:
    """The GM colour this ship's own palette resolves a shade index to.

    The palette is the *team's*, not the ship's -- a hull spawns into one and is
    tinted by it -- so this is only what ShipMaker would show while editing,
    which is exactly what `image_blend` is for.
    """
    kind = 0
    core = ship.core
    if core is not None:
        kind = int(core.num(1))
    name = COLOUR_TYPES[kind] if 0 <= kind < len(COLOUR_TYPES) else 'player'
    shades = sprites.teams().get(name) or sprites.teams()['player']
    r, g, b = shades[min(shade, len(shades) - 1)]
    return r + g * 256 + b * 65536


# --------------------------------------------------------------------------
# donors
# --------------------------------------------------------------------------

#: A real ship, to clone a section's tier-2 block from when the hull being
#: built has no section of its own yet.
SECTION_DONOR = paths.PENDULUM


def pick_donor(ship: model.Ship, sprite: str, explicit: int | None,
               parent: int) -> tuple[model.Section | None, str]:
    """(donor, why) -- the section a new one copies its unmodelled state from.

    Preference order is by how likely the copy is to be faithful: the same
    sprite first (identical art almost always means identical rotator and
    effect setup), then the parent it is being attached to, then anything on
    this hull -- and only then a section off a real ship on disk.

    That last fallback is what makes an **empty** hull buildable. Without it the
    first section of a new design got no `nSecB/C/D/Tr` at all, and since every
    later section clones the first, a whole ship came out with no tier-2 records
    anywhere: no rotator state, and -- because `l_colourmod` lives in `nSecB` --
    nowhere for a fixed colour to live either. Cloning from disk is the same
    answer `weapon_template` already gives for the same problem (D16); inventing
    a default block is the one thing D7 rules out.
    """
    if explicit is not None:
        d = ship.section(explicit)
        if d is None:
            raise EditError(f'no section {explicit} to use as a donor')
        return d, f'section {explicit}, as asked'
    for s in ship.sections:
        if s.sprite == sprite:
            return s, f'section {s.id}, which uses the same sprite'
    p = ship.section(parent)
    if p is not None:
        return p, f'section {parent}, the new parent'
    if ship.sections:
        s = ship.sections[0]
        return s, f'section {s.id}, the only candidate'
    if SECTION_DONOR.exists():
        d = model.load(SECTION_DONOR)
        s = _plainest(d)
        if s is not None:
            return s, (f'{SECTION_DONOR.name} section {s.id} -- this hull has '
                       f'none of its own yet')
    return None, 'none -- corpus defaults used'


def _plainest(ship: model.Ship) -> model.Section | None:
    """The most inert section on a ship: no effect, no rotation, no movement.

    Only ever used for the off-ship fallback, and there it matters. Taking
    `sections[0]` took Pendulum's, which carries `effect = 5` -- the Aegis blur,
    which redraws its sprite dozens of times a frame under additive blending.
    Ten sections of it came back on the first hull built from nothing, on a
    design whose whole point was to look switched off. A caller who has asked
    for nothing has asked for a plain plate.
    """
    def loud(s: model.Section) -> int:
        n = 0
        for kind, field in (('nSecC', 1), ('nSecB', 1), ('nSecD', 5)):
            r = _tier2(ship, kind, s.id)
            n += bool(r is not None and _int(r, field, 0))
        return n

    return min(ship.sections, key=loud, default=None)


def write_section_block(ship: model.Ship, seca: list[str],
                        donor: model.Section | None,
                        mirrored: bool = False) -> list[model.Record]:
    """Append a whole section -- `nSecA` then its tier-2 records -- in one block.

    ShipMaker writes each section as five consecutive records, so the block goes
    in after the last section-family record rather than each record after its
    own kind. Interleaving them parses identically but makes the file unreadable
    next to the editor's own output, and a `ship diff` unreadable with it.

    Only the fields that describe *this* section's own state are rewritten: its
    id, and -- when the new section is a mirror image -- the handed rotator,
    effect and trigger settings. Everything else is carried across verbatim,
    which is the point of cloning rather than templating.

    The donor is a `Section`, not an id, because it may belong to a *different*
    ship: an empty hull has nothing of its own to clone and falls back to one on
    disk. Reading the records off `donor.ship` rather than off `ship` is the
    whole of what that costs.
    """
    new_id = int(float(seca[0]))
    after = _last_record(ship, ('nSecA',) + SECTION_TIER2)
    after = ship.add_record('nSecA', seca, after)
    made = [after]
    if donor is None:
        return made
    for kind in SECTION_TIER2:
        src = None
        for r in donor.ship.of_kind(kind):
            if _int(r, 0) == donor.id:
                src = r
                break
        if src is None:
            continue
        toks = list(src.tokens)
        toks[0] = str(new_id)
        if mirrored:
            _mirror_tier2(kind, toks)
        after = ship.add_record(kind, toks, after)
        made.append(after)
    return made


def _mirror_tier2(kind: str, t: list[str]) -> None:
    """Apply ShipMaker's handed-field transform in place."""
    def num(i, d=0.0):
        try:
            return float(t[i])
        except (IndexError, ValueError):
            return d

    if kind == 'nSecB':
        for a, b in SECB_SWAP:
            if max(a, b) < len(t):
                t[a], t[b] = t[b], t[a]
        for a, b in SECB_NEGSWAP:
            if max(a, b) < len(t):
                va, vb = num(a), num(b)
                t[a], t[b] = model.gmstr(-vb), model.gmstr(-va)
        for i in SECB_NEG:
            if i < len(t):
                t[i] = model.gmstr(-num(i))
        if SECB_SIDE < len(t):
            t[SECB_SIDE] = '0' if num(SECB_SIDE) < 0 else '-1'
    elif kind == 'nSecC':
        for i in SECC_NEG:
            if i < len(t):
                t[i] = model.gmstr(-num(i))
    elif kind == 'nSecTr':
        for i in SECTR_TYPES:
            if i < len(t):
                t[i] = str(TRIGGER_FLIP.get(int(num(i)), int(num(i))))


# --------------------------------------------------------------------------
# add
# --------------------------------------------------------------------------

def add_section(ship: model.Ship, sprite: str, x: float, y: float, *,
                parent: int = 0, angle: float = 0.0,
                xscale: float = 1.0, yscale: float = 1.0,
                depth: float | None = None,
                donor: int | None = None) -> tuple[int, list[str]]:
    """Create a section at a core-relative position. Returns (secid, notes)."""
    if sprites.resolve(sprite) is None:
        raise EditError(
            f'no sprite resolves to {sprite!r}\n'
            f'  sb4 names a file under "Custom sprites/", '
            f'e.g. Stock Sections\\BSF_Stock17.png')
    if parent and ship.section(parent) is None:
        raise EditError(f'no section {parent} to parent to')

    sid = next_secid(ship)
    d, why = pick_donor(ship, sprite, donor, parent)
    notes = [f'donor: {why}']

    if d is not None:
        toks = list(d.rec.tokens)
    else:
        toks = ['0', '0', '0', sprite, '1', '1', '0', '-1',
                model.gmstr(DEFAULT_DEFHP), '1', '1', str(DEFAULT_BLEND), '1', '0']
        notes.append(f'no donor: l_defhp defaults to {DEFAULT_DEFHP} (corpus '
                     f'median) — it is per-section state with no formula, so '
                     f'set it in ShipMaker if it matters')
    S = model.Section
    toks[0] = str(sid)
    toks[S.X] = model.gmstr(ship.core_x + x)
    toks[S.Y] = model.gmstr(ship.core_y + y)
    toks[S.SPRITE] = sprite
    toks[S.XS] = model.gmstr(xscale)
    toks[S.YS] = model.gmstr(yscale)
    toks[S.ANGLE] = model.gmstr(angle)
    toks[S.DEPTH] = model.gmstr(next_depth(ship) if depth is None else depth)
    toks[S.PARENT] = str(parent)
    if d is not None and d.sprite != sprite:
        notes.append(f'l_defhp {toks[S.DEFHP]} inherited from a section with a '
                     f'different sprite — set it in ShipMaker if it matters')

    write_section_block(ship, toks, d)
    if d is None:
        notes.append('no donor: this section has no nSecB/C/D/Tr records, so '
                     'ShipMaker will load it with its own defaults')
    return sid, notes


# --------------------------------------------------------------------------
# weapons
# --------------------------------------------------------------------------

#: A real weapon, to clone the unrecovered tail of `nWepB` and friends from.
WEAPON_DONOR = paths.PENDULUM


#: `nWepB` fields that `export` feeds to `nWep2a`, every one of which that
#: handler tests against `-1` before assigning. **(GML)** In order: firingrate,
#: firingclip, firingreload, damage, hp, range, deviation, turning, bulletcol,
#: bulletspeed. `nWepC[1..5]` are the five specials and behave the same way.
WEPB_STATS = (4, 5, 6, 7, 8, 9, 10, 11, 12, 13)
WEPC_STATS = (1, 2, 3, 4, 5)

#: `l_arcrange`. `nTur2` assigns it unconditionally -- it is the one turret
#: field with **no** `-1` sentinel -- so a new mount has to state a real value
#: and there is no "whatever the object thinks". 180 means the full circle.
DEFAULT_ARC = 180.0


def weapon_template(ship: model.Ship) -> dict[str, list[str]]:
    """Token lists for one real weapon's records.

    `nWepA` is understood field by field, but `nWepB` past `parent.secid` and
    all of `nWepC/D/Tr` were never recovered -- so a new weapon clones them from
    an existing one rather than inventing values, exactly as a new section
    clones its tier-2 records from a donor section (D16). A weapon already on
    the ship is the best donor; failing that, one off a real ship on disk.

    **The least customised weapon, not the first.** Pendulum's weapon 0 is its
    PlasmaBall, which carries a hand-tuned firing rate, clip, reload, damage,
    range and five specials -- and taking `ids[0]` handed every one of those to
    whatever you mounted next.
    """
    for src in (ship, None):
        s = src
        if s is None:
            if not WEAPON_DONOR.exists():
                return {}
            s = model.load(WEAPON_DONOR)
        ids = [int(r.num(0)) for r in s.of_kind('nWepA')]
        if not ids:
            continue
        by_id = {k: {r.kind: r for r in s.records
                     if r.kind.startswith('nWep') and r.kind != 'nWepMir'
                     and _int(r, 0) == k} for k in ids}

        def tuned(k: int) -> int:
            recs = by_id[k]
            n = sum(_int(recs['nWepB'], i, -1) != -1 for i in WEPB_STATS
                    if 'nWepB' in recs)
            n += sum(_int(recs['nWepC'], i, -1) != -1 for i in WEPC_STATS
                     if 'nWepC' in recs)
            return n

        wid = min(ids, key=tuned)
        out = {k: list(r.tokens) for k, r in by_id[wid].items()}
        if 'nWepA' in out:
            return out
    return {}


def _stock_stats(tpl: dict[str, list[str]], arc: float | None) -> None:
    """Blank the donor's *stats* out of a cloned weapon template, in place.

    Cloning is right for the fields nobody has decoded and wrong for the ones
    that are the weapon's identity. A Railgun mounted by copying Pendulum's
    PlasmaBall came out firing at the PlasmaBall's rate, for its damage, to its
    range -- correct in every render, because a render only draws the sprite.

    `-1` is the loader's own answer: `nWep2a` tests each stat against it and
    only then assigns, so a mount written in `-1`s shoots exactly like the
    object it names. `arcrange` is the exception and gets a real value, because
    `nTur2` has no sentinel for it.
    """
    b = tpl.get('nWepB')
    if b is not None:
        for i in WEPB_STATS:
            if i < len(b):
                b[i] = '-1'
        while len(b) <= 2:
            b.append('0')
        b[2] = model.gmstr(DEFAULT_ARC if arc is None else arc)
    c = tpl.get('nWepC')
    if c is not None:
        for i in WEPC_STATS:
            if i < len(c):
                c[i] = '-1'
    d = tpl.get('nWepD')
    if d is not None and len(d) > 3:
        d[3] = ''                       # l_name: "" also means keep


def add_weapon(ship: model.Ship, obj: str, x: float, y: float, *,
               parent: int = 0, angle: float = 0.0, arc: float | None = None,
               mirror: bool = False) -> tuple[int, list[str]]:
    """Mount a weapon at a core-relative position. Returns (wepid, notes).

    `obj` is the game's own object name -- `PointMaser`, `Blaster`,
    `ParticleGun` -- which is what `nWepA[3]` stores and what the sprite
    resolver already knows how to find.

    A **module** is not one of those, however much it looks like a turret on the
    hull, and this function used to take one without complaint: an earlier
    version of this docstring offered `NanoMatrix` as an example, which is
    exactly how `station_bolthole` acquired a module in its weapon table and
    shipped a `.shp` that loaded with no weapons at all. Modules go through
    `add_module`, and `ship arm` routes by object so the caller does not have to
    know which is which.
    """
    if obj in sprites.MODULES:
        raise EditError(
            f'{obj} is a module, not a weapon -- the game reads l_bullet off '
            f'every weapon mount and a module has none, which kills the whole '
            f'ship on load. Use add_module (ship arm does this for you).')
    sp, _path, _note = sprites.best(obj, mask=False, pivot=True)
    if sp is None:
        raise EditError(f'no sprite resolves to weapon {obj!r}')
    if parent and ship.section(parent) is None:
        raise EditError(f'no section {parent} to mount on')
    tpl = weapon_template(ship)
    if 'nWepA' not in tpl:
        raise EditError('no weapon to clone the unmodelled nWep fields from')
    _stock_stats(tpl, arc)

    notes: list[str] = []
    wid = next_mount_id(ship, 'weapon')
    after = _last_record(ship, tuple(tpl))
    a = list(tpl['nWepA'])
    a[0] = str(wid)
    a[1] = model.gmstr(ship.core_x + x)
    a[2] = model.gmstr(ship.core_y + y)
    a[3] = obj
    a[6] = model.gmstr(angle)
    after = ship.add_record('nWepA', a, after)
    if 'nWepB' in tpl:
        b = list(tpl['nWepB'])
        b[0] = str(wid)
        b[1] = str(parent)
        if arc is not None and len(b) > 2:
            b[2] = model.gmstr(arc)
        after = ship.add_record('nWepB', b, after)
    for kind in ('nWepC', 'nWepD', 'nWepTr'):
        if kind in tpl:
            t = list(tpl[kind])
            t[0] = str(wid)
            after = ship.add_record(kind, t, after)
    notes.append(f'{obj} {wid} at {x:+g},{y:+g} on '
                 f'{"the core" if not parent else f"section {parent}"}, '
                 f'stock stats, arc {DEFAULT_ARC if arc is None else arc:g}')

    if mirror and abs(y) >= 1:
        twin = next_mount_id(ship, 'weapon')
        pm = ship.mirrors.get(parent, model.UNMIRRORED)
        host = pm if pm >= 0 else parent
        a2 = list(a)
        a2[0] = str(twin)
        a2[2] = model.gmstr(ship.core_y - y)
        a2[6] = model.gmstr(-angle)          # weapons negate angle, never yscale
        after = ship.add_record('nWepA', a2, after)
        if 'nWepB' in tpl:
            b2 = list(tpl['nWepB'])
            b2[0] = str(twin)
            b2[1] = str(host)
            if arc is not None and len(b2) > 2:
                b2[2] = model.gmstr(arc)
            after = ship.add_record('nWepB', b2, after)
        for kind in ('nWepC', 'nWepD', 'nWepTr'):
            if kind in tpl:
                t = list(tpl[kind])
                t[0] = str(twin)
                after = ship.add_record(kind, t, after)
        _pair(ship, 'weapon', wid, twin)
        notes.append(f'mirrored as {twin} at {x:+g},{-y:+g}')
    return wid, notes


def add_module(ship: model.Ship, obj: str, x: float, y: float, *,
               parent: int = 0, angle: float = 0.0,
               mirror: bool = False) -> tuple[int, list[str]]:
    """Mount a module at a core-relative position. Returns (modid, notes).

    The counterpart to `add_weapon`, and the reason it exists is that the two
    are not interchangeable to the game even though they are both "a thing bolted
    to a section": the loader reads `l_bullet` off every *weapon* mount, a module
    has none, and the read throws inside the ship's Create event and abandons
    everything after it. A module in the weapon table therefore does not cost
    you a module -- it costs you every weapon on the ship.

    Unlike a weapon, this does not clone a donor. `nModA`/`nModB` are understood
    field by field (they are in the reference table), so the records are written
    outright -- from `sprites.MODULE_DEFAULTS` where the object has been measured
    in a running game, and otherwise from the `-1` sentinel, which `nMod2` reads
    as *keep whatever the object's Create event set*. Stock stats either way.

    Writing a **zero** is the thing to never do: `0 != -1`, so it overrides, and
    a NanoMatrix with range 0 repairs nothing while looking exactly like one
    that works.
    """
    if obj not in sprites.MODULES:
        raise EditError(f'{obj} is not a module -- use add_weapon')
    sp, _path, _note = sprites.best(obj, mask=False, pivot=True)
    if sp is None:
        raise EditError(f'no sprite resolves to module {obj!r}')
    if parent and ship.section(parent) is None:
        raise EditError(f'no section {parent} to mount on')
    K = sprites.MODULE_KEEP
    d = sprites.MODULE_DEFAULTS.get(obj) or dict(
        hp=K, range=K, eng=K, engregen=K, cost=K, special=(K,) * 8)

    notes: list[str] = []
    if obj not in sprites.MODULE_DEFAULTS:
        notes.append(f'{obj} has no measured entry, so every stat is written as '
                     f'-1 and the game uses the object\'s own')
    mid = next_mount_id(ship, 'module')
    after = _last_record(ship, ('nModC', 'nModB', 'nModA',
                                'nWepTr', 'nWepD', 'nWepC', 'nWepB', 'nWepA'))

    def records(mno: int, yy: float, ang: float, host: int) -> None:
        nonlocal after
        a = [str(mno), model.gmstr(ship.core_x + x), model.gmstr(ship.core_y + yy),
             obj, '1', '1', model.gmstr(ang), '0', '0', '-1',
             model.gmstr(d['hp']), model.gmstr(d['range']), '0',
             model.gmstr(d['eng']), model.gmstr(d['engregen']),
             model.gmstr(d['cost'])]
        after = ship.add_record('nModA', a, after)
        b = ([str(mno), str(host)]
             + [model.gmstr(v) for v in d['special']] + ['1', '0'])
        after = ship.add_record('nModB', b, after)
        after = ship.add_record('nModC', [str(mno), '0'], after)

    records(mid, y, angle, parent)
    notes.append(f'{obj} {mid} at {x:+g},{y:+g} on '
                 f'{"the core" if not parent else f"section {parent}"}')

    if mirror and abs(y) >= 1:
        twin = next_mount_id(ship, 'module')     # the first record is already in
        pm = ship.mirrors.get(parent, model.UNMIRRORED)
        host = pm if pm >= 0 else parent
        records(twin, -y, -angle, host)
        _pair(ship, 'module', mid, twin)
        notes.append(f'mirrored as {twin} at {x:+g},{-y:+g}')
    return mid, notes


def find_mount(ship: model.Ship, kind: str, mid: int) -> model.Mount | None:
    for m in ship.mounts:
        if m.kind == kind and m.id == mid:
            return m
    return None


def move_mount(ship: model.Ship, kind: str, mid: int, dx: float, dy: float, *,
               mirror: bool = True) -> list[str]:
    """Nudge one mounted part on its own, without moving its section.

    The counterpart to D18: a section edit carries its mounts, but placing a
    turret on a hull is its own operation and needs the mount to move alone.
    """
    m = find_mount(ship, kind, mid)
    if m is None:
        raise EditError(f'no {kind} {mid}')
    done = []
    m.set_pos(round(m.x + dx, 2), round(m.y + dy, 2))
    done.append(f'{kind} {mid} -> {m.x:+g},{m.y:+g}')
    if mirror:
        partner = ship.mirror_map(kind).get(mid, model.UNMIRRORED)
        tw = find_mount(ship, kind, partner) if partner >= 0 else None
        if tw is not None and tw is not m:
            tw.set_pos(round(tw.x + dx, 2), round(tw.y - dy, 2))
            done.append(f'{kind} {partner} -> {tw.x:+g},{tw.y:+g}  (mirror)')
    return done


def rotate_mount(ship: model.Ship, kind: str, mid: int, by: float, *,
                 mirror: bool = True) -> list[str]:
    m = find_mount(ship, kind, mid)
    if m is None:
        raise EditError(f'no {kind} {mid}')
    done = []
    m.angle = round((m.angle + by) % 360, 2)
    done.append(f'{kind} {mid} -> {m.angle:g}deg')
    if mirror:
        partner = ship.mirror_map(kind).get(mid, model.UNMIRRORED)
        tw = find_mount(ship, kind, partner) if partner >= 0 else None
        if tw is not None and tw is not m:
            tw.angle = round((tw.angle - by) % 360, 2)
            done.append(f'{kind} {partner} -> {tw.angle:g}deg  (mirror)')
    return done


def remove_mount(ship: model.Ship, kind: str, mid: int, *,
                 mirror: bool = True) -> list[str]:
    """Unbolt one mounted part, and its reflected twin unless told otherwise."""
    m = find_mount(ship, kind, mid)
    if m is None:
        raise EditError(f'no {kind} {mid}')
    victims = [mid]
    if mirror:
        partner = ship.mirror_map(kind).get(mid, model.UNMIRRORED)
        if partner >= 0 and partner != mid and find_mount(ship, kind, partner):
            victims.append(partner)
    doomed: list[model.Record] = []
    gone = []
    for v in victims:
        mv = find_mount(ship, kind, v)
        gone.append(f'removed {kind} {v} ({mv.name})')
        doomed += owned_records(ship, kind, v)
    ship.drop_records(doomed)
    return gone


# --------------------------------------------------------------------------
# mirror
# --------------------------------------------------------------------------

def mirror_section(ship: model.Ship, sid: int, *,
                   with_children: bool = False) -> tuple[list[int], list[str]]:
    """Create the reflected partner of a section, and of everything on it.

    Reflection is about the core's horizontal centreline, which is what
    `nSecMir` records and what the editor's own routine does.
    """
    todo = _subtree(ship, sid) if with_children else [sid]
    made: list[int] = []
    notes: list[str] = []
    pairs: dict[int, int] = {}          # original secid -> new secid

    for t in todo:
        src = ship.section(t)
        if src is None:
            continue
        if ship.mirrors.get(t, model.UNMIRRORED) >= 0:
            notes.append(f'section {t} already has a partner '
                         f'({ship.mirrors[t]}) — left alone')
            continue
        new = _reflect_section(ship, src)
        pairs[t] = new
        made.append(new)

    # Parents are remapped only once every partner exists, because a child's
    # new parent may be a section created moments ago in this same loop.
    for old, new in pairs.items():
        _remap_parent(ship, old, new, pairs)
        for m in ship.mounts_of(old):
            _reflect_mount(ship, m, new, pairs, notes)

    if not made:
        notes.append('nothing to mirror')
    return made, notes


def _subtree(ship: model.Ship, sid: int) -> list[int]:
    out, stack = [], [sid]
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.append(cur)
        stack += [s.id for s in ship.sections if s.parent == cur]
    return out


def open_depth_behind(ship: model.Ship, depth: float) -> float:
    """Free up the layer immediately behind `depth`, and return it.

    Measured across the ships on disk: 69 of 73 mirror pairs sit at **adjacent**
    depths, and the four that do not carry hand-set values. That is the
    convention because a reflection is the same part on the other side of the
    hull -- it belongs in its partner's layer, not at the back of the stack,
    which is where `next_depth()` used to put it. On the Ratline beacon that
    left one of four otherwise identical spar caps drawn *behind* the spar the
    other three sat in front of, on a hull that was symmetric in every other
    respect.

    Everything at or beyond the new layer shifts back one to keep depths
    unique, which they must be: `export` warns and ShipMaker drops sections that
    collide.
    """
    want = depth + 1
    for s in ship.sections:
        if s.depth >= want:
            s.depth = s.depth + 1
    return want


def _reflect_section(ship: model.Ship, src: model.Section) -> int:
    sid = next_secid(ship)
    S = model.Section
    depth = open_depth_behind(ship, src.depth)
    toks = list(src.rec.tokens)
    toks[0] = str(sid)
    toks[S.Y] = model.gmstr(ship.core_y - src.y)
    toks[S.YS] = model.gmstr(-src.yscale)
    toks[S.ANGLE] = model.gmstr(-src.angle)
    toks[S.DEPTH] = model.gmstr(depth)
    write_section_block(ship, toks, src, mirrored=True)
    _pair(ship, 'section', src.id, sid)
    return sid


def _remap_parent(ship: model.Ship, old: int, new: int,
                  pairs: dict[int, int]) -> None:
    """The reflected copy hangs off the reflection of the original's parent.

    Transcribed from the editor:

        if src.parent is the core || |src.parent.y - core.y| < 1:
            copy.parent = src.parent            # on the centreline: shared
        else:
            copy.parent = src.parent.l_mirrored

    A parent sitting on the centreline is its own mirror, so both halves hang
    off the same one; anything else would leave the copy parented across the
    ship.
    """
    src = ship.section(old)
    dst = ship.section(new)
    if src is None or dst is None:
        return
    pid = src.parent
    if pid == 0:
        dst.parent = 0
        return
    p = ship.section(pid)
    if p is not None and abs(p.y) < 1:
        dst.parent = pid
        return
    partner = pairs.get(pid, ship.mirrors.get(pid, model.UNMIRRORED))
    dst.parent = partner if partner >= 0 else pid


def _reflect_mount(ship: model.Ship, m: model.Mount, new_parent: int,
                   pairs: dict[int, int], notes: list[str]) -> None:
    """Copy a mount onto the reflected section, with its handed fields flipped.

    Weapons negate their angle (and `Sidewinder` alone also flips its yscale,
    because its sprite is not symmetric about the barrel). Modules negate their
    angle, retarget through the mirror, and thrusters reverse their exhaust
    direction. Doodads only negate their angle -- the editor does not flip their
    yscale, and matching that matters because a doodad is art, not geometry.
    """
    if m.mirror is not None and m.mirror >= 0:
        return
    spec = model.MOUNTS[m.kind]
    new_id = next_mount_id(ship, m.kind)

    made: dict[str, model.Record] = {}
    src = [r for r in owned_records(ship, m.kind, m.id) if r.kind != spec.mir]
    after = _last_record(ship, tuple({r.kind for r in src}))
    for r in src:
        toks = list(r.tokens)
        toks[0] = str(new_id)
        after = ship.add_record(r.kind, toks, after)
        made[r.kind] = after

    a = made.get(spec.a)
    if a is None:
        return
    b = made.get(spec.b) if spec.b else None
    copy = model.Mount(spec, a, b, ship)
    copy.set_pos(m.x, -m.y)
    copy.angle = round(-m.angle, 2)
    copy.parent = new_parent
    if m.kind == 'weapon' and m.name == 'Sidewinder':
        copy.yscale = -m.yscale
    elif m.kind == 'module':
        tgt = _int(a, 12)
        if tgt > 0:
            moved = pairs.get(tgt, ship.mirrors.get(tgt, model.UNMIRRORED))
            if moved >= 0:
                a.set_num(12, moved)
        if b is not None and m.name in ('Thruster', 'ThrusterEx'):
            b.set_num(7, round(360 - b.num(7), 2))
    _pair(ship, m.kind, m.id, new_id)
    notes.append(f'{m.kind} {m.id} mirrored as {new_id}')


def _pair(ship: model.Ship, kind: str, a: int, b: int) -> None:
    """Record the mirror link in both directions, as ShipMaker does."""
    rk = FAMILY[kind]['mir']
    after = _last_record(ship, (rk,))
    for lhs, rhs in ((a, b), (b, a)):
        for r in ship.of_kind(rk):
            if _int(r, 0) == lhs:
                r.set_num(1, rhs)
                break
        else:
            after = ship.add_record(rk, [str(lhs), str(rhs)], after)


# --------------------------------------------------------------------------
# remove
# --------------------------------------------------------------------------

def remove_section(ship: model.Ship, sid: int, *, orphan: bool = False,
                   mirror: bool = True) -> tuple[list[str], list[str]]:
    """Delete a section and everything that hangs off it. (removed, warnings)

    The cascade is the whole point: a section owns its mounts and doodads
    outright, and by default owns its children too, so deleting only the
    `nSecA` would leave a ship full of parts orbiting nothing. `--orphan`
    re-parents the children to the deleted section's own parent instead of
    taking them.
    """
    roots = [sid]
    if mirror:
        partner = ship.mirrors.get(sid, model.UNMIRRORED)
        if partner >= 0 and partner != sid and ship.section(partner) is not None:
            roots.append(partner)

    victims: list[int] = []
    for r in roots:
        for t in _subtree(ship, r) if not orphan else [r]:
            if t not in victims:
                victims.append(t)

    removed: list[str] = []
    if orphan:
        for r in roots:
            sec = ship.section(r)
            up = sec.parent if sec else 0
            for kid in [s for s in ship.sections if s.parent == r]:
                kid.parent = up
                removed.append(f'kept    section {kid.id}, now on '
                               f'{"the core" if not up else f"section {up}"}')

    doomed: list[model.Record] = []
    for t in victims:
        sec = ship.section(t)
        if sec is None:
            continue
        removed.append(f'removed section {t} ({sec.name})')
        for m in ship.mounts_of(t):
            removed.append(f'        {m.kind} {m.id} ({m.name})')
            doomed += owned_records(ship, m.kind, m.id)
        doomed += owned_records(ship, 'section', t)

    ship.drop_records(doomed)
    return removed, dangling(ship)


# --------------------------------------------------------------------------
# reparent
# --------------------------------------------------------------------------

def reparent(ship: model.Ship, sid: int, to: int, *,
             mirror: bool = True) -> list[str]:
    """Re-hang a section, taking its partner to the partner of the new parent."""
    sec = ship.section(sid)
    if sec is None:
        raise EditError(f'no section {sid}')
    if to and ship.section(to) is None:
        raise EditError(f'no section {to} to parent to')
    if to == sid or to in _subtree(ship, sid):
        raise EditError(f'section {to} is inside {sid}\'s own subtree — '
                        f'that would make a cycle')
    done = []
    sec.parent = to
    done.append(f'section {sid} -> {to or "core"}')
    if mirror:
        partner = ship.mirrors.get(sid, model.UNMIRRORED)
        psec = ship.section(partner) if partner >= 0 else None
        if psec is not None:
            up = ship.section(to)
            if to == 0:
                pto = 0
            elif up is not None and abs(up.y) < 1:
                pto = to
            else:
                pto = ship.mirrors.get(to, model.UNMIRRORED)
                pto = pto if pto >= 0 else to
            psec.parent = pto
            done.append(f'section {partner} -> {pto or "core"}  (mirror)')
    return done

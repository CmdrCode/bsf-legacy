#!/usr/bin/env python3
"""Read, edit and write Battleships Forever ship files without losing anything.

A ship file is a flat list of comma-separated records. ShipMaker's `.sb4` carries
far more per section than geometry -- rotators, effects, fades, triggers, driver
links -- and most of it has semantics we have only partially recovered. So the
model has **two tiers**:

  understood   nShp, nCor, nSecA, nSecMir, nWepA, nWepB
               parsed into typed views, editable, rendered, queryable

  preserved    everything else
               kept as its original token text and re-emitted unchanged

The mechanism that makes the second tier free is that a record holds its fields
as **strings**, never as parsed numbers. Typed accessors convert on read and
format on write, so a field nobody touched is emitted as the exact bytes it
arrived as. Byte-exact round-trip is therefore a property of the design rather
than something the number formatter has to earn -- which matters, because GM
writes reals at exactly two decimals (`1.50`, `230.33`, `8454016.02`) and
re-serialising an untouched value would show up in `ship diff` as corruption.

Two `.sb4` versions exist in the wild and both are handled:

    //sb4 ver1   Pendulum.sb4              nSecTr has 10 fields
    //sb4 ver2   station_bolthole.sb4      nSecTr has a trailing comma

Line endings, blank runs, comment banners and the trailing-comma quirk all
survive because unparsed lines are stored verbatim.
"""
from __future__ import annotations

import pathlib
import re

#: Old-format ship files are obfuscated by adding this to every byte. Newer ones
#: are plain and start with `//`. The transform is its own inverse under mod 256
#: arithmetic in the opposite direction, so encode/decode round-trip exactly.
BYTE_OFFSET = 68

#: A record line: an `n`-prefixed identifier followed by a comma. Everything else
#: (comment banners, blank lines, stray GML in sh1/sh2 files) is kept verbatim.
RECORD_RE = re.compile(r'^(n[A-Za-z0-9_]*),')

#: Records we parse into typed views. Everything else round-trips untouched.
UNDERSTOOD = {'nShp', 'nShp2', 'nCor', 'nSecA', 'nSecMir',
              'nWepA', 'nWepB', 'nWepMir',
              'nModA', 'nModB', 'nModMir',
              'nDooA', 'nDooMir'}

#: ShipMaker writes `-4` into a mirror record when the part has no partner. It is
#: GML's "no instance" sentinel leaking into the file format.
UNMIRRORED = -4

#: The core's sprite by `image_index` -- ShipMaker's `getcore()`. `.sb4` stores
#: the index in `nCor`; every other generation stores the name it maps to, as a
#: plain `sprite_index` setting rather than a record.
CORE_SPRITES = {
    0: 'spr_Core', 1: 'spr_Alien', 2: 'spr_Pirate', 3: 'spr_Civilian',
    4: 'spr_Coresml', 5: 'spr_Platform', 6: 'spr_Spacestation',
    7: 'spr_Spacestationrot',
}
CORE_INDEX = {v.lower(): k for k, v in CORE_SPRITES.items()}

#: A top-level `key,value` (sh3) or `key=value` (sh1/sh2) line. Anchored on the
#: whole left-hand side so a per-section `l_section[j].image_xscale=1` cannot be
#: mistaken for the ship's own setting -- there are hundreds of those in an sh1
#: file and exactly one of the real thing.
SETTING_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*[,=]\s*(.*?)\s*$')


def gmstr(v: float) -> str:
    """Format a number the way Game Maker's `string(real)` does.

    GM prints an integral value with no decimal point and everything else at
    exactly two places -- which is why every non-integer in a real `.sb4` is
    `1.50`, `230.33`, `-1.10`, `8454016.02` and never `1.5` or `230.333`.

    Only ever applied to fields that were actually modified; untouched fields
    keep their original text, so a bug here cannot corrupt a field nobody edited.
    """
    if v != v or v in (float('inf'), float('-inf')):
        raise ValueError(f'not representable in a ship file: {v!r}')
    r = round(float(v), 2)
    if r == int(r):
        return str(int(r))
    return f'{r:.2f}'


# --------------------------------------------------------------------------
# raw document
# --------------------------------------------------------------------------

class Line:
    """A verbatim line: comment banner, blank line, or anything unrecognised."""

    __slots__ = ('text', 'eol')

    def __init__(self, text: str, eol: str):
        self.text = text
        self.eol = eol

    def render(self) -> str:
        return self.text + self.eol


class Record(Line):
    """A `kind,field,field,...` line, with fields held as strings.

    `tokens` excludes the kind. A trailing comma in the source becomes a final
    empty token, so re-joining reproduces it -- that is how `.sb4` ver2's
    `nSecTr,...,90,90,` survives without a special case.
    """

    __slots__ = ('kind', 'tokens', 'dirty')

    def __init__(self, kind: str, tokens: list[str], eol: str):
        self.kind = kind
        self.tokens = tokens
        self.eol = eol
        self.dirty = False

    @property
    def text(self) -> str:                                    # type: ignore[override]
        return self.kind + ',' + ','.join(self.tokens)

    def render(self) -> str:
        return self.text + self.eol

    # -- field access ------------------------------------------------------
    def num(self, i: int, default: float = 0.0) -> float:
        try:
            return float(self.tokens[i])
        except (IndexError, ValueError):
            return default

    def txt(self, i: int, default: str = '') -> str:
        try:
            return self.tokens[i]
        except IndexError:
            return default

    def set_num(self, i: int, v: float) -> None:
        self._set(i, gmstr(v))

    def set_txt(self, i: int, v: str) -> None:
        self._set(i, v)

    def _set(self, i: int, s: str) -> None:
        while len(self.tokens) <= i:
            self.tokens.append('0')
        if self.tokens[i] != s:
            self.tokens[i] = s
            self.dirty = True


def _readable(raw: bytes, sample: int = 4096) -> float:
    """Fraction of a sample that is printable ASCII or ordinary whitespace."""
    head = raw[:sample]
    if not head:
        return 1.0
    ok = sum(1 for b in head if b in (9, 10, 13) or 32 <= b < 127)
    return ok / len(head)


def decode(raw: bytes) -> tuple[str, bool]:
    """Return (text, was_obfuscated), choosing whichever reading is text.

    Sniffing for a leading `//` is not enough, and getting this wrong is silent:
    of the 168 ship files on disk only 20 begin with a comment, 141 are plain
    Game Maker source beginning with `event_inherited()` or `sprite_index=`, and
    7 are genuinely shifted. Treating "does not start with //" as "obfuscated"
    turns those 141 into mojibake -- which a byte-exact round-trip test cannot
    catch, because `encode` undoes whatever `decode` did and the bytes come back
    identical either way. It only shows up the moment something tries to *read*
    a ship, which is why the corpus miner found sections in 19 files out of 168.

    So both readings are scored and the one that looks like text wins. There is
    no threshold to tune: the shift maps most letters out of the ASCII range, so
    for a real file the two scores are never close.
    """
    if raw[:2] == b'//':
        return raw.decode('latin1'), False
    shifted = bytes((b - BYTE_OFFSET) & 0xFF for b in raw)
    if _readable(shifted) > _readable(raw):
        return shifted.decode('latin1'), True
    return raw.decode('latin1'), False


def encode(text: str, obfuscated: bool) -> bytes:
    raw = text.encode('latin1')
    if not obfuscated:
        return raw
    return bytes((b + BYTE_OFFSET) & 0xFF for b in raw)


def split_lines(text: str) -> list[tuple[str, str]]:
    """Split into (content, eol) pairs, preserving CRLF/LF/absent-final-newline."""
    out: list[tuple[str, str]] = []
    i = 0
    n = len(text)
    while i < n:
        j = text.find('\n', i)
        if j < 0:
            out.append((text[i:], ''))
            break
        line = text[i:j]
        if line.endswith('\r'):
            out.append((line[:-1], '\r\n'))
        else:
            out.append((line, '\n'))
        i = j + 1
    return out


# --------------------------------------------------------------------------
# typed views
# --------------------------------------------------------------------------

class Section:
    """A hull section, backed by its `nSecA` record.

    Field order is ShipMaker's own, recovered from the save routine:

        nSecA,secid,x,y,lname,image_xscale,image_yscale,image_angle,
              l_hp,l_defhp,l_blend,image_alpha,image_blend,depth,secparent

    Coordinates in the file are absolute canvas; callers work in core-relative
    space and the ship converts. `secparent` is 0 for the core (unlike `.shp`,
    which uses -1).
    """

    X, Y = 1, 2
    SPRITE = 3
    XS, YS, ANGLE = 4, 5, 6
    HP, DEFHP = 7, 8
    BLEND, ALPHA, IMAGE_BLEND = 9, 10, 11
    DEPTH, PARENT = 12, 13

    def __init__(self, rec: Record, ship: 'Ship'):
        self.rec = rec
        self.ship = ship

    # -- identity ----------------------------------------------------------
    @property
    def id(self) -> int:
        return int(self.rec.num(0))

    @property
    def sprite(self) -> str:
        """Path relative to `Custom sprites/`, using the file's own backslashes."""
        return self.rec.txt(self.SPRITE)

    @property
    def name(self) -> str:
        """Bare sprite stem, e.g. `BSF_Stock17`."""
        return self.sprite.replace('\\', '/').rsplit('/', 1)[-1].rsplit('.', 1)[0]

    # -- geometry, core-relative -------------------------------------------
    @property
    def x(self) -> float:
        return round(self.rec.num(self.X) - self.ship.core_x, 2)

    @property
    def y(self) -> float:
        return round(self.rec.num(self.Y) - self.ship.core_y, 2)

    def set_pos(self, x: float, y: float) -> None:
        self.rec.set_num(self.X, self.ship.core_x + x)
        self.rec.set_num(self.Y, self.ship.core_y + y)

    @property
    def angle(self) -> float:
        return self.rec.num(self.ANGLE)

    @angle.setter
    def angle(self, v: float) -> None:
        self.rec.set_num(self.ANGLE, v)

    @property
    def xscale(self) -> float:
        return self.rec.num(self.XS, 1.0)

    @xscale.setter
    def xscale(self, v: float) -> None:
        self.rec.set_num(self.XS, v)

    @property
    def yscale(self) -> float:
        return self.rec.num(self.YS, 1.0)

    @yscale.setter
    def yscale(self, v: float) -> None:
        self.rec.set_num(self.YS, v)

    @property
    def depth(self) -> float:
        return self.rec.num(self.DEPTH)

    @depth.setter
    def depth(self, v: float) -> None:
        self.rec.set_num(self.DEPTH, v)

    @property
    def parent(self) -> int:
        """Parent section id; 0 means the core."""
        return int(self.rec.num(self.PARENT))

    @parent.setter
    def parent(self, v: int) -> None:
        self.rec.set_num(self.PARENT, v)

    # -- appearance --------------------------------------------------------
    @property
    def hp(self) -> float:
        return self.rec.num(self.HP)

    @property
    def defhp(self) -> float:
        return self.rec.num(self.DEFHP)

    @property
    def colour(self) -> float:
        """`image_blend`; the fractional part encodes the team shade."""
        return self.rec.num(self.IMAGE_BLEND)

    @property
    def alpha(self) -> float:
        return self.rec.num(self.ALPHA, 1.0)

    # -- relationships -----------------------------------------------------
    @property
    def mirror(self) -> int | None:
        """Partner section id from `nSecMir`, or None if unpaired."""
        return self.ship.mirrors.get(self.id)

    @property
    def children(self) -> list['Section']:
        return [s for s in self.ship.sections if s.parent == self.id]

    def __repr__(self) -> str:
        return f'<Section {self.id} {self.name} at {self.x:+g},{self.y:+g}>'


class Section2(Section):
    """A hull section in an sh3 file (`.shp`) — the generation the game loads.

    sh3 is not a reordering of `.sb4`; it is a smaller record that leaves two
    fields out and encodes them positionally. Recovered by aligning
    `Custom Ships/Pendulum.sb4` against its own export `Pendulum.shp`, which are
    the same eight sections in both generations:

        nSec2a,x,y,sprite,image_xscale,image_yscale,image_angle,l_hp,blend,alpha,?

      * **coordinates are already core-relative** — there is no `nCor`, and
        section 1 is `3590,3075` against a core at `3620,3060` in the `.sb4`
        and `-30,15` here. `core_x`/`core_y` return 0 without a core record, so
        the inherited accessors need no special case;
      * **there is no secid** — a section is identified by its position in the
        file, and `nPar2` refers to sections that way;
      * **there is no depth field**. The records are written in strictly
        descending depth: the eight sections above carry sb4 depths 8,7,6,5,4,3,
        2,1 in exactly this order, which is also why the two files list them
        differently. Depth is therefore synthesised from the index, preserving
        the ordering every renderer sorts on.

    The last token is not yet understood (it is 2,2,0,0,1,1,0,0 for Pendulum,
    symmetric across the mirror and not the depth). Nothing reads it, and like
    every other tier-2 field it round-trips untouched.
    """

    X, Y = 0, 1
    SPRITE = 2
    XS, YS, ANGLE = 3, 4, 5
    HP = 6
    BLEND, ALPHA = 7, 8

    def __init__(self, rec: Record, ship: 'Ship', index: int):
        super().__init__(rec, ship)
        self.index = index

    @property
    def id(self) -> int:
        """1-based, so it means the same thing as an `.sb4` secid — and so 0
        keeps meaning "the core" for parents and for `children`."""
        return self.index + 1

    @property
    def sprite(self) -> str:
        """sh3 quotes the path; `.sb4` does not."""
        return self.rec.txt(self.SPRITE).strip('"')

    @property
    def defhp(self) -> float:
        return self.rec.num(self.HP)

    #: The last token: which of the team's three shades this section wears.
    SHADE = 9

    @property
    def colour(self) -> float:
        """The team shade, resolved against the player palette.

        sh3 stores no literal colour, because the colour is not the ship's to
        choose — the game tints a hull by the team it spawns into, which is why
        `importShip` takes a team. What the section does store is *which shade*,
        and `.sb4` stores the same choice already resolved: across Pendulum's
        eight sections the shade indices 2,2,0,0,1,1,0,0 line up exactly with
        image_blend values (128,255,128), (0,255,0) and (64,255,64) — the player
        palette's three entries, in order.

        Player is the right default for a prediction: it is the palette the
        `.sb4` twin was authored against, which is what makes comparing the two
        renders meaningful in the first place.
        """
        import sprites                                  # local: avoids a cycle
        pal = sprites.teams().get('player') or [(0, 255, 0)]
        r, g, b = pal[min(max(int(self.rec.num(self.SHADE, 0)), 0), len(pal) - 1)]
        return float(r + g * 256 + b * 65536)           # GM packs colours BGR

    @property
    def depth(self) -> float:
        """Synthesised from record order — see the class note."""
        return float(len(self.ship.sections) - self.index)

    @depth.setter
    def depth(self, v: float) -> None:
        raise TypeError('sh3 stores depth as record order; reorder instead')

    @property
    def parent(self) -> int:
        """From `nPar2,<parent>,<child>`, both 0-based record indices."""
        return self.ship.sh3_parents.get(self.index, -1) + 1

    @parent.setter
    def parent(self, v: int) -> None:
        raise TypeError('sh3 stores parents in nPar2, not on the section')


class MountKind:
    """How one family of mounted parts lays its fields out.

    Weapons, modules and doodads are all *rigidly attached* to a section and all
    store **absolute canvas coordinates plus a parent id** -- so a section edit
    that ignores them strands them in space. They share the first eight fields
    (`id, x, y, sprite, xscale, yscale, angle, image_speed`) and then diverge,
    which is what this table is for. Layouts are ShipMaker's own, read out of its
    save routine:

        nWepA  wepid, x, y, sprite, xs, ys, ang, image_speed,
               image_alpha, image_blend, 0, colour
        nWepB  wepid, parent.secid, arcrange, ...
        nModA  modid, x, y, sprite, xs, ys, ang, image_speed,
               0, duplicate, l_hp, l_range, l_target.secid, l_eng, l_engregen, l_cost
        nModB  modid, parent.secid, l_special1..8, image_alpha, colour
        nDooA  dooid, x, y, lname, xs, ys, ang, image_speed, depth,
               image_blend, l_colour, l_start, l_blend, image_alpha, parent.secid

    Note the asymmetry: a weapon and a module keep their parent in the *second*
    record, a doodad keeps it in the first. Alpha and blend move around too.
    """

    __slots__ = ('kind', 'a', 'b', 'mir', 'parent_rec', 'parent_idx',
                 'alpha_rec', 'alpha_idx', 'blend_idx', 'depth_idx')

    def __init__(self, kind, a, b, mir, parent_rec, parent_idx,
                 alpha_rec, alpha_idx, blend_idx, depth_idx):
        self.kind = kind
        self.a, self.b, self.mir = a, b, mir
        self.parent_rec, self.parent_idx = parent_rec, parent_idx
        self.alpha_rec, self.alpha_idx = alpha_rec, alpha_idx
        self.blend_idx, self.depth_idx = blend_idx, depth_idx


MOUNTS = {
    'weapon': MountKind('weapon', 'nWepA', 'nWepB', 'nWepMir', 'b', 1, 'a', 8, 9, None),
    'module': MountKind('module', 'nModA', 'nModB', 'nModMir', 'b', 1, 'b', 10, None, None),
    'doodad': MountKind('doodad', 'nDooA', None, 'nDooMir', 'a', 14, 'a', 13, 9, 8),
}

#: sh3 collapses weapons and modules into one record, so there is one spec
#: rather than three. Field indices live on `Mount2`; only `kind` is read here.
MOUNT2 = MountKind('weapon', 'nTur2', None, None, 'a', 6, 'a', None, None, None)


class Mount:
    """A weapon, module or doodad: geometry plus a rigid link to one section.

    Coordinates are exposed core-relative like `Section`, and written back
    absolute. `id` is deliberately not durable -- `wepid`, `modid` and `dooid`
    are all renumbered from scratch on every ShipMaker save, in arbitrary GM
    instance order -- so it is fine to use within a single command and never
    across a round-trip.
    """

    X, Y = 1, 2
    SPRITE = 3
    XS, YS, ANGLE = 4, 5, 6

    def __init__(self, spec: MountKind, a: Record, b: Record | None, ship: 'Ship'):
        self.spec = spec
        self.rec = a
        self.recb = b
        self.ship = ship

    @property
    def kind(self) -> str:
        return self.spec.kind

    @property
    def id(self) -> int:
        return int(self.rec.num(0))

    @property
    def sprite(self) -> str:
        return self.rec.txt(self.SPRITE)

    @property
    def name(self) -> str:
        return self.sprite.replace('\\', '/').rsplit('/', 1)[-1].rsplit('.', 1)[0]

    # -- geometry, core-relative -------------------------------------------
    @property
    def x(self) -> float:
        return round(self.rec.num(self.X) - self.ship.core_x, 2)

    @property
    def y(self) -> float:
        return round(self.rec.num(self.Y) - self.ship.core_y, 2)

    def set_pos(self, x: float, y: float) -> None:
        self.rec.set_num(self.X, self.ship.core_x + x)
        self.rec.set_num(self.Y, self.ship.core_y + y)

    @property
    def angle(self) -> float:
        return self.rec.num(self.ANGLE)

    @angle.setter
    def angle(self, v: float) -> None:
        self.rec.set_num(self.ANGLE, v)

    @property
    def xscale(self) -> float:
        return self.rec.num(self.XS, 1.0)

    @xscale.setter
    def xscale(self, v: float) -> None:
        self.rec.set_num(self.XS, v)

    @property
    def yscale(self) -> float:
        return self.rec.num(self.YS, 1.0)

    @yscale.setter
    def yscale(self, v: float) -> None:
        self.rec.set_num(self.YS, v)

    @property
    def depth(self) -> float:
        """Doodads carry one; weapons and modules are ordered by layer alone."""
        i = self.spec.depth_idx
        return self.rec.num(i) if i is not None else 0.0

    # -- appearance --------------------------------------------------------
    @property
    def alpha(self) -> float:
        r = self.rec if self.spec.alpha_rec == 'a' else self.recb
        return r.num(self.spec.alpha_idx, 1.0) if r is not None else 1.0

    @property
    def colour(self) -> float:
        """`image_blend`. Modules have none in the file and draw untinted."""
        i = self.spec.blend_idx
        return self.rec.num(i, 16777215.0) if i is not None else 16777215.0

    # -- relationships -----------------------------------------------------
    @property
    def parent(self) -> int:
        """Owning section id; 0 means the core."""
        r = self.rec if self.spec.parent_rec == 'a' else self.recb
        return int(r.num(self.spec.parent_idx)) if r is not None else 0

    @parent.setter
    def parent(self, v: int) -> None:
        r = self.rec if self.spec.parent_rec == 'a' else self.recb
        if r is not None:
            r.set_num(self.spec.parent_idx, v)

    @property
    def mirror(self) -> int | None:
        return self.ship.mirror_map(self.kind).get(self.id)

    def __repr__(self) -> str:
        return f'<{self.kind} {self.id} {self.name} at {self.x:+g},{self.y:+g}>'


# --------------------------------------------------------------------------
# sh1/sh2: the ship as Game Maker source
# --------------------------------------------------------------------------
#
# The oldest generation is not records at all — it is the Create event that
# builds the ship, `l_section[j] = instance_create(x, y, ShipSection)` and so
# on. 168 of the 175 ship files on disk are this, including seven of the eight
# `Custom Ships/` designs that ship with the game, so "cannot read sh1" means
# "cannot see most of the ships that exist".
#
# The parser lives here rather than in stockship.py, which had the only copy,
# for two reasons: reading a file format is this module's job, and stockship
# imports this module, so the dependency could not run the other way.

_GML_CREATE = re.compile(
    r'l_(section|weapon)\[(?P<idx>[^\]]+)\]\s*=\s*instance_create\('
    r'\s*(?P<x>-?[\d.]+)\s*,\s*(?P<y>-?[\d.]+)\s*,\s*(?P<obj>[A-Za-z_]\w*)\s*\)')
#: `l_section[j].l_child[l_section[j].l_childnum] = l_section[j-1]` — the
#: subscript inside the subscript is why the inner group must be lazy.
_GML_CHILD = re.compile(
    r'l_section\[(?P<par>[^\]]+)\]\.l_child\[.*?\]\s*=\s*'
    r'l_(?P<kind>section|weapon)\[(?P<kid>[^\]]+)\]')
_GML_ATTR = re.compile(
    r'l_(section|weapon)\[[^\]]+\]\.(?P<k>\w+)\s*=\s*(?P<v>-?[\d.]+)')


def _gml_idx(expr: str, j: int) -> int | None:
    """Resolve `j`, `j-2`, or a bare number against the running counter."""
    expr = expr.strip()
    if expr == 'j':
        return j
    m = re.fullmatch(r'j\s*-\s*(\d+)', expr)
    if m:
        return j - int(m.group(1))
    return int(expr) if expr.isdigit() else None


def parse_gml(text: str) -> dict:
    """Sections and weapons out of an sh1/sh2 Create event.

    ⚠ sh1 declares attachment **backwards**: `l_section[j].l_child[...] =
    l_section[j-1]` means *j owns j-1*, the opposite of every record format.
    """
    secs: dict[int, dict] = {}
    weps: dict[int, dict] = {}
    parent: dict[int, int] = {}
    wparent: dict[int, int] = {}
    j = 0
    cur: tuple[str, int] | None = None

    for line in text.splitlines():
        s = line.strip()
        if re.fullmatch(r'j\s*=\s*0', s):
            j = 0
            continue
        if re.fullmatch(r'j\s*\+=\s*1', s):
            j += 1
            continue
        m = _GML_CREATE.search(s)
        if m:
            i = _gml_idx(m.group('idx'), j)
            if i is None:
                continue
            rec = {'x': float(m.group('x')), 'y': float(m.group('y')),
                   'obj': m.group('obj'), 'xs': 1.0, 'ys': 1.0, 'ang': 0.0,
                   'shade': 0.0}
            (secs if m.group(1) == 'section' else weps)[i] = rec
            cur = (m.group(1), i)
            continue
        m = _GML_CHILD.search(s)
        if m:
            par, kid = _gml_idx(m.group('par'), j), _gml_idx(m.group('kid'), j)
            if par is not None and kid is not None:
                (wparent if m.group('kind') == 'weapon' else parent)[kid] = par
            continue
        if cur is None:
            continue
        m = re.search(r'sprite_index\s*=\s*([A-Za-z_]\w*)', s)
        if m and cur[0] == 'section':
            secs[cur[1]]['obj'] = m.group(1)
            continue
        # `l_colour = global.colour[round((l_colour mod 1) * 10), 0]` is the
        # team lookup; a literal index in the same shape is the shade.
        m = re.search(r'l_colour\s*=\s*global\.colour\[\s*(\d+)', s)
        if m and cur[0] == 'section':
            secs[cur[1]]['shade'] = float(m.group(1))
            continue
        m = _GML_ATTR.search(s)
        if m:
            bag = secs if cur[0] == 'section' else weps
            k, v = m.group('k'), float(m.group('v'))
            if k == 'image_xscale':
                bag[cur[1]]['xs'] = v
            elif k == 'image_yscale':
                bag[cur[1]]['ys'] = v
            elif k in ('l_angle', 'image_angle'):
                bag[cur[1]]['ang'] = v
            elif k == 'l_arcrange':
                bag[cur[1]]['arc'] = v

    return {'sections': secs, 'weapons': weps,
            'parent': parent, 'wparent': wparent}


#: sh2 is sh3's structure in call syntax: `nSec(x,y,sprite,xs,ys,ang,hp,shade)`,
#: `nTur(x,y,sprite,angle,...)`, and the same reversed `nPar(parent,child)`. Its
#: lines end in a bare CR, so the text is normalised before matching.
_CALL_RE = re.compile(r'^n(?P<kind>Sec|Tur|Par)\((?P<args>.*)\)\s*$', re.M)


def parse_calls(text: str) -> dict:
    """Sections and turrets out of an sh2 file's call syntax."""
    secs: dict[int, dict] = {}
    weps: dict[int, dict] = {}
    parent: dict[int, int] = {}
    for m in _CALL_RE.finditer(text.replace('\r', '\n')):
        a = [t.strip() for t in m.group('args').split(',')]
        kind = m.group('kind')
        try:
            if kind == 'Sec':
                secs[len(secs)] = {
                    'x': float(a[0]), 'y': float(a[1]), 'obj': a[2].strip('"\''),
                    'xs': float(a[3]), 'ys': float(a[4]), 'ang': float(a[5]),
                    'shade': float(a[7]) if len(a) > 7 else 0.0}
            elif kind == 'Tur':
                weps[len(weps)] = {
                    'x': float(a[0]), 'y': float(a[1]), 'obj': a[2].strip('"\''),
                    'xs': 1.0, 'ys': 1.0, 'ang': float(a[3]) if len(a) > 3 else 0.0,
                    'shade': 0.0}
            elif kind == 'Par':
                parent[int(float(a[1]))] = int(float(a[0]))
        except (ValueError, IndexError):
            continue
    return {'sections': secs, 'weapons': weps,
            'parent': parent, 'wparent': {}}


class _GMLPart:
    """Read-only view over one part parsed out of Game Maker source.

    sh1 is source, not a record, so there is nothing to write back into and
    nothing that could round-trip: every setter on `Section` and `Mount` is
    absent here by design. It carries exactly what `scene.py` consumes.
    """

    def __init__(self, spec: dict, ship: 'Ship', index: int,
                 parent_id: int, total: int):
        self.spec, self.ship, self.index = spec, ship, index
        self._parent, self._total = parent_id, total

    @property
    def id(self) -> int:
        return self.index + 1

    @property
    def sprite(self) -> str:
        return self.spec['obj']

    @property
    def name(self) -> str:
        return self.sprite.replace('\\', '/').rsplit('/', 1)[-1].rsplit('.', 1)[0]

    @property
    def x(self) -> float:
        return round(self.spec['x'], 2)

    @property
    def y(self) -> float:
        return round(self.spec['y'], 2)

    @property
    def angle(self) -> float:
        return self.spec['ang']

    @property
    def xscale(self) -> float:
        return self.spec['xs']

    @property
    def yscale(self) -> float:
        return self.spec['ys']

    @property
    def alpha(self) -> float:
        return 1.0

    @property
    def parent(self) -> int:
        return self._parent

    @property
    def mirror(self) -> int | None:
        return None

    @property
    def depth(self) -> float:
        """Creation order, later parts in front — the game's own draw order.

        sh1 sets no depth: the sections are plain instances at the object's
        default, so Game Maker draws them in creation order and the ship is
        authored knowing that.
        """
        return float(self._total - self.index)

    def __repr__(self) -> str:
        return f'<{type(self).__name__} {self.id} {self.name} at {self.x:+g},{self.y:+g}>'


class SectionGML(_GMLPart):
    """A hull section from sh1/sh2 source."""

    @property
    def hp(self) -> float:
        return -1.0

    @property
    def defhp(self) -> float:
        return -1.0

    @property
    def colour(self) -> float:
        import sprites                                  # local: avoids a cycle
        pal = sprites.teams().get('player') or [(0, 255, 0)]
        r, g, b = pal[min(max(int(self.spec.get('shade', 0)), 0), len(pal) - 1)]
        return float(r + g * 256 + b * 65536)

    @property
    def children(self) -> list['SectionGML']:
        return [s for s in self.ship.sections if s.parent == self.id]


class MountGML(_GMLPart):
    """A weapon from sh1/sh2 source. sh1 records no modules separately."""

    @property
    def kind(self) -> str:
        return 'weapon'

    @property
    def colour(self) -> float:
        return 16777215.0

    @property
    def depth(self) -> float:
        return 0.0


class Mount2(Mount):
    """A weapon or module in an sh3 file, from one `nTur2` record.

        nTur2,x,y,sprite,image_angle,?,?,parent

    sh3 keeps no separate weapon and module families: Pendulum's four records
    are its three weapons *and* its ThrusterEx, and each matches its `.sb4`
    counterpart's core-relative position and angle exactly — `24,0 PlasmaBall`
    against `3644,3060` with the core at `3620,3060`, and so on.

    Scale is not recorded, which is why there is no XS/YS here: every mount in
    the twin has `image_xscale = image_yscale = 1`, and 1 is what the inherited
    accessors already return for a token that is not there.
    """

    X, Y = 0, 1
    SPRITE = 2
    ANGLE = 3
    XS = YS = 99                        # absent; num() falls back to 1.0

    def __init__(self, rec: Record, ship: 'Ship', index: int):
        super().__init__(MOUNT2, rec, None, ship)
        self.index = index

    @property
    def id(self) -> int:
        return self.index

    @property
    def sprite(self) -> str:
        return self.rec.txt(self.SPRITE).strip('"')

    @property
    def parent(self) -> int:
        """Owning section, as a 0-based record index; -1 is the core."""
        p = int(self.rec.num(6, -1))
        return p + 1 if p >= 0 else 0

    @property
    def alpha(self) -> float:
        return 1.0

    @property
    def colour(self) -> float:
        return 16777215.0               # sh3 stores no mount tint

    @property
    def mirror(self) -> int | None:
        return None                     # sh3 records no mount pairing


class Ship:
    """A parsed ship file: verbatim lines, plus typed views over the ones we know."""

    def __init__(self, path: pathlib.Path, text: str, obfuscated: bool):
        self.path = path
        self.obfuscated = obfuscated
        self._text = text                # sh1/sh2 are source, not records
        self.lines: list[Line] = []
        self.records: list[Record] = []

        for content, eol in split_lines(text):
            m = RECORD_RE.match(content)
            if m:
                rec = Record(m.group(1), content[m.end():].split(','), eol)
                self.lines.append(rec)
                self.records.append(rec)
            else:
                self.lines.append(Line(content, eol))

        self.generation = self._generation(text)
        self.version = self._version(text)

    # -- format detection --------------------------------------------------
    @staticmethod
    def _generation(text: str) -> str:
        head = text[:64]
        for tag in ('sb4', 'sh3', 'sh2'):
            if '//' + tag in head:
                return tag
        return 'sh1'

    @staticmethod
    def _version(text: str) -> str:
        m = re.match(r'//s[bh]\d ?(ver\d+)', text[:64])
        return m.group(1) if m else ''

    # -- record lookup -----------------------------------------------------
    def of_kind(self, kind: str) -> list[Record]:
        return [r for r in self.records if r.kind == kind]

    def first(self, *kinds: str) -> Record | None:
        for r in self.records:
            if r.kind in kinds:
                return r
        return None

    # -- core --------------------------------------------------------------
    @property
    def core(self) -> Record | None:
        return self.first('nCor')

    @property
    def core_x(self) -> float:
        """Canvas x of the core. Ships without an `nCor` are already core-relative."""
        c = self.core
        return c.num(6) if c else 0.0

    @property
    def core_y(self) -> float:
        c = self.core
        return c.num(7) if c else 0.0

    # -- the core, whichever generation stated it --------------------------
    #
    # Only `.sb4` keeps the core in a record. The rest write it as plain
    # settings, and because sh1/sh2 end their lines in a bare CR the file is a
    # single `Line` as far as `split_lines` is concerned -- so this reads the
    # text with all three endings normalised rather than walking `self.lines`.
    # Nothing here mutates, so the verbatim lines that guarantee the round trip
    # are untouched.
    #: `nCor` field order, from ShipMaker's own reader.
    COR_INDEX, COR_COLOUR, COR_XS, COR_YS = 0, 2, 3, 4

    def setting(self, key: str) -> str | None:
        for raw in re.split(r'\r\n|\r|\n', self._text):
            m = SETTING_RE.match(raw)
            if m and m.group(1) == key:
                return m.group(2)
        return None

    def _setting_num(self, key: str, default: float | None) -> float | None:
        v = self.setting(key)
        try:
            return float(v)                                   # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    @property
    def has_core(self) -> bool:
        return self.core is not None or self.setting('sprite_index') is not None

    @property
    def core_shape(self) -> int:
        """`image_index`, which picks the core sprite. 0 when unstated."""
        c = self.core
        if c is not None:
            return int(c.num(self.COR_INDEX))
        name = self.setting('sprite_index')
        return CORE_INDEX.get(name.strip().lower(), 0) if name else 0

    @property
    def core_scale(self) -> tuple[float, float]:
        c = self.core
        if c is not None:
            return c.num(self.COR_XS, 1.0), c.num(self.COR_YS, 1.0)
        # Written only when not 1, so an absent line means 1 rather than 0.
        return (self._setting_num('image_xscale', 1.0),
                self._setting_num('image_yscale', 1.0))

    @property
    def core_colour(self) -> float | None:
        """The core's resolved GM colour, or `None` for "whatever the team is".

        `.sb4` always stores a resolved value. The others store `l_colour` only
        when it differs from the palette's own, which is the same reason a
        section stores a shade index rather than a colour: the ship does not own
        its colour, the team it spawns into does.
        """
        c = self.core
        if c is not None:
            return c.num(self.COR_COLOUR)
        return self._setting_num('l_colour', None)

    # -- ship header -------------------------------------------------------
    #: `l_name` sits at token 6 in both `nShp` (sb4) and `nShp2` (sh3): sb4
    #: prefixes thrust and sh3 keeps an unused field, and the two cancel out.
    NAME = 6

    @property
    def name(self) -> str:
        """The ship's display name, as the game's UI shows it.

        sh3 quotes the value and sb4 does not, so the quotes are stripped here
        and put back on write -- otherwise a name read from one generation and
        written to the other grows or loses a pair.
        """
        r = self.first('nShp', 'nShp2')
        if r is None:
            return self.path.stem
        return r.txt(self.NAME).strip().strip('"')

    @name.setter
    def name(self, v: str) -> None:
        r = self.first('nShp', 'nShp2')
        if r is None:
            raise ValueError(f'{self.path.name} has no nShp record to name')
        old = r.txt(self.NAME)
        # A comma would split the field into two on the next read, and the
        # loader has no escaping for it.
        if ',' in v:
            raise ValueError('a ship name cannot contain a comma')
        r.set_txt(self.NAME, f'"{v}"' if old.strip().startswith('"') else v)

    # -- sections ----------------------------------------------------------
    @property
    def sections(self) -> list[Section]:
        if not hasattr(self, '_sections'):
            # `nSecA` is the .sb4 record and `nSec2a` the .shp one; a file has
            # one or the other, never both, so this needs no generation test.
            self._sections = [Section(r, self) for r in self.of_kind('nSecA')]
            if not self._sections:
                self._sections = [Section2(r, self, i)
                                  for i, r in enumerate(self.of_kind('nSec2a'))]
            if not self._sections:
                self._sections = self._gml_parts('sections', 'parent', SectionGML)
        return self._sections

    def _gml_parts(self, bag: str, links: str, view) -> list:
        """Build sh1/sh2 views. sh1 declares attachment backwards — see
        `parse_gml` — so the link table is inverted on the way in."""
        spec = self.gml
        items = spec[bag]
        if not items:
            return []
        order = sorted(items)
        pos = {k: i for i, k in enumerate(order)}
        owner = {kid: par for kid, par in spec[links].items()}
        out = []
        for i, k in enumerate(order):
            p = owner.get(k)
            out.append(view(items[k], self, i,
                            pos[p] + 1 if p in pos else 0, len(order)))
        return out

    @property
    def gml(self) -> dict:
        """The parts of an sh1/sh2 file, whichever shape it is written in."""
        if not hasattr(self, '_gml'):
            self._gml = (parse_calls(self._text) if _CALL_RE.search(
                self._text.replace('\r', '\n')) else parse_gml(self._text))
        return self._gml

    @property
    def sh3_parents(self) -> dict[int, int]:
        """child index -> parent index, from `nPar2,<parent>,<child>`.

        The argument order is the reverse of everything else in the format and
        was settled by aligning Pendulum's two generations: its four records
        (6,2) (7,3) (6,4) (7,5) reproduce the .sb4's 5→3, 6→3, 7→4, 8→4 exactly.
        """
        if not hasattr(self, '_sh3_parents'):
            out: dict[int, int] = {}
            for r in self.of_kind('nPar2'):
                try:
                    out[int(r.num(1))] = int(r.num(0))
                except ValueError:
                    continue
            self._sh3_parents = out
        return self._sh3_parents

    def section(self, sid: int) -> Section | None:
        for s in self.sections:
            if s.id == sid:
                return s
        return None

    def _rec_by_id(self, kind: str) -> dict[int, Record]:
        """`{first field -> record}` for a kind whose first field is an id."""
        out: dict[int, Record] = {}
        for r in self.of_kind(kind):
            try:
                out[int(r.num(0))] = r
            except ValueError:
                continue
        return out

    # -- mounted parts -----------------------------------------------------
    @property
    def mounts(self) -> list[Mount]:
        """Every weapon, module and doodad, in that order."""
        if not hasattr(self, '_mounts'):
            out: list[Mount] = []
            tur = self.of_kind('nTur2')
            if tur:                              # sh3: one record family, no ids
                self._mounts = [Mount2(r, self, i) for i, r in enumerate(tur)]
                return self._mounts
            if not self.records:                 # sh1/sh2: Game Maker source
                self._mounts = self._gml_parts('weapons', 'wparent', MountGML)
                return self._mounts
            for spec in MOUNTS.values():
                bs = self._rec_by_id(spec.b) if spec.b else {}
                for r in self.of_kind(spec.a):
                    try:
                        mid = int(r.num(0))
                    except ValueError:
                        continue
                    out.append(Mount(spec, r, bs.get(mid), self))
            self._mounts = out
        return self._mounts

    def mounts_of(self, sid: int) -> list[Mount]:
        """Everything rigidly attached to one section."""
        return [m for m in self.mounts if m.parent == sid]

    @property
    def weapons(self) -> list[Mount]:
        return [m for m in self.mounts if m.kind == 'weapon']

    @property
    def modules(self) -> list[Mount]:
        return [m for m in self.mounts if m.kind == 'module']

    @property
    def doodads(self) -> list[Mount]:
        return [m for m in self.mounts if m.kind == 'doodad']

    # -- mirror links ------------------------------------------------------
    def mirror_map(self, kind: str = 'section') -> dict[int, int]:
        """`id -> partner id` for one part family, `-4` entries dropped.

        ShipMaker writes both directions (`1,2` and `2,1`), so this is symmetric
        in practice, but it is built as a plain map rather than assuming that.
        """
        if not hasattr(self, '_mirror_maps'):
            self._mirror_maps: dict[str, dict[int, int]] = {}
        if kind not in self._mirror_maps:
            rk = 'nSecMir' if kind == 'section' else MOUNTS[kind].mir
            m: dict[int, int] = {}
            for r in self.of_kind(rk):
                try:
                    a, b = int(r.num(0)), int(r.num(1))
                except ValueError:
                    continue
                if b != UNMIRRORED:
                    m[a] = b
            self._mirror_maps[kind] = m
        return self._mirror_maps[kind]

    @property
    def mirrors(self) -> dict[int, int]:
        """secid -> partner secid, from the `nSecMir` records."""
        return self.mirror_map('section')

    # -- structure ---------------------------------------------------------
    def invalidate(self) -> None:
        """Drop cached views after records are added or removed."""
        for attr in ('_sections', '_mounts', '_mirror_maps'):
            if hasattr(self, attr):
                delattr(self, attr)

    def add_record(self, kind: str, tokens: list[str], after: Record | None = None) -> Record:
        """Insert a new record, next to `after` if given, else at the end.

        Placing it beside a sibling keeps the file readable and keeps ShipMaker's
        own grouping (all `nSecA` together, all `nSecB` together) intact.
        """
        eol = after.eol if after is not None else (
            self.lines[-1].eol if self.lines else '\n')
        rec = Record(kind, list(tokens), eol or '\n')
        rec.dirty = True
        if after is not None and after in self.lines:
            i = self.lines.index(after)
            self.lines.insert(i + 1, rec)
            self.records.insert(self.records.index(after) + 1, rec)
        else:
            if self.lines and self.lines[-1].eol == '':
                self.lines[-1].eol = '\n'
            self.lines.append(rec)
            self.records.append(rec)
        self._added = True
        self.invalidate()
        return rec

    def drop_records(self, recs: list[Record]) -> None:
        gone = set(id(r) for r in recs)
        if not gone:
            return
        self.lines = [l for l in self.lines if id(l) not in gone]
        self.records = [r for r in self.records if id(r) not in gone]
        self._dropped = True
        self.invalidate()

    # -- output ------------------------------------------------------------
    def render(self) -> str:
        return ''.join(l.render() for l in self.lines)

    def to_bytes(self) -> bytes:
        return encode(self.render(), self.obfuscated)

    @property
    def dirty(self) -> bool:
        return (any(r.dirty for r in self.records)
                or getattr(self, '_added', False)
                or getattr(self, '_dropped', False))


def load(path: str | pathlib.Path) -> Ship:
    p = pathlib.Path(path)
    text, obf = decode(p.read_bytes())
    return Ship(p, text, obf)

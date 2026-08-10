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


class Ship:
    """A parsed ship file: verbatim lines, plus typed views over the ones we know."""

    def __init__(self, path: pathlib.Path, text: str, obfuscated: bool):
        self.path = path
        self.obfuscated = obfuscated
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

    # -- ship header -------------------------------------------------------
    @property
    def name(self) -> str:
        r = self.first('nShp', 'nShp2')
        if r is None:
            return self.path.stem
        # sb4 prefixes thrust and drops sh3's unused 6th field, so the name sits
        # one position later than in sh3's nShp2.
        return r.txt(6 if self.generation == 'sb4' else 6).strip()

    # -- sections ----------------------------------------------------------
    @property
    def sections(self) -> list[Section]:
        if not hasattr(self, '_sections'):
            self._sections = [Section(r, self) for r in self.of_kind('nSecA')]
        return self._sections

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

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
UNDERSTOOD = {'nShp', 'nShp2', 'nCor', 'nSecA', 'nSecMir', 'nWepA', 'nWepB'}


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


def decode(raw: bytes) -> tuple[str, bool]:
    """Return (text, was_obfuscated). Plain files start with `//`."""
    if raw[:2] == b'//':
        return raw.decode('latin1'), False
    return bytes((b - BYTE_OFFSET) & 0xFF for b in raw).decode('latin1'), True


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

    @property
    def mirrors(self) -> dict[int, int]:
        """secid -> partner secid, from the `nSecMir` records.

        ShipMaker writes both directions (`1,2` and `2,1`), so this is symmetric
        in practice, but it is built as a plain map rather than assuming that.
        """
        if not hasattr(self, '_mirrors'):
            m: dict[int, int] = {}
            for r in self.of_kind('nSecMir'):
                try:
                    m[int(r.num(0))] = int(r.num(1))
                except ValueError:
                    continue
            self._mirrors = m
        return self._mirrors

    # -- output ------------------------------------------------------------
    def render(self) -> str:
        return ''.join(l.render() for l in self.lines)

    def to_bytes(self) -> bytes:
        return encode(self.render(), self.obfuscated)

    @property
    def dirty(self) -> bool:
        return any(r.dirty for r in self.records)


def load(path: str | pathlib.Path) -> Ship:
    p = pathlib.Path(path)
    text, obf = decode(p.read_bytes())
    return Ship(p, text, obf)

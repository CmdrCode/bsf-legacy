#!/usr/bin/env python3
"""A small predicate language for picking parts out of a ship.

Numeric ids are not a durable handle: `wepid`, `modid` and `dooid` are all
renumbered from scratch on every ShipMaker save, in whatever order GM happens to
iterate instances. Only `secid` survives a round-trip, and even that only until
someone deletes a section. So the way to say "the two forward turrets" has to be
a description, not a list of numbers:

    ship select 'weapon and x > 60'
    ship select 'section and name ~ Kae_sec46 and y < 0'
    ship select 'occluded > 0.9'
    ship select 'touching(5) and not mirrored'

**Two performance classes, and the output says which one you are in.** Plain
field tests read the parsed file and cost nothing. `visible`, `area`,
`occluded`, `touching()`, `near()` and `floating` need to know what the ship
actually looks like, so they trigger one render -- which the whole query then
shares. That split exists because the offline core's entire point is a cheap
edit loop; making every selector pay for a raster would undo it.

Grammar, in full:

    expr    := or
    or      := and ('or' and)*
    and     := not ('and' not)*            -- juxtaposition also means 'and'
    not     := 'not' not | atom
    atom    := '(' expr ')' | call | field OP value | word
    call    := touching '(' num ')' | near '(' num ',' num ')'
    OP      := = | == | != | < | <= | > | >= | ~

`~` is a case-insensitive regular expression search, so `name ~ sec4[67]` works
and plain substrings do too. Bare words are shorthand: a kind (`section`,
`weapon`, `module`, `doodad`) tests `kind =`, and `mirrored` / `floating` are
predicates in their own right.

`touching(N)` and `near(N, D)` take a **section** id, deliberately: pointing a
durable selector at a weapon id would be building on the one thing the format
guarantees will change.
"""
from __future__ import annotations

import re

#: Read straight off the parsed records. Free.
FAST_FIELDS = {
    'id', 'kind', 'name', 'sprite', 'x', 'y', 'angle', 'xscale', 'yscale',
    'depth', 'parent', 'mirror', 'hp', 'defhp', 'alpha', 'colour',
}

#: Answered from the id buffer. Each of these makes the query render once.
DERIVED_FIELDS = {'visible', 'area', 'occluded'}

KINDS = ('section', 'weapon', 'module', 'doodad')


class QueryError(ValueError):
    """A selector that does not parse, or names something that does not exist."""


# --------------------------------------------------------------------------
# the uniform part view
# --------------------------------------------------------------------------

class Part:
    """One selectable thing: a section, weapon, module or doodad.

    Sections and mounts have different record layouts and different capabilities
    -- only a section has HP, only a mount has a rigid parent -- but a selector
    should not have to care, so missing fields read as neutral values rather
    than raising.
    """

    __slots__ = ('kind', 'obj')

    def __init__(self, kind: str, obj):
        self.kind = kind
        self.obj = obj

    def __getattr__(self, name: str):
        return getattr(self.obj, name)

    def field(self, name: str):
        if name == 'kind':
            return self.kind
        if name in ('hp', 'defhp') and self.kind != 'section':
            return 0.0
        try:
            v = getattr(self.obj, name)
        except AttributeError:
            raise QueryError(f'no such field: {name}')
        return -1 if v is None and name == 'mirror' else v

    @property
    def ref(self) -> str:
        """How this part is named in output: kind plus id."""
        return f'{self.kind} {self.obj.id}'

    def __repr__(self) -> str:
        return f'<{self.ref} {self.obj.name}>'


def parts(ship) -> list[Part]:
    """Everything selectable, sections first."""
    return ([Part('section', s) for s in ship.sections]
            + [Part(m.kind, m) for m in ship.mounts])


# --------------------------------------------------------------------------
# tokenizer
# --------------------------------------------------------------------------

TOKEN_RE = re.compile(r'''
    \s*(?:
      (?P<op>>=|<=|!=|==|=|<|>|~)
    | (?P<punct>[(),])
    | (?P<num>-?\d+(?:\.\d+)?)
    | (?P<str>"[^"]*"|'[^']*')
    | (?P<word>[A-Za-z_][\w.\\/\[\]-]*)
    )
''', re.X)


def tokenize(src: str) -> list[tuple[str, str]]:
    out, i = [], 0
    while i < len(src):
        m = TOKEN_RE.match(src, i)
        if not m or m.end() == i:
            if src[i:].strip() == '':
                break
            raise QueryError(f'cannot read {src[i:]!r}')
        i = m.end()
        for kind in ('op', 'punct', 'num', 'str', 'word'):
            v = m.group(kind)
            if v is not None:
                out.append((kind, v))
                break
    return out


# --------------------------------------------------------------------------
# parser -> a tree of predicates
# --------------------------------------------------------------------------

class Parser:
    """Recursive descent. Emits closures taking (part, ctx) -> bool.

    `ctx` is only consulted by derived predicates, and `self.derived` records
    whether any of them were built -- that is what lets the caller decide to
    render once, up front, and tell the user it did.
    """

    def __init__(self, src: str, fields: set[str] | None = None,
                 words: dict | None = None):
        self.toks = tokenize(src)
        self.i = 0
        self.derived = False
        # The parts catalogue queries a different domain -- sprite metrics
        # rather than placed parts -- with the same grammar, so the field and
        # keyword tables are swappable rather than duplicated.
        self.fast = FAST_FIELDS if fields is None else fields
        self.words = words
        if not self.toks:
            raise QueryError('empty selector')

    # -- token helpers -----------------------------------------------------
    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def accept_word(self, w: str) -> bool:
        k, v = self.peek()
        if k == 'word' and v.lower() == w:
            self.i += 1
            return True
        return False

    def expect(self, v: str) -> None:
        k, got = self.take()
        if got != v:
            raise QueryError(f'expected {v!r}, found {got!r}')

    # -- grammar -----------------------------------------------------------
    def parse(self):
        f = self.parse_or()
        if self.i != len(self.toks):
            raise QueryError(f'unexpected {self.peek()[1]!r}')
        return f

    def parse_or(self):
        left = self.parse_and()
        while self.accept_word('or'):
            right = self.parse_and()
            left = (lambda a, b: lambda p, c: a(p, c) or b(p, c))(left, right)
        return left

    def parse_and(self):
        left = self.parse_not()
        while True:
            if self.accept_word('and'):
                pass
            elif self._starts_atom():
                pass                      # juxtaposition: `weapon x > 60`
            else:
                break
            right = self.parse_not()
            left = (lambda a, b: lambda p, c: a(p, c) and b(p, c))(left, right)
        return left

    def _starts_atom(self) -> bool:
        k, v = self.peek()
        if k is None or v in (')', ','):
            return False
        return not (k == 'word' and v.lower() == 'or')

    def parse_not(self):
        if self.accept_word('not'):
            inner = self.parse_not()
            return lambda p, c: not inner(p, c)
        return self.parse_atom()

    def parse_atom(self):
        k, v = self.peek()
        if v == '(':
            self.take()
            inner = self.parse_or()
            self.expect(')')
            return inner
        if k != 'word':
            raise QueryError(f'expected a field or keyword, found {v!r}')
        self.take()
        low = v.lower()

        if self.words is not None:
            if low in self.words:
                return self.words[low]
            return self._comparison(low)

        if low in ('touching', 'near'):
            return self._call(low)
        if low in KINDS:
            return lambda p, c, kind=low: p.kind == kind
        if low == 'mirrored':
            # `field` has already turned "no partner" into -1, so compare
            # directly -- partner id 0 is a real mount and must not read false.
            return lambda p, c: p.field('mirror') >= 0
        if low == 'floating':
            self.derived = True
            return lambda p, c: c.floating(p)
        if low == 'all':
            return lambda p, c: True

        # otherwise it is a field, and a comparison must follow
        return self._comparison(low)

    def _call(self, name: str):
        self.derived = True
        self.expect('(')
        sid = int(float(self._number()))
        dist = 1.0
        if name == 'near':
            self.expect(',')
            dist = self._number()
        self.expect(')')
        return lambda p, c, s=sid, d=dist: c.within(s, d, p)

    def _number(self) -> float:
        k, v = self.take()
        if k != 'num':
            raise QueryError(f'expected a number, found {v!r}')
        return float(v)

    def _comparison(self, field: str):
        if self.words is not None:
            if field not in self.fast:
                raise QueryError(f'no such field: {field}\n'
                                 f'  fields: {", ".join(sorted(self.fast))}\n'
                                 f'  words:  {", ".join(sorted(self.words))}')
        elif field in DERIVED_FIELDS:
            self.derived = True
        elif field not in FAST_FIELDS:
            raise QueryError(
                f'no such field: {field}\n'
                f'  fields:  {", ".join(sorted(FAST_FIELDS | DERIVED_FIELDS))}\n'
                f'  words:   {", ".join(KINDS)}, mirrored, floating, all\n'
                f'  calls:   touching(secid), near(secid, px)')
        k, op = self.take()
        if k != 'op':
            raise QueryError(f'{field}: expected a comparison, found {op!r}')
        vk, raw = self.take()
        if vk is None:
            raise QueryError(f'{field} {op}: missing a value')
        val = raw[1:-1] if vk == 'str' else raw

        if op == '~':
            try:
                rx = re.compile(val, re.I)
            except re.error as e:
                raise QueryError(f'bad pattern {val!r}: {e}')
            return lambda p, c, f=field: bool(rx.search(str(_get(p, c, f))))

        num = None
        if vk == 'num':
            num = float(val)

        def cmp(p, c, f=field, o=op, s=val, n=num):
            got = _get(p, c, f)
            if n is not None and not isinstance(got, str):
                a, b = float(got), n
            else:
                a, b = str(got).lower(), str(s).lower()
            if o in ('=', '=='):
                return a == b
            if o == '!=':
                return a != b
            if isinstance(a, str):
                raise QueryError(f'{f} {o} {s}: {o} needs numbers')
            return (a < b if o == '<' else a <= b if o == '<='
                    else a > b if o == '>' else a >= b)
        return cmp


def _get(part: Part, ctx, field: str):
    if field in DERIVED_FIELDS:
        return ctx.metric(part, field)
    return part.field(field)


# --------------------------------------------------------------------------
# evaluation context
# --------------------------------------------------------------------------

class Context:
    """Holds the one render, and builds it only if something asks.

    Every derived predicate funnels through here, so the render happens at most
    once per command no matter how many times a selector mentions `occluded`.
    """

    def __init__(self, ship, scene_builder=None):
        self.ship = ship
        self._scene_builder = scene_builder
        self._an = None
        self.rendered = False

    @property
    def an(self):
        if self._an is None:
            import analysis
            import scene as _scene
            sc = (self._scene_builder or _scene.build)(self.ship)
            self._an = analysis.Analysis(sc)
            self.rendered = True
        return self._an

    def _index(self, part: Part) -> int | None:
        return self.an.index_of(part.kind, part.obj.id)

    def metric(self, part: Part, field: str):
        i = self._index(part)
        if i is None:                      # unresolved sprite: nothing was drawn
            return 0.0 if field == 'occluded' else 0
        if field == 'visible':
            return self.an.visible[i]
        if field == 'area':
            return self.an.area[i]
        return self.an.occluded(i)

    def within(self, sid: int, dist: float, part: Part) -> bool:
        key = ('within', sid, dist)
        if not hasattr(self, '_cache'):
            self._cache: dict = {}
        if key not in self._cache:
            src = self.an.index_of('section', sid)
            if src is None:
                raise QueryError(f'touching/near: no section {sid}')
            self._cache[key] = self.an.within(src, dist)
        i = self._index(part)
        return i is not None and i in self._cache[key]

    def floating(self, part: Part) -> bool:
        """Not connected, through touching parts, to the group holding the core."""
        if not hasattr(self, '_hull'):
            core = self.an.index_of('core', 0)
            groups = self.an.islands()
            hull: set[int] = set()
            for g in groups:
                if core is None or core in g:
                    hull = set(g)
                    break
            self._hull = hull or set(groups[0] if groups else [])
        i = self._index(part)
        return i is not None and i not in self._hull


def select(ship, src: str, scene_builder=None) -> tuple[list[Part], Context, bool]:
    """(matches, context, needed_a_render) for a selector against a ship."""
    p = Parser(src)
    pred = p.parse()
    ctx = Context(ship, scene_builder)
    out = [q for q in parts(ship) if pred(q, ctx)]
    return out, ctx, p.derived

#!/usr/bin/env python3
"""Where everything lives, discovered rather than hardcoded.

No path here may be written down as a literal: an absolute one embeds whoever's
account it was authored on, and even a relative layout discloses a directory
tree nobody else has.

What these tools actually depend on is **a Battleships Forever v0.90d install**
-- the same copy the README asks you to bring. Sprites, `ShipMaker.exe` and the
`Pendulum.sb4` reference ship all come from there. Only `stockship.py` wants
something extra, the GML dump of the stock ships, and that sits beside the
install rather than anywhere new.

Resolution order for the install, first hit wins:

1. ``$BSF_GAME`` -- the install directory itself;
2. ``$BSF_BASE/battleshipsforeverv090d`` -- the older knob, still honoured;
3. the install dropped straight into this checkout;
4. a copy within two levels of the directory holding this checkout;
5. one in the home directory.

Nothing raises at import time. A missing install is only an error for the
callers that need it, so `ship.py` still opens a `.sb4` without one -- and
`require()` gives those callers one clear instruction instead of a stack trace.
"""

from __future__ import annotations

import os
import pathlib

__all__ = ['REPO', 'MAIN', 'SHIPS', 'GAME', 'SPRITES', 'GML', 'PENDULUM',
           'SHIPMAKER_EXE', 'require']

#: The game's own distribution folder name -- as shipped, and as `.gitignore`
#: already spells it.
_DIST = 'battleshipsforeverv090d'


def _checkout(start: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Return (this checkout's root, the main checkout's root).

    They differ inside a linked worktree, where `.git` is a *file* reading
    `gitdir: <main>/.git/worktrees/<name>` -- which is how the main checkout is
    recovered without shelling out to git.
    """
    for d in (start, *start.parents):
        dot = d / '.git'
        if dot.is_dir():
            return d, d
        if dot.is_file():
            try:
                line = dot.read_text(encoding='utf-8', errors='replace').strip()
            except OSError:
                break
            if line.startswith('gitdir:'):
                gitdir = pathlib.Path(line.split(':', 1)[1].strip())
                if not gitdir.is_absolute():
                    gitdir = (d / gitdir).resolve()
                for anc in gitdir.parents:      # <main>/.git/worktrees/<name>
                    if anc.name == '.git':
                        return d, anc.parent
            return d, d
    root = start.parents[1] if len(start.parents) > 1 else start
    return root, root


def _find_game(main: pathlib.Path) -> pathlib.Path:
    """Locate the install. Returns the preferred location even if absent, so
    error messages name somewhere sensible."""
    env = os.environ.get('BSF_GAME')
    if env:
        return pathlib.Path(env).expanduser()

    cands = []
    base = os.environ.get('BSF_BASE')
    if base:
        cands.append(pathlib.Path(base).expanduser() / _DIST)
    cands.append(main / _DIST)
    # Siblings of the checkout, one and two levels down. A checkout kept beside
    # other work finds an install in any of it without either being named here.
    for pat in (f'*/{_DIST}', f'*/*/{_DIST}'):
        try:
            cands.extend(sorted(main.parent.glob(pat)))
        except OSError:
            pass
    cands.append(pathlib.Path.home() / _DIST)

    for c in cands:
        if (c / 'ShipMaker.exe').exists() or (c / 'Custom sprites').is_dir():
            return c
    return cands[0]


_HERE = pathlib.Path(__file__).resolve().parent

#: This checkout — the worktree in use, or the main checkout outside one.
REPO: pathlib.Path
#: The main checkout. Untracked assets live here and nowhere else.
MAIN: pathlib.Path
REPO, MAIN = _checkout(_HERE)

#: The game install.
GAME = _find_game(MAIN)
SPRITES = GAME / 'Custom sprites'

#: Stock ships dumped as GML -- `stockship.py`'s input, kept beside the install.
GML = pathlib.Path(os.environ.get('BSF_GML') or (GAME.parent / 'dump' / 'ships_gml'))

#: The only stock ship carrying mounts: reference fixture, and the donor for the
#: `nWep*` fields the model preserves but does not understand.
PENDULUM = GAME / 'Custom Ships' / 'Pendulum.sb4'
SHIPMAKER_EXE = GAME / 'ShipMaker.exe'

#: Ships kept in this repo. Gitignored, so they exist in whichever checkout
#: made them -- prefer the one being worked in, fall back to the main one.
SHIPS = REPO / 'mods' / 'ships'
if not SHIPS.is_dir() and (MAIN / 'mods' / 'ships').is_dir():
    SHIPS = MAIN / 'mods' / 'ships'


def require(path: pathlib.Path, what: str) -> pathlib.Path:
    """Return `path`, or fail with the one instruction that actually helps."""
    if not path.exists():
        raise SystemExit(
            f'{what} not found at {path}\n'
            'Point BSF_GAME at a Battleships Forever v0.90d install, or put one '
            'beside this checkout.')
    return path

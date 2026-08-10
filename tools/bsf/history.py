#!/usr/bin/env python3
"""Write safety and version history for ship files.

Two editors share one document -- this CLI and ShipMaker -- and the document
lives in the game's `Custom Ships/` folder, which is not under version control.
So two mechanisms:

**hash guard.** A write is refused if the file changed since it was read. That
turns a lost update from something that happens quietly into something that
fails loudly and tells you who else touched it.

**shadow git.** Every version seen -- whether this CLI wrote it or ShipMaker did
-- is committed into a repository inside the gitignored cache, keyed by the
ship's absolute path. `.sb4` is line-oriented text, so `log`, `diff`, `undo` and
variant branches all come free. The real file is never touched by git and the
repo can be deleted at any time without consequence.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import subprocess

CACHE = pathlib.Path(__file__).resolve().parent / '.cache'
REPO = CACHE / 'history'


class Conflict(Exception):
    """The file changed on disk since it was read."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def slug(path: pathlib.Path) -> str:
    """A stable, filesystem-safe name for a ship's absolute path."""
    p = path.resolve()
    return f'{p.stem}-{hashlib.sha256(str(p).encode()).hexdigest()[:8]}{p.suffix}'


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(('git', '-C', str(REPO)) + args,
                          capture_output=True, text=True, check=check)


def _ensure_repo() -> None:
    if (REPO / '.git').exists():
        return
    REPO.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'init', '-q', str(REPO)], check=True)
    _git('config', 'user.name', 'bsf-ship-cli')
    _git('config', 'user.email', 'ship-cli@localhost')
    (REPO / 'README').write_text(
        'Shadow history for BSF ship files, written by tools/bsf/ship.py.\n'
        'Safe to delete: the real ship files live elsewhere and are unaffected.\n')
    _git('add', 'README')
    _git('commit', '-qm', 'init')


def record(path: pathlib.Path, data: bytes, message: str) -> str | None:
    """Commit this version of the ship. Returns the short sha, or None if unchanged."""
    _ensure_repo()
    name = slug(path)
    dest = REPO / name
    if dest.exists() and dest.read_bytes() == data:
        return None
    dest.write_bytes(data)
    _git('add', name)
    r = _git('commit', '-qm', f'{path.name}: {message}', check=False)
    if r.returncode != 0 and 'nothing to commit' not in (r.stdout + r.stderr):
        return None
    return _git('rev-parse', '--short', 'HEAD').stdout.strip()


def log(path: pathlib.Path, limit: int = 20) -> list[tuple[str, str, str]]:
    """[(sha, iso-date, message)] newest first, for this ship only."""
    if not (REPO / '.git').exists():
        return []
    r = _git('log', f'-{limit}', '--format=%h\t%ad\t%s', '--date=format:%Y-%m-%d %H:%M',
             '--', slug(path), check=False)
    out = []
    for line in r.stdout.splitlines():
        parts = line.split('\t', 2)
        if len(parts) == 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


def show(path: pathlib.Path, rev: str) -> bytes | None:
    if not (REPO / '.git').exists():
        return None
    r = subprocess.run(['git', '-C', str(REPO), 'show', f'{rev}:{slug(path)}'],
                       capture_output=True, check=False)
    return r.stdout if r.returncode == 0 else None


def diff(path: pathlib.Path, rev: str) -> str:
    if not (REPO / '.git').exists():
        return ''
    return _git('diff', rev, '--', slug(path), check=False).stdout


def baseline_path(path: pathlib.Path) -> pathlib.Path:
    return REPO / (slug(path) + '.accepted.json')


def read_baseline(path: pathlib.Path) -> list[str]:
    """Finding keys the user has already said are fine.

    Lives beside the ship in the shadow repo so it is versioned with the
    history: `ship log` shows when a finding was accepted, and `undo` takes the
    baseline back with the ship (D20).
    """
    p = baseline_path(path)
    if not p.exists():
        return []
    import json
    try:
        return list(json.loads(p.read_text()).get('accepted', []))
    except (ValueError, OSError):
        return []


def write_baseline(path: pathlib.Path, keys: list[str], note: str = '') -> None:
    import json
    _ensure_repo()
    p = baseline_path(path)
    p.write_text(json.dumps({'ship': path.name, 'accepted': sorted(keys)}, indent=1))
    _git('add', p.name)
    _git('commit', '-qm', f'{path.name}: accept {len(keys)} finding(s) {note}',
         check=False)


class Guarded:
    """Read a ship, and refuse to write it back if it moved underneath us."""

    def __init__(self, path: str | pathlib.Path):
        self.path = pathlib.Path(path)
        self.original = self.path.read_bytes()
        self.hash = digest(self.original)
        self.mtime = self.path.stat().st_mtime
        # Capture whatever is on disk now, so a save made in ShipMaker is in the
        # history even if this session never writes anything.
        record(self.path, self.original, 'seen on disk')

    def check(self) -> None:
        current = self.path.read_bytes()
        if digest(current) != self.hash:
            when = ''
            try:
                import datetime
                when = datetime.datetime.fromtimestamp(
                    self.path.stat().st_mtime).strftime(' at %H:%M')
            except OSError:
                pass
            raise Conflict(
                f'{self.path.name} changed on disk since it was read{when}\n'
                f'  re-run the command to work from the new version')

    def write(self, data: bytes, message: str) -> str | None:
        self.check()
        tmp = self.path.with_suffix(self.path.suffix + '.tmp')
        tmp.write_bytes(data)
        os.replace(tmp, self.path)
        self.hash = digest(data)
        self.mtime = self.path.stat().st_mtime
        return record(self.path, data, message)

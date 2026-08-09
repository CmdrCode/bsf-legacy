#!/usr/bin/env python3
"""The write gate: prove the model never loses anything before it may write.

Two checks, deliberately different in strength.

**exact** -- parse, re-render, compare bytes. Because records hold their fields
as strings, this passes by construction for anything the parser recognises; what
it actually catches is the boring, fatal stuff: a dropped final newline, CRLF
flattened to LF, a mishandled trailing comma, a `latin1` byte mangled through a
utf-8 assumption. Every ship file on disk must pass.

**strict** -- re-serialise *every* numeric token through `gmstr()` and compare.
This does not have to pass. It is a measurement of how faithfully `gmstr()`
reproduces Game Maker's `string(real)`, run against every number in every real
ship on disk. Fields it disagrees on are the fields it would be unsafe to edit,
so the mismatch list is the honest boundary of the writer.

    python3 roundtrip.py                 # every unique ship on disk
    python3 roundtrip.py --strict        # also measure the number formatter
    python3 roundtrip.py path/to/*.sb4
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import paths    # noqa: E402
import model  # noqa: E402

#: Where ships live when no paths are given. Sibling game copies hold identical
#: duplicates, so the corpus is deduplicated by content before testing.
SEARCH_ROOTS = [paths.SHIPS, paths.GAME.parent]


def corpus(paths: list[str]) -> list[pathlib.Path]:
    if paths:
        return [pathlib.Path(p) for p in paths]
    seen: dict[str, pathlib.Path] = {}
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for p in sorted(root.rglob('*')):
            if p.suffix.lower() not in ('.sb4', '.shp') or not p.is_file():
                continue
            digest = hashlib.md5(p.read_bytes()).hexdigest()
            seen.setdefault(digest, p)
    return sorted(seen.values())


def check_exact(path: pathlib.Path) -> tuple[bool, str]:
    original = path.read_bytes()
    ship = model.load(path)
    produced = ship.to_bytes()
    if produced == original:
        return True, ''
    # Locate the first divergence so a failure is actionable rather than a
    # bare "differs".
    for i, (a, b) in enumerate(zip(original, produced)):
        if a != b:
            lo = max(0, i - 30)
            return False, (f'byte {i}: {original[lo:i+30]!r} != {produced[lo:i+30]!r}')
    return False, f'length {len(original)} -> {len(produced)}'


def check_strict(path: pathlib.Path) -> list[str]:
    """Re-format every numeric token via gmstr(); report tokens it changes."""
    ship = model.load(path)
    bad: list[str] = []
    for rec in ship.records:
        for i, tok in enumerate(rec.tokens):
            t = tok.strip()
            if not t:
                continue
            try:
                v = float(t)
            except ValueError:
                continue          # a sprite path or ship name, not a number
            out = model.gmstr(v)
            if out != t:
                bad.append(f'{rec.kind}[{i}] {t!r} -> {out!r}')
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='*', help='ship files (default: every unique one on disk)')
    ap.add_argument('--strict', action='store_true', help='also measure gmstr() fidelity')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    files = corpus(args.paths)
    if not files:
        print('no ship files found')
        return 1

    by_gen: dict[str, list[int]] = {}
    failures: list[tuple[pathlib.Path, str]] = []

    for p in files:
        try:
            gen = model.load(p).generation
        except Exception as e:                                # noqa: BLE001
            failures.append((p, f'parse: {type(e).__name__}: {e}'))
            continue
        ok, why = check_exact(p)
        tally = by_gen.setdefault(gen, [0, 0])
        tally[1] += 1
        if ok:
            tally[0] += 1
            if args.verbose:
                print(f'  ok   [{gen}] {p.name}')
        else:
            failures.append((p, why))

    total_ok = sum(v[0] for v in by_gen.values())
    total = sum(v[1] for v in by_gen.values()) + len([f for f in failures if 'parse:' in f[1]])

    print('exact round-trip')
    for gen in sorted(by_gen):
        ok, n = by_gen[gen]
        mark = '✓' if ok == n else '✗'
        print(f'  {mark} {gen:>4}  {ok}/{n}')
    print(f'  {"✓" if not failures else "✗"} total {total_ok}/{total}')

    for p, why in failures:
        print(f'\n  FAIL {p}\n       {why}')

    if args.strict:
        print('\ngmstr() fidelity  (informational -- bounds which fields are safe to edit)')
        checked = 0
        mismatched: dict[str, int] = {}
        examples: dict[str, str] = {}
        for p in files:
            try:
                bad = check_strict(p)
            except Exception:                                 # noqa: BLE001
                continue
            checked += 1
            for b in bad:
                key = b.split(' ', 1)[0]
                mismatched[key] = mismatched.get(key, 0) + 1
                examples.setdefault(key, b)
        if not mismatched:
            print(f'  ✓ every numeric token in {checked} files reformats identically')
        else:
            for key in sorted(mismatched, key=lambda k: -mismatched[k]):
                print(f'  ⚠ {mismatched[key]:>5}×  {examples[key]}')

    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())

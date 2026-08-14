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


#: The `.shp` lines ShipMaker's *current* writer cannot produce, which a
#: reference file written by an older one still carries. Each is inert:
#:
#: * `//sh3 ver1` -- Pendulum predates the `ver2` tag `saveShipSHP` now writes.
#: * `nTrigS,i,9,0,0` / `nTrigW,i,9,0,0` -- these set `tr_toggle = 1` on a part
#:   whose four trigger types are all zero, and the game's own `nSecT`/`nWepT`
#:   handlers already set exactly that for exactly those parts. Today's
#:   `tr_checkToggle` gates on a non-zero type, so it cannot emit them at all.
EXPORT_ALLOWED = ('//sh3 ver', 'nTrigS,', 'nTrigW,')


#: Where to look for a design that exists in *both* generations.
#:
#: Deliberately the game's own ship folder and nothing else. Any `.sb4` beside
#: its own `.shp` is a valid oracle only if something other than this writer
#: produced the `.shp` -- and `ship export` writes exactly that pairing into
#: `mods/ships/`. Widening this to every root would quietly start grading the
#: writer against its own output, which passes by construction and proves
#: nothing. Stock ships are the author's and ShipMaker's; ours are not.
ORACLE_ROOT = ['Custom Ships']


def oracle_pairs() -> list[tuple[pathlib.Path, pathlib.Path]]:
    out = []
    for sub in ORACLE_ROOT:
        for src in sorted((paths.GAME / sub).glob('*.sb4')):
            ref = src.with_suffix('.shp')
            if ref.exists():
                out.append((src, ref))
    return out


def check_export_semantic(src: pathlib.Path) -> list[str]:
    """Export a `.sb4`, read the result back, and compare what it describes.

    Needs no reference file, so it runs on *every* `.sb4` there is rather than
    only the ones that happen to ship beside a `.shp`. What it proves is
    narrower, though, and the two checks are not substitutes: this one would
    still pass if the writer and the reader shared a wrong idea of the format,
    because it never leaves our own code. `check_export` is the only thing that
    can catch that, and it is why a real ShipMaker-written pair is worth having.
    """
    import export

    a = model.load(src)
    text = export.sb4_to_sh3(a)
    tmp = src.with_suffix('.shp')
    b = model.Ship(tmp, text, False)

    def parts(ship, items):
        return sorted((round(p.x, 2), round(p.y, 2), round(p.angle, 2),
                       round(p.xscale, 2), round(p.yscale, 2),
                       p.sprite.strip('"').replace('\\', '/').split('/')[-1])
                      for p in items)

    bad = []
    if parts(a, a.sections) != parts(b, b.sections):
        bad.append(f'{len(a.sections)} sections in, {len(b.sections)} out, '
                   'and their geometry differs')
    if parts(a, a.mounts) != parts(b, b.mounts):
        bad.append(f'{len(a.mounts)} mounts in, {len(b.mounts)} out, '
                   'and their geometry differs')
    # A parent is an id in one generation and a slot in the other, so the
    # numbers must differ; what has to hold is that they name the same part.
    where_a = {s.id: (round(s.x, 2), round(s.y, 2)) for s in a.sections}
    where_b = {s.id: (round(s.x, 2), round(s.y, 2)) for s in b.sections}
    for ma, mb in zip(a.mounts, b.mounts):
        if where_a.get(ma.parent) != where_b.get(mb.parent):
            bad.append(f'mount on section {ma.parent} re-hung elsewhere')
            break
    return bad


def check_export() -> tuple[bool, list[str]]:
    """Re-export every design that exists in both generations, and compare.

    This is the only check on the writer that does not depend on believing the
    writer. Differences are reported unless they are on the allow-list above,
    which is what keeps it a regression gate rather than a diff.
    """
    import export

    pairs = oracle_pairs()
    if not pairs:
        return True, ['skipped: no .sb4 shipped beside its own .shp']

    notes: list[str] = []
    ok = True
    for src, ref in pairs:
        got = export.sb4_to_sh3(model.load(src)).split('\r\n')
        want = model.decode(ref.read_bytes())[0].split('\r\n')
        diff = [f'-{line}' for line in want if line not in got]
        diff += [f'+{line}' for line in got if line not in want]
        unexplained = [d for d in diff
                       if not any(d[1:].startswith(p) for p in EXPORT_ALLOWED)]
        if unexplained:
            ok = False
            notes += [f'{src.stem}: {d}' for d in unexplained]
        else:
            notes += [f'{src.stem}: {d}' for d in diff]
    return ok, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='*', help='ship files (default: every unique one on disk)')
    ap.add_argument('--strict', action='store_true', help='also measure gmstr() fidelity')
    ap.add_argument('--export', action='store_true',
                    help='also check the sb4 -> sh3 writer against ShipMaker')
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

    export_ok = True
    if args.export:
        print('\nsb4 -> sh3 writer')

        # Every .sb4 there is: does the exported file still describe the ship?
        sources = [p for p in files if model.load(p).generation == 'sb4']
        sem_bad: list[str] = []
        for src in sources:
            sem_bad += [f'{src.name}: {b}' for b in check_export_semantic(src)]
        for b in sem_bad:
            print(f'  ✗ {b}')
        if not sem_bad:
            print(f'  ✓ re-read: {len(sources)} design(s) come back with the '
                  'same parts in the same places')

        # The matched pairs: is it the file ShipMaker would have written?
        pairs = oracle_pairs()
        export_ok, notes = check_export()
        if export_ok:
            print('  ✓ vs ShipMaker: %s — every line its current writer would '
                  'produce' % (', '.join(p[0].stem for p in pairs) or 'no pairs'))
            if args.verbose:
                for n in notes:
                    print(f'    (allowed) {n}')
        else:
            for n in notes:
                print(f'  ✗ {n}')
        export_ok = export_ok and not sem_bad

    return 1 if failures or not export_ok else 0


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Behavioural gate for the edit and analysis layers.

`roundtrip.py` proves the bytes survive; it cannot see whether an edit did the
right thing to them. Everything here is a property that was either broken once
or is expensive to notice by eye:

  * mounts follow their section (the v1 bug that stranded turrets in space)
  * a mirrored copy is field-for-field what ShipMaker itself would have written
  * deleting half a hull and mirroring it back reproduces the original exactly
  * a decode that reads as text, on a corpus that is mostly *not* comment-led
  * the linter's holes are gaps between plates, not windows in the artwork

Run it alongside the round-trip gate:

    python3 roundtrip.py && python3 selftest.py
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import paths    # noqa: E402
import analysis   # noqa: E402
import catalogue  # noqa: E402
import check      # noqa: E402
import edits      # noqa: E402
import model      # noqa: E402
import query      # noqa: E402
import scene      # noqa: E402
import ship as shipcli  # noqa: E402

PENDULUM = paths.PENDULUM
BOLTHOLE = paths.SHIPS / 'station_bolthole.sb4'

#: A doodad fixture, built on demand. No ship on disk has one -- `nDooA` was
#: recovered from ShipMaker's save routine, not from data -- so the only way to
#: exercise doodad support is to write the records the editor would write.
DOODADS = (
    'nDooA,0,3710,3068,Doodads\\DooSpinner.gif,1,1,0,0.30,5.9999,'
    '16777215,8454016,0,1,1,5\n'
    'nDooA,1,3710,3052,Doodads\\DooSpinner.gif,1,1,0,0.30,4.9999,'
    '16777215,8454016,0,1,1,7\n'
    '\nnDooMir,0,1\nnDooMir,1,0\n'
)

FAILURES: list[str] = []
PASSES = [0]


def ok(cond, label: str, detail: str = '') -> bool:
    if cond:
        PASSES[0] += 1
    else:
        FAILURES.append(f'{label}{"  -- " + detail if detail else ""}')
    return bool(cond)


def scratch(src: pathlib.Path, extra: str = '') -> pathlib.Path:
    """A writable copy, optionally with extra records under a banner.

    The inserted block takes the file's own line ending. Real `.sb4` files are
    CRLF, and a fixture that quietly switched to LF would be testing a file
    shape that ShipMaker never produces.
    """
    text, _obf = model.decode(src.read_bytes())
    if extra:
        eol = '\r\n' if '\r\n' in text else '\n'
        block = extra.replace('\n', eol)
        text = text.replace('//DOODADS' + eol,
                            '//DOODADS' + eol + eol + block, 1)
    d = pathlib.Path(tempfile.mkdtemp(prefix='bsf-selftest-'))
    p = d / src.name
    p.write_bytes(text.encode('latin1'))
    return p


# --------------------------------------------------------------------------

def test_mounts_follow():
    """D18: a section edit carries its weapons, modules and doodads."""
    p = scratch(PENDULUM, DOODADS)
    sh = model.load(p)
    before = {(m.kind, m.id): (m.x, m.y) for m in sh.mounts}
    shipcli.do_move(sh, 5, 50, 0, False, True)
    after = {(m.kind, m.id): (m.x, m.y) for m in sh.mounts}
    # weapon 2 and doodad 0 sit on section 5; weapon 1 and doodad 1 on its
    # mirror partner 7, and must move with it.
    for key in (('weapon', 2), ('doodad', 0), ('weapon', 1), ('doodad', 1)):
        ok(after[key][0] - before[key][0] == 50, f'move carries {key[0]} {key[1]}',
           f'{before[key]} -> {after[key]}')
    ok(after[('weapon', 0)] == before[('weapon', 0)],
       'move leaves a core-mounted weapon alone')

    sh = model.load(p)
    sec = sh.section(5)
    px, py = sec.x, sec.y
    m = [x for x in sh.mounts if x.kind == 'weapon' and x.id == 2][0]
    dx, dy = m.x - px, m.y - py
    shipcli.do_rotate(sh, 5, 90, False, True)
    m = [x for x in sh.mounts if x.kind == 'weapon' and x.id == 2][0]
    # +90 in GM's y-down CCW convention takes an offset (dx,dy) to (dy,-dx)
    ok(abs(m.x - (px + dy)) < 0.01 and abs(m.y - (py - dx)) < 0.01,
       'rotate orbits a mount about the pivot',
       f'expected {px + dy:+g},{py - dx:+g} got {m.x:+g},{m.y:+g}')


def test_doodads_modelled():
    """D17: doodads parse, resolve, render and sort in front of their host."""
    p = scratch(PENDULUM, DOODADS)
    sh = model.load(p)
    ok(len(sh.doodads) == 2, 'doodads parse')
    ok(sh.doodads[0].parent == 5, 'doodad parent comes from nDooA[14]')
    ok(sh.doodads[0].mirror == 1 and sh.doodads[1].mirror == 0,
       'doodad mirror links read both ways')
    sc = scene.build(sh)
    ok(sc['counts']['doodad'] == 2, 'doodads reach the draw list')
    ok(not sc['missing'], 'doodad sprite resolves', str(sc['missing']))
    z = {(o['kind'], o['id']): o['z'] for o in sc['ops']}
    ok(abs(z[('doodad', 0)] - (z[('section', 5)] - 0.0001)) < 1e-9,
       'doodad depth is parent.depth - 0.0001')
    ok(p.read_bytes() == model.load(p).to_bytes(), 'doodad file round-trips')


def test_mirror_rebuilds_exactly():
    """Delete half a wing, mirror it back, and get the original geometry."""
    p = scratch(PENDULUM)
    sh = model.load(p)
    edits.remove_section(sh, 7, mirror=False)
    p.write_bytes(sh.to_bytes())
    sh = model.load(p)
    edits.mirror_section(sh, 5)
    p.write_bytes(sh.to_bytes())

    def geom(path):
        s = model.load(path)
        return ({(x.sprite, x.x, x.y, x.angle, x.xscale, x.yscale)
                 for x in s.sections},
                {(m.kind, m.name, m.x, m.y, m.angle) for m in s.mounts})
    want, got = geom(PENDULUM), geom(p)
    ok(want[0] == got[0], 'mirror reproduces section geometry',
       str(want[0] ^ got[0]))
    ok(want[1] == got[1], 'mirror reproduces mount geometry',
       str(want[1] ^ got[1]))


def test_tier2_clone_convention():
    """D16: a cloned partner carries the handed fields the real pairs carry."""
    p = scratch(PENDULUM)
    sh = model.load(p)
    made, _notes = edits.mirror_section(sh, 6)   # 6/8 are already paired
    ok(not made, 'mirror refuses a section that already has a partner')

    sh = model.load(p)
    edits.remove_section(sh, 7, mirror=False)
    p.write_bytes(sh.to_bytes())
    sh = model.load(p)
    new = edits.mirror_section(sh, 5)[0][0]

    def rec(kind, sid):
        for r in sh.of_kind(kind):
            if int(r.num(0)) == sid:
                return r.tokens
        return None
    src_b, new_b = rec('nSecB', 5), rec('nSecB', new)
    src_c, new_c = rec('nSecC', 5), rec('nSecC', new)
    ok(src_b[edits.SECB_SIDE] == '-1' and new_b[edits.SECB_SIDE] == '0',
       'nSecB mirror side flips -1 -> 0',
       f'{src_b[edits.SECB_SIDE]} / {new_b[edits.SECB_SIDE]}')
    ok(float(new_c[15]) == -float(src_c[15]),
       'nSecC eff_yscale negates', f'{src_c[15]} / {new_c[15]}')
    ok([t for i, t in enumerate(src_b) if i not in
        (0, edits.SECB_SIDE, 3, 4, 5, 6, 7, 8, 10)] ==
       [t for i, t in enumerate(new_b) if i not in
        (0, edits.SECB_SIDE, 3, 4, 5, 6, 7, 8, 10)],
       'untouched nSecB fields are copied verbatim')


def test_remove_cascade():
    """D19: removal takes the subtree, the mounts and the mirror, and reports."""
    p = scratch(PENDULUM)
    sh = model.load(p)
    gone, warn = edits.remove_section(sh, 3)
    ids = {s.id for s in sh.sections}
    ok(ids == {1, 2}, 'cascade removes subtree and mirror', str(sorted(ids)))
    ok(len(sh.weapons) == 1, 'cascade removes the mounted weapons')
    ok(any('weapon' in g for g in gone), 'removal reports the mounts it took')
    ok(not warn, 'no dangling reference left behind', str(warn))

    sh = model.load(p)
    edits.remove_section(sh, 3, orphan=True)
    ok({s.id for s in sh.sections} == {1, 2, 5, 6, 7, 8},
       '--orphan keeps the children')
    ok(all(s.parent == 0 for s in sh.sections if s.id in (5, 6, 7, 8)),
       '--orphan reparents them upward')

    # A trigger pointing at a weapon that a delete takes with it must be seen.
    text, _ = model.decode(PENDULUM.read_bytes())
    q = p.with_name('dangle.sb4')
    q.write_bytes(text.replace('nWepB,0,0,', 'nWepB,0,1,').encode('latin1'))
    sh = model.load(q)
    _gone, warn = edits.remove_section(sh, 1)
    ok(any('missing weapon 0' in w for w in warn),
       'dangling nTrigS is reported', str(warn))


def test_new_ids_never_reuse_a_gap():
    p = scratch(PENDULUM)
    sh = model.load(p)
    edits.remove_section(sh, 5, mirror=False)
    sid, _notes = edits.add_section(sh, r'Kae_generic\Kae_sec46.png', 10, 10)
    ok(sid == 9, 'a new section takes max(secid)+1, not the freed 5', str(sid))


def test_query_grammar():
    p = scratch(PENDULUM, DOODADS)
    sh = model.load(p)
    for src, want in (
        ('weapon', 3), ('doodad', 2), ('section and x > 60', 2),
        ('name ~ sec4[67]', 2), ('not mirrored', 2),
        ('module or doodad', 3),
    ):
        got, _ctx, derived = query.select(sh, src)
        ok(len(got) == want, f'query {src!r} -> {want}', f'got {len(got)}')
        ok(not derived, f'query {src!r} needs no render')
    got, _ctx, derived = query.select(sh, 'touching(3)')
    ok(derived, 'touching() is flagged as needing a render')
    ok(any(g.kind == 'section' and g.obj.id == 5 for g in got),
       'touching(3) finds a section that touches it')
    for bad in ('nonsense > 3', 'x >', 'and'):
        try:
            query.select(sh, bad)
            ok(False, f'bad query {bad!r} is rejected')
        except query.QueryError:
            ok(True, f'bad query {bad!r} is rejected')


def test_check_and_baseline():
    p = scratch(BOLTHOLE)
    sh = model.load(p)
    found, _an = check.run(sh)
    pairs = {f.subject for f in found if f.code == 'mirror'}
    # D20's calibration: seven pairs drift, all by exactly 1 or 2 whole pixels.
    ok(len(pairs) == 7, 'seven mirror pairs drift on the reference hull',
       str(sorted(pairs)))
    mags = {abs(float(f.detail.split()[-1])) for f in found if f.code == 'mirror'}
    ok(mags <= {1.0, 2.0}, 'drift is whole-pixel, never fractional', str(mags))
    ok(not any(f.code == 'floating' for f in found), 'reference hull is connected')

    import history
    history.write_baseline(p, [f.key for f in found])
    ok(set(history.read_baseline(p)) == {f.key for f in found},
       'baseline round-trips through the shadow repo')
    again, _an = check.run(model.load(p))
    known = set(history.read_baseline(p))
    ok(all(f.key in known for f in again), 'an unchanged ship is fully accepted')


def test_holes_are_gaps_not_windows():
    sh = model.load(PENDULUM)
    an = analysis.Analysis(scene.build(sh))
    holes = an.holes(check.MIN_HOLE)
    ok(holes, 'the reference ship has enclosed pockets at all')
    ok(any(len(h['parts']) == 1 for h in holes),
       'some pockets are one part\'s own art')
    reported = [h for h in holes if len(h['parts']) > 1]
    ok(len(reported) < len(holes),
       'single-part windows are filtered out of the findings',
       f'{len(reported)} of {len(holes)}')


def test_decode_reads_as_text():
    """The corpus is mostly plain files that do not begin with a comment."""
    files = catalogue.corpus_files()
    ok(len(files) > 100, 'a corpus is present', str(len(files)))
    unreadable = []
    for f in files:
        text, _obf = model.decode(f.read_bytes())
        if model._readable(text.encode('latin1')) < 0.9:
            unreadable.append(f.name)
    ok(not unreadable, 'every ship file decodes to readable text',
       f'{len(unreadable)}: {unreadable[:3]}')
    for f in files:
        raw = f.read_bytes()
        text, obf = model.decode(raw)
        if model.encode(text, obf) != raw:
            ok(False, 'decode/encode is exact', f.name)
            return
    ok(True, 'decode/encode is exact for every file')


def test_corpus_mining():
    data = catalogue.build_cooccurrence()
    ok(data['parsed'] > 90, 'most ship files yield section placements',
       f'{data["parsed"]}/{data["files"]}')
    ok(data['placements'] > 900, 'the corpus is around a thousand placements',
       str(data['placements']))
    got, support, _d = catalogue.neighbours('spr_Section04')
    ok(support > 50, 'the commonest stock plate has real support', str(support))


# --------------------------------------------------------------------------

def main() -> int:
    if not PENDULUM.exists() or not BOLTHOLE.exists():
        print('skipped: the reference ships are not available here')
        return 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        try:
            t()
        except Exception as e:                       # noqa: BLE001
            FAILURES.append(f'{t.__name__} raised {type(e).__name__}: {e}')
    print(f'behaviour  {PASSES[0]} passed, {len(FAILURES)} failed')
    for f in FAILURES:
        print(f'  ✗ {f}')
    return 1 if FAILURES else 0


if __name__ == '__main__':
    raise SystemExit(main())

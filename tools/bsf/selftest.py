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

import io
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


def test_name_survives_both_generations():
    """sh3 quotes l_name and sb4 does not; neither may grow or lose a pair."""
    shp = BOLTHOLE.with_suffix('.shp')
    for src in (BOLTHOLE, shp if shp.exists() else BOLTHOLE):
        p = scratch(src)
        sh = model.load(p)
        was, tokens = sh.name, len(sh.first('nShp', 'nShp2').tokens)
        ok('"' not in was, f'{src.suffix}: name reads unquoted', repr(was))
        sh.name = 'test_rename'
        p.write_bytes(sh.to_bytes())
        again = model.load(p)
        ok(again.name == 'test_rename', f'{src.suffix}: name round-trips',
           repr(again.name))
        ok(len(again.first('nShp', 'nShp2').tokens) == tokens,
           f'{src.suffix}: renaming does not disturb the other fields')
        raw = again.first('nShp', 'nShp2').txt(model.Ship.NAME)
        quoted = src.suffix == '.shp'
        ok(raw.startswith('"') == quoted,
           f'{src.suffix}: quoting matches the generation', repr(raw))
    sh = model.load(scratch(BOLTHOLE))
    try:
        sh.name = 'has,comma'
        ok(False, 'a comma in a name is refused')
    except ValueError:
        ok(True, 'a comma in a name is refused')


def test_sh3_agrees_with_its_sb4_twin():
    """The same ship read from both generations must describe the same hull.

    `Custom Ships/` ships Pendulum twice — `Pendulum.sb4` and the `Pendulum.shp`
    exported from it — which is the only cross-generation pair in existence and
    therefore the whole evidence base for the sh3 reader. Byte equality is not
    the test and never can be: the export crosses a ShipMaker version, sh3 drops
    two fields, and it reorders the sections. Geometry, structure and identity
    are the test.
    """
    shp = PENDULUM.with_suffix('.shp')
    if not shp.exists():
        return
    a, b = model.load(PENDULUM), model.load(shp)
    ok(b.generation == 'sh3' and a.generation == 'sb4',
       'the twin really is one file per generation', f'{a.generation}/{b.generation}')
    ok(len(a.sections) == len(b.sections) == 8,
       'both generations build the same section count',
       f'{len(a.sections)} vs {len(b.sections)}')

    # Keyed on placement, because the ids cannot match: sb4 numbers sections in
    # creation order and sh3 identifies them by position in depth order.
    def key(s):
        return (round(s.x, 2), round(s.y, 2), s.name, s.xscale, s.yscale, s.angle)
    ka, kb = {key(s): s for s in a.sections}, {key(s): s for s in b.sections}
    ok(set(ka) == set(kb), 'every section appears in both, same place and pose',
       f'only in sb4: {sorted(set(ka) - set(kb))}  only in sh3: {sorted(set(kb) - set(ka))}')

    # Parenthood has to survive the renumbering: compare the relation itself,
    # each end resolved back to a placement.
    def links(sh, index):
        out = set()
        for s in sh.sections:
            if s.parent > 0:
                out.add((key(s), key(index[s.parent])))
        return out
    ia = {s.id: s for s in a.sections}
    ib = {s.id: s for s in b.sections}
    la, lb = links(a, ia), links(b, ib)
    ok(la == lb, 'the parent relation survives the renumbering',
       f'{len(la)} vs {len(lb)} links')

    # sh3 has no depth field; the reader synthesises it from record order, and
    # what matters is that the resulting *order* matches the .sb4's depths.
    oa = [key(s) for s in sorted(a.sections, key=lambda s: -s.depth)]
    obs = [key(s) for s in sorted(b.sections, key=lambda s: -s.depth)]
    ok(oa == obs, 'draw order matches the sb4 depth ordering')

    # Colour is the field sh3 stores differently rather than not at all: the
    # .sb4 keeps a resolved image_blend, sh3 keeps the shade index behind it.
    # Reading it as "no colour" rendered the whole hull black and looked
    # plausible in the tree, so this is the assertion that would have caught it.
    ca = {key(s): s.colour for s in a.sections}
    cb = {key(s): s.colour for s in b.sections}
    ok(ca == cb, 'every section resolves to the same team shade',
       f'{sorted(set(ca.values()))} vs {sorted(set(cb.values()))}')
    ok(len(set(cb.values())) > 1,
       'the hull is not flattened to a single shade', str(set(cb.values())))

    # Mounts: sh3 collapses weapons and modules into one nTur2 family, so the
    # counts cannot match per-kind — placement can, and does.
    ma = {(round(m.x, 2), round(m.y, 2), m.name) for m in a.mounts}
    mb = {(round(m.x, 2), round(m.y, 2), m.name) for m in b.mounts}
    ok(ma == mb, 'every mount appears in both, same place',
       f'only in sb4: {sorted(ma - mb)}  only in sh3: {sorted(mb - ma)}')
    ok({round(m.angle, 2) for m in a.mounts} == {round(m.angle, 2) for m in b.mounts},
       'mount angles survive the generation change')


def test_every_stock_custom_ship_reads():
    """The eight designs shipped in `Custom Ships/` must all build.

    They are the ships a mission may reference without shipping anything, so
    "can the editor draw it" is a real question about them. Seven are byte-
    shifted and were unreadable until decode; five are sh1 (Game Maker source),
    two sh2 (call syntax), one sh3 (records) — three generations across eight
    files, which is why this walks the folder rather than naming one.
    """
    folder = paths.GAME / 'Custom Ships'
    if not folder.is_dir():
        return
    ships = sorted(folder.glob('*.shp'))
    ok(len(ships) >= 8, 'the stock custom ships are present', str(len(ships)))
    for p in ships:
        sh = model.load(p)
        ok(len(sh.sections) > 0, f'{p.stem} builds sections',
           f'{sh.generation}: {len(sh.sections)}')
        ok(all(s.sprite for s in sh.sections), f'{p.stem} names a sprite per section')
        # A section whose colour collapsed to 0 renders black, which is how the
        # sh3 shade index was missed the first time.
        ok(all(s.colour > 0 for s in sh.sections), f'{p.stem} resolves team colours')


def test_stock_ship_import():
    """sh1 declares attachment backwards; the importer has to invert it."""
    import stockship
    if not stockship.GML.exists():
        return
    spec = stockship.read('Hestia')
    ok(len(spec['sections']) == 6, 'Hestia parses as 6 sections',
       str(len(spec['sections'])))
    ok(len(spec['weapons']) == 8, 'Hestia parses as 8 weapons',
       str(len(spec['weapons'])))
    # `l_section[1].l_child[...] = l_section[0]` means 1 owns 0, not the reverse.
    ok(spec['parent'].get(0) == 1 and spec['parent'].get(3) == 4,
       'child links invert into parent links', str(spec['parent']))
    ok(spec['wparent'].get(2) == 2, 'weapons resolve to their host section',
       str(spec['wparent']))

    p = scratch(PENDULUM)
    sh = model.load(p)
    before = len(sh.sections)
    root, ids = stockship.dock(sh, 'Hestia', 300, 0, tint=stockship.DAMAGE_TINT)
    ok(len(sh.sections) == before + 7, 'docking adds the hull plus a core section',
       f'{before} -> {len(sh.sections)}')
    ok(sh.section(root) is not None and sh.section(root).parent == 0,
       'the moored hull hangs off one root')
    ok(all(sh.section(i).colour == stockship.DAMAGE_TINT
           for i in ids if sh.section(i)), 'every moored part carries the tint')
    ok(len(sh.weapons) > 0, 'moored hull keeps its turrets', str(len(sh.weapons)))

    # removing the root must take the whole wreck -- sections and weapons
    edits.remove_section(sh, root, mirror=False)
    ok(len(sh.sections) == before, 'removing the root removes the whole hull',
       f'{len(sh.sections)} vs {before}')
    ok(len(sh.weapons) == len(model.load(p).weapons),
       'and its turrets go with it')


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
    """Assert the mechanism, not the reference hull's current geometry.

    An earlier version pinned D20's calibration directly -- "seven pairs drift
    on station_bolthole, all by whole pixels" -- which was true of the ship as
    found and stopped being true the moment someone edited it. A gate that
    breaks when the asset it measures is legitimately improved is measuring the
    wrong thing. The drift is introduced here instead, so the magnitude under
    test is known by construction.
    """
    p = scratch(BOLTHOLE)
    sh = model.load(p)
    found, _an = check.run(sh)
    ok(not any(f.code == 'floating' for f in found), 'reference hull is connected')

    pair = next(((a, b) for a, b in sh.mirrors.items()
                 if b > a and sh.section(a) and sh.section(b)), None)
    ok(pair is not None, 'the reference hull has a mirror pair to test with')
    if pair:
        a, b = pair
        sec = sh.section(a)
        sec.set_pos(round(sec.x + 3, 2), sec.y)     # a known 3px x deviation
        p.write_bytes(sh.to_bytes())
        found, _an = check.run(model.load(p))
        hits = [f for f in found
                if f.code == 'mirror' and f.subject == f'sections {a}/{b}']
        ok(any('dx' in f.detail and abs(abs(float(f.detail.split()[-1])) - 3) < .01
               for f in hits),
           'check reports the exact magnitude of a mirror deviation',
           str([f.detail for f in hits]))

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


def test_serve_index_and_routes():
    """The preview's ship list, without a socket.

    `resolve()` is split out of the request handler precisely so this can run:
    the fiddly half of the multi-ship page is pairing, staleness and key
    resolution, and none of it is visible in a render.
    """
    import ipaddress
    import json
    import os
    import serve

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        sb4 = root / 'hull.sb4'
        sb4.write_bytes(BOLTHOLE.read_bytes())
        shp = root / 'hull.shp'
        shp.write_bytes(BOLTHOLE.read_bytes())      # content is irrelevant here
        lone = root / 'orphan.shp'
        lone.write_bytes(BOLTHOLE.read_bytes())
        (root / 'hull.sb4.txt').write_text('a ShipMaker description sidecar')

        os.utime(shp, (1, 1))                       # export older than its source
        ix = serve.Index([root])
        keys = [e['key'] for e in ix.entries]
        ok(keys == ['0/hull.sb4', '0/hull.shp', '0/orphan.shp'],
           'the index lists .sb4 first, its export next, orphans in order',
           str(keys))
        by = ix.by_key
        ok(by['0/hull.shp']['pair'] == '0/hull.sb4',
           'a same-stem .shp is paired to its source')
        ok(by['0/hull.shp']['stale'] is True,
           'an export older than its .sb4 is flagged stale')
        ok(by['0/orphan.shp']['pair'] is None
           and by['0/orphan.shp']['stale'] is False,
           'an unpaired .shp is neither paired nor stale')
        ok(not any(e['file'].endswith('.txt') for e in ix.entries),
           'description sidecars are not ships')
        wire = json.dumps({'roots': ix.labels, 'ships': ix.entries})
        ok(str(root) not in wire and str(root.parent) not in wire,
           'nothing on the wire carries the root\'s absolute path')

        os.utime(shp, None)                         # re-export: no longer behind
        ix.rescan()
        ok(ix.by_key['0/hull.shp']['stale'] is False,
           'a fresh export clears the stale mark')

        st, ctype, body = serve.resolve('index', {}, ix)
        got = json.loads(body)
        ok(st == 200 and 'json' in ctype, 'GET /index is JSON')
        ok(got['sel'] == '0/hull.sb4',
           'with nothing named, the newest .sb4 is picked', str(got['sel']))
        ok(got['rev'] and len(got['rev']) == 12, 'the selected hull carries a hash')
        ok(got['roots'] == [root.name], 'roots are labelled, not pathed')

        st, _c, body = serve.resolve('index', {'ship': ['9/nope.sb4']}, ix)
        got = json.loads(body)
        ok(got['gone'] is True and got['sel'] == '0/hull.sb4',
           'a vanished selection falls back and says so')
        # A poll in flight when the page switches hulls answers about the old
        # one. Without `req` the page cannot tell, and adopting the answer
        # undoes the switch -- which is exactly what it did once.
        ok(got['req'] == '9/nope.sb4',
           'an answer names the key it was asked about')

        st, _c, body = serve.resolve('scene.json', {'ship': ['9/nope.sb4']}, ix)
        ok(st == 404, 'an unknown key is a 404, not a file read', str(st))
        st, _c, body = serve.resolve('scene.json', {'ship': ['0/../../etc/passwd']}, ix)
        ok(st == 404, 'a traversal-shaped key is just a miss', str(st))

        st, _c, body = serve.resolve('scene.json', {'ship': ['0/hull.sb4']}, ix)
        got = json.loads(body)
        served_rev = got.pop('rev', None)
        want = scene.for_web(scene.build(model.load(sb4)))
        ok(st == 200 and got == want,
           'the served scene is the scene the renderer draws')
        _st, _c, ixb = serve.resolve('index', {'ship': ['0/hull.sb4']}, ix)
        ok(served_rev == json.loads(ixb)['rev'],
           'a scene names its own revision, so the page re-fetches only on change')

        # The model is lenient -- junk content previews as a bare core rather
        # than raising -- so the failure path is reached by I/O and by a bug in
        # the build, not by a malformed file. Both are isolated to one hull.
        lone.unlink()                               # deleted between scan and read
        st, _c, body = serve.resolve('scene.json', {'ship': ['0/orphan.shp']}, ix)
        ok(st == 404 and 'error' in json.loads(body),
           'a hull deleted mid-flight answers with a reason, not a traceback',
           str(st))
        real_build = scene.build
        scene.build = lambda *a, **k: (_ for _ in ()).throw(ValueError('boom'))
        try:
            st, _c, body = serve.resolve('scene.json', {'ship': ['0/hull.sb4']}, ix)
        finally:
            scene.build = real_build
        ok(st == 500 and json.loads(body).get('error', '').startswith('ValueError'),
           'a failed scene build is one hull failing, named')
        st, _c, _b = serve.resolve('index', {'ship': ['0/hull.sb4']}, ix)
        ok(st == 200, 'and the index still serves around it')

        ix2 = serve.Index([root], first=sb4)
        ok(ix2.default() == '0/hull.sb4', 'a named file is the initial selection')

        # Where it listens. `auto` is loopback plus the tailnet when there is
        # one -- two sockets rather than a wildcard bind, so the URL works from
        # another device without offering the page to the local network.
        ok(serve.addresses('192.168.1.9') == [('192.168.1.9', '')],
           'an explicit --bind is taken literally, one socket')
        auto = serve.addresses('auto')
        ok(auto[0][0] == '127.0.0.1' and len(auto) <= 2,
           'auto always listens on loopback first', str(auto))
        ok(all(h != '0.0.0.0' for h, _n in auto),
           'auto never binds the wildcard')
        ts = serve.tailscale_ip()
        ok(ts is None or ipaddress.ip_address(ts) in serve._CGNAT,
           'a detected tailnet address is in the CGNAT range, not any 100.x',
           str(ts))
        ok((len(auto) == 2) == (ts is not None),
           'the tailnet address is offered exactly when Tailscale is up')
        links = serve._links([('10.0.0.1', 'note')], 8771, '0/a b.sb4')
        ok(links == ['  http://10.0.0.1:8771/?ship=0%2Fa%20b.sb4   note'],
           'a deep link quotes the key, spaces and all', str(links))

    empty = serve.Index([pathlib.Path(td) / 'gone'])
    ok(empty.entries == [] and empty.default() is None,
       'a missing root is empty, not an exception')


def test_sprites_hot_reload():
    """Art added, edited or deleted reaches the page without a restart.

    A ship's own bytes say nothing about the sprites it names, so before this
    the preview drew whatever it happened to load first: a sprite dropped in
    beside a hull that was waiting for it stayed `unresolved` until the ship
    file itself was touched -- which is exactly the state you are in while
    drawing the sprite. Three separate caches had to learn it: the loader's
    LRU (keyed by path), the hull revision the page polls, and the browser's
    image cache (keyed by `spr`).
    """
    import numpy as np
    import sprites
    from PIL import Image

    def art(shade: int, w: int = 12) -> bytes:
        a = np.zeros((16, w, 3), dtype=np.uint8)
        a[4:12, 2:w - 2] = shade                     # bottom-left stays the key
        buf = io.BytesIO()
        Image.fromarray(a).save(buf, format='PNG')
        return buf.getvalue()

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td) / 'Custom sprites'
        (root / 'Sections').mkdir(parents=True)
        f = root / 'Sections' / 'probe.png'
        old_root, old_exe = sprites.SPRITES, sprites.EXE_CACHE
        sprites.SPRITES = root
        sprites.EXE_CACHE = pathlib.Path(td) / 'no-exe-cache'
        try:
            empty = sprites.tree_rev(fresh=True)
            ok(sprites.resolve('Sections\\probe.png') is None,
               'a sprite that does not exist yet resolves to nothing')

            f.write_bytes(art(200))
            added = sprites.tree_rev(fresh=True)
            ok(added != empty, 'a sprite appearing moves the tree revision')
            ok(sprites.resolve('Sections\\probe.png') == f,
               'and it resolves the moment it is there — no rescan to arrange')
            first = sprites.load(str(f), mask=False)

            # Same name, same path, different pixels: the case a path-keyed
            # cache serves stale forever.
            f.write_bytes(art(90, w=14))
            edited = sprites.tree_rev(fresh=True)
            ok(edited != added, 'a sprite edited in place moves it too')
            second = sprites.load(str(f), mask=False)
            ok(second.w != first.w or not np.array_equal(second.frames[0],
                                                         first.frames[0]),
               'and the loader returns the new pixels, not the cached ones')

            f.unlink()
            ok(sprites.tree_rev(fresh=True) != edited,
               'a sprite deleted moves it as well')
            ok(sprites.resolve('Sections\\probe.png') is None,
               'and it goes back to unresolved rather than to stale art')
        finally:
            sprites.SPRITES, sprites.EXE_CACHE = old_root, old_exe
            sprites.tree_rev(fresh=True)   # drop the temp tree's digest


def test_scene_wire_carries_no_path():
    """What `/scene.json` sends names no local directory.

    `--bind auto` offers the page on the tailnet, so the payload travels. Two
    fields were absolute filesystem paths: every op's `spr`, and the ship's own
    `file`. `for_web` is the wire boundary, so both stop there -- `spr` becomes
    a token for the pixels, which is also what lets the browser cache it.
    """
    import json

    sc = scene.build(model.load(BOLTHOLE))
    web = scene.for_web(sc)
    blob = json.dumps(web)
    for probe in (str(paths.GAME), str(paths.REPO), str(pathlib.Path.home())):
        ok(probe not in blob, 'the wire scene names no local directory',
           f'found {probe!r}')
    ok('file' not in web, "the ship's own path does not go over the wire")
    ok(all(len(o['spr']) == 16 and o['spr'].isalnum() for o in web['ops']),
       'every op names its art by an opaque token')
    ok(set(web['sprites']) == {o['spr'] for o in web['ops']},
       'and the token is the key the pixels arrive under')
    # build()'s ops keep the path: render and check read them and need one.
    ok(all('/' in o['spr'] or '\\' in o['spr'] for o in sc['ops']),
       'while build() still hands the renderers real paths')


def test_page_pick_matches_the_blitter():
    """The preview's hover pick names the part the blitter actually drew.

    Both halves of the old test were the same mistake -- that a sprite *is* its
    sheet. A section's sheet is 80x80 holding a plate that fills 4% of it
    (BSF_Stock09) to 27% (BSF_Stock17), and `ox, oy` is the rotation point, not
    the centre: a Blaster's is 5.0px right of it. So a box centred on the origin
    claimed clear space in every direction, and -- sections sorting by depth --
    the front plate's empty sheet shadowed everything behind it. Measured on the
    Bolthole, it named the right part on 39.9% of painted pixels and claimed a
    part on 47.6% of the background.

    The renderer's id buffer already holds the answer per pixel, so it is the
    key here rather than a second implementation. Runs the page's own JS under
    node; without node there is nothing to run and the gate says so.
    """
    import base64
    import json
    import shutil
    import subprocess

    node = shutil.which('node')
    if node is None:
        print('  (page pick: node not installed, not run)')
        return

    import render
    import serve
    import numpy as np
    from PIL import Image

    sc = scene.build(model.load(BOLTHOLE))
    _img, ids, info = render.render(sc, scale=1, pad=8)

    # The scene the *browser* gets, not the one the renderer holds: `for_web`
    # rewrites every `spr` into a token and inlines the pixels, and the page
    # keys its caches by that. Decoding the alpha back out of those data URIs
    # rather than re-reading the files is what makes this end to end -- a token
    # that named the wrong pixels would show up here as a pick that misses.
    web = scene.for_web(sc)
    alphas = {}
    for tok, uri in web['sprites'].items():
        px = np.array(Image.open(io.BytesIO(
            base64.b64decode(uri.split(',', 1)[1]))).convert('RGBA'))
        alphas[tok] = {'w': int(px.shape[1]),
                       'a': base64.b64encode(
                           np.ascontiguousarray(px[..., 3]).tobytes()).decode()}

    blob = {'js': serve.PAGE.split('<script>')[1].split('</script>')[0],
            'ops': web['ops'], 'alphas': alphas,
            'cx': info['cx'], 'cy': info['cy'],
            'W': int(ids.shape[1]), 'H': int(ids.shape[0]),
            'ids': base64.b64encode(ids.astype(np.int32).tobytes()).decode()}

    checker = pathlib.Path(__file__).resolve().parent / 'pickcheck.mjs'
    with tempfile.NamedTemporaryFile('w', suffix='.json') as fh:
        json.dump(blob, fh)
        fh.flush()
        r = subprocess.run([node, str(checker), fh.name],
                           capture_output=True, text=True)
    if r.returncode not in (0, 1):
        ok(False, 'the page pick harness runs', r.stderr.strip()[-300:])
        return
    got = json.loads(r.stdout)
    ok(got['painted'] > 10000 and got['empty'] > 10000,
       'the pick gate covers a real hull', json.dumps(
           {k: got[k] for k in ('painted', 'empty')}))
    ok(got['hitOk'] == got['painted'],
       'hover names the part the blitter drew, on every painted pixel',
       got['onArt'] + '  ' + json.dumps(got['bad'][:3]))
    ok(got['emptyOk'] == got['empty'],
       'and picks nothing over a sheet\'s clear space',
       got['onClearSpace'] + '  ' + json.dumps(got['bad'][:3]))


def test_bbox_bounds_the_art():
    """`scene.bbox` contains what the blitter paints, origin off-centre or not.

    It never did for a turret. The corners were taken as +/-w/2 about the op
    origin, but a Blaster's origin is the base of its barrel, so the box sat
    5px left of the art and clipped the muzzle at every angle. Whole hulls hid
    it -- their extremes are set by 80x80 plates whose origin *is* the centre --
    which is why a rotated turret alone is the case worth pinning.
    """
    import render
    import numpy as np

    sc = scene.build(model.load(BOLTHOLE))
    blaster = next((o for o in sc['ops'] if o['name'] == 'Blaster'), None)
    if blaster is None:
        return
    for ang in (0, 45, 90, 180):
        o = dict(blaster)
        o['x'] = o['y'] = 0.0
        o['ang'] = float(ang)
        box = scene.bbox([o])
        # Frame the render on a box far larger than any candidate. Sizing the
        # canvas from the box under test would clip the art to it and the test
        # would pass by construction -- which is how the first draft of this
        # gate let three of these four angles through.
        room = [-o['w'] - o['h'], -o['w'] - o['h'], o['w'] + o['h'], o['w'] + o['h']]
        _im, ids, info = render.render({**sc, 'ops': [o], 'bbox': room},
                                       scale=1, pad=0)
        ys, xs = np.where(ids >= 0)
        art = (xs.min() - info['cx'], ys.min() - info['cy'],
               xs.max() + 1 - info['cx'], ys.max() + 1 - info['cy'])
        # One pixel of slack, and it belongs to the renderer rather than to the
        # box: `_transform` pastes at `round(half - ox)`, so a half-pixel origin
        # like the Blaster's 6.5 lands the art up to half a pixel off where the
        # arithmetic puts it, and the cell it falls in rounds that to one. The
        # default `pad=8` absorbs it. The error this gate exists for is 5px.
        slack = 1.0
        ok(box[0] <= art[0] + slack and box[1] <= art[1] + slack
           and box[2] >= art[2] - slack and box[3] >= art[3] - slack,
           f'bbox contains a turret rotated {ang} deg',
           f'box {box} art {list(art)}')


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

#!/usr/bin/env python3
"""Raise Battleships Forever's render resolution by editing room viewports.

NOTE: this is now the FALLBACK path. `mods/resolution.gml` does the same thing at
runtime via room_set_view -- and better, because it can read the player's actual
monitor, offer a picker, and switch live without restarting the game. Keep this
for setting a default before first launch, or for a build with no mod loader.


    patch_res.py <exe> --scale 2     double every room's viewport
    patch_res.py <exe> --scale 1     restore
    patch_res.py <exe> --show        report current values, change nothing

The drawing region -- GM's actual render target -- is established when a room
loads, from that room's authored view PORT. Changing `view_wport` at runtime does
not resize it (that only zooms inside the existing buffer), so the port has to be
changed in the resource tree instead.

VIEW is deliberately left alone. View = world area, port = pixels, so scaling
only the port keeps the framing identical and renders it into more pixels. BSF
drives `view_wview` itself every step in battle rooms, and that keeps working.

Every edited field is a fixed-size u32, so this is a same-length edit: no length
field anywhere in the tree moves, and only the touched bytes are re-encrypted.
"""
import os
import shutil
import struct
import sys
import zlib

import gm7
import gm7tree

EXPECTED_ROOMS = 25          # cross-checked against room_get_name in the live game


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    exe = sys.argv[1]
    show = '--show' in sys.argv
    scale = 1
    if '--scale' in sys.argv:
        scale = int(sys.argv[sys.argv.index('--scale') + 1])

    # --port/--view set the fields outright, which --scale cannot express.
    # Needed because GM clamps the region to the display, so a 4K target wants
    # port = the display's real 16:9 size, and view widened to match or the
    # scale is non-uniform and the picture is stretched.
    def wh(flag):
        if flag not in sys.argv:
            return None
        w, h = sys.argv[sys.argv.index(flag) + 1].lower().split('x')
        return int(w), int(h)
    want_port, want_view = wh('--port'), wh('--view')

    # --room NAME=WxH overrides the port for one room, on top of whatever the
    # global setting is. Repeatable. Needed both to test whether the region is
    # rebuilt per room load, and for the real per-room widescreen treatment
    # (battle rooms are 2048x2048 and can take a wide view; the 1024-wide menu
    # rooms cannot).
    per_room = {}
    for i, a in enumerate(sys.argv):
        if a == '--room':
            name, size = sys.argv[i + 1].split('=')
            w, h = size.lower().split('x')
            per_room[name] = (int(w), int(h))

    raw, (pos, clen, blob) = gm7.load(exe)
    tail = raw[pos + 4 + clen:]
    plain, seed, swap_start, swap_offset = gm7.gmkrypt_decrypt(blob)

    rooms = gm7tree.find_rooms(plain)
    if len(rooms) != EXPECTED_ROOMS:
        sys.exit(f'found {len(rooms)} rooms, expected {EXPECTED_ROOMS}; refusing')

    if show:
        for r in rooms:
            v = r['views'][0]
            print(f'{r["name"]:22s} view {v["view"][0]}x{v["view"][1]}  '
                  f'port {v["port"][0]}x{v["port"][1]}')
        return

    # A scale is relative to the stock 1024x768 port, not to whatever is there
    # now, so re-running with a different scale replaces rather than compounds.
    BASE = (1024, 768)
    SKIP_PORTS = {(640, 480)}      # rm_Options: views disabled, non-standard port
    edits = []
    buf = bytearray(plain)
    for r in rooms:
        for v in r['views']:
            pw, ph = v['port']
            # Whitelisting "known" port sizes was a mistake: after --port wrote a
            # custom size, a later run could no longer recognise it and silently
            # patched nothing. Invert it -- patch everything except the one
            # documented oddity, rm_Options' 640x480 (whose views are disabled
            # anyway, so its region comes from the room size regardless).
            if (pw, ph) in SKIP_PORTS:
                continue
            new_port = per_room.get(r['name']) or want_port or (BASE[0] * scale, BASE[1] * scale)
            if new_port != (pw, ph):
                struct.pack_into('<II', buf, v['port_off'], *new_port)
                edits.append((v['port_off'], 8, r['name'] + ':port'))
            if want_view and want_view != v['view']:
                # view_w/view_h sit 4 u32s before port_w in the same record
                voff = v['port_off'] - 4 * 4
                struct.pack_into('<II', buf, voff, *want_view)
                edits.append((voff, 8, r['name'] + ':view'))

    if not edits:
        print('nothing to change (already at that scale)')
        return
    print(f"{len(edits)} field edits")

    patched = bytes(buf)

    # Re-encrypt only the touched spans; the cipher is position-dependent, so
    # each span is re-encrypted at its own index.
    new_blob = bytearray(blob)
    for off, length, _name in edits:
        idx = off - swap_start
        enc = gm7.encrypt_bytes(patched[off:off + length], seed, swap_offset, idx, length)
        new_blob[swap_offset + idx: swap_offset + idx + length] = enc
    assert len(new_blob) == len(blob)

    # It must decrypt back to exactly what we intended, and re-parse cleanly.
    check, *_ = gm7.gmkrypt_decrypt(bytes(new_blob))
    if check != patched:
        sys.exit('re-encryption did not round-trip; aborting without writing')
    verify = gm7tree.find_rooms(check)
    if len(verify) != EXPECTED_ROOMS:
        sys.exit('tree no longer parses after edit; aborting without writing')
    print(f'verified: round-trips, and all {EXPECTED_ROOMS} rooms still parse')
    v0 = next(v for r in verify if r['name'] == 'rm_Sandbox' for v in r['views'][:1])
    print(f'  rm_Sandbox view {v0["view"][0]}x{v0["view"][1]}  port {v0["port"][0]}x{v0["port"][1]}')

    comp = zlib.compress(bytes(new_blob), 9)
    out = raw[:pos] + struct.pack('<I', len(comp)) + comp + tail

    bak = exe + '.res.bak'
    if not os.path.exists(bak):
        shutil.copy2(exe, bak)
        print(f'backup -> {bak}')
    with open(exe, 'wb') as f:
        f.write(out)
    print(f'patched {exe}: {len(raw)} -> {len(out)} bytes')


if __name__ == '__main__':
    main()

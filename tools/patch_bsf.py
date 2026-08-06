#!/usr/bin/env python3
"""Battleships Forever patcher: mod loader, the HWVP device-flag fix, the cursor cache.

Three independent fixes, all applied by default:

  1. MOD LOADER — injects a one-line bootstrap into the game's startup code so it
     will run GML from `mods/init.gml` next to the exe. Patch once; every mod
     after that is a text file.
  2. HWVP — flips the Direct3D 8 device from software to hardware vertex
     processing. Two bytes. Large speedup under wine, much
     less on Windows; see the README.
  3. CURSOR CACHE — `mouse_x` costs 176 us a read under wine and the game reads
     the pair ~70 times a frame; this answers them from a cache refreshed twice a
     frame. Changes no bytes of the exe — it is a DLL plus two files in `mods/`.
     Needs the mod loader. See the README.

    patch_bsf.py <BattleshipsForever.exe>               all three
    patch_bsf.py <BattleshipsForever.exe> --no-hwvp     no device-flag patch
    patch_bsf.py <BattleshipsForever.exe> --no-cursor   no cursor cache
    patch_bsf.py <ShipMaker.exe> --hwvp-only            HWVP only (no mod loader)
    patch_bsf.py <exe> --cursor-only                    cursor cache only
    patch_bsf.py <exe> --revert                         restore .bak (pre-mod-loader state)
    patch_bsf.py <exe> --revert-hwvp                    undo just the two HWVP bytes
    patch_bsf.py <exe> --revert-cursor                  remove the cursor cache

Contains no game data — only the 61-byte line it writes and two flag bytes. It
operates on the copy of the game you already have.

The two patches are orthogonal: the mod loader rewrites the resource tree at the
tail of the exe, HWVP rewrites two bytes in CODE. The build check below hashes the
exe with the HWVP bytes normalised out, so either can be applied first, and having
one already applied never makes the other refuse.

How it works: GM 7.0 keeps its resource tree as `[u32 len][zlib]` at the tail of
the exe, encrypted with "gmkrypt" (see gm7.py). We inflate, decrypt, overwrite a
dead comment with the bootstrap at EXACTLY the same length -- so no length field
anywhere in the tree changes -- re-encrypt just that span, re-deflate, and write
back with a corrected outer length. The bytes after the tree are preserved.
"""
import hashlib
import os
import shutil
import struct
import sys
import zlib

import cursorfix
import gm7
import hwvp

# The one build this patcher understands. Offsets and the anchor are specific to
# it, so anything else is refused rather than corrupted. (The bundled readme says
# v0.90c; the package is v0.90d. Trust the hash, not the text.)
KNOWN = {
    '0a393a0a46c410d87c003bdda8a58fbd777e5f1844a4de0c04d8acb53dede551': 'v0.90d',
}

# A dead comment inside GUI_MainTitle's startup event — code that provably runs
# when the main menu loads.
ANCHOR = b'//DIFFICULTY SETTING HERE SO THAT IT CAN RESET AFTER SKIRMISH MODES'

# Guarded so an install with no mods folder still runs untouched.
BOOTSTRAP = b'if file_exists("mods/init.gml") execute_file("mods/init.gml")'

MARKER = b'execute_file("mods/init.gml")'   # how we recognise our own work

# GM's "display error messages" flag, in the SETTINGS block — which lives in the
# plain, unencrypted part of the exe, before the resource tree. Stock BSF ships
# with it on, and because GMZ.dll is in no distribution, every start throws a pile
# of "Error defining an external function" dialogs from the zip extension's init.
# Those functions are never called (there are no gmz_* call sites in the game), so
# the dialogs are pure noise. `error_log` stays on, so errors still land in
# game_errors.log — which is where a modder should look when their init.gml is
# wrong.
ERROR_DISPLAY_OFF = 0x1efa68
# Sanity fingerprint: error_display, error_log, error_abort, uninitialized_zero,
# then the 43-entry constants block.
ERROR_FLAGS_EXPECTED = (1, 1, 0, 0, 43)


def sha256_build(path):
    """sha256 with the HWVP flag bytes normalised to SWVP.

    So the build check identifies the *build*, not which of our patches happen to
    be applied. Without this, HWVP-first would make the mod loader report an
    unrecognised build and refuse.
    """
    with open(path, 'rb') as f:
        d = bytearray(f.read())
    for o in hwvp.OFFSETS:
        if o < len(d) and d[o] == hwvp.HWVP:
            d[o] = hwvp.SWVP
    return hashlib.sha256(bytes(d)).hexdigest()


def hwvp_step(exe, to=hwvp.HWVP):
    """Apply (or revert) the two device-flag bytes, reporting before and after."""
    label = 'HWVP' if to == hwvp.HWVP else 'SWVP'
    try:
        # apply() runs verify_build then verify_shape before reading anything at
        # the target offsets, so a short or foreign file refuses rather than
        # raising IndexError.
        changed, before, after = hwvp.apply(exe, to)
    except hwvp.ShapeError as exc:
        sys.exit(f'HWVP: {exc}')
    where = ', '.join(f'{o:#010x}' for o in hwvp.OFFSETS)
    was = ' '.join(f'{v:#04x}' for v in before)
    now = ' '.join(f'{v:#04x}' for v in after)
    if not changed:
        print(f'HWVP: already {label} ({now}) at {where} — nothing to do')
    else:
        print(f'HWVP: {was} -> {now} at {where} '
              f'(D3DCREATE_{"HARDWARE" if to == hwvp.HWVP else "SOFTWARE"}'
              f'_VERTEXPROCESSING|FPU_PRESERVE)')


def cursor_step(exe, install=True):
    """Install or remove the cursor cache. Unlike HWVP this touches no bytes of
    the executable, so there is nothing to verify a build against — the pieces
    are files next to it, and their absence IS the revert."""
    game_dir = os.path.dirname(os.path.abspath(exe))
    if not install:
        gone = cursorfix.remove(game_dir)
        print('cursor cache: removed ' + (', '.join(gone) if gone else 'nothing — was not installed'))
        return
    try:
        added = cursorfix.install(game_dir)
    except cursorfix.InstallError as exc:
        sys.exit(f'cursor cache: {exc}')
    st = cursorfix.state(game_dir)
    print('cursor cache: bsfnat.dll + mods/cursor.gml + mods/cursor.on installed'
          + ('; chained from mods/init.gml' if added else '; already chained'))
    print(f'  state: {st}')
    print('  disable at any time by deleting mods/cursor.on (no repatch needed)')


def revert(exe):
    bak = exe + '.bak'
    if not os.path.exists(bak):
        sys.exit(f'no backup at {bak}')
    shutil.copy2(bak, exe)
    print(f'restored {exe} from {bak}')
    # The cursor cache lives entirely outside the exe, so restoring the backup
    # would otherwise leave it installed and silently unloadable (no init.gml).
    gone = cursorfix.remove(os.path.dirname(os.path.abspath(exe)))
    if gone:
        print('cursor cache: also removed ' + ', '.join(gone))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    exe = sys.argv[1]
    if not os.path.exists(exe):
        sys.exit(f'no such file: {exe}')

    if '--revert' in sys.argv:
        return revert(exe)
    if '--revert-hwvp' in sys.argv:
        return hwvp_step(exe, to=hwvp.SWVP)
    if '--revert-cursor' in sys.argv:
        return cursor_step(exe, install=False)

    if '--hwvp-only' in sys.argv:
        return hwvp_step(exe)
    if '--cursor-only' in sys.argv:
        return cursor_step(exe)

    mod_loader(exe, keep_errors='--keep-errors' in sys.argv)
    if '--no-hwvp' not in sys.argv:
        hwvp_step(exe)
    # Last: it needs mods/init.gml, which mod_loader() creates the folder for.
    if '--no-cursor' not in sys.argv:
        cursor_step(exe)


def mod_loader(exe, keep_errors=False):
    digest = sha256_build(exe)
    known = digest in KNOWN
    if known:
        print(f'{os.path.basename(exe)}: recognised {KNOWN[digest]}')

    raw, (pos, clen, blob) = gm7.load(exe)
    tail = raw[pos + 4 + clen:]          # anything after the tree, preserved verbatim
    plain, seed, swap_start, swap_offset = gm7.gmkrypt_decrypt(blob)

    # Check for our own marker BEFORE rejecting on hash: a patched exe necessarily
    # has an unknown hash, and "unrecognised build" is an alarming way to tell
    # someone they simply ran the patcher twice.
    if plain.count(MARKER):
        # Return rather than exit: the HWVP step is independent and must still run
        # (and report) when the mod loader is already in place.
        print('mod loader: already patched — nothing to do.\n'
              '  Edit mods/init.gml to change your mod (no repatch needed), '
              'or run with --revert to restore.')
        return
    if not known:
        sys.exit(f'unrecognised build (sha256 {digest}).\n'
                 'This patcher only knows BSF v0.90d; refusing to touch it.')

    print(f'tree @ {pos:#x} clen={clen} inflated={len(blob)} trailing={len(tail)}B')
    n = plain.count(ANCHOR)
    if n != 1:
        sys.exit(f'anchor found {n} times, expected exactly 1; refusing')

    payload = BOOTSTRAP.ljust(len(ANCHOR))     # same length: no length fields move
    assert len(payload) == len(ANCHOR)
    at = plain.find(ANCHOR)
    print(f'anchor at plain[{at}]; injecting {len(BOOTSTRAP)}B bootstrap '
          f'({len(ANCHOR)}B slot)')

    patched_plain = plain[:at] + payload + plain[at + len(ANCHOR):]

    # Re-encrypt only the span we touched; everything else stays byte-identical.
    idx = at - swap_start
    enc = gm7.encrypt_bytes(payload, seed, swap_offset, idx, len(payload))
    new_blob = blob[:swap_offset + idx] + enc + blob[swap_offset + idx + len(enc):]
    assert len(new_blob) == len(blob)

    # Sanity: it must decrypt back to what we intended.
    check, *_ = gm7.gmkrypt_decrypt(new_blob)
    if check != patched_plain:
        sys.exit('re-encryption did not round-trip; aborting without writing')
    print('verified: re-encrypted tree decrypts to the patched text')

    comp = zlib.compress(new_blob, 9)
    out = bytearray(raw[:pos] + struct.pack('<I', len(comp)) + comp + tail)

    # Silence the stock startup error dialogs, unless asked not to.
    if not keep_errors:
        got = struct.unpack_from('<5I', out, ERROR_DISPLAY_OFF)
        if got != ERROR_FLAGS_EXPECTED:
            sys.exit(f'settings fingerprint mismatch at {ERROR_DISPLAY_OFF:#x}: '
                     f'{got} != {ERROR_FLAGS_EXPECTED}; refusing to touch it')
        struct.pack_into('<I', out, ERROR_DISPLAY_OFF, 0)
        print('error dialogs disabled (errors still go to game_errors.log)')

    bak = exe + '.bak'
    if not os.path.exists(bak):
        shutil.copy2(exe, bak)
        print(f'backup -> {bak}')
    with open(exe, 'wb') as f:
        f.write(out)
    print(f'patched {exe}: {len(raw)} -> {len(out)} bytes')

    mods = os.path.join(os.path.dirname(os.path.abspath(exe)), 'mods')
    os.makedirs(mods, exist_ok=True)
    print(f'drop your GML in {os.path.join(mods, "init.gml")}')


if __name__ == '__main__':
    main()

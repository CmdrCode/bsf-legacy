#!/usr/bin/env python3
"""Battleships Forever patcher: mod loader, the HWVP device-flag fix, the cursor cache.

Knows two executables, both from the v0.90d package and both the same GM 7.0
runner: `BattleshipsForever.exe` (the game) and `ShipMaker.exe` (the ship
editor). The build is identified by hash and each gets its own patch recipe.

Three independent fixes, all applied by default:

  1. MOD LOADER — injects a one-line bootstrap into the startup code so the exe
     will run GML from a file next to it (`mods/init.gml` for the game,
     `mods/sm.gml` for ShipMaker). Patch once; every mod after that is a text
     file. For ShipMaker this also installs `mods/sm.gml` + `mods/smres.gml`,
     the 1:1-resolution module that makes the drawing region follow the window.
  2. HWVP — flips the Direct3D 8 device from software to hardware vertex
     processing. Two bytes, identical in both exes (their CODE sections are
     byte-identical). Large speedup under wine, much less on Windows.
  3. CURSOR CACHE — `mouse_x` costs 176 us a read under wine and both exes read
     the pair constantly; this answers them from a cache refreshed twice a
     frame. Changes no bytes of the exe — it is a DLL plus files in `mods/`.
     Needs the mod loader.

    patch_bsf.py <BattleshipsForever.exe>               all three
    patch_bsf.py <ShipMaker.exe>                        all three + resize module
    patch_bsf.py <exe> --no-hwvp                        no device-flag patch
    patch_bsf.py <exe> --no-cursor                      no cursor cache
    patch_bsf.py <exe> --hwvp-only                      HWVP only (no mod loader)
    patch_bsf.py <exe> --cursor-only                    cursor cache only
    patch_bsf.py <exe> --revert                         restore .bak (pre-mod-loader state)
    patch_bsf.py <exe> --revert-hwvp                    undo just the two HWVP bytes
    patch_bsf.py <exe> --revert-cursor                  remove the cursor cache

On Linux the patcher additionally drops `<Exe>_Linux.sh` next to each exe it
patches -- a self-contained wine launcher (private prefix, no setup knowledge
needed). `--revert` removes it.

Contains no game data — only the one-line bootstraps it writes, a handful of
same-length GML expression rewrites, and two flag bytes. It operates on the copy
of the game you already have.

The patches are orthogonal: the mod loader rewrites the resource tree at the
tail of the exe, HWVP rewrites two bytes in CODE. The build check below hashes the
exe with the HWVP bytes normalised out, so either can be applied first, and having
one already applied never makes the other refuse.

How it works: GM 7.0 keeps its resource tree as `[u32 len][zlib]` at the tail of
the exe, encrypted with "gmkrypt" (see gm7.py). We inflate, decrypt, overwrite
dead comments (and, for ShipMaker, a few hardcoded-resolution expressions) with
same-length replacements -- so no length field anywhere in the tree changes --
re-encrypt just the touched spans, re-deflate, and write back with a corrected
outer length. The bytes after the tree are preserved.
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

# ---------------------------------------------------------------------- the game
# A dead comment inside GUI_MainTitle's startup event — code that provably runs
# when the main menu loads.
ANCHOR = b'//DIFFICULTY SETTING HERE SO THAT IT CAN RESET AFTER SKIRMISH MODES'

# Guarded so an install with no mods folder still runs untouched.
BOOTSTRAP = b'if file_exists("mods/init.gml") execute_file("mods/init.gml")'

MARKER = b'execute_file("mods/init.gml")'   # how we recognise our own work

# ------------------------------------------------------------------- ShipMaker
# A dead comment inside obj_sidebar's Create event — the editor's master init,
# run once at startup (and again after the game_restart behind "New ship").
# It sits BEFORE the editor's own WinAPI init, so a mod must not call the API_*
# wrappers until its first Step.
SM_ANCHOR = b"//What next? Blood type? Mother's maiden name? Favorite color?"

SM_BOOTSTRAP = b'if file_exists("mods/sm.gml") execute_file("mods/sm.gml")'

SM_MARKER = b'execute_file("mods/sm.gml")'

# ShipMaker positions its popup/context menus by scaling room coordinates with
# window/1016 (x) and window/704 (y) — correct for the stock model, where the
# fixed 1016x704 drawing region is stretched to fill the window. mods/smres.gml
# replaces that model with a region that always EQUALS the window client size
# (1:1 pixels), under which the correct screen offset of a UI coordinate is the
# coordinate itself. Each rewrite below is padded to the original length, keeps
# a window_get_* call so the shape stays recognisable, and evaluates to plain
# `x` / `15`. The 800/609 pair is stock sloppiness (copied from elsewhere; the
# window was never 800x609) — same treatment.
#
# Note the trade-off: with the exe patched but the smres module removed, a
# RESIZED window positions menus unscaled (stock misplaced them too, only
# scaled); at the default 1016x704 both models agree exactly.
SM_MENU_EDITS = (
    (b'x*window_get_width()/1016',           b'x+0*window_get_width()',           4),
    (b'15*window_get_height()/704',          b'15+0*window_get_height()',         4),
    (b'x*window_get_width()/800',            b'x+0*window_get_width()',           1),
    (b'(y+l_ysize)*window_get_height()/609', b'(y+l_ysize)+0*window_get_height()', 1),
)

# GM's "display error messages" flag, in the SETTINGS block — which lives in the
# plain, unencrypted part of the exe, before the resource tree. Stock BSF ships
# with it on, and because GMZ.dll is in no distribution, every start throws a pile
# of "Error defining an external function" dialogs from the zip extension's init.
# Those functions are never called (there are no gmz_* call sites in the game), so
# the dialogs are pure noise. `error_log` stays on, so errors still land in
# game_errors.log — which is where a modder should look when their init.gml is
# wrong.
#
# ShipMaker has no GMZ extension (or any extension) and starts clean, so its
# entry leaves the flag alone: an editor throwing a REAL error should say so.
#
# The fingerprint is error_display, error_log, error_abort, uninitialized_zero,
# then the constants-block entry count.

#: Per-build patch recipes, keyed by sha256_build() digest. `error_off` of None
#: means "leave the error-dialog flag alone".
KNOWN = {
    '0a393a0a46c410d87c003bdda8a58fbd777e5f1844a4de0c04d8acb53dede551': {
        'name': 'v0.90d',
        'anchor': ANCHOR,
        'bootstrap': BOOTSTRAP,
        'marker': MARKER,
        'error_off': 0x1efa68,
        'error_expect': (1, 1, 0, 0, 43),
        'edits': (),
        'shipmaker': False,
    },
    '3d5932fbab07099ef7662391fec47c3934e3367f9106d4e16b7ca2e20479e6c8': {
        'name': 'ShipMaker v0.90d',
        'anchor': SM_ANCHOR,
        'bootstrap': SM_BOOTSTRAP,
        'marker': SM_MARKER,
        'error_off': None,
        'error_expect': None,
        'edits': SM_MENU_EDITS,
        'shipmaker': True,
    },
}


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


#: The ShipMaker modules this patcher installs next to the exe. sm.gml is the
#: entry point the bootstrap runs (kept if the user edited it); the rest are
#: modules and are refreshed on every run.
SM_MODULES = (('sm.gml', False), ('smres.gml', True), ('smpan.gml', True),
              ('smzoom.gml', True), ('mipdraw.gml', True), ('smpick.gml', True))


def sm_mods_step(exe):
    """Install mods/sm.gml + mods/smres.gml next to ShipMaker.exe.

    Searched the same way cursorfix finds its pieces: the checkout this script
    runs from, or the PyInstaller unpack dir when frozen.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    roots = [os.path.dirname(here), here, os.getcwd()]
    if getattr(sys, 'frozen', False):
        roots.insert(0, getattr(sys, '_MEIPASS', here))

    mods = os.path.join(os.path.dirname(os.path.abspath(exe)), 'mods')
    os.makedirs(mods, exist_ok=True)
    for name, overwrite in SM_MODULES:
        src = next((p for r in roots
                    for p in (os.path.join(r, 'mods', name),)
                    if os.path.exists(p)), None)
        if src is None:
            sys.exit(f'ShipMaker modules: no mods/{name} in this checkout')
        dst = os.path.join(mods, name)
        if os.path.exists(dst) and not overwrite:
            print(f'ShipMaker modules: mods/{name} already present — kept')
            continue
        shutil.copy2(src, dst)
        print(f'ShipMaker modules: installed mods/{name}')
    print('  resize behaviour: region follows the window 1:1; opt out by '
          'creating mods/smres.off')
    print('  part picker: Factorio-style quickbar + inventory; opt out by '
          'creating mods/smpick.off')


# The wine launcher dropped next to each patched exe -- Linux only, and
# GENERATED rather than shipped, so it only ever exists where it is valid.
# Every choice in it was settled empirically on a live setup:
#   * a PRIVATE prefix, so a user's ~/.wine (virtual desktops, DLL overrides,
#     a broken prefix) can never interfere -- and we never touch theirs;
#   * mscoree/mshtml disabled, so the first boot never prompts to download
#     Wine Mono or Gecko (GM 7.0 needs neither);
#   * no WINEARCH, so it works on both multiarch and new-wow64 wine builds;
#   * no wine virtual desktop -- the mod's fullscreen is a borderless window,
#     which killed the display-mode changes that made desktops necessary;
#   * UseXRandR=N in the prefix -- on a clean exit wine tears the D3D device
#     down and re-enumerates the displays, and on multi-monitor NVIDIA that
#     re-enumeration triggers a full modeset (every monitor blanks for a few
#     seconds). Nothing here needs XRandR -- the render is a borderless window
#     that never changes the display mode -- so turning it off is pure upside.
#     Measured: the editor's game_end() fired 30 RRScreenChangeNotify events
#     without it, zero with it; a hard kill (which skips the teardown) fired
#     none either way, which is what pinned the cause to the clean shutdown.
# @EXE@ / @STEM@ are substituted at write time.
LAUNCHER = '''#!/bin/sh
# @EXE@ under wine -- written by the BSF-Legacy patcher (Linux only).
# Safe to delete; repatching writes it again.
#
# Runs in a private wine prefix under ~/.local/share/bsf-legacy, so nothing
# in ~/.wine is touched or inherited. The first run creates the prefix (about
# ten seconds); after that, launches are instant. No winetricks, no virtual
# desktop, no other setup.

EXE="@EXE@"
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE" || exit 1

if [ ! -f "$EXE" ]; then
    echo "$EXE is not next to this script -- keep them in the game folder." >&2
    exit 1
fi

if ! command -v wine >/dev/null 2>&1; then
    echo "wine is not installed. One of these should get it:" >&2
    echo "  Ubuntu/Mint: sudo apt install wine" >&2
    echo "  Debian:      sudo dpkg --add-architecture i386 && sudo apt update && sudo apt install wine wine32" >&2
    echo "  Fedora:      sudo dnf install wine" >&2
    echo "  Arch:        sudo pacman -S wine    # needs the multilib repo" >&2
    exit 127
fi

WINEPREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/bsf-legacy/prefix"
export WINEPREFIX
export WINEDLLOVERRIDES="mscoree,mshtml="    # skip the Mono/Gecko download prompts
export WINEDEBUG=-all

if [ ! -d "$WINEPREFIX" ]; then
    echo "First run: creating a private wine prefix (about ten seconds)..."
    mkdir -p "$WINEPREFIX"
    wineboot >/dev/null 2>&1
fi

# Stop wine from driving XRandR: a clean exit tears the D3D device down and
# re-enumerates the displays, which on multi-monitor NVIDIA triggers a full
# modeset -- every monitor blanks for a few seconds. The render is a borderless
# window that never changes the display mode, so nothing here needs XRandR.
# Applied once and marked, so later launches skip the extra wine call; the
# marker also carries the fix into a prefix created before this was added.
if [ ! -f "$WINEPREFIX/.bsf-no-xrandr" ]; then
    if wine reg add "HKCU\\Software\\Wine\\X11 Driver" /v UseXRandR /d N /f >/dev/null 2>&1; then
        touch "$WINEPREFIX/.bsf-no-xrandr"
    fi
fi

LOG="$WINEPREFIX/@STEM@.log"
wine "$EXE" >"$LOG" 2>&1
STATUS=$?
if [ "$STATUS" -ne 0 ]; then
    if grep -qiE "bad exe format|32-bit" "$LOG" 2>/dev/null; then
        echo "This wine cannot run 32-bit programs. On Debian/Ubuntu:" >&2
        echo "  sudo dpkg --add-architecture i386 && sudo apt update && sudo apt install wine32" >&2
    else
        echo "wine exited with status $STATUS -- log kept at $LOG" >&2
    fi
fi
exit "$STATUS"
'''


def launcher_step(exe, remove=False):
    """Write (or remove) the `<Exe>_Linux.sh` wine launcher next to the exe.

    A no-op on anything but Linux: the Windows installer must not leave stray
    shell scripts in a Windows install.
    """
    if sys.platform != 'linux':
        return
    base = os.path.basename(exe)
    stem = base[:-4] if base.lower().endswith('.exe') else base
    path = os.path.join(os.path.dirname(os.path.abspath(exe)), stem + '_Linux.sh')
    if remove:
        if os.path.exists(path):
            os.remove(path)
            print(f'launcher: removed {os.path.basename(path)}')
        return
    with open(path, 'w', newline='\n') as f:
        f.write(LAUNCHER.replace('@EXE@', base).replace('@STEM@', stem))
    os.chmod(path, 0o755)
    print(f'launcher: wrote {os.path.basename(path)} — run it to play under wine')


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
    launcher_step(exe, remove=True)


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

    build = mod_loader(exe, keep_errors='--keep-errors' in sys.argv)
    if '--no-hwvp' not in sys.argv:
        hwvp_step(exe)
    if build and build['shipmaker']:
        sm_mods_step(exe)
    # Last: it needs mods/init.gml, which mod_loader() creates the folder for.
    if '--no-cursor' not in sys.argv:
        cursor_step(exe)
    launcher_step(exe)


def mod_loader(exe, keep_errors=False):
    """Inject the bootstrap (and the build's extra tree edits). Returns the
    build recipe that applies to this exe, or None if it could not be told."""
    digest = sha256_build(exe)
    build = KNOWN.get(digest)
    if build:
        print(f'{os.path.basename(exe)}: recognised {build["name"]}')

    raw, (pos, clen, blob) = gm7.load(exe)
    tail = raw[pos + 4 + clen:]          # anything after the tree, preserved verbatim
    plain, seed, swap_start, swap_offset = gm7.gmkrypt_decrypt(blob)

    # Check for our own marker BEFORE rejecting on hash: a patched exe necessarily
    # has an unknown hash, and "unrecognised build" is an alarming way to tell
    # someone they simply ran the patcher twice. Each build has its own marker,
    # which is also how a patched exe's build is identified.
    for b in KNOWN.values():
        if plain.count(b['marker']):
            # Return rather than exit: the HWVP step is independent and must
            # still run (and report) when the mod loader is already in place.
            entry = b['bootstrap'].split(b'"')[1].decode()
            print(f'mod loader: already patched ({b["name"]}) — nothing to do.\n'
                  f'  Edit {entry} to change your mod (no repatch needed), '
                  'or run with --revert to restore.')
            return b
    if not build:
        sys.exit(f'unrecognised build (sha256 {digest}).\n'
                 'This patcher only knows BSF v0.90d (game and ShipMaker); '
                 'refusing to touch it.')

    print(f'tree @ {pos:#x} clen={clen} inflated={len(blob)} trailing={len(tail)}B')

    # Every edit is a same-length span replacement: (offset, new bytes). The
    # bootstrap goes over the anchor comment; a build's extra edits are content-
    # matched with an exact expected count, so a foreign or drifted tree refuses
    # rather than half-patching.
    anchor, bootstrap = build['anchor'], build['bootstrap']
    n = plain.count(anchor)
    if n != 1:
        sys.exit(f'anchor found {n} times, expected exactly 1; refusing')
    assert len(bootstrap) <= len(anchor)
    at = plain.find(anchor)
    spans = [(at, bootstrap.ljust(len(anchor)))]
    print(f'anchor at plain[{at}]; injecting {len(bootstrap)}B bootstrap '
          f'({len(anchor)}B slot)')

    for old, new, expect in build['edits']:
        c = plain.count(old)
        if c != expect:
            sys.exit(f'expression {old.decode()!r} found {c} times, expected '
                     f'{expect}; refusing')
        assert len(new) <= len(old)
        start = 0
        while True:
            hit = plain.find(old, start)
            if hit < 0:
                break
            spans.append((hit, new.ljust(len(old))))
            start = hit + len(old)
    if build['edits']:
        print(f'{len(spans) - 1} hardcoded-resolution expressions rewritten '
              'for the 1:1 region model')

    buf = bytearray(plain)
    for off, data in spans:
        buf[off:off + len(data)] = data
    patched_plain = bytes(buf)

    # Re-encrypt only the spans we touched; everything else stays byte-identical.
    new_blob = bytearray(blob)
    for off, data in spans:
        idx = off - swap_start
        enc = gm7.encrypt_bytes(data, seed, swap_offset, idx, len(data))
        new_blob[swap_offset + idx: swap_offset + idx + len(enc)] = enc
    assert len(new_blob) == len(blob)

    # Sanity: it must decrypt back to what we intended.
    check, *_ = gm7.gmkrypt_decrypt(bytes(new_blob))
    if check != patched_plain:
        sys.exit('re-encryption did not round-trip; aborting without writing')
    print('verified: re-encrypted tree decrypts to the patched text')

    comp = zlib.compress(bytes(new_blob), 9)
    out = bytearray(raw[:pos] + struct.pack('<I', len(comp)) + comp + tail)

    # Silence the stock startup error dialogs, unless asked not to (or the build
    # has none to silence — ShipMaker).
    if build['error_off'] is not None and not keep_errors:
        got = struct.unpack_from('<5I', out, build['error_off'])
        if got != build['error_expect']:
            sys.exit(f'settings fingerprint mismatch at {build["error_off"]:#x}: '
                     f'{got} != {build["error_expect"]}; refusing to touch it')
        struct.pack_into('<I', out, build['error_off'], 0)
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
    entry = bootstrap.split(b'"')[1].decode()
    print(f'drop your GML in {os.path.join(os.path.dirname(mods), entry)}')
    return build


if __name__ == '__main__':
    main()

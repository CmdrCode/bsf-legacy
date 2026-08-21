#!/bin/sh
# Build the two native extensions: bsfnat.dll (cursor cache) and
# bsfshader.dll (the pixel-shader API behind mods/shader.gml).
#
#   build.sh                 build both DLLs
#   build.sh abi             also build bsfnatat.dll and diff the export names
#   build.sh install         build, then copy into the game directory
#   build.sh uninstall       remove them from it
#
# `abi` is the ABI probe: GM7's external_define takes a symbol NAME, and whether
# it needs "s_nop2" or "s_nop2@16" depends on whether the DLL was linked with
# --kill-at. Two DLLs from one source is how that was answered. The shipping
# module uses dll_cdecl only, so the default build does not need it -- nor the
# objdump that reads it.
set -e

# Prefer whatever i686 mingw is on PATH; a distro package (Debian/Ubuntu:
# gcc-mingw-w64-i686) is fine. MINGW_PREFIX exists because the machine this was
# written on has no passwordless sudo and uses a root-free unpack of the mingw
# debs instead.
if [ -z "${CC:-}" ]; then
    if command -v i686-w64-mingw32-gcc >/dev/null 2>&1; then
        CC=i686-w64-mingw32-gcc
    else
        PREFIX="${MINGW_PREFIX:-$HOME/.local/mingw32}"
        PATH="$PREFIX/usr/bin:$PATH"
        export PATH
        CC="$PREFIX/usr/bin/i686-w64-mingw32-gcc-win32"
    fi
fi

if ! command -v "$CC" >/dev/null 2>&1 && [ ! -x "$CC" ]; then
    echo "no i686-w64-mingw32 compiler found (tried: $CC)" >&2
    echo "  Debian/Ubuntu:  sudo apt install gcc-mingw-w64-i686" >&2
    echo "  or set CC, or MINGW_PREFIX, to point at your own toolchain." >&2
    exit 1
fi

HERE="$(cd "$(dirname "$0")" && pwd)"

# Where the game is. Resolved by tools/bsf/paths.py, which is the single answer
# to that question in this repo -- this script used to carry a second one, and
# two answers is how a DLL lands in one install while every other tool reads
# another. BSF_DIR still wins, for pointing a step at a specific copy.
#
# Called only by the install/uninstall steps: a plain build needs no game
# directory, and should not need python3 either.
game_dir() {
    if [ -n "${BSF_DIR:-}" ]; then
        printf '%s\n' "$BSF_DIR"
        return
    fi
    python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import paths; print(paths.GAME)' \
            "$HERE/bsf" 2>/dev/null
}

# Guard every use: an empty GAME would make `rm -f "$GAME/bsfnat.dll"` delete
# /bsfnat.dll, and `cp` write to the filesystem root.
require_game() {
    GAME="$(game_dir)"
    if [ -z "$GAME" ] || [ ! -d "$GAME" ]; then
        echo "no game directory at '${GAME:-<not found>}' -- set BSF_DIR, or \$BSF_GAME" >&2
        exit 1
    fi
}

CFLAGS="-O2 -s -Wall -Wextra -shared -static-libgcc"   # -s: mingw GCC 13 emits ~230 KB of DWARF without it

# --kill-at: __stdcall exports come out undecorated, which is what the GML side
# names them by.
"$CC" $CFLAGS -o "$HERE/bsfnat.dll" "$HERE/bsfnat.c" -Wl,--kill-at
echo "built $HERE/bsfnat.dll"

# bsfshader is two translation units on purpose: d3d8.h and d3d9.h both define
# D3D_SDK_VERSION and cannot be included together, so the D3D9 half is its own
# file and the boundary between them is plain `void *`.
"$CC" $CFLAGS -o "$HERE/bsfshader.dll" "$HERE/bsfshader.c" "$HERE/bsfshader_d9.c" -Wl,--kill-at
echo "built $HERE/bsfshader.dll"

if [ "${1:-}" = "abi" ]; then
    "$CC" $CFLAGS -o "$HERE/bsfnatat.dll" "$HERE/bsfnat.c"
    OBJDUMP="${OBJDUMP:-i686-w64-mingw32-objdump}"
    if command -v "$OBJDUMP" >/dev/null 2>&1; then
        for dll in bsfnat bsfnatat; do
            echo "--- $dll.dll stdcall exports ---"
            "$OBJDUMP" -p "$HERE/$dll.dll" |
                sed -n '/Ordinal\/Name Pointer/,/^$/p' | grep -E 's_(nop|strlen)'
        done
    else
        echo "($OBJDUMP not found -- built both DLLs, skipped the export dump)"
    fi
fi

case "${1:-}" in
install)
    require_game
    cp "$HERE/bsfnat.dll" "$HERE/bsfshader.dll" "$GAME/"
    echo "installed into $GAME"
    ;;
uninstall)
    require_game
    rm -f "$GAME/bsfnat.dll" "$GAME/bsfnatat.dll" "$GAME/bsfshader.dll"
    echo "removed from $GAME"
    ;;
esac

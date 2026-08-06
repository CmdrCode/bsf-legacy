#!/bin/sh
# Build bsfnat.dll -- the native half of the cursor cache.
#
#   build.sh                 build bsfnat.dll
#   build.sh abi             also build bsfnatat.dll and diff the export names
#   build.sh install         build, then copy into $BSF_DIR
#   build.sh uninstall       remove it from $BSF_DIR
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
GAME="${BSF_DIR:-$HERE/../battleshipsforeverv090d}"

CFLAGS="-O2 -s -Wall -Wextra -shared -static-libgcc"   # -s: mingw GCC 13 emits ~230 KB of DWARF without it

# --kill-at: __stdcall exports come out undecorated, which is what the GML side
# names them by.
"$CC" $CFLAGS -o "$HERE/bsfnat.dll" "$HERE/bsfnat.c" -Wl,--kill-at
echo "built $HERE/bsfnat.dll"

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
    [ -d "$GAME" ] || { echo "no game directory at $GAME -- set BSF_DIR" >&2; exit 1; }
    cp "$HERE/bsfnat.dll" "$GAME/"
    echo "installed into $GAME"
    ;;
uninstall)
    rm -f "$GAME/bsfnat.dll" "$GAME/bsfnatat.dll"
    echo "removed from $GAME"
    ;;
esac

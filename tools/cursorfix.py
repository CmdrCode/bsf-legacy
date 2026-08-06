#!/usr/bin/env python3
"""The cursor cache: install/remove the files, and the guards around doing it.

Shared by `patch_bsf.py` (shipping patcher) and the measurement harness, so the
guard exists once. Deliberately dependency-free.

------------------------------------------------------------------------ what it is
Under wine, reading `mouse_x` costs **176 us**. It is not a variable but a getter
whose implementation calls the cursor helper twice, and `mouse_y` repeats all of
it, so reading the pair is FOUR OS cursor round-trips. Each one is an
unconditional `wine_server_call` -- a wineserver IPC round-trip with no fast path
-- plus an X11 driver round-trip whenever the cursor has been IDLE for over
100 ms. BSF reads the pair ~70 times a frame in a battle.

The fix replaces the game's `GetCursorPos` IMPORT with one that answers from a
cache refreshed twice a frame. Every caller is fixed at once, and only the OS
cursor is held: GM still applies its own view transform on every read, so
`mouse_x` stays correct while the camera scrolls and zooms.

--------------------------------------------------------------- why not pure GML
`object_event_add` APPENDS to a stock event rather than replacing it (verified
in-game). A mod can therefore only ADD work to an event -- it can never remove
the stock cursor reads, which are the entire cost.

--------------------------------------------------------------------- the pieces
Unlike HWVP this changes **no bytes of the executable**. It is three files next
to the exe, and removing any of them restores stock behaviour exactly:

    bsfnat.dll          the hook (built from tools/bsfnat.c)
    mods/cursor.gml     installs it, ticks it twice a frame
    mods/cursor.on      the marker that makes init.gml chain it

It does require the MOD LOADER patch, because `mods/init.gml` is what runs it.
"""
import os
import sys
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))

DLL = 'bsfnat.dll'
MOD = os.path.join('mods', 'cursor.gml')
MARKER = os.path.join('mods', 'cursor.on')

#: The shipped mods/init.gml chains every module from an ordered table, which has
#: a row for the cursor module already. Recognising that table is what stops this
#: script appending a second chain and running cursor.gml twice.
TABLE_MARK = "bsf-legacy module table"

#: The line a bare init.gml (one this script wrote, or a user's own) needs, and
#: how to recognise it.
CHAIN_MARK = "mods/cursor.gml"
CHAIN = (
    "// Cursor cache. mouse_x costs 176 us to read under wine and the game reads the\n"
    "// pair ~70 times a frame; this reads it twice and serves every consumer from a\n"
    "// cache installed over the GetCursorPos import. Remove mods/cursor.on to disable.\n"
    "if (file_exists('mods/cursor.on') && file_exists('mods/cursor.gml'))\n"
    "    execute_file('mods/cursor.gml');\n"
)


class InstallError(Exception):
    pass


def sources():
    """(dll, mod) in this checkout, or raise. The DLL is built by build.sh; it is
    not checked in as a binary blob by this script.

    Several layouts are searched rather than one hardcoded pair. This file began
    in a research tree where `native/` and `mods/` were siblings of the script;
    in the published repo the script lives in `tools/` with `mods/` beside it,
    and inside a PyInstaller bundle both are unpacked next to each other. Looking
    in one place only meant the shipped --cursor-only flag could never find its
    own files.
    """
    roots = [HERE, os.path.dirname(HERE), os.getcwd()]
    if getattr(sys, 'frozen', False):
        roots.insert(0, getattr(sys, '_MEIPASS', HERE))

    dll = mod = None
    for r in roots:
        for cand in (os.path.join(r, DLL), os.path.join(r, 'native', DLL)):
            if dll is None and os.path.exists(cand):
                dll = cand
        cand = os.path.join(r, MOD)
        if mod is None and os.path.exists(cand):
            mod = cand

    if dll is None:
        raise InstallError('no %s -- build it first:  bash tools/build.sh' % DLL)
    if mod is None:
        raise InstallError('no mods/cursor.gml in this checkout')
    return dll, mod


def state(game_dir):
    """What is already in place, so the caller can report rather than guess."""
    init = os.path.join(game_dir, 'mods', 'init.gml')
    chained = False
    if os.path.exists(init):
        with open(init, encoding='latin-1') as f:
            text = f.read()
        chained = CHAIN_MARK in text or TABLE_MARK in text
    return {
        'dll': os.path.exists(os.path.join(game_dir, DLL)),
        'mod': os.path.exists(os.path.join(game_dir, MOD)),
        'marker': os.path.exists(os.path.join(game_dir, MARKER)),
        'chained': chained,
        'mod_loader': os.path.exists(init),
    }


#: What to write when there is no init.gml at all. The mod-loader patch creates
#: the folder but leaves the file to the user, so a fresh install has nowhere to
#: chain from; a minimal file is friendlier than refusing, and a user who later
#: drops in a fuller init.gml keeps the chain because it is appended, not
#: inserted at a fixed place.
INIT_STUB = (
    "// Mod loader entry point. The bootstrap patched into the exe runs only\n"
    "// this file, so every other mod is chained from here.\n"
    "if (variable_global_exists('bsf_mods_init')) exit;\n"
    "global.bsf_mods_init = 1;\n"
)


def install(game_dir):
    """Copy the pieces in and chain the mod from init.gml. Idempotent."""
    dll, mod = sources()
    mods = os.path.join(game_dir, 'mods')
    os.makedirs(mods, exist_ok=True)
    init = os.path.join(mods, 'init.gml')
    if not os.path.exists(init):
        with open(init, 'w', encoding='latin-1') as f:
            f.write(INIT_STUB)
    shutil.copy2(dll, os.path.join(game_dir, DLL))
    shutil.copy2(mod, os.path.join(game_dir, MOD))
    open(os.path.join(game_dir, MARKER), 'w').close()

    with open(init, encoding='latin-1') as f:
        text = f.read()
    if CHAIN_MARK in text or TABLE_MARK in text:
        return False
    # Appended rather than inserted at a fixed place: init.gml is a file the
    # user edits, and this must not depend on its current shape.
    with open(init, 'a', encoding='latin-1') as f:
        if not text.endswith('\n'):
            f.write('\n')
        f.write('\n' + CHAIN)
    return True


def remove(game_dir):
    """Take it out. The DLL is deliberately left behind -- other mods use it for
    its QueryPerformanceCounter export, and it is inert with no marker file."""
    gone = []
    for rel in (MARKER, MOD):
        p = os.path.join(game_dir, rel)
        if os.path.exists(p):
            os.remove(p)
            gone.append(rel)
    init = os.path.join(game_dir, 'mods', 'init.gml')
    if os.path.exists(init):
        with open(init, encoding='latin-1') as f:
            text = f.read()
        new = text.replace(CHAIN, '').replace('\n\n\n', '\n\n')
        if new != text:
            with open(init, 'w', encoding='latin-1') as f:
                f.write(new)
            gone.append('mods/init.gml chain')
        elif TABLE_MARK in text:
            # The shipped init.gml chains from a table, so there is no block to
            # cut. Deleting the files above is the whole removal: the table's row
            # is guarded by file_exists and is now a no-op.
            pass
        elif CHAIN_MARK in text:
            # A hand-edited or older chain that does not match CHAIN verbatim.
            # Say so rather than reporting a removal that did not happen: the
            # mod is now gone but the (harmless, guarded) chain line remains.
            gone.append('mods/cursor.gml [NOTE: mods/init.gml still references '
                        'it in a form this script did not write; the reference '
                        'is guarded by file_exists so it is inert]')
    return gone


def disable(game_dir):
    """Fastest possible off switch: drop the marker, leave everything else.
    This is also what a player does to A/B it themselves."""
    p = os.path.join(game_dir, MARKER)
    if os.path.exists(p):
        os.remove(p)
        return True
    return False

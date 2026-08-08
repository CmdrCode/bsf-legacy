#!/usr/bin/env python3
"""Battleships Forever Legacy installer -- the entry point the .exe wraps.

Does the whole job in one run: find the game, confirm it is the build this patcher
knows, put the modules in place, and apply the two executable patches. Safe to run
twice; every step reports what it found and what it changed.

    python3 tools/install.py                    find the game, install
    python3 tools/install.py <path-to-exe>      point it at a specific copy
    python3 tools/install.py --uninstall        restore the .bak and remove modules

Built for Windows as a single .exe by .github/workflows/build-installer.yml, where
`mods/` is bundled inside the binary and unpacked to sys._MEIPASS at run time.

--------------------------------------------------------------- the cursor cache
Deliberately NOT part of the Windows installer. It replaces the game's
GetCursorPos import with a cached one, which is worth ~176 us a read under wine
and close to nothing on Windows, where GetCursorPos is cheap. It also needs
bsfnat.dll, which is built by a cross-compiler and is not checked in. If the DLL
happens to sit next to this script it is installed anyway; otherwise the step is
skipped with a note rather than an error.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cursorfix                                            # noqa: E402
import patch_bsf                                            # noqa: E402
import hwvp                                                 # noqa: E402

EXE_NAME = 'BattleshipsForever.exe'
SM_NAME = 'ShipMaker.exe'


def resource_root():
    """Where `mods/` lives: the PyInstaller unpack dir when frozen, else the repo."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', HERE)
    return os.path.dirname(HERE)


def candidate_dirs():
    """Places to look for the game, nearest first.

    A double-clicked installer inherits an arbitrary working directory, so the
    directory containing the BINARY is checked before the cwd -- the usual case
    is a user dropping the installer into the game folder.
    """
    here_bin = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False)
                                               else sys.argv[0]))
    dirs = [here_bin, os.getcwd(), os.path.join(here_bin, 'BSF')]
    for base in (r'C:\Program Files (x86)', r'C:\Program Files', r'C:\Games', 'C:\\'):
        dirs += [os.path.join(base, 'Battleships Forever'),
                 os.path.join(base, 'BattleshipsForever'),
                 os.path.join(base, 'BSF')]
    return dirs


def find_game(explicit=None):
    if explicit:
        p = os.path.abspath(explicit)
        if os.path.isdir(p):
            p = os.path.join(p, EXE_NAME)
        if not os.path.exists(p):
            raise SystemExit('no such file: %s' % p)
        return p
    for d in candidate_dirs():
        p = os.path.join(d, EXE_NAME)
        if os.path.exists(p):
            return p
    raise SystemExit(
        'Could not find %s.\n'
        'Put this installer in your Battleships Forever folder and run it again,\n'
        'or pass the path:  install %s' % (EXE_NAME, os.path.join('<game folder>', EXE_NAME)))


def already_patched(exe):
    """True if a mod-loader bootstrap of ours is already in the resource tree.

    Read-only: inflates and decrypts the tree and looks for the markers, exactly
    as patch_bsf.mod_loader does before it decides to act. Each build has its
    own marker (the game runs mods/init.gml, ShipMaker runs mods/sm.gml).
    """
    try:
        import gm7
        _raw, (_pos, _clen, blob) = gm7.load(exe)
        plain = gm7.gmkrypt_decrypt(blob)[0]
        return any(b['marker'] in plain for b in patch_bsf.KNOWN.values())
    except Exception:
        # Anything unreadable falls through to the hash check, which refuses
        # safely rather than guessing.
        return False


def identify(exe, label):
    """Report the build, refusing an exe this patcher does not know.

    Identify BEFORE writing anything. sha256_build normalises the HWVP bytes
    out, so an HWVP-patched copy is still recognised -- but the mod loader
    rewrites the resource tree, so an already-installed copy hashes to something
    unknown by definition. Check for our own marker FIRST, or running the
    installer twice reports "unrecognised build", which reads like a corrupted
    game rather than "you already did this".
    """
    if already_patched(exe):
        print('%s: already has the mod loader -- updating modules in place' % label)
        return
    digest = patch_bsf.sha256_build(exe)
    if digest not in patch_bsf.KNOWN:
        raise SystemExit(
            'Unrecognised %s build (sha256 %s).\n'
            'This installer only knows Battleships Forever v0.90d, and will not\n'
            'touch anything else.' % (label, digest))
    print('%s: %s -- recognised' % (label, patch_bsf.KNOWN[digest]['name']))


def install_mods(game_dir):
    """Copy mods/ next to the exe, preserving anything already there.

    An existing mods/ is moved aside rather than merged: the modules chain from
    init.gml, and silently overwriting a user's edited init.gml with ours would
    lose their configuration with no way back.
    """
    src = os.path.join(resource_root(), 'mods')
    if not os.path.isdir(src):
        raise SystemExit('bundled mods/ folder is missing from this build')
    dst = os.path.join(game_dir, 'mods')

    if os.path.isdir(dst):
        n = 1
        while os.path.exists('%s.bak%d' % (dst, n)):
            n += 1
        shutil.move(dst, '%s.bak%d' % (dst, n))
        print('  existing mods/ kept as mods.bak%d' % n)

    shutil.copytree(src, dst)
    print('  installed %d files into mods/' % sum(len(f) for _, _, f in os.walk(dst)))


def install_dll(game_dir):
    """Install the cursor cache if its DLL was bundled, else disable the module.

    The DLL name, the marker filename and the search roots all belong to
    `cursorfix`; this only decides whether to use them.
    """
    for root in (resource_root(), HERE, os.path.dirname(HERE)):
        p = os.path.join(root, cursorfix.DLL)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(game_dir, cursorfix.DLL))
            print('  installed %s (cursor cache active)' % cursorfix.DLL)
            return True
    print('  %s not bundled -- cursor cache skipped.' % cursorfix.DLL)
    print('    It is a wine-specific optimisation and buys ~nothing on Windows.')
    cursorfix.disable(game_dir)
    return False


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith('-')]
    flags = {a for a in sys.argv[1:] if a.startswith('-')}

    print('Battleships Forever -- Legacy installer')
    print('=' * 44)

    exe = find_game(argv[0] if argv else None)
    game_dir = os.path.dirname(exe)
    print('game: %s' % exe)

    # The ship editor sits next to the game and shares its mods/ folder; it is
    # patched too when present, and its absence is not an error.
    sm = os.path.join(game_dir, SM_NAME)
    if not os.path.exists(sm):
        sm = None
        print('%s not found next to the game -- skipping the ship editor' % SM_NAME)

    if '--uninstall' in flags:
        patch_bsf.revert(exe)                    # also removes the Linux launcher
        hwvp.revert(exe)
        if sm and os.path.exists(sm + '.bak'):
            patch_bsf.revert(sm)
            hwvp.revert(sm)
        print('done. mods/ left in place -- delete it to remove the modules.')
        return

    identify(exe, 'game')
    if sm:
        identify(sm, 'ship editor')

    print('\ninstalling modules...')
    install_mods(game_dir)
    install_dll(game_dir)

    print('\npatching executable...')
    patch_bsf.mod_loader(exe)
    patch_bsf.hwvp_step(exe)
    patch_bsf.launcher_step(exe)                 # Linux only; no-op on Windows

    if sm:
        print('\npatching ship editor...')
        patch_bsf.mod_loader(sm)
        patch_bsf.hwvp_step(sm)
        patch_bsf.launcher_step(sm)

    print('\nDone. Launch the game as usual.')
    print('Each module is a marker file in mods/ -- delete one to turn it off.')
    if sm:
        print('The ship editor now renders 1:1 at any window size; its window')
        print('size is remembered in mods/smres.cfg.')
    print('To undo the executable patches:  install --uninstall')


if __name__ == '__main__':
    try:
        main()
    except SystemExit as e:
        if e.code not in (0, None):
            print('\nERROR: %s' % e.code)
        code = e.code if isinstance(e.code, int) else 1
    else:
        code = 0
    # A double-clicked console window closes the instant the process ends, taking
    # the report with it. Only pause when frozen, so scripted use is unaffected.
    if getattr(sys, 'frozen', False):
        try:
            input('\nPress Enter to close...')
        except EOFError:
            pass
    sys.exit(code)

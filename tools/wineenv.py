#!/usr/bin/env python3
"""The wine DLL overrides, owned in one place because there are four launch paths.

`game.py`, the editor's launcher, and the Linux launcher `patch_bsf.py` writes
into the player's install all need the same string, and the capture notes carried
a fourth copy. Four copies is how one of them quietly stops matching the others --
the same failure this repo already hit with install discovery, fixed the same
way: one owner, everyone reads it.

    mscoree,mshtml=   disable Mono and Gecko so wine never offers to download
                      them.

    d3d8=n,b          prefer the `d3d8.dll` sitting next to the exe over wine's
                      builtin. That file is d3d8to9, which translates the game's
                      Direct3D 8 calls to Direct3D 9 -- and D3D9 is what
                      `mods/shader.gml` needs, because programmable shading above
                      PS 1.4 is a D3D9 feature and D3D8 has no way to express it.

                      This is for VISUAL EFFECTS and nothing else. It buys no
                      performance: measured at 111.6 -> 110.2 ms, i.e. nothing,
                      and d3d8to9 still forwards one DrawPrimitiveUP per sprite
                      exactly as the builtin does.

                      `n,b` is native-then-builtin, so it is safe when the file
                      is absent: wine falls back to its own d3d8, the game runs
                      exactly as before, and the shader layer reports itself off.

                      The override is needed at all because wine will not prefer
                      a native DLL unsolicited -- it keeps the builtin unless the
                      builtin carries IMAGE_DLLCHARACTERISTICS_PREFER_NATIVE, and
                      wine's d3d8 does not. On real Windows no override exists or
                      is needed: the exe's own directory is searched first and
                      d3d8 is not a KnownDLL.
"""
import os

#: Also interpolated into the shipped Linux launcher, so keep it shell-safe.
OVERRIDES = 'mscoree,mshtml=;d3d8=n,b'


def overrides(extra=None):
    """`OVERRIDES` plus anything the caller adds.

    Wine lets a later entry win, so a caller can turn a default back *off*:
    `WINEDLLOVERRIDES_EXTRA='d3d8=b'` forces the builtin d3d8 and with it the
    stock renderer -- which is how you A/B the shim without editing anything.
    """
    if extra is None:
        extra = os.environ.get('WINEDLLOVERRIDES_EXTRA', '')
    extra = (extra or '').strip()
    return OVERRIDES + ';' + extra if extra else OVERRIDES

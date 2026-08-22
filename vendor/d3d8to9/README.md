# d3d8to9

Third-party, vendored. Not ours, not the game's, and not built from either.

| | |
|---|---|
| upstream | https://github.com/crosire/d3d8to9 |
| version | v1.15.1, released 2026-03-07 |
| asset | `d3d8.dll`, from that release's downloads |
| sha256 | `ab6bf7a9a9f4b3e66a75ca038d8d10289c88acbfe8d52c3b5a8a9a259cb26cd5` |
| size | 124,416 bytes — PE32, Intel 80386 |
| licence | BSD 2-Clause — `LICENSE.md` beside this file, reproduced verbatim |

## What it is for

`mods/shader.gml` runs HLSL on the device the game is already drawing with. It
gets at that device through d3d8to9's inner `IDirect3DDevice9`: BSF is a D3D8
title, there is no D3D9 device to reach until something translates, and this is
the something. No shader effect in this repo works without it.

Loading it is just placement — Windows resolves `d3d8.dll` from the game's own
directory before the system one, which is the whole install procedure. Wine
needs to be told as well, and `tools/wineenv.py` sets `d3d8=n,b` to tell it.

## Why the binary is committed

This repo holds sources and ships generators, never their output — and `*.dll`
is in `.gitignore` to enforce exactly that. That rule is about the game's own
files and about *our* build products (`bsfnat.dll`, `bsfshader.dll` are built by
`tools/build.sh` and stay ignored). This file is a third party's released
artefact, which is a different thing, so `.gitignore` carries one negation
naming this exact path and nothing wider.

Committed rather than fetched during the build, deliberately: a release asset
downloaded at build time is a live dependency on someone else's hosting, and it
can move, change or 404 between one build and the next. Vendored, the installer
builds from the tree and only from the tree.

## Attribution

BSD 2-Clause requires that a binary redistribution reproduce the copyright
notice, the conditions and the disclaimer "in the documentation and/or other
materials provided with the distribution". A `LICENSE.md` sitting in this
repository does not travel with a released installer, so `tools/install.py`
copies it into the game folder as `d3d8to9-LICENSE.txt` next to the DLL, and
names the project and its author on the way past. Do not remove either.

## Updating it

Download the new release asset, replace `d3d8.dll`, and update the version,
date and sha256 in the table above — the recorded hash is the only thing that
says which upstream build this is. Verify with:

    sha256sum vendor/d3d8to9/d3d8.dll

Check the licence file too: it is reproduced here verbatim, so an upstream
change to it has to be mirrored.

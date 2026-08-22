#!/usr/bin/env python3
"""Sprite loading for BSF ships: resolution, transparency keying, origins.

Ported from an earlier prototype renderer that had already earned the parts
that are easy to get wrong. Kept verbatim in substance:

  * transparency keys on the **bottom-left pixel's colour**, not on black and not
    on a GIF flag (these files carry none). Sections key on black; every turret
    sheet keys on `(0,128,64)`.
  * a GIF strip gives **each frame its own local palette**, so the key must be
    resolved per frame. Keying by palette index leaves the backdrop opaque on
    every frame but the first.
  * a turret rotates about **the base of its barrel**, not its centre. GM keeps
    sprite origins in the exe's resource tree, but a turret's shape gives it
    away: the base is the run of tallest columns. Drawing turrets centred leaves
    them visibly 5-6px behind their mounts.

What is new here is a second resolver. `ship_html.py` only ever saw GM sprite
*names* (`spr_Section01`) because it read `.shp` files. ShipMaker's `.sb4`
instead stores a path relative to `Custom sprites/` (`Stock Sections\\BSF_Stock17.png`),
which is both easier and unambiguous -- so `resolve()` handles both.
"""
from __future__ import annotations

import base64
import configparser
import functools
import io
import os
import pathlib
import re

import numpy as np
from PIL import Image

import paths

GAME = paths.GAME
SPRITES = paths.SPRITES

#: Searched in order when resolving a bare GM sprite name. `.sb4` files name a
#: folder explicitly and never need this.
FOLDERS = ('Stock Weapons', 'Stock Misc', 'Doodads', 'Stock Sections', 'Sections',
           'Old Sections', 'Kae_stock', 'Kae_generic', 'Kae_detail', 'Kae_small',
           'Kae_misc', 'Kae_alien')

#: Weapon objects that draw an extra additive pass at 1.5x scale in `$FF2222` --
#: a GM literal, so BGR: rgb(34,34,255), a *blue* glow. It is what makes
#: deflectors and boosters read as glowing beads.
#:
#: `UmbraCloak` is the one entry the shipped game does not have: it is a module
#: type `mods/umbracloak.gml` builds at load, parented to `ctr_Turrets` like
#: every stock module. It belongs in this set for the reason the set exists --
#: the loader reads `l_bullet` off every *weapon* mount, and a module has none,
#: so filing it as a weapon would cost the whole ship (D19c).
MODULES = {
    'Deflector', 'AegisDeflector', 'NanoMatrix', 'Booster', 'Thruster',
    'Impeder', 'ImpederDeployer', 'GluonBolter', 'Lancet', 'Teller', 'Gosling',
    'Frosch', 'Gravbeam', 'DemeterPod', 'PlatformDeployer', 'Dieterling',
    'Rorschach', 'ProjectorSol', 'ShipDeployer',
    'UmbraCloak',
}

#: Mount art this repo provides rather than the install. The game reaches it the
#: same way -- `mods/` is copied into the game directory whole, and the module
#: that needs it calls `sprite_add` on the copy -- so searching here first is
#: what makes the CLI draw what the game will draw.
MOD_ART = paths.REPO / 'mods'

#: ...and for the same reason the exe cache overrides `barrel_pivot()`, so does
#: this: the origin of a sprite this repo authored is not a thing to infer, it is
#: the argument `mods/umbracloak.gml` passes to `sprite_add`. The heuristic gets
#: this one within half a pixel, which is close enough to look right and wrong
#: enough that the preview and the game would not agree.
MOD_ORIGIN = {'spr_UmbraCloak': (7, 7)}
MODULE_GLOW = (34, 34, 255)

#: The sentinel every `nMod2` stat is tested against: `if argument4 != -1 then
#: l_hp = argument4`, and the same for cost, eng, engregen, range and all eight
#: specials. **(GML)** So `-1` is not "missing", it is *keep what the object's
#: own Create event set* -- and a module written entirely in `-1`s comes up with
#: exactly the stock stats. `initCustomWep` is only called when something was
#: overridden, so the deferring path is also the one the game does least on.
MODULE_KEEP = -1

#: What a module's own Create event sets, where it has been read out of a
#: *running game* rather than deferred to. Purely an override table: a module
#: absent from it is written in `-1`s and behaves stock, which is why
#: `add_module` no longer refuses one.
#:
#: An earlier note here claimed `nMod2` overrides the object's defaults rather
#: than deferring to them, and concluded that every module had to be measured
#: before it could be mounted. Half right, and the wrong half was load-bearing:
#: writing **zeros** does override (0 is not -1, so it assigns 0, and a
#: NanoMatrix with range 0 repairs nothing while looking like it works), but
#: writing `-1` defers. The rule is "never write a zero you did not mean",
#: not "never mount an unmeasured module" -- which had blocked Deflector and
#: AegisDeflector, the game's only two shield modules, from being mounted at all.
MODULE_DEFAULTS = {
    #                hp  range   eng  engregen  cost  special1..8
    'NanoMatrix': dict(hp=50, range=200, eng=500, engregen=0.40, cost=0.10,
                       special=(0.10, -1, -1, -1, -1, -1, -1, -1)),
}

#: Object name -> sprite file stem, where they differ. `Deflecctor` is
#: misspelled in the game itself.
TURRET_ALIAS = {
    'Deflector': 'spr_Deflecctor', 'ScatterBeam': 'spr_Scatter',
    'Sidewinder': 'spr_Sider', 'Plasma': 'spr_PlasmaBall',
    'Frosch': 'spr_FroschGun', 'GluonBolter': 'spr_Gluon',
    'Gravbeam': 'spr_GravBeam', 'DemeterPod': 'spr_DemeterPodLauncher',
    'PlatformDeployer': 'spr_Platformer', 'MiniMissile': 'spr_MiniMissileRack',
    'PointMaser': 'spr_Maser', 'PointRocket': 'spr_PDRocketPack',
    'ProjectorSol': 'spr_Projector',
}

#: Verified absent from disk -- these live only inside the encrypted gamedata.
#: Substituted with the nearest stand-in and always flagged, so a substitution is
#: never mistaken for the real art.
TURRET_SUBSTITUTE = {'Pulse': 'spr_Turret', 'Tesla': 'spr_Turret',
                     'Dieterling': 'spr_Projector'}

#: Drawn at every ship's origin, untinted; 10px across. The single most visible
#: thing missing if you only replay sections and turrets.
BRIDGE = 'spr_Bridge'

#: Fitted at 0 by diffing the ported renderer against a game screenshot of the
#: Hestia across -3..0 (Jaccard 0.46, zero translation). Kept as an escape hatch
#: because it was the one free parameter.
PIVOT_BIAS = float(os.environ.get('BSF_PIVOT_BIAS', 0))

#: Section masks hold exactly two tones under GM's transparency key. Snapping to
#: them keeps the edge highlight crisp under multiply rather than letting
#: resampling noise soften it.
MASK_FILL, MASK_EDGE, MASK_SPLIT = 47, 255, 140


# --------------------------------------------------------------------------
# team colours
# --------------------------------------------------------------------------

#: Fallback if the install is missing. Real values are read from bfdefault.ini.
_TEAMS_FALLBACK = {
    'player': [(0, 255, 0), (64, 255, 64), (128, 255, 128)],
    'allied': [(0, 255, 255), (64, 128, 128), (128, 196, 196)],
    'pirate': [(255, 0, 0), (255, 64, 64), (155, 45, 45)],
    'alien':  [(255, 0, 255), (128, 0, 255), (255, 128, 128)],
}

_INI_SECTIONS = {
    'player': 'Player Colours', 'allied': 'Allied Ship Colours',
    'pirate': 'Pirate Ship Colours', 'alien': 'Alien Ship Colours',
    'razor':  'Razor Alien Colours',
}


@functools.cache
def teams() -> dict[str, list[tuple[int, int, int]]]:
    """Team colours, three shades each, read from the game's own bfdefault.ini.

    A hull is never one flat colour: a section stores which shade it uses and
    sections that set nothing inherit shade 0 from the hull.
    """
    ini = GAME / 'bfdefault.ini'
    if not ini.exists():
        return dict(_TEAMS_FALLBACK)
    cp = configparser.ConfigParser()
    cp.read(ini)
    out: dict[str, list[tuple[int, int, int]]] = {}
    for key, section in _INI_SECTIONS.items():
        if section not in cp:
            continue
        shades = []
        for n in (1, 2, 3):
            try:
                shades.append((int(cp[section][f'{n}red']),
                               int(cp[section][f'{n}green']),
                               int(cp[section][f'{n}blue'])))
            except KeyError:
                break
        if shades:
            out[key] = shades
    return out or dict(_TEAMS_FALLBACK)


def gm_colour(value: float) -> tuple[int, int, int]:
    """A GM colour integer to RGB.

    Game Maker packs colours **BGR**, which is why `$FF2222` is a blue glow and
    not a red one. Verified against real data: `8454016` is `0x80FF80`, giving
    (128,255,128) -- exactly the player shade-2 from bfdefault.ini.

    The fractional part encodes the team shade (it mirrors the section's own
    `l_colourmod`) and is discarded here; the integer part is the literal colour
    ShipMaker draws, which is the view being modelled.
    """
    c = int(value)
    if c < 0:
        return (255, 255, 255)
    return (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF)


# --------------------------------------------------------------------------
# resolution
# --------------------------------------------------------------------------

def _find_stem(stem: str) -> pathlib.Path | None:
    for ext in ('.png', '.gif'):
        p = MOD_ART / (stem + ext)
        if p.exists():
            return p
    for folder in FOLDERS:
        for ext in ('.png', '.gif'):
            p = SPRITES / folder / (stem + ext)
            if p.exists():
                return p
    return None


def resolve(ref: str) -> pathlib.Path | None:
    """Resolve either a `.sb4` relative path or a GM sprite name to a file.

    `.sb4` names a file directly (`Kae_detail\\Kae_sec12.png`), Windows
    separators and all. `.shp` names a GM resource, and three conventions
    coexist there: `spr_SectionNN` is filed as `BSF_StockNN`, doodads drop the
    `spr_` prefix, and everything else matches its own name.
    """
    if not ref:
        return None
    if '\\' in ref or '/' in ref or ref.lower().endswith(('.png', '.gif')):
        p = SPRITES / ref.replace('\\', '/')
        return p if p.exists() else None

    m = re.match(r'spr_Section(\d+)$', ref)
    if m:
        p = SPRITES / 'Stock Sections' / f'BSF_Stock{int(m.group(1)):02d}.png'
        return p if p.exists() else None
    # `.sb4` weapon and module records name the bare stem (`PlasmaBall`,
    # `ParticleGun`), while the files carry the `spr_` prefix -- so try both
    # directions rather than only stripping it.
    return (_find_stem(ref)
            or (_find_stem(ref[4:]) if ref.startswith('spr_') else _find_stem('spr_' + ref)))


def resolve_turret(obj: str) -> tuple[pathlib.Path | None, str | None]:
    """(path, substitution_note) for a weapon object name."""
    stem = TURRET_ALIAS.get(obj, 'spr_' + obj)
    p = _find_stem(stem)
    if p is None and obj in TURRET_SUBSTITUTE:
        sub = TURRET_SUBSTITUTE[obj]
        p = _find_stem(sub)
        if p:
            return p, f'{obj}: no on-disk sprite (exe-only) — drawn as {sub}'
    return p, None


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

class Sprite:
    """Frames as RGBA arrays, plus the origin to rotate about."""

    __slots__ = ('frames', 'w', 'h', 'ox', 'oy', 'is_mask', 'path')

    def __init__(self, frames, ox, oy, is_mask, path):
        self.frames = frames
        self.h, self.w = frames[0].shape[:2]
        self.ox, self.oy = ox, oy
        self.is_mask = is_mask
        self.path = path

    @property
    def n(self) -> int:
        return len(self.frames)


def _frames_rgb(im: Image.Image) -> list[np.ndarray]:
    out = []
    for i in range(getattr(im, 'n_frames', 1)):
        im.seek(i)
        out.append(np.array(im.convert('RGB')))
    return out


def barrel_pivot(vis: np.ndarray) -> float:
    """Pixels from the left edge to a turret's rotation point.

    A turret sprite is a round base with a thin barrel off to the right, so the
    base is the run of tallest columns and its midpoint is the pivot. Measured
    against the game: Blaster 5.0px right of centre, GatBlaster and Turret 4.5,
    ParticleGun 2.5, the round Deflector 0.5 -- each within a pixel.
    """
    colh = vis.sum(axis=0)
    tall = np.where(colh >= colh.max() - 1)[0]
    if not len(tall):
        return vis.shape[1] / 2
    run = [tall[0]]
    for c in tall[1:]:
        if c != run[-1] + 1:
            break
        run.append(c)
    return (run[0] + run[-1]) / 2 + PIVOT_BIAS


@functools.lru_cache(maxsize=512)
def load(path_str: str, mask: bool, pivot: bool = False) -> Sprite:
    """Load a sprite, keyed and converted, with its origin resolved."""
    path = pathlib.Path(path_str)
    rgb_frames = _frames_rgb(Image.open(path))
    key = rgb_frames[0][-1, 0]                     # bottom-left pixel: GM's key
    out, first_vis = [], None
    for n, rgb in enumerate(rgb_frames):
        vis = np.any(rgb != key, axis=2)
        if n == 0:
            first_vis = vis
        if mask:
            v = np.where(rgb.mean(axis=2) > MASK_SPLIT, MASK_EDGE, MASK_FILL)
            rgb = np.dstack([v, v, v]).astype(np.uint8)
        rgba = np.zeros(rgb.shape[:2] + (4,), dtype=np.uint8)
        rgba[..., :3] = rgb
        rgba[..., 3] = vis * 255
        out.append(rgba)
    h, w = out[0].shape[:2]
    known = MOD_ORIGIN.get(path.stem) if path.parent == MOD_ART else None
    if known is not None:
        return Sprite(out, known[0], known[1], mask, path)
    ox = barrel_pivot(first_vis) if pivot else w / 2
    return Sprite(out, ox, h / 2, mask, path)


def get(ref: str, mask: bool = True, pivot: bool = False) -> Sprite | None:
    p = resolve(ref)
    return load(str(p), mask, pivot) if p else None


# --------------------------------------------------------------------------
# art recovered from the exe
# --------------------------------------------------------------------------
# The gamedata is not locked -- `exeart.py` decrypts the GM7 resource tree with
# the same gmkrypt inversion the mod patcher already relies on. That yields two
# things the exported files cannot:
#
#   * sprites that were never exported at all (every core shape past frame 0,
#     plus Tesla, Dieterling, Pulse, ThrusterEx), and
#   * the TRUE origin, which is a field in the record. `barrel_pivot()` exists
#     only because that field used to be unreachable; where the exe cache is
#     present the measurement wins and the heuristic is not consulted.
#
# Section art is deliberately NOT taken from here: `.sb4` names files under
# `Custom sprites/` directly, and those are the authored masks.

EXE_CACHE = pathlib.Path(__file__).resolve().parent / '.cache' / 'exeart'


@functools.cache
def exe_index() -> dict:
    p = EXE_CACHE / 'index.json'
    if not p.exists():
        return {}
    import json
    return json.loads(p.read_text())


def exe_frame_path(name: str, frame: int = 0) -> pathlib.Path | None:
    """The PNG for one frame of an exe sprite, matched case-insensitively."""
    idx = exe_index()
    if not idx:
        return None
    key = name if name in idx else next(
        (k for k in idx if k.lower() == name.lower()), None)
    if key is None:
        return None
    n = idx[key]['frames']
    if n <= 0:
        return None
    frame = max(0, min(frame, n - 1))
    p = EXE_CACHE / (f'{key}.png' if n == 1 else f'{key}_{frame:02d}.png')
    return p if p.exists() else None


@functools.lru_cache(maxsize=512)
def load_rgba(path_str: str, mask: bool) -> Sprite:
    """Load an already-keyed RGBA frame, preserving its alpha.

    Exe-extracted frames arrive with transparency resolved by Game Maker itself
    -- alpha is 0/255 and the `(0,128,64)` key is already invisible. Running them
    back through the bottom-left keying that `load()` applies to exported GIFs
    would throw that away and re-derive it, worse.
    """
    im = Image.open(path_str).convert('RGBA')
    a = np.array(im)
    if mask:
        rgb = a[..., :3]
        v = np.where(rgb.mean(axis=2) > MASK_SPLIT, MASK_EDGE, MASK_FILL)
        a[..., :3] = np.dstack([v, v, v]).astype(np.uint8)
    h, w = a.shape[:2]
    return Sprite([a], w / 2, h / 2, mask, pathlib.Path(path_str))


def get_exe(name: str, frame: int = 0, mask: bool = False) -> Sprite | None:
    """An exe-extracted sprite carrying its real origin from the resource tree."""
    p = exe_frame_path(name, frame)
    if p is None:
        return None
    idx = exe_index()
    key = name if name in idx else next(k for k in idx if k.lower() == name.lower())
    ox, oy = idx[key]['origin']
    sp = load_rgba(str(p), mask)
    return Sprite(sp.frames, float(ox), float(oy), mask, p)


def data_uri(sprite: Sprite) -> str:
    """Pack every frame into one horizontal RGBA strip as a data URI.

    This is what the browser canvas consumes -- the same pixels the PIL renderer
    blits, so the two backends cannot disagree about the source art.
    """
    h, w = sprite.h, sprite.w
    strip = np.zeros((h, w * sprite.n, 4), dtype=np.uint8)
    for i, f in enumerate(sprite.frames):
        strip[:, i * w:(i + 1) * w] = f
    buf = io.BytesIO()
    Image.fromarray(strip, 'RGBA').save(buf, format='PNG', optimize=True)
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def load_any(path_str: str, mask: bool, pivot: bool = False) -> Sprite:
    """Load by path, choosing the right decoder.

    Exe-extracted frames keep their own alpha; exported GIFs and PNGs need GM's
    bottom-left keying applied. Callers hold only a path, so the choice is made
    here rather than duplicated at every call site.
    """
    if str(EXE_CACHE) in path_str:
        return load_rgba(path_str, mask)
    return load(path_str, mask, pivot)


def best(name: str, mask: bool, pivot: bool = False):
    """(sprite, path, note) for a mount or core sprite, preferring exe art.

    The exe is authoritative: it has every frame and the true origin. Disk art
    is the fallback for anything the tree does not carry, and only then is the
    pivot heuristic used.
    """
    sp = get_exe(name, 0, mask)
    if sp is not None:
        return sp, sp.path, None
    path, note = resolve_turret(name)
    if path is None:
        path = resolve(name)
    if path is None:
        return None, None, None
    return load(str(path), mask, pivot), path, note

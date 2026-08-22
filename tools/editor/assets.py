#!/usr/bin/env python3
"""Sprites out of BattleshipsForever.exe, in memory, on demand.

Nothing is ever written to disk: the exe is decrypted into RAM at startup
(~50 ms for the whole 6.9 MB tree), sprite headers are indexed, and a frame is
only inflated and PNG-encoded the first time something asks for it. That keeps
derived game art out of the repo by construction — there is no file to commit.

GM 7.0 sprite record, verified against every sprite in the v0.90d tree:

    [u32 len][name][u32 542]
    [i32 w][i32 h]
    [i32 bbox_l][i32 bbox_r][i32 bbox_b][i32 bbox_t]
    [u32 transparent][u32 smooth][u32 preload][u32 bbox_mode][u32 precise]
    [i32 origin_x][i32 origin_y]            <-- data, never assume centred
    [u32 n_frames]
    n × ( [u32 540][u32 1][u32 w][u32 h][u32 len][zlib raw BGRA] )

Origins really do vary: spr_Rock is (24,24) on a 48×48, spr_MesHQ is (0,0).

Usage as a script (debug):  python3 assets.py [game-dir] [sprite-name]
"""
import os
import re
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # tools/, for gm7.py

SPRITE_VER = 542
FRAME_VER = 540
NAME_RE = re.compile(rb'^[A-Za-z_][A-Za-z0-9_]{2,40}$')

# The install is discovered, never hardcoded: an absolute path embeds whoever's
# account it was authored on. tools/bsf/paths.py is the module that answers this
# for the whole repo — $BSF_GAME, then $BSF_BASE, then a search near the
# checkout, validated by ShipMaker.exe — and it documents that nothing raises at
# import time, which is what makes it safe to read at module scope here.
#
# Not campaign/build.py, which resolves the same two directories: that is the
# YAML mission compiler, it needs PyYAML, and it sys.exit()s at import when
# PyYAML is absent. A sprite reader that decrypts the exe has no business
# failing over a missing YAML parser.
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'bsf'))
import paths                                                        # noqa: E402

INSTALL = str(paths.GAME)
RESEARCH = str(paths.GAME.parent)


def u32(b, p):
    return struct.unpack_from('<I', b, p)[0]


def i32(b, p):
    return struct.unpack_from('<i', b, p)[0]


def png_encode(w, h, bgra):
    """BGRA rows -> PNG bytes. Channel swap by stride slicing, not per pixel."""
    a = bytearray(bgra)
    a[0::4], a[2::4] = a[2::4], a[0::4]
    stride = w * 4
    raw = bytearray()
    for y in range(h):
        raw.append(0)                       # filter: none
        raw += a[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data
                + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(raw), 6))
            + chunk(b'IEND', b''))


def is_palette_mask(bgra):
    """Section art is a 3-shade grey mask the game multiplies by the team colour.
    Drawn naively it is a black box, so the client has to know which is which.
    Strided slices, not a per-pixel loop — this runs over every sprite at start."""
    return bgra[0::4] == bgra[1::4] == bgra[2::4]


class Library:
    """Sprite index over a decrypted tree. Headers eagerly, pixels lazily."""

    def __init__(self, tree):
        self.tree = tree
        self.sprites = {}
        self._png = {}
        self._scan()

    @classmethod
    def from_game(cls, game_dir=None):
        import gm7
        d = os.path.expanduser(game_dir) if game_dir else INSTALL
        exe = os.path.join(d, 'BattleshipsForever.exe')
        if not os.path.exists(exe):
            raise FileNotFoundError(
                f'BattleshipsForever.exe not found at {exe} — point $BSF_GAME '
                'at a v0.90d install, or put one beside this checkout')
        _raw, (_pos, _clen, blob) = gm7.load(exe)
        plain, *_ = gm7.gmkrypt_decrypt(blob)
        lib = cls(plain)
        lib.source = exe
        return lib

    def _scan(self):
        b = self.tree
        marker = struct.pack('<I', SPRITE_VER)
        pos = 0
        while True:
            hit = b.find(marker, pos)
            if hit < 0:
                break
            pos = hit + 4
            for n in range(3, 42):                       # walk back over the name
                start = hit - n - 4
                if start < 0:
                    break
                if u32(b, start) != n:
                    continue
                name = b[start + 4:start + 4 + n]
                if not NAME_RE.match(name):
                    break
                try:
                    rec = self._parse(hit + 4, name.decode())
                except (struct.error, ValueError):
                    rec = None
                if rec:
                    self.sprites[rec['name']] = rec
                break

    def _parse(self, p, name):
        b = self.tree
        w, h = i32(b, p), i32(b, p + 4)
        if not (0 < w <= 4096 and 0 < h <= 4096):
            return None
        p += 8 + 16 + 20                                  # bbox (4) + flags (5)
        ox, oy = i32(b, p), i32(b, p + 4)
        p += 8
        nframes = u32(b, p)
        p += 4
        if not (0 < nframes <= 512):
            return None
        frames = []
        for _ in range(nframes):
            if u32(b, p) != FRAME_VER:
                return None
            p += 8                                        # frame version + flag
            fw, fh, ln = u32(b, p), u32(b, p + 4), u32(b, p + 8)
            p += 12
            if fw != w or fh != h or not (0 < ln <= len(b) - p):
                return None
            frames.append((p, ln))
            p += ln
        return {'name': name, 'w': w, 'h': h, 'ox': ox, 'oy': oy,
                'n': nframes, 'frames': frames, 'mask': None}

    # ---------------------------------------------------------------- output
    def bgra(self, name, frame=0):
        s = self.sprites[name]
        off, ln = s['frames'][frame % s['n']]
        d = zlib.decompress(self.tree[off:off + ln])
        if len(d) != s['w'] * s['h'] * 4:
            raise ValueError(f'{name}: frame {frame} is not {s["w"]}x{s["h"]} BGRA')
        return d

    def png(self, name, frame=0):
        key = (name, frame)
        if key not in self._png:
            s = self.sprites[name]
            d = self.bgra(name, frame)
            if s['mask'] is None:
                s['mask'] = is_palette_mask(d)
            self._png[key] = png_encode(s['w'], s['h'], d)
        return self._png[key]

    def classify(self):
        """Decide mask-vs-colour for every sprite (frame 0 only). Needed before
        the client draws anything, so it is worth the one-off inflate."""
        for nm, s in self.sprites.items():
            if s['mask'] is None:
                try:
                    s['mask'] = is_palette_mask(self.bgra(nm, 0))
                except Exception:                                    # noqa: BLE001
                    s['mask'] = False
        return self

    def manifest(self):
        return {nm: {'w': s['w'], 'h': s['h'], 'ox': s['ox'], 'oy': s['oy'],
                     'n': s['n'], 'mask': s['mask']}
                for nm, s in self.sprites.items()}


# --------------------------------------------------------------------------
# object -> sprite name. The object record carries a sprite *index*, and index
# order is not file order (see tools/gmobj.py), so resolving it from the exe
# alone means walking both sections properly. The runtime dump the game itself
# writes already has the answer, so the prototype reads that when it is there
# and falls back to the handful EP9 needs.
# --------------------------------------------------------------------------
RT_DUMP = os.path.join(INSTALL, 'mods', 'objects_rt.txt')

FALLBACK_OBJ_SPRITE = {
    'Hestia': 'spr_Core', 'SpaceStation': 'spr_Spacestation', 'ter_Planet': 'spr_Planet',
    'ter_Nebula': 'spr_Nebula', 'ter_MegaNebula': 'spr_Nebula', 'ter_Rock': 'spr_Rock',
    'ter_Sun': 'spr_Sun', 'obs_Meteor': 'spr_Meteor', 'MoveToArea': 'spr_Marker',
    'Marker': 'spr_Marker', 'Civilian': 'spr_Civilian', 'EPirate06': 'spr_Pirate',
}


def object_sprites(path=RT_DUMP):
    out = dict(FALLBACK_OBJ_SPRITE)
    if os.path.exists(path):
        for ln in open(path, encoding='latin-1'):
            m = re.match(r'\s*\d+\s+(\S+)\s+sprite=(-?\d+)\s+(\S+)', ln)
            if m and m.group(3) != '-':
                out[m.group(1)] = m.group(3)
    return out


# Ship hulls are not in the exe in any readable form (the built-in designs stay
# locked); the render-model dump in the research tree carries section geometry
# plus its own sprites, so a real hull can be drawn when that dump is present.
SHIP_HTML = os.path.join(RESEARCH, 'dump', 'ship_html')


def _hull_index(root=SHIP_HTML):
    """Squashed hull-dump name -> file.

    The dump is named for the *design* ("Space Station.html"), the mission names
    the *object* (`SpaceStation`), and nothing carries the mapping. Squashing
    both to lowercase letters and digits resolves the mechanical ones —
    SpaceStation, BattleStation, HestiaAlpha, MoiraX, OenoneDelta — which is
    every station and every ship variant EP9 can spawn. The rest (a platform
    with no object of its own, "Major Hong s Ship") have no object name to match
    and fall back to the object's sprite, as before.
    """
    out = {}
    if not os.path.isdir(root):
        return out
    for f in os.listdir(root):
        if f.endswith('.html') and f != 'index.html':
            out[re.sub(r'[^a-z0-9]', '', f[:-5].lower())] = os.path.join(root, f)
    return out


_HULLS = None


def _hull_path(name):
    """Where `name`'s hull dump is, or '' if it has none.

    Two steps: the dump named for the object exactly, then the squashed index.
    Both `ship()` and `hull_objects()` ask through here rather than each
    spelling the rule out, because they must agree — `hull_objects()` is what
    tells the editor to draw something as a ship, and `ship()` is what has to
    serve the hull when it does. Two transcriptions of the fallback is one
    chance for the editor to offer a hull thumbnail that then 404s.
    """
    global _HULLS
    if _HULLS is None:
        _HULLS = _hull_index()
    p = os.path.join(SHIP_HTML, name.replace(' ', '_') + '.html')
    if os.path.exists(p):
        return p
    p = _HULLS.get(re.sub(r'[^a-z0-9]', '', name.lower()), '')
    return p if p and os.path.exists(p) else ''


def hull_objects(names):
    """Which of `names` are ships rather than props.

    The distinction the editor needs up front. An object's `sprite_index` does
    not carry it: every stock hull's is `spr_Core`, the core section, because a
    ship draws its sections and never its own sprite — so the sprite manifest
    alone makes the Hestia, the Athena and a hundred others indistinguishable
    from each other and describes none of them. Having the hull is the test.
    """
    return sorted(n for n in names if _hull_path(n))


def ship(name):
    import json
    p = _hull_path(name)
    if not p:
        return None
    s = open(p, encoding='utf-8').read()
    def grab(const):
        m = re.search(r'const %s\s*=\s*(\{.*?\});\s*\n' % const, s, re.S)
        return json.loads(m.group(1)) if m else None
    sh, sp = grab('SHIP'), grab('SPRITES')
    if not sh or not sp:
        return None
    sh['sprites'] = sp
    return sh


def main():
    game = sys.argv[1] if len(sys.argv) > 1 else None
    lib = Library.from_game(game)
    print(f'{len(lib.sprites)} sprites from {lib.source}')
    if len(sys.argv) > 2:
        nm = sys.argv[2]
        s = lib.sprites[nm]
        png = lib.png(nm)
        print(f'{nm}: {s["w"]}x{s["h"]} origin=({s["ox"]},{s["oy"]}) frames={s["n"]} '
              f'mask={s["mask"]} png={len(png)}B')
    else:
        for nm in ['spr_Rock', 'spr_Nebula', 'spr_Spacestation', 'spr_Planet',
                   'spr_Meteor', 'spr_Marker', 'spr_MesHQ', 'spr_Section01']:
            if nm in lib.sprites:
                s = lib.sprites[nm]
                lib.png(nm)
                print(f'  {nm:20s} {s["w"]:>4}x{s["h"]:<4} origin=({s["ox"]},{s["oy"]})'
                      f' frames={s["n"]:<3} mask={s["mask"]}')


if __name__ == '__main__':
    main()

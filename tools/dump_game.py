#!/usr/bin/env python3
"""Launch Battleships Forever under wine and dump everything recoverable from
its address space: ship definitions, all GML, and any embedded images.

Game Maker 7 keeps GML as source text and compiles it at load, so once the game
settles at its menu the whole game's logic is present as plain text. Reading
/proc/<pid>/mem requires the game to be a descendant of this process (yama
ptrace_scope=1 allows that without privilege), hence the launch happens here.
"""
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game                                                # noqa: E402

# The game directory, the wine prefix, the exe name and the process scan all
# belong to game.py -- including the cwd filter that keeps this from killing a
# sibling checkout's run, which a name-only scan here used to get wrong.
OUT = os.path.join(os.path.dirname(game.BASE), 'dump')

#: Maximal printable runs at least this long are candidate GML fragments.
MIN_RUN = 120
RUN = re.compile(rb'[\t\r\n\x20-\x7e]{%d,}' % MIN_RUN)
#: A fragment is GML if it mentions any of these.
GML_HINT = (b'event_inherited', b'instance_', b'draw_', b'var ', b'with(', b'global.',
            b'sprite_index', b'point_direction', b'l_hp', b'if ', b'else', b'return ')
#: A fragment defines a ship if it builds sections.
SHIP_HINT = (b'nSec(', b'initSections', b'ShipSection')
#: Worth keeping if it looks like either.
KEEP_HINT = GML_HINT + SHIP_HINT
BMP_HEAD = b'\x00\x00\x00\x00\x36\x00\x00\x00\x28\x00\x00\x00'


def launch_and_settle():
    """Start the game and return its pid once memory use stops growing."""
    game.stop()
    subprocess.Popen(['wine', game.EXE], cwd=game.GAME_DIR, env=game.env(),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, start_new_session=True)
    last, stable = -1, 0
    for i in range(48):
        time.sleep(5)
        cand = [(p, r) for p, r in game.running() if r > 100_000]
        if not cand:
            continue
        pid, rss = cand[0]
        stable = stable + 1 if rss == last else 0
        last = rss
        print(f't={i*5+5}s pid={pid} rss={rss}kB stable={stable}', flush=True)
        if stable >= 3:
            return pid, last
    return None, last


def regions(pid):
    """Yield each readable mapping's bytes."""
    mem = open(f'/proc/{pid}/mem', 'rb', 0)
    for line in open(f'/proc/{pid}/maps'):
        f = line.split()
        if 'r' not in f[1]:
            continue
        lo, hi = (int(x, 16) for x in f[0].split('-'))
        if hi - lo > 512 * 1024 * 1024:
            continue
        try:
            mem.seek(lo)
            yield lo, mem.read(hi - lo)
        except OSError:
            continue


def main() -> int:
    pid, rss = launch_and_settle()
    if pid is None:
        print('game never settled; last rss', rss)
        return 1
    print(f'target pid {pid}, rss {rss} kB\n')

    frags = set()
    bmps = []
    # PNG/GIF are only ever reported as a count, so they are counted, not located.
    counts = {'PNG': 0, 'GIF': 0}
    scanned = 0
    for lo, buf in regions(pid):
        scanned += 1
        for m in RUN.finditer(buf):
            s = m.group()
            if any(k in s for k in KEEP_HINT):
                frags.add(s)
        i = 0
        while True:
            i = buf.find(b'BM', i)
            if i < 0:
                break
            if buf[i + 6:i + 18] == BMP_HEAD:
                bmps.append((lo + i, int.from_bytes(buf[i+2:i+6], 'little')))
            i += 2
        for sig, key in ((b'\x89PNG\r\n\x1a\n', 'PNG'), (b'GIF89a', 'GIF'), (b'GIF87a', 'GIF')):
            counts[key] += buf.count(sig)
    print(f'scanned {scanned} regions, {len(frags)} unique text fragments')

    os.makedirs(OUT, exist_ok=True)
    ships_dir = os.path.join(OUT, 'ships')
    os.makedirs(ships_dir, exist_ok=True)

    ships = [s for s in frags if any(k in s for k in SHIP_HINT)]
    # Longest first, so a full script wins over a truncated copy of itself.
    ships.sort(key=len, reverse=True)

    named: dict[str, bytes] = {}
    unnamed = 0
    for s in ships:
        m = re.search(rb'l_name\s*=\s*"([^"]{1,40})"', s)
        if m:
            key = m.group(1).decode('latin1').strip() or 'unnamed'
        else:
            unnamed += 1
            key = f'_unnamed{unnamed:03d}'
        if key not in named or len(s) > len(named[key]):
            named[key] = s
    for key, s in named.items():
        safe = re.sub(r'[^A-Za-z0-9_.-]', '_', key)
        open(os.path.join(ships_dir, f'{safe}.shp'), 'wb').write(s)

    sep = b'\n\n// ==== fragment ====\n\n'
    allgml = sorted(frags, key=len, reverse=True)
    open(os.path.join(OUT, 'all_gml.txt'), 'wb').write(sep.join(allgml))

    print(f'\nship-building fragments: {len(ships)}  -> {len(named)} named files')
    for key in sorted(named):
        s = named[key]
        print(f'  {key:28} {len(s):>6}B nSec={s.count(b"nSec(")} nTur={s.count(b"nTur(")}')
    print(f'\nall GML -> {os.path.join(OUT, "all_gml.txt")} '
          f'({sum(len(x) for x in allgml)} bytes, {len(allgml)} fragments)')
    print('images found in memory:', dict(BMP=len(bmps), **counts))
    big = [(a, n) for a, n in bmps if n > 2000]
    print(f'  BMPs with plausible size: {len(big)}')
    if big:
        os.makedirs(os.path.join(OUT, 'bmp'), exist_ok=True)
        open(os.path.join(OUT, 'bmp', 'index.txt'), 'w').write(
            '\n'.join(f'0x{a:x} {n}' for a, n in big))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

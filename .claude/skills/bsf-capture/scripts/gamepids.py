#!/usr/bin/env python3
"""List (or kill) the wine game processes, without the pgrep self-match trap.

`pgrep -f BattleshipsForever` matches the shell running it, because the pattern
appears in that shell's own command line -- so `kill $(pgrep -f ...)` kills the
caller. This walks /proc instead and excludes this process and its ancestors,
which cannot match by construction.

    gamepids.py            list
    gamepids.py --kill     SIGTERM each
"""
import os
import signal
import sys

SELF = {os.getpid(), os.getppid()}


def ancestors(pid):
    out = set()
    while pid and pid > 1:
        out.add(pid)
        try:
            with open(f'/proc/{pid}/stat') as f:
                pid = int(f.read().rsplit(') ', 1)[1].split()[1])
        except OSError:
            break
    return out


def game_pids():
    skip = ancestors(os.getpid()) | SELF
    found = []
    for d in os.listdir('/proc'):
        if not d.isdigit():
            continue
        pid = int(d)
        if pid in skip:
            continue
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                argv = f.read().split(b'\0')
        except OSError:
            continue
        if not argv or not argv[0]:
            continue
        # argv[0] is the executable itself, never a shell quoting the name.
        if os.path.basename(argv[0].decode('latin-1', 'replace')).lower() \
                .startswith('battleshipsforever'):
            found.append((pid, b' '.join(a for a in argv if a).decode('latin-1', 'replace')))
    return found


if __name__ == '__main__':
    pids = game_pids()
    for pid, cmd in pids:
        print(pid, cmd[:90])
    if '--kill' in sys.argv:
        for pid, _ in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        print(f'sent SIGTERM to {len(pids)}')
    if not pids:
        print('(none)')

#!/usr/bin/env python3
"""Run Battleships Forever under wine.

    game.py run            launch and leave it running
    game.py stop           stop it
    game.py diag           launch with DLL logging, wait, stop, report failures

Lives in a file rather than a shell one-liner on purpose: `pkill -f` / `pgrep -f`
match against full command lines including the caller's own, so naming the exe in
a shell command makes the caller kill itself (exit 144).
"""
import glob
import os
import signal
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
GAME_DIR = os.path.join(BASE, 'battleshipsforeverv090d')
PREFIX = os.path.join(BASE, 'wineprefix')
EXE = 'Battleships' + 'Forever.exe'
LOG = '/tmp/bsf_run.log'


def env(winedebug='-all'):
    # WINEDLLOVERRIDES_EXTRA lets a caller add overrides without editing this
    # file -- e.g. `d3d8=n,b` to prefer the d3d8to9 shim sitting next to the exe
    # over wine's builtin d3d8.
    overrides = 'mscoree,mshtml='
    extra = os.environ.get('WINEDLLOVERRIDES_EXTRA', '').strip()
    if extra:
        overrides += ';' + extra
    return dict(os.environ, WINEPREFIX=PREFIX, WINEARCH='win32',
                WINEDLLOVERRIDES=overrides, WINEDEBUG=winedebug, DISPLAY=':0')


def game_procs():
    """(pid, cwd, rss_kB) for every game process on the box except this one.

    ⚠ The name match alone is not enough. Sibling copies of the game directory
    can be running at the same time -- e.g. `battleshipsforeverv090d-dll/`,
    `battleshipsforeverv090d-hud/` -- and every one of them is a process called
    `BattleshipsForever.exe`. A name-only scan sees those too, so `stop()` would
    kill their runs, which to them look like the game simply exited. The cwd is
    what distinguishes them, because each copy is launched with `cwd=` its own
    directory -- hence cwd is reported here and every caller filters on it.
    """
    me = os.getpid()
    for d in glob.glob('/proc/[0-9]*'):
        pid = int(d.rsplit('/', 1)[-1])
        if pid == me:
            continue
        try:
            if EXE.encode() not in open(d + '/cmdline', 'rb').read():
                continue
            cwd = os.path.realpath(os.readlink(d + '/cwd'))
            rss = 0
            for line in open(d + '/status'):
                if line.startswith('VmRSS'):
                    rss = int(line.split()[1])
        except (OSError, ValueError):
            continue
        yield pid, cwd, rss


def running():
    """Game processes belonging to THIS checkout."""
    mine = os.path.realpath(GAME_DIR)
    return [(pid, rss) for pid, cwd, rss in game_procs() if cwd == mine]


def foreign():
    """Game processes from a SIBLING copy -- reported, never killed."""
    mine = os.path.realpath(GAME_DIR)
    return [(pid, cwd) for pid, cwd, _ in game_procs() if cwd != mine]


def stop():
    """Stop this checkout's game, and nothing else.

    ⚠ `wineserver -k` is NOT used at all any more. The wine PREFIX is shared
    across every copy of the game directory, so `-k` kills every wine process in
    it -- including a sibling checkout's game -- and to it that looks like its run
    simply exited. Guarding it on "no sibling is running right now" is not enough:
    that sample and the kill are not atomic, so a sibling launching in between
    still dies. SIGTERM then SIGKILL on our own pids is sufficient for every case
    this function actually needs to handle; a genuinely wedged wineserver is rare
    and is better dealt with deliberately than as a side effect of `stop()`.
    """
    others = foreign()
    for sig, pause in ((signal.SIGTERM, 2), (signal.SIGKILL, 1)):
        for pid, _ in running():
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        time.sleep(pause)
    msg = 'stopped; %d left' % len(running())
    if others:
        msg += '  (left %d sibling-copy process(es) alone: %s)' % (
            len(others), ', '.join('%d@%s' % (p, os.path.basename(c)) for p, c in others))
    print(msg)


def launch(winedebug='-all', desktop=None):
    """Start the game.

    Windowing comes from the prefix's registry virtual desktop
    (HKCU\\Software\\Wine\\Explorer), so the plain `wine EXE` path is correct and
    is what `desktop=None` does. Passing a size instead routes through
    `wine explorer /desktop=`, which windows it too but makes the game stall at
    ~78 MB RSS and never finish loading — kept only for comparison.
    """
    log = open(LOG, 'wb')
    cmd = ['wine', 'explorer', f'/desktop=bsf,{desktop}', EXE] if desktop else ['wine', EXE]
    subprocess.Popen(cmd, cwd=GAME_DIR, env=env(winedebug),
                     stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                     start_new_session=True)
    for i in range(15):
        time.sleep(3)
        r = [(p, s) for p, s in running() if s > 50_000]
        if r:
            print(f't={i*3+3}s pid={r[0][0]} rss={r[0][1]}kB')
            if r[0][1] > 200_000:
                return r[0][0]
    r = running()
    print('procs:', r)
    return r[0][0] if r else None


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else 'run'
    if mode == 'stop':
        stop()
        return 0
    stop()
    if mode == 'diag':
        launch('+loaddll')
        time.sleep(5)
        stop()
        data = open(LOG, 'rb').read().decode('latin1', 'replace').splitlines()
        bad = [l for l in data if any(k in l.lower() for k in
                                     ('failed', 'err:', 'cannot', 'unable', 'not found'))]
        print(f'\n--- {len(bad)} problem lines (first 25) ---')
        for l in bad[:25]:
            print('  ', l[:200])
        local = [l for l in data if any(k in l.lower() for k in
                 ('bass', 'bgm', 'winapi', 'screencapture', 'tinyweb'))]
        print(f'\n--- {len(local)} lines mentioning the bundled DLLs (first 15) ---')
        for l in local[:15]:
            print('  ', l[:200])
        return 0
    # Optional 2nd arg forces the (broken) explorer-desktop route for comparison.
    size = sys.argv[2] if len(sys.argv) > 2 else None
    pid = launch(desktop=size)
    print('running' if pid else 'did not start', '- log:', LOG)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

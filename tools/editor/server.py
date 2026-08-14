#!/usr/bin/env python3
"""Mission editor — the dev server.

    python3 tools/editor/server.py                 # serve, open a browser
    python3 tools/editor/server.py --no-open       # just serve
    python3 tools/editor/server.py --port 8778
    python3 tools/editor/server.py --res 2560x1440 # the game's window
    python3 tools/editor/server.py --fullscreen    # give the game the monitor
    python3 tools/editor/server.py --host '*'        # everything, v4 and v6
                                   --host tailscale | lan | <address>

It binds loopback unless told otherwise, and that default is deliberate: this
process launches the game, reads the exe and writes mission files, so a machine
that can reach the port can do all three. `*` binds a dual-stack wildcard, so
loopback, LAN and tailnet answer from one socket; `--host tailscale` binds the
tailnet address and nothing else, for when the LAN is not somewhere you want it.

The editor is a browser app; this is everything it cannot do from a page. It owns
the four things that touch the machine:

  * **the game art** — BattleshipsForever.exe is decrypted into RAM at startup and
    sprite frames are inflated on demand. Nothing derived from the game is ever
    written to disk, which is not politeness: it is what keeps extracted art out
    of the repository by construction. There is no file to commit by accident.
  * **the compiler** — campaign/build.py, imported rather than shelled out to, so
    the editor lints with exactly the rules that will reject the build. Imported
    means held in RAM, so an edit to it is invisible to a long-running server;
    reload_changed() below is what keeps that from being true.
  * **the install** — the built mod is copied into the live game directory.
  * **the wine process and the command channel** — mods/edit/cmd in, ack, state
    and dump back out. See mods/editor.gml for the grammar.

Apply is explicit and is also save (DESIGN.md decision 8): the client posts the
YAML its own model round-tripped to, the server lints it, and only a clean lint
gets written. The game therefore never runs something that is not on disk.

⚠ Commands are written to a temporary file and renamed over mods/edit/cmd. The
game polls that path once a step; a poll landing mid-write would read half a
command, and half a command is a GM7 syntax error, which is silent.
"""
import atexit
import http.server
import importlib
import json
import os
import re
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(TOOLS)
APP = os.path.join(HERE, 'app')

sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(REPO, 'campaign'))
# tools/bsf: the ship model and the draw list. The map draws a ship design from
# the same scene the PIL renderer and `ship serve` consume, so the three cannot
# disagree about geometry — only sprite *bytes* come from the editor's own
# in-RAM reader, which is what keeps this process writing nothing to disk.
sys.path.insert(0, os.path.join(TOOLS, 'bsf'))

import assets as A                                                   # noqa: E402
import build as B                     # campaign/build.py             # noqa: E402

INSTALL = B.INSTALL
EDIT = os.path.join(INSTALL, 'mods', 'edit')

LIB = None                            # assets.Library, or None with no game
OBJ_SPRITES = {}
SHIPS = {}
GAME = None                           # --game, kept so a reload can rebuild art


# ---------------------------------------------------------------------------
# picking up our own edits
# ---------------------------------------------------------------------------

# This server is long-lived and imports its dependencies rather than shelling
# out to them, so an edit to campaign/build.py sits unseen in this process until
# someone restarts it. That is not hypothetical: a save once failed with
# KeyError: 'object' for five hours because the running server held a build.py
# from before the fix, while the same build from the command line was clean —
# the worst kind of bug, one where the evidence on disk exonerates the code.
#
# Restarting on change is the wrong cure. This process owns the command channel
# to a running game, the display settings it borrowed from the player, and 503
# sprites read out of the exe; dropping all of that to pick up a one-line edit
# costs more than it saves. So reload the changed module, and only that one.

SELF = os.path.abspath(__file__)
_MTIMES = {}
_RELOAD = threading.Lock()

# assets.py and build.py both derive INSTALL and RESEARCH from paths.GAME at
# import, and a value read at import stays read: reloading paths alone would
# leave them pointing at the old install. What needs naming here is a *copied
# value*, not an import — `import x as X` re-binds itself, `Y = x.thing` does
# not.
DEPENDENTS = {'paths': ['assets', 'build']}


def reloadable():
    """Imported modules whose source lives in this repo, in import order.

    Import order is dependency order, which is the order a reload wants: a
    module is re-executed after the ones it imports, not before.
    """
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, '__file__', None) or ''
        # __main__ is this file. A process cannot reload the module it is
        # running — re-executing it would re-enter main() — so it is warned
        # about instead, below.
        if name != '__main__' and f.endswith('.py') and f.startswith(REPO + os.sep):
            yield name, mod, f


def reload_changed():
    """Re-import repo modules whose file changed, before serving an API request.

    Returns the names reloaded. A module's recorded mtime advances only after a
    successful reload, so a file saved mid-edit with a syntax error is retried
    on the next request rather than being written off as done; the exception
    reaches the client as the 500 body, which is where the author is looking.
    """
    with _RELOAD:
        # Snapshotted once, not walked twice. The docstring's "import order is
        # dependency order" only holds if both passes see the same table in the
        # same order, and a lazily-imported module appearing between two walks
        # would break exactly that — it would be reloaded without ever having
        # had an mtime recorded. One list makes the invariant structural.
        mods = list(reloadable())
        stale = []
        for name, _mod, f in mods:
            try:
                mt = os.stat(f).st_mtime_ns
            except OSError:                       # deleted under us; nothing to do
                continue
            if _MTIMES.setdefault(name, mt) != mt:
                stale.append(name)
        for name in list(stale):
            stale += [d for d in DEPENDENTS.get(name, []) if d in sys.modules
                      and d not in stale]

        done = []
        for name, mod, f in mods:
            if name not in stale:
                continue
            importlib.reload(mod)                 # raises: see the docstring
            _MTIMES[name] = os.stat(f).st_mtime_ns
            done.append(name)

        if done:
            print('reloaded: ' + ', '.join(done))
            rebind(done)

        mt = os.stat(SELF).st_mtime_ns
        if _MTIMES.setdefault(SELF, mt) != mt:
            _MTIMES[SELF] = mt
            print('server.py changed on disk — restart to pick it up; this is '
                  'the one file the reload above cannot cover')
        return done


def rebind(done):
    """Refresh the state a reloaded module leaves behind.

    Reload rebinds a module's contents but not what was built out of them: a
    value copied at import is still the old value, and an instance of a class
    the reload replaced still runs the old code.
    """
    global INSTALL, EDIT
    if 'build' in done:
        INSTALL = B.INSTALL
        EDIT = os.path.join(INSTALL, 'mods', 'edit')
    if 'assets' in done:
        load_art()                        # LIB is an instance of the old class


def load_art():
    """Read the sprite library out of the game exe into RAM.

    Nothing is written to disk — see the module docstring. Cheap enough (tens of
    milliseconds) that a reload can afford to redo it rather than reason about
    which half of the library the edit invalidated.
    """
    global LIB, OBJ_SPRITES
    try:
        t0 = time.time()
        LIB = A.Library.from_game(GAME).classify()
        OBJ_SPRITES = A.object_sprites()
        SHIPS.clear()
        masks = sum(1 for s in LIB.sprites.values() if s['mask'])
        print(f'art: {len(LIB.sprites)} sprites in memory from '
              f'{os.path.basename(LIB.source)} in {time.time() - t0:.2f}s '
              f'({masks} palette masks, {len(OBJ_SPRITES)} object bindings)')
    except Exception as e:                                           # noqa: BLE001
        LIB, OBJ_SPRITES = None, {}
        print(f'art: unavailable ({e}) — the map falls back to vector shapes')


# ---------------------------------------------------------------------------
# missions
# ---------------------------------------------------------------------------

def mission_files():
    d = B.MISSIONS
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d) if f.endswith('.yaml'))


def mission_list():
    """Act II YAML missions only. Act I is stock GML in the exe with no source,
    no seek ladder and no editor flags, so it is not listed at all — when one is
    transcribed it becomes an ordinary Act II mission and appears like any other."""
    out = []
    for f in mission_files():
        try:
            m = B.yaml.safe_load(open(os.path.join(B.MISSIONS, f), encoding='utf-8'))
        except Exception as e:                                       # noqa: BLE001
            out.append({'stem': f[:-5], 'error': str(e)})
            continue
        out.append({'stem': f[:-5], 'id': m.get('id'), 'episode': m.get('episode'),
                    'mission': m.get('mission'), 'title': m.get('title'),
                    'beats': len(m.get('beats') or [])})
    return out


def _split_comment(line):
    """(code, comment) for one YAML line, honouring quotes.

    `#` is the DSL's own line-break character and appears inside dialogue —
    `text: "Follow the Ratlines# #Reach each beacon"` — so a naive split would
    saw a mission's prose in half.
    """
    q = None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
            continue
        if ch in '"\'':
            q = ch
            continue
        if ch == '#' and (i == 0 or line[i - 1].isspace()):
            return line[:i].rstrip(), line[i:]
    return line.rstrip(), None


def _key_of(line):
    code = line.rstrip()
    if not code.strip() or code.lstrip().startswith('-'):
        return None
    indent = len(code) - len(code.lstrip())
    name = code.strip().split(':', 1)[0]
    return (indent, name) if ':' in code else None


def reattach_comments(old, new):
    """Carry the hand-written comments of `old` onto the regenerated `new`.

    A writer built from a parsed model cannot preserve comments, and the ones in
    a mission file are not decoration: ep9.yaml records that its narrative is the
    V1 voice, that `damage: 0.55` means the ship arrives hurt, and that the gates
    are called the Ratlines. None of that is derivable from the model, so none of
    it can be regenerated — it has to be carried.

    Comments are matched by (indent, key), not by line text, so a note survives
    its value changing. Anything whose key is ambiguous — `x:` occurs dozens of
    times — is dropped rather than guessed at.
    """
    old_lines = old.splitlines()
    header, i = [], 0
    while i < len(old_lines) and (not old_lines[i].strip() or old_lines[i].lstrip().startswith('#')):
        header.append(old_lines[i])
        i += 1
    while header and not header[-1].strip():
        header.pop()

    trailing, blocks, seen, pending = {}, {}, {}, []
    for line in old_lines[i:]:
        if line.lstrip().startswith('#'):
            pending.append(line)
            continue
        if not line.strip():
            pending = []
            continue
        k = _key_of(line)
        if k:
            seen[k] = seen.get(k, 0) + 1
            _code, com = _split_comment(line)
            if com:
                trailing[k] = com
            if pending:
                blocks[k] = pending
        pending = []

    new_lines = new.splitlines()
    n_seen = {}
    for line in new_lines:
        k = _key_of(line)
        if k:
            n_seen[k] = n_seen.get(k, 0) + 1
    ok = {k for k in seen if seen[k] == 1 and n_seen.get(k) == 1}

    out, started = [], False
    for line in new_lines:
        if not started:
            # the regenerated header is replaced wholesale by the original one
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            out.extend(header)
            out.append('')
            started = True
        k = _key_of(line)
        if k in ok:
            if k in blocks:
                # The writer emits its own canonical block for keys like `zones`.
                # The file's own words are better, so drop the generated one
                # rather than stack two paragraphs saying the same thing.
                while out and out[-1].lstrip().startswith('#'):
                    out.pop()
                out.extend(blocks[k])
            if k in trailing:
                code, _ = _split_comment(line)
                out.append(code.ljust(22) + trailing[k].strip())
                continue
        out.append(line)
    return '\n'.join(out) + '\n'


def lint_text(text, src):
    """Parse and lint without writing anything. Returns (mission, errors, warnings).

    The emitter is run for its side effects — it is the only thing that knows
    which resource names and which quoting a beat will actually produce.
    """
    try:
        m = B.yaml.safe_load(text)
    except Exception as e:                                           # noqa: BLE001
        return None, [f'yaml: {e}'], []
    if not isinstance(m, dict) or 'beats' not in m:
        return None, ['not a mission: no beats'], []
    m['_src'] = src
    lint = B.Lint()
    try:
        B.Emitter(m, lint).build()
    except Exception as e:                                           # noqa: BLE001
        lint.err(f'emitter: {type(e).__name__}: {e}')
    return m, lint.errors, lint.warnings


# ---------------------------------------------------------------------------
# the game
# ---------------------------------------------------------------------------

class Wine:
    """The game process.

    tools/game.py already carries the hard-won parts of this — the env, and above
    all matching processes by their cwd rather than by name, because sibling
    copies of the game directory are all called BattleshipsForever.exe and a
    name-only kill takes theirs down too. It is imported and re-pointed at the
    install rather than reimplemented.
    """

    # A puppetted game is a second screen, not the thing you are looking at, so
    # it launches windowed at 1080p rather than covering the monitor the editor
    # is on. Two ordinary mod config files carry that:
    #   mods/res.cfg    width and height, one per line, read once at startup
    #   mods/mode.cfg   1 = borderless window filling the display, 0 = bordered
    WINDOW = (1920, 1080)

    # ⚠ The prefix, not the command line, decides whether there is a wine virtual
    # desktop: `HKCU\Software\Wine\Explorer` `Desktop` names one and every app in
    # that prefix gets it. So the editor uses the same PRIVATE prefix the shipped
    # `<Exe>_Linux.sh` launcher makes — which is exactly why that launcher makes
    # its own — and the research prefix, whose registry still asks for a
    # 3840x2160 desktop, is left alone for the capture harness that depends on it.
    #
    # No WINEARCH here, deliberately, for the same reason the launcher omits it:
    # the prefix is shared with the launcher, and forcing win32 onto a prefix
    # that wine created as new-wow64 makes wine refuse to start at all.
    PREFIX = os.path.join(os.environ.get('XDG_DATA_HOME')
                          or os.path.expanduser('~/.local/share'), 'bsf-legacy', 'prefix')

    def __init__(self, window=None, fullscreen=False, prefix=None):
        self.window = window or self.WINDOW
        self.fullscreen = fullscreen
        self.prefix = os.path.expanduser(prefix or self.PREFIX)
        self.game = None
        self.why = None
        try:
            import game
            game.GAME_DIR = INSTALL          # process discovery is by cwd, not prefix
            self.game = game
        except Exception as e:                                       # noqa: BLE001
            self.why = f'tools/game.py unavailable: {e}'

    @property
    def ok(self):
        return self.game is not None and os.path.isdir(INSTALL)

    def env(self):
        overrides = 'mscoree,mshtml='                # skip the Mono/Gecko prompts
        extra = os.environ.get('WINEDLLOVERRIDES_EXTRA', '').strip()
        if extra:
            overrides += ';' + extra
        return dict(os.environ, WINEPREFIX=self.prefix, WINEDLLOVERRIDES=overrides,
                    WINEDEBUG='-all', DISPLAY=os.environ.get('DISPLAY', ':0'))

    def desktop(self):
        """The virtual desktop this prefix asks for, or None. Reported at startup
        so a prefix that silently wraps the game in one is never a mystery."""
        try:
            reg = open(os.path.join(self.prefix, 'user.reg'), encoding='latin-1').read()
        except OSError:
            return None
        block = re.search(r'\[Software\\\\Wine\\\\Explorer\][^\[]*', reg)
        if not block:
            return None
        name = re.search(r'"Desktop"="([^"]+)"', block.group(0))
        if not name:
            return None
        size = re.search(r'"%s"="(\d+x\d+)"' % re.escape(name.group(1)), reg)
        return size.group(1) if size else name.group(1)

    def ensure_prefix(self):
        """Create the private prefix on first use, as the launcher does. Returns
        True if it had to be made (which costs about ten seconds)."""
        if os.path.isdir(self.prefix):
            return False
        os.makedirs(self.prefix, exist_ok=True)
        print(f'wine: creating the private prefix at {self.prefix} (about ten seconds)…')
        subprocess.run(['wineboot'], env=self.env(), stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=180, check=False)
        # On a clean exit wine tears the D3D device down and re-enumerates the
        # displays; on multi-monitor NVIDIA that is a full modeset and every
        # screen blanks for a few seconds. Nothing here needs XRandR.
        subprocess.run(['wine', 'reg', 'add', r'HKCU\Software\Wine\X11 Driver',
                        '/v', 'UseXRandR', '/d', 'N', '/f'], env=self.env(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=60, check=False)
        return True

    def running(self):
        if not self.ok:
            return False
        try:
            return bool(self.game.running())
        except Exception:                                            # noqa: BLE001
            return False

    # ------------------------------------------------------------- display
    # `res.cfg` and `mode.cfg` are the PLAYER's settings — the game rewrites them
    # itself whenever someone picks a resolution or toggles Display, so they hold
    # a real preference, not scratch state. Borrowing them for an editor session
    # and handing them back is therefore the only honest thing to do: the
    # originals are stashed on the first launch and put back when the game is
    # stopped, when the server exits, and — because neither of those is
    # guaranteed to run — on the next server start, which repairs a crash.
    STASH = 'display.saved'

    def _cfg(self, name):
        return os.path.join(INSTALL, 'mods', name)

    def _stash(self):
        return os.path.join(EDIT, self.STASH)

    def borrow_display(self):
        """Stash the player's display settings, then write the editor's."""
        if not os.path.isdir(os.path.join(INSTALL, 'mods')):
            return
        os.makedirs(EDIT, exist_ok=True)
        if not os.path.exists(self._stash()):
            saved = {}
            for name in ('res.cfg', 'mode.cfg'):
                try:
                    saved[name] = open(self._cfg(name), encoding='latin-1').read()
                except OSError:
                    saved[name] = None            # absent, and must stay absent
            with open(self._stash(), 'w', encoding='utf-8') as f:
                json.dump(saved, f)
        for name, value in (('res.cfg', '%d\n%d\n' % self.window),
                            ('mode.cfg', '1\n' if self.fullscreen else '0\n')):
            with open(self._cfg(name), 'w', encoding='ascii', newline='\n') as f:
                f.write(value)

    def return_display(self):
        """Put the player's display settings back. Safe to call at any time."""
        try:
            with open(self._stash(), encoding='utf-8') as f:
                saved = json.load(f)
        except (OSError, ValueError):
            return None
        for name, text in saved.items():
            p = self._cfg(name)
            if text is None:
                try:
                    os.remove(p)
                except OSError:
                    pass
            else:
                with open(p, 'w', encoding='ascii', newline='\n') as f:
                    f.write(text)
        os.remove(self._stash())
        return {k: (v or '').split() for k, v in saved.items()}

    # ------------------------------------------------------------- process
    def launch(self, mission=None):
        """Start the game, optionally straight into a mission.

        The argument reaches mods/editor.gml through parameter_string, which then
        drives the game's own menu sequence. Never a room_goto into a mission
        room: that leaves the globals the controller reads unset.

        ⚠ res.cfg and mode.cfg are read exactly once, in a Create event, so the
        display settings only ever apply to a launch — writing them under a
        running game does nothing. The resolution is not applied by resizing
        anything either: GM 7 builds the drawing region from a room's authored
        view port when the room loads, so mods/resolution.gml rewrites all 25
        rooms and restarts. That is also why the generated mission mods author
        their room's view once and never again.
        """
        if not self.ok:
            return {'ok': False, 'why': self.why or f'no install at {INSTALL}'}
        if self.running():
            return {'ok': True, 'note': 'already running'}
        made = self.ensure_prefix()
        self.borrow_display()
        os.makedirs(EDIT, exist_ok=True)
        for f in ('cmd', 'ack', 'state', 'dump'):
            try:
                os.remove(os.path.join(EDIT, f))
            except OSError:
                pass
        cmd = ['wine', self.game.EXE]
        if mission is not None:
            cmd += ['mission_editor', str(mission)]
        log = open('/tmp/bsf_editor_run.log', 'wb')
        subprocess.Popen(cmd, cwd=INSTALL, env=self.env(),
                         stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                         start_new_session=True)
        return {'ok': True, 'launched': cmd[1:], 'prefixCreated': made,
                'display': ('%dx%d ' % self.window)
                           + ('borderless fullscreen' if self.fullscreen else 'windowed')}

    def stop(self):
        if not self.ok:
            return {'ok': False, 'why': self.why}
        self.game.stop()
        return {'ok': True, 'restored': self.return_display()}


class Channel:
    """mods/edit — one command in, an ack out, plus state and dump."""

    def __init__(self):
        self.seq = 0
        self.lock = threading.Lock()

    def _path(self, name):
        return os.path.join(EDIT, name)

    def send(self, line, timeout=6.0):
        """Write one command and wait for the game to acknowledge that sequence.

        Serialised: the channel is a single file, so two commands in flight would
        mean the second overwriting the first before the game had polled.
        """
        with self.lock:
            if not os.path.isdir(EDIT):
                return {'ok': False, 'why': f'no channel at {EDIT}'}
            self.seq += 1
            seq = self.seq
            tmp = self._path('cmd.tmp')
            with open(tmp, 'w', encoding='ascii', newline='\n') as f:
                f.write(f'{seq}\n{line}\n')
            os.replace(tmp, self._path('cmd'))          # atomic: see the header
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    with open(self._path('ack'), encoding='latin-1') as f:
                        parts = f.read().strip().split(' ', 2)
                    if parts and parts[0] == str(seq):
                        return {'ok': parts[1] == 'ok', 'seq': seq, 'cmd': line,
                                'result': parts[2] if len(parts) > 2 else ''}
                except (OSError, IndexError):
                    pass
                time.sleep(0.02)
            return {'ok': False, 'seq': seq, 'cmd': line, 'result': 'no ack — is the game running?'}

    def forget_state(self):
        """Drop the published state, so the next read is one the game wrote after
        whatever we just asked it to do."""
        try:
            os.remove(self._path('state'))
        except OSError:
            pass

    def state(self):
        try:
            with open(self._path('state'), encoding='latin-1') as f:
                raw = f.read().strip()
        except OSError:
            return None
        out = {}
        for tok in raw.split():
            k, _, v = tok.partition('=')
            try:
                out[k] = int(v)
            except ValueError:
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
        return out or None

    def dump(self):
        """Live instances, for the ghost overlay. Positions are room coordinates,
        so they land on the prediction without a transform."""
        try:
            with open(self._path('dump'), encoding='latin-1') as f:
                lines = f.read().splitlines()
        except OSError:
            return None
        if not lines:
            return None
        head = {}
        for tok in lines[0].split():
            k, _, v = tok.partition('=')
            try:
                head[k] = float(v)
            except ValueError:
                head[k] = v
        out = []
        for ln in lines[1:]:
            p = ln.split()
            if len(p) < 11:
                continue
            try:
                out.append({'obj': p[0], 'x': float(p[1]), 'y': float(p[2]),
                            'angle': float(p[3]), 'xscale': float(p[4]),
                            'yscale': float(p[5]), 'sprite': p[6],
                            'blend': int(float(p[7])), 'alpha': float(p[8]),
                            'depth': float(p[9]), 'visible': int(float(p[10]))})
            except ValueError:
                continue
        return {'head': head, 'instances': out}


WINE = Wine()                         # re-made in main() once the flags are read
CH = Channel()

# Instances the ghost overlay has nothing to say about: chrome, particles, the
# editor's own bookkeeping objects, and the nebula scatter — which the prediction
# deliberately does not model, because `nebula: 16` is re-randomised on every
# entry, so a ghost for one would only ever report that random numbers differ.
# Filtered here rather than in the client to keep the payload small: a mission
# room dumps ~90 rows and most of them are scenery.
GHOST_SKIP = ('text', 'GUI_', 'SFX_', 'Doodad', '__newobject', 'ter_Nebula', 'ctr_')


def in_mission(st):
    """A generated mission room, with a controller that has already run Create.
    room_get_name reports a dynamically added room as __newroomN."""
    return bool(st and st.get('ctr') == 1 and str(st.get('room', '')).startswith('__newroom'))


def wait_for_mission(timeout=25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = CH.state()
        if in_mission(st):
            return st
        time.sleep(0.15)
    return CH.state()


def goto(rung, mission=None, force=False):
    """Put the running game at rung `rung`, whatever it is doing now.

    Forward is one command. Backward is not possible at all — the generated seek
    ladder is cumulative, so replaying it from a later point would duplicate every
    spawn — so backward is a warm re-entry and a forward seek from zero. Since BSF
    never calls randomize(), a re-entry replays identically and nothing drifts.

    `force` re-enters even when the game looks like it is already in the right
    place, and an apply always passes it. Reloading a mission mod re-binds its
    events; it cannot touch the instances the *old* code already created, and the
    seek ladder's delta guard means a seek to where the game already is runs
    nothing at all. Without the re-entry both commands succeed, the editor
    believes them, and the map shows the previous build — which is the one
    failure a truth loop must not have.
    """
    steps = []
    st = CH.state()
    need_open = force or not in_mission(st)
    if not need_open and rung < (st.get('seekfrom') or 0):
        need_open = True
    if not need_open and mission is not None and st.get('mission') != mission:
        need_open = True
    if need_open:
        if mission is None:
            mission = st.get('mission') if st else None
        if mission is None:
            return {'ok': False, 'steps': steps, 'why': 'no mission to open'}
        steps.append(CH.send(f'open {mission}'))
        # The state file describes the room the game was in a moment ago, and
        # entering a mission takes seconds. Left in place it answers "are we
        # there yet?" with the previous run's room, the seek fires into a
        # briefing screen and comes back "no mission controller". Deleting it
        # means the next answer can only be one the game wrote after the open.
        CH.forget_state()
        st = wait_for_mission()
        if not in_mission(st):
            return {'ok': False, 'steps': steps, 'why': 'the mission never came up'}
    # Freeze, then seek, then dump — in that order, and the freeze goes here
    # rather than before the re-entry because entering a mission clears it: the
    # enter driver hands back a running world by design. Seeking into a world
    # that is still moving is a race the editor loses (the ladder can advance
    # between the seek and the dump), and it is the freeze that makes the ghost
    # overlay a comparison rather than a photograph of two different moments.
    st = CH.state()
    if st and not st.get('pause'):
        steps.append(CH.send('pause 1'))
    if rung > 0:
        steps.append(CH.send(f'seek {rung}'))
    steps.append(CH.send('dump'))
    return {'ok': all(s.get('ok') for s in steps), 'steps': steps, 'state': CH.state()}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=APP, **kw)

    def log_message(self, *a):
        pass

    def end_headers(self):
        """Never let a browser cache the editor's own source.

        The static half of this server is the app being worked on, and
        SimpleHTTPRequestHandler's Last-Modified is enough for Chrome to serve a
        reloaded page's scripts straight out of the memory cache. The failure is
        the worst kind: the editor looks reloaded, behaves like the old build,
        and the difference is invisible — a bug fixed in app/paint.js can be
        re-reported from the same tab an hour later. The API replies are already
        no-store by omission; the sprite frames set their own max-age and keep
        it, since a frame is content-addressed by name.
        """
        if not self._headers_buffer or b'Cache-Control' not in b''.join(self._headers_buffer):
            self.send_header('Cache-Control', 'no-store, must-revalidate')
        super().end_headers()

    def _send(self, body, ctype, cache=False):
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        if cache:
            self.send_header('Cache-Control', 'max-age=3600')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        return json.loads(self.rfile.read(n) or b'{}')

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        parts = [urllib.parse.unquote(p) for p in u.path.split('/') if p]
        q = dict(urllib.parse.parse_qsl(u.query))
        if parts[:1] != ['api']:
            return super().do_GET()
        try:
            reload_changed()
            return self._api_get(parts[1:], q)
        except Exception as e:                                       # noqa: BLE001
            return self._json({'ok': False, 'why': f'{type(e).__name__}: {e}'}, 500)

    def _api_get(self, p, q):
        if p[:1] == ['missions']:
            return self._json({'ok': True, 'missions': mission_list(),
                               'dir': os.path.relpath(B.MISSIONS, REPO)})

        if p[:1] == ['mission'] and len(p) > 1:
            path = os.path.join(B.MISSIONS, p[1] + '.yaml')
            if not os.path.exists(path):
                return self._json({'ok': False, 'why': 'no such mission'}, 404)
            raw = open(path, encoding='utf-8').read()
            m, errs, warns = lint_text(raw, p[1] + '.yaml')
            return self._json({'ok': True, 'stem': p[1], 'yaml': raw, 'mission': m,
                               'errors': errs, 'warnings': warns,
                               'path': os.path.relpath(path, REPO)})

        if p[:1] == ['assets']:
            if not LIB:
                return self._json({'ok': False, 'why': 'game not found'})
            return self._json({'ok': True, 'source': os.path.basename(LIB.source),
                               'sprites': LIB.manifest(), 'objects': OBJ_SPRITES})

        if p[:1] == ['sprite'] and len(p) > 1:
            name, frame = p[1], int(q.get('f', 0))
            if not LIB or name not in LIB.sprites:
                return self._json({'ok': False, 'why': 'no such sprite'}, 404)
            return self._send(LIB.png(name, frame), 'image/png', cache=True)

        if p[:1] == ['ships']:
            return self._json({'ok': True, 'ships': ship_list()})

        if p[:1] == ['shipscene']:
            import model, scene                                      # noqa: PLC0415
            f = ship_file(q.get('f'))
            if not f:
                return self._json({'ok': False, 'why': 'no such ship'}, 404)
            sc = scene.build(model.load(f))
            # The draw list is shared with the ship CLI and the PIL renderer, so
            # the map cannot disagree with them about geometry. Only the sprite
            # reference is rewritten: a filesystem path means nothing to a page.
            for op in sc['ops']:
                op['spr'] = 'api/shipart?p=' + urllib.parse.quote(op['spr'])
            return self._json({'ok': True, 'scene': sc})

        if p[:1] == ['shipart']:
            a = ship_art(q.get('p'))
            if not a:
                return self._json({'ok': False, 'why': 'not a ship sprite'}, 404)
            with open(a, 'rb') as fh:
                return self._send(fh.read(), 'image/png', cache=True)

        if p[:1] == ['ship'] and len(p) > 1:
            if p[1] not in SHIPS:
                SHIPS[p[1]] = A.ship(p[1])
            if not SHIPS[p[1]]:
                return self._json({'ok': False, 'why': 'no hull dump'}, 404)
            return self._json(SHIPS[p[1]])

        if p[:1] == ['live']:
            # mods/edit/state outlives the process that wrote it, so a dead game
            # would otherwise keep reporting the room it died in — and the editor
            # would happily seek into it.
            running = WINE.running()
            st = CH.state() if running else None
            out = {'ok': True, 'running': running, 'state': st,
                   'inMission': in_mission(st), 'install': os.path.isdir(INSTALL)}
            if q.get('ghosts') and running:
                d = CH.dump()
                if d:
                    d['instances'] = [i for i in d['instances']
                                      if not i['obj'].startswith(GHOST_SKIP)]
                out['dump'] = d
            return self._json(out)

        return self._json({'ok': False, 'why': 'no such endpoint'}, 404)

    # --------------------------------------------------------------- POST
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        parts = [urllib.parse.unquote(p) for p in u.path.split('/') if p]
        try:
            reload_changed()
            return self._api_post(parts[1:], self._body())
        except Exception as e:                                       # noqa: BLE001
            return self._json({'ok': False, 'why': f'{type(e).__name__}: {e}'}, 500)

    def _api_post(self, p, body):
        if p[:1] == ['lint']:
            _m, errs, warns = lint_text(body.get('yaml', ''), body.get('stem', '?') + '.yaml')
            return self._json({'ok': not errs, 'errors': errs, 'warnings': warns})

        if p[:1] == ['apply']:
            return self._json(apply(body))

        if p[:1] == ['cmd']:
            return self._json(CH.send(str(body.get('cmd', '')).strip()))

        if p[:1] == ['goto']:
            return self._json(goto(int(body.get('rung', 0)), body.get('mission'),
                                   force=bool(body.get('force'))))

        if p[:1] == ['launch']:
            return self._json(WINE.launch(body.get('mission')))

        if p[:1] == ['stop']:
            return self._json(WINE.stop())

        return self._json({'ok': False, 'why': 'no such endpoint'}, 404)


def apply(body):
    """Save, build, install, and put the running game back where it was.

    The order matters and is the whole of decision 8: lint first, so a mission
    that would not compile never reaches the disk; write second; build third;
    only then touch the game. A failure at any stage leaves everything before it
    intact and everything after it untouched.
    """
    t0 = time.time()
    stem = body.get('stem')
    text = body.get('yaml', '')
    if not stem or stem not in [f[:-5] for f in mission_files()] and not body.get('create'):
        return {'ok': False, 'stage': 'stem', 'why': f'unknown mission {stem!r}'}

    m, errs, warns = lint_text(text, stem + '.yaml')
    if errs:
        return {'ok': False, 'stage': 'lint', 'errors': errs, 'warnings': warns}

    path = os.path.join(B.MISSIONS, stem + '.yaml')
    if os.path.exists(path):
        text = reattach_comments(open(path, encoding='utf-8').read(), text)
        # Carrying comments must not be able to change what the file *means*.
        m2, errs2, _ = lint_text(text, stem + '.yaml')
        if errs2 or m2 != m:
            return {'ok': False, 'stage': 'comments',
                    'why': 'reattaching comments changed the mission — nothing written',
                    'errors': errs2}
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text if text.endswith('\n') else text + '\n')
    os.replace(tmp, path)

    if not B.build_one(path):
        return {'ok': False, 'stage': 'build', 'why': 'build.py rejected it after writing',
                'errors': errs, 'warnings': warns}

    installed = False
    if os.path.isdir(os.path.join(INSTALL, 'mods')):
        B.install()
        installed = True

    out = {'ok': True, 'stage': 'built', 'warnings': warns, 'installed': installed,
           'path': os.path.relpath(path, REPO), 'ms': int((time.time() - t0) * 1000)}

    if body.get('reload') and WINE.running() and installed:
        steps = [CH.send('reload')]
        if steps[0].get('ok'):
            g = goto(int(body.get('rung', 0)), m.get('mission'), force=True)
            steps += g.get('steps', [])
            out['state'] = g.get('state')
        out['steps'] = steps
        out['stage'] = 'applied'
        out['ms'] = int((time.time() - t0) * 1000)
    return out


class Server(socketserver.ThreadingTCPServer):
    # An apply takes seconds and holds its thread; without threading the page
    # would stall behind it and the sprite fetches with it.
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, handler):
        # `::` is the one bind that answers on *everything*: a dual-stack
        # wildcard socket takes IPv6 and, with V6ONLY off, IPv4 as well — which
        # is what someone means by "*" and what a plain 0.0.0.0 does not give
        # you. Any other IPv6 literal gets the v6 family too, or bind() would be
        # handed an address its family cannot parse.
        if ':' in addr[0]:
            self.address_family = socket.AF_INET6
        super().__init__(addr, handler)

    def server_bind(self):
        if self.address_family == socket.AF_INET6:
            try:
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            except OSError:
                pass                     # some kernels refuse; v6-only is still a bind
        super().server_bind()


# --------------------------------------------------------------------------
# ship designs
# --------------------------------------------------------------------------
#
# Two roots, and the difference between them is the whole of the distribution
# question. `mods/ships/` is ours: tracked, and the installer copies it into the
# player's game with the rest of `mods/`. `Custom Ships/` is the game's: eight
# designs that ship inside bsf090d.zip, so every player already has them —
# referenced in place and never copied here, because a file taken out of the
# game is extracted game data.
#
# A mission names a ship by its path relative to the game directory, which is
# exactly the string importShip receives, so these keys are the mission's keys.

def ship_roots():
    """(kind, path relative to the mission, directory it lives under).

    A function rather than a constant because INSTALL is rebound by rebind()
    after a reload — a tuple built at import would still name the old install.
    """
    return (('campaign', 'mods/ships', REPO), ('stock', 'Custom Ships', INSTALL))


def ship_list():
    """Every design a mission may reference, both roots, newest scan each call.

    Scanned per request rather than once at startup: exporting a ship is a thing
    that happens *while* the editor is open, and a fresh export that needs a
    server restart to appear is a fresh export nobody sees.
    """
    import model                                                     # noqa: PLC0415
    out = []
    for kind, rel, root in ship_roots():
        d = os.path.join(root, rel)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.lower().endswith('.shp'):
                continue
            p = os.path.join(d, f)
            rec = {'file': f'{rel}/{f}', 'root': kind, 'name': os.path.splitext(f)[0],
                   'mtime': os.path.getmtime(p)}
            # The .sb4 is the design source and the .shp is what the game loads;
            # a source newer than its export means the mission is about to draw
            # and spawn something older than what was drawn in ShipMaker.
            src = os.path.splitext(p)[0] + '.sb4'
            rec['stale'] = (os.path.exists(src)
                            and os.path.getmtime(src) > rec['mtime'])
            try:
                sh = model.load(p)
                rec.update(title=sh.name, generation=sh.generation,
                           sections=len(sh.sections), mounts=len(sh.mounts))
            except Exception as e:                                   # noqa: BLE001
                rec.update(error=f'{type(e).__name__}: {e}')
            out.append(rec)
    return out


def ship_file(rel):
    """Resolve a mission's ship path, refusing anything outside the two roots."""
    rel = (rel or '').replace('\\', '/')
    for _kind, sub, root in ship_roots():
        if rel.startswith(sub + '/'):
            p = os.path.realpath(os.path.join(root, rel))
            base = os.path.realpath(os.path.join(root, sub))
            if p.startswith(base + os.sep) and os.path.isfile(p):
                return p
    return None


def ship_art(path):
    """A sprite file a ship names, if it really is one of the game's own.

    Ship art lives in `Custom sprites/` as ordinary PNGs, so this serves bytes
    off disk rather than going through the exe reader — and the realpath check
    is what keeps `spr` in a scene from becoming an arbitrary file read.
    """
    base = os.path.realpath(os.path.join(INSTALL, 'Custom sprites'))
    p = os.path.realpath(path or '')
    return p if p.startswith(base + os.sep) and os.path.isfile(p) else None


LOOPBACK = {'127.0.0.1', 'localhost', '::1'}
ANY = {'0.0.0.0', '*', '::'}


def tailscale_ip():
    """The local node's tailnet address, or None if Tailscale is not up."""
    try:
        out = subprocess.run(['tailscale', 'ip', '-4'], capture_output=True,
                             text=True, timeout=5, check=False).stdout.split()
        return out[0] if out else None
    except (OSError, subprocess.SubprocessError):
        return None


def local_ip():
    """The local address the OS would send from to reach the outside world."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('192.0.2.1', 9))          # TEST-NET-1: routed nowhere, no packet sent
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def resolve_host(v):
    """--host, with the two names worth not making anyone look up.

    The default is loopback and stays loopback: this server launches processes,
    reads the game out of the exe and writes mission files, so opening it to a
    network is a decision, never a default. `tailscale` binds the tailnet
    address only — reachable from your own devices and from nothing else, which
    is the case that actually comes up; `lan` and a wildcard are there because
    refusing them would only mean someone edits the line instead.
    """
    v = (v or '').strip()
    if v in ('tailscale', 'ts'):
        ip = tailscale_ip()
        if not ip:
            sys.exit('--host tailscale: no tailnet address — is tailscaled up? '
                     '(`tailscale status`)')
        return ip
    if v == 'lan':
        ip = local_ip()
        if not ip:
            sys.exit('--host lan: could not work out which address to bind on the LAN')
        return ip
    if v in ('any', 'all', '*'):
        return '::'                      # dual-stack: v6 and v4, see Server.__init__
    return v or '127.0.0.1'


def main():
    global WINE, GAME
    argv = sys.argv[1:]

    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default

    res = opt('--res', '%dx%d' % Wine.WINDOW).lower().split('x')
    try:
        window = (int(res[0]), int(res[1]))
    except (ValueError, IndexError):
        sys.exit(f'--res wants WIDTHxHEIGHT, e.g. 1920x1080 (got {opt("--res")!r})')
    WINE = Wine(window=window, fullscreen='--fullscreen' in argv,
                prefix=opt('--prefix'))

    GAME = opt('--game')
    load_art()

    # Seed the reload table now, so an edit made while the page is still loading
    # counts as a change rather than as the baseline.
    reload_changed()

    # mission_files(), not mission_list(): the count is the same number from one
    # listdir, where mission_list() parses every file's YAML to produce it.
    print(f'missions: {len(mission_files())} in {os.path.relpath(B.MISSIONS, REPO)}')
    print(f'install:  {INSTALL}' + ('' if os.path.isdir(INSTALL) else '   [missing]'))
    print(f'game:     {"running" if WINE.running() else "not running"}'
          + (f'   [{WINE.why}]' if WINE.why else ''))
    print(f'display:  {window[0]}x{window[1]} '
          + ('borderless fullscreen' if WINE.fullscreen else 'windowed')
          + '   (--res WxH, --fullscreen)')
    desk = WINE.desktop()
    print(f'prefix:   {WINE.prefix}'
          + (f'   [wine virtual desktop {desk}]' if desk else '   (no virtual desktop)')
          + ('' if os.path.isdir(WINE.prefix) else '   [will be created on first launch]'))

    # A previous session that was killed rather than stopped still has the
    # player's display settings stashed. Give them back before doing anything.
    back = WINE.return_display()
    if back:
        print('display:  handed back the settings a previous session borrowed: '
              + ' '.join(f'{k}={"/".join(v) or "absent"}' for k, v in back.items()))
    atexit.register(WINE.return_display)

    port = int(opt('--port', 8777))
    host = resolve_host(opt('--host', '127.0.0.1'))
    with Server((host, port), Handler) as srv:
        # The address to *reach* it on is not always the address it binds. A
        # wildcard belongs to every interface and to none of them, so print
        # something that can be pasted — and on a wildcard print all of them,
        # because "which of these do I type" is the next question.
        wild = host in ANY
        url = f'http://{"127.0.0.1" if wild else host}:{port}/'
        print(f'\n  editor: {url}')
        if wild:
            for label, ip in (('tailnet', tailscale_ip()), ('lan', local_ip())):
                if ip:
                    print(f'  {label + ":":8s}http://{ip}:{port}/')
        if host not in LOOPBACK:
            print(f'  bound:  {host}:{port} — reachable from other machines. '
                  'This API launches the game, reads the exe and writes missions.')
        print('  ctrl-c to stop\n')
        # Open what it is actually serving. A non-loopback bind answers on that
        # address and only that one, so the local browser reaches it there too —
        # 127.0.0.1 would be a browser tab that cannot connect.
        if '--no-open' not in argv:
            webbrowser.open(url)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print()


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Act II mission pipeline: beat-script YAML -> lint -> GML mod + HTML viewer.

Usage:
    python3 campaign/build.py                       # build every mission
    python3 campaign/build.py ep9                   # build one
    python3 campaign/build.py --install             # build + copy mods into the
                                                    # live install (see INSTALL)

Outputs, per mission id declared in the YAML (e.g. a2m1):
    mods/act2m1.gml            the runtime mod (room + controller + ladder)
    campaign/out/ep9.html      the progression viewer (open in a browser)

The GML emitter honours the GM7 traps from MODDING-GUIDE.md by construction:
  * no `&&` / `||` is ever emitted — conditions nest
  * event-code strings are single-quoted and never contain an apostrophe;
    dialogue lives in double-quoted `global.<id>_t<n>` assignments in plain
    file scope, where apostrophes are legal
  * every temporary is declared with `var`
  * every referenced resource name is checked against the decrypted tree
    (objects.json + identifiers harvested from dump/all_gml.txt)
"""
import html
import json
import math
import os
import re
import shutil
import sys

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required: pip install pyyaml")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MISSIONS = os.path.join(HERE, "missions")
OUT_HTML = os.path.join(HERE, "out")
OUT_MODS = os.path.join(REPO, "mods")

# The decrypted tree and the live install. Discovered, never hardcoded: an
# absolute path embeds whoever's account it was authored on. tools/bsf/paths.py
# is the module that answers this for the whole repo — $BSF_GAME, then
# $BSF_BASE, then a search near the checkout, each candidate validated by
# ShipMaker.exe rather than merely existing — and it resolves a linked
# worktree's main checkout through the `gitdir:` file instead of guessing at
# ancestors. It is stdlib-only and documented not to raise at import, so it is
# safe to read at module scope here.
#
# One discovery answer, not two: tools/editor/server.py imports *both* this
# module and tools/editor/assets.py in one process, and takes the install from
# here while taking the sprite library from paths.GAME. Two implementations
# would let $BSF_GAME split the editor in half — art from one install, commands
# written to another.
sys.path.insert(0, os.path.join(REPO, "tools", "bsf"))
import paths                                                          # noqa: E402

INSTALL = str(paths.GAME)
RESEARCH = str(paths.GAME.parent)

GREEN = "$00FF00"
COLORS = {"green": "$00FF00", "red": "c_red", "magenta": "$FF00FF", "white": "c_white"}

# ----------------------------------------------------------------------------
# resource tables from the decrypted tree
# ----------------------------------------------------------------------------

def load_resources():
    objs = set()
    p = os.path.join(RESEARCH, "objects.json")
    if os.path.exists(p):
        objs = {o["name"] for o in json.load(open(p))}
    idents = set()
    p = os.path.join(RESEARCH, "dump", "all_gml.txt")
    if os.path.exists(p):
        txt = open(p, encoding="latin-1").read()
        idents = set(re.findall(r"\b(?:spr|snd|scr|mus|bgm)_[A-Za-z0-9_]+\b", txt))
    return objs, idents

OBJECTS, IDENTS = load_resources()

# scripts/builtins the emitter itself uses — verified once in INTERNALS.md
KNOWN_CALLS = {
    "showMessage", "showPing", "showHighlight", "centreCamera",
    "missionFail", "missionSucc", "saveGame", "stopMusic", "bgm_Play",
    # The game's own ship-file loader, as used by the sandbox's spawn-ship.
    "importShip",
    # `damage(amount, target)` — the one way anything in BSF hurts anything.
    # Every weapon and every asteroid goes through it, and it is where a section
    # is destroyed and where `l_owner.l_syshp` is debited; nothing polls `l_hp`
    # for death. The storm calls it for the same reason. Its body is not in the
    # plaintext object tree — the exe's script section is zlib'd and byte
    # substituted, and `_local/research/SCRIPT-OBFUSCATION.md` is how it comes
    # back out.
    "damage",
}

#: `meteors:` when the mission does not say. See the alarm-5 emitter for what
#: the pair means — `cap` is the density, `interval` only the refill rate. The
#: editor's mission sheet keeps its own copy of these two numbers (core.js,
#: `Meteors.DEFAULTS`) so a mission with no block still has something to edit;
#: they are the same numbers and want changing together.
METEORS = {"interval": 240, "cap": 8}


class Lint:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def err(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def resource(self, name, where):
        if name in OBJECTS or name in IDENTS:
            return
        self.err(f"{where}: unknown resource '{name}' (not in tree)")

    def text(self, s, where):
        if '"' in s:
            self.err(f'{where}: double quote in text (GM7 has no escapes): {s[:60]}')
        if "\n" in s:
            self.err(f"{where}: literal newline in text — use '#' breaks")
        for ch in "—–’‘“”…":
            if ch in s:
                self.err(f"{where}: non-ASCII '{ch}' (game font): {s[:60]}")

    def event_string(self, s, where):
        if "'" in s:
            self.err(f"{where}: apostrophe inside event-code string: …{s[:70]}")
        if "&&" in s or "||" in s:
            self.err(f"{where}: && / || emitted (GM7 does not short-circuit)")
        if s.count("{") != s.count("}"):
            self.err(f"{where}: unbalanced braces")
        if s.count("(") != s.count(")"):
            self.err(f"{where}: unbalanced parens")


# ----------------------------------------------------------------------------
# the storm field
# ----------------------------------------------------------------------------

class Storm:
    """The painted storm field: one mask over the room, not a list of circles.

    A cell is `.` clear, `#` damaging or `@` hot, at `cell` world units square.
    The mask is the single source of truth for both halves of a storm — what
    hurts you and what you can see — which is the whole point: the editor paints
    it, and the red gas clouds are drawn from the same cells that do the damage.

    Everything downstream of the mask (the row runs a lightning strike samples,
    the cells the gas clouds are scattered over) is derived at runtime from it,
    so the compiler emits the picture and nothing else. `zones:` is the older circle
    form and is rasterised into the same field, so hand-written missions keep
    working; the editor only ever writes a mask.
    """

    CHARS = {".": 0, " ": 0, "#": 1, "@": 2}

    def __init__(self, m, lint):
        st = m.get("storm") or {}
        self.lint = lint
        self.cell = int(st.get("cell", 50)) or 50
        self.dmg = st.get("dmg", 0.30)
        self.hot = st.get("hot", 0.40)
        self.density = st.get("density", 0.18)
        self.lightning = int(st.get("lightning", 90))
        self.cols = max(1, -(-int(m["room"]["width"]) // self.cell))
        self.rows = max(1, -(-int(m["room"]["height"]) // self.cell))
        self.grid = [[0] * self.cols for _ in range(self.rows)]

        rows = st.get("mask") or []
        if len(rows) > self.rows:
            lint.err(f"storm.mask has {len(rows)} rows, the room holds {self.rows}")
        for r, line in enumerate(rows[:self.rows]):
            line = str(line)
            if len(line) > self.cols:
                lint.err(f"storm.mask row {r} is {len(line)} wide, the room holds {self.cols}")
            for c, ch in enumerate(line[:self.cols]):
                if ch not in self.CHARS:
                    lint.err(f"storm.mask row {r}: '{ch}' is not one of . # @")
                    continue
                self.grid[r][c] = self.CHARS[ch]

        for z in m.get("zones", []):
            self._circle(z)

    def _circle(self, z):
        """Legacy `zones:` — a circle, stamped into the mask it replaced."""
        lvl = 2 if abs(z["dmg"] - self.hot) < abs(z["dmg"] - self.dmg) else 1
        if z["dmg"] not in (self.dmg, self.hot):
            self.lint.warn(f"zones: dmg {z['dmg']} is not storm.dmg or storm.hot — "
                           f"rasterised as the nearer of the two")
        rr = z["r"] / self.cell
        cx, cy = z["x"] / self.cell, z["y"] / self.cell
        for r in range(max(0, int(cy - rr)), min(self.rows, int(cy + rr) + 1)):
            for c in range(max(0, int(cx - rr)), min(self.cols, int(cx + rr) + 1)):
                if (c + 0.5 - cx) ** 2 + (r + 0.5 - cy) ** 2 <= rr * rr:
                    self.grid[r][c] = max(self.grid[r][c], lvl)

    def any(self):
        return any(v for row in self.grid for v in row)

    def mask(self):
        """The mask as it should appear in the YAML — the picture, round-tripped."""
        inv = {0: ".", 1: "#", 2: "@"}
        return ["".join(inv[v] for v in row) for row in self.grid]

    def spans(self):
        """(x, y, w) per contiguous run in a row — the SVG viewer's fill."""
        out = []
        for r, row in enumerate(self.grid):
            c0 = None
            for c in range(self.cols + 1):
                v = row[c] if c < self.cols else 0
                if v and c0 is None:
                    c0 = c
                elif not v and c0 is not None:
                    out.append((c0 * self.cell, r * self.cell, (c - c0) * self.cell))
                    c0 = None
        return out


# ----------------------------------------------------------------------------
# GML assembly helpers
# ----------------------------------------------------------------------------

def ping_anchors(m):
    """Everything a `ping:` may be attached to, as {name: (x, y)}.

    Named spawns and the player start — the things in a mission that *are* a
    position and that something else might want to point at. A spawn has to
    carry `name:` to be nameable here, which it already does for `damage:` and
    for anything the ladder addresses later; the editor's ping card names one on
    the author's behalf when they pick an unnamed spawn.
    """
    out = {"player": (m["player"]["x"], m["player"]["y"])}
    for b in m["beats"]:
        for sp in b.get("spawn", []):
            if "name" in sp:
                out[sp["name"]] = (sp["x"], sp["y"])
    return out


def ping_at(m, b):
    """`ping:` as a point, whichever of its two forms was written.

    A pair of numbers is a fixed point. A string is a *link*: the name of a
    spawn (or `player`) whose position the ping follows, resolved here at build
    time so the emitted `showPing` is still two literals.

    The link exists because the pair drifts. Dragging a spawn on the editor's
    map moves the spawn and nothing else, so a `ping:` written to sit on that
    hull quietly ends up pointing at where the hull used to be — which for a
    ping is total failure, since announcing empty space is the one thing it must
    never do. A link cannot drift: there is only one copy of the position.

    Returns None for an unresolvable name; the lint reports it, and emitting
    nothing is better than emitting a flash at (0, 0).
    """
    p = b.get("ping")
    if p is None:
        return None
    if isinstance(p, (list, tuple)):
        return (p[0], p[1])
    return ping_anchors(m).get(str(p))


def gml_quote_lines(code):
    """Turn a GML fragment into the  'line' + \n 'line' + …  literal used for
    object_event_add. The fragment must not contain apostrophes."""
    lines = [ln for ln in code.splitlines() if ln.strip()]
    return " +\n    ".join("'" + ln.rstrip() + "'" for ln in lines)


class Emitter:
    def __init__(self, m, lint):
        self.m = m
        self.lint = lint
        self.gid = m["id"]                       # e.g. a2m1
        self.texts = []                          # (varname, string)
        self.room_slot = m["mission"] - 7        # mission 8 -> act2_room1
        self.storm = Storm(m, lint)
        self.damaged = []                        # damage: fractions, by slot

    def tvar(self, s, where):
        self.lint.text(s, where)
        name = f"global.{self.gid}_t{len(self.texts)}"
        self.texts.append((name, s))
        return name

    # ---- beat actions -> GML statements (apostrophe-free by construction) --

    def say_stmt(self, say, where):
        color = COLORS[say.get("color", "green")]
        sprite = say.get("sprite", "spr_MesHint")
        self.lint.resource(sprite, where)
        who = say["who"]
        text = say["text"]
        wv = self.tvar(who, where) if "'" in who else f'"{who}"'
        tv = self.tvar(text, where)
        delay = say.get("delay", 0)
        return f"showMessage({delay},{color},{wv},{tv},{sprite})"

    SPAWN_KEYS = {"object", "x", "y", "name", "sprite", "scale", "angle", "frame",
                  "tint", "ship", "team", "hold", "facing", "damage"}

    #: `importShip(file, team, x, y)` is the game's own loader — it is what the
    #: sandbox's spawn-ship uses, and it returns the instance. The team numbers
    #: come from those call sites: the one commented `//SPAWN ENEMY SHHIP`
    #: passes 1, the plain sandbox spawn passes 0 and the ctrl-modified one 2.
    #: ⚠ 0 and 2 are inferred from that pairing rather than from a comment, so
    #: they want one look in a running game before anyone relies on them.
    TEAMS = {"player": 0, "enemy": 1, "ally": 2}

    #: The eight designs that ship inside bsf090d.zip. A mission may name one
    #: and every player will have it; anything else under `Custom Ships/` is a
    #: file on *this* machine and would be missing on someone else's.
    STOCK_SHIPS = {"cronus.shp", "eos2.shp", "leviathan.shp", "nagaya1.shp",
                   "nagaya2.shp", "nagayaship 3.shp", "pendulum.shp", "sinope.shp"}

    # `image_blend` is a BGR literal in GM, which is unreadable in a mission
    # file; authors write CSS-ish hex or a colour word and the compiler emits
    # make_color_rgb, which takes the channels in the order everyone thinks in.
    TINTS = {"white": (255, 255, 255), "red": (255, 90, 77), "green": (78, 240, 138),
             "blue": (127, 216, 255), "amber": (255, 182, 72), "magenta": (255, 92, 255),
             "grey": (150, 150, 150), "gray": (150, 150, 150)}

    def tint_expr(self, v, where):
        s = str(v).strip()
        if s.lower() in self.TINTS:
            r, g, b = self.TINTS[s.lower()]
        elif re.fullmatch(r"#?[0-9a-fA-F]{6}", s):
            s = s.lstrip("#")
            r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        else:
            self.lint.err(f"{where}: tint '{v}' is not #rrggbb or one of "
                          f"{', '.join(sorted(self.TINTS))}")
            return "c_white"
        return f"make_color_rgb({r},{g},{b})"

    def spawn_stmt(self, sp, where):
        """One `spawn:` entry.

        Plain, it is the one call it always was. With a look on it — a different
        sprite, a scale, an angle — the instance has to be caught in something
        first, so it goes into the mission's own global when the entry is named
        and into the scratch `s` otherwise. Every ladder that can run a spawn
        declares `var s`.

        The overrides are assignments *after* instance_create, which means after
        the object's own Create event: whatever it set for itself is what they
        replace. That is the point — `ter_Planet` is one object and the game has
        several planets' worth of art.
        """
        g = self.gid
        for k in sp:
            if k not in self.SPAWN_KEYS:
                self.lint.err(f"{where}: unknown spawn key '{k}'")
        if "ship" in sp:
            return self.ship_stmt(sp, where)
        if "object" not in sp:
            self.lint.err(f"{where}: a spawn needs object: or ship:")
            return "0"
        self.lint.resource(sp["object"], where)
        create = f"instance_create({sp['x']},{sp['y']},{sp['object']})"
        look = []
        tgt = f"global.{g}_{sp['name']}" if "name" in sp else "s"
        if "sprite" in sp:
            self.lint.resource(sp["sprite"], where)
            look.append(f"{tgt}.sprite_index = {sp['sprite']}")
        if "frame" in sp:
            look.append(f"{tgt}.image_index = {sp['frame']}")
        if "scale" in sp:
            look.append(f"{tgt}.image_xscale = {sp['scale']}; "
                        f"{tgt}.image_yscale = {sp['scale']}")
        if "angle" in sp:
            look.append(f"{tgt}.image_angle = {sp['angle']}")
        if "tint" in sp:
            look.append(f"{tgt}.image_blend = {self.tint_expr(sp['tint'], where)}")
        look += self.fixture_stmts(sp, tgt, where)
        if not look and "name" not in sp:
            return create
        return "; ".join([f"{tgt} = {create}"] + look)

    def fixture_stmts(self, sp, tgt, where):
        """`hold:`, `facing:` and `damage:` — the three that describe a hull
        already in the world rather than one arriving in it.

        Shared by both spawn kinds deliberately. These used to live in
        `ship_stmt` alone, which meant `hold:` on an `object:` spawn passed the
        key check and then did *nothing* — the mission said the hull was moored
        and the hull flew away.

        `hold:` is the whole of what makes a docked hull scenery, and it takes
        both of the game's own flags to say it. `l_holdposition` is what the AI
        reads. `l_myship` is what the command UI reads — `if l_myship then
        global.selected[...] = id` is how select-all works, so a player-team
        hull without it is a ship the player can take and fly off the dock. The
        movement properties are zeroed as well: a ship file carries its own
        (`l_thrust,0.05` with a non-zero top speed), and stilling the AI does
        not still a hull that is already drifting.

        `facing:` sets `direction` *and* `image_angle`, never one alone. The
        hull is drawn from `image_angle` — every section places itself at
        `l_offsetdir + l_owner.image_angle` — while `direction` is where it
        would travel. A held hull only shows the first, but leaving the second
        pointing somewhere else is a trap for whoever later unholds it.
        """
        out = []
        if sp.get("hold"):
            out.append(f"{tgt}.l_holdposition = true; {tgt}.l_myship = 0; "
                       f"{tgt}.l_thrust = 0; {tgt}.l_maxspeed = 0; "
                       f"{tgt}.l_turning = 0")
        if "facing" in sp:
            out.append(f"{tgt}.direction = {sp['facing']}; "
                       f"{tgt}.image_angle = {sp['facing']}")
        if "damage" in sp:
            out.append(self.damage_stmt(sp, tgt, where))
        return out

    def damage_stmt(self, sp, tgt, where):
        """`damage: 0.3` — every section of this hull starts at 0.3 of its HP,
        and *stays* there.

        The multiplier is the same one `player.damage` has always meant. What
        is new is that it holds, and it has to: the engine repairs any section
        under half maximum, once a second, forever
        (`if l_hp < l_maxhp/2 then l_hp += l_maxhp * World_Repairrate`). Below
        0.5 that alarm is also the only thing that makes a hull *look* hurt —
        it rolls a 10% chance per section per second to trail an SFX_Streamer —
        so the smoke and the healing are the same clock and you cannot silence
        one without the other. Hence a mission-side tick (alarm 6) that pushes
        the sections back down to where the author put them, which leaves the
        smoke running and the hull permanently wrecked.

        `l_drawglow` carries `0.5 - 0.5*l_hp/l_maxhp` of its own, so the damage
        glow needs nothing from us — it follows the HP down and stays there.
        """
        try:
            f = float(sp["damage"])
        except (TypeError, ValueError):
            self.lint.err(f"{where}: damage '{sp['damage']}' is not a number")
            return "0"
        if not 0 < f <= 1:
            self.lint.err(f"{where}: damage {f} is out of range — it is a "
                          f"multiplier on section HP, so 0 < damage <= 1")
            return "0"
        if "name" not in sp:
            # The tick needs a handle a second later; `s` is reused by the next
            # spawn in the same rung and would leave the wrong hull registered.
            self.lint.err(f"{where}: a damaged spawn needs name: — the hull has "
                          f"to be nameable for the damage to be held on it")
            return "0"
        # A slot per damaged spawn, fixed at compile time rather than appended
        # at run time. A seek replays the spawns of every rung it passes, and an
        # appending registry would grow by four every time the editor scrubbed
        # the timeline. With a fixed slot a replay overwrites its own entry.
        slot = len(self.damaged)
        self.damaged.append(f)
        g = self.gid
        return (f"with (ShipSection) {{ if (l_owner = {tgt}) l_hp = l_hp * {f}; }}; "
                f"global.{g}_dmg[{slot}] = {tgt}")

    def ship_stmt(self, sp, where):
        """A `spawn:` entry that names a ship *design* rather than an object.

            spawn:
              - {ship: mods/ships/station_bolthole.shp, x: 2760, y: 1050,
                 team: ally, hold: true, name: station}

        The stock designs are objects and `object:` reaches them; this is for
        the hulls that exist only as files — the campaign's own, under
        `mods/ships/`, and the eight the game ships in `Custom Ships/`. The path
        is relative to the game directory and is exactly the string the loader
        receives, so a mission means the same thing on every machine.

        `hold:` is what makes a station a station. A ship file records its own
        movement properties and the campaign's does too — `l_thrust,0.05` with
        a non-zero top speed — so imported as-is it would drift and turn under
        AI. The stock stations solve this in their own GML (`Leviathan` is
        `l_thrust=0, l_maxspeed=0.01`); a mission solves it per instance,
        because the same design may legitimately fly somewhere else.
        """
        g = self.gid
        # ⚠ Double quotes, not single. Event code is emitted as single-quoted
        # GM strings, so an apostrophe anywhere inside it is a syntax error with
        # no escape available — the same reason `say_stmt` double-quotes a
        # speaker's name. A path with a double quote in it is not a path.
        path = str(sp["ship"]).replace("\\", "/")
        if "'" in path or '"' in path:
            self.lint.err(f"{where}: quote in a ship path — event code is "
                          f"single-quoted and GM7 has no escapes: {path}")
        if "object" in sp:
            self.lint.err(f"{where}: a spawn is either object: or ship:, not both")
        if "team" not in sp:
            self.lint.err(f"{where}: ship spawns need team: "
                          f"({' | '.join(sorted(self.TEAMS))}) — there is no safe default")
        team = self.TEAMS.get(str(sp.get("team", "")).lower())
        if "team" in sp and team is None:
            self.lint.err(f"{where}: team '{sp['team']}' is not "
                          f"{' | '.join(sorted(self.TEAMS))}")
            team = 0
        self.check_ship_file(path, where)

        tgt = f"global.{g}_{sp['name']}" if "name" in sp else "s"
        # Guarded exactly the way the game guards its own calls — every stock
        # caller of importShip is preceded by `if !file_exists(fname) then
        # exit`. Ours was not, and the failure is brutal out of proportion to
        # the cause: a missing file makes importShip return a non-instance, the
        # very next statement assigns a property to it, GM7 raises "Cannot
        # assign to the variable", and *the entire code action is abandoned*.
        # One absent .shp therefore erased a station, a planet, four berthed
        # hulls and the line of dialogue after them, with nothing on screen to
        # say why. Guarding costs one file_exists and confines the loss to the
        # hull that is actually missing.
        #
        # The fixtures go inside the instance_exists arm rather than after it:
        # `initSections()` has already run by the time importShip returns, so
        # the hull is built and only the core needs settling — but only if
        # there is a core at all.
        fixtures = self.fixture_stmts(sp, tgt, where)
        body = "; ".join(fixtures)
        # importShip is the sandbox's interactive tool, and the x/y it takes are
        # not a placement: all it does is parse the design into a fresh object
        # (parented to ctr_Ship) and hand that object to a ctr_Spawner, which
        # then waits for the player to click. Measured in a running game — after
        # importShip returned, the object existed and instance_number of it was
        # 0, and the spawner sat there holding it. A mission cannot click, so it
        # takes the object off the cursor and places the hull itself.
        #
        # The object comes from importShip's *return value*, not off the cursor.
        # Both carry it, but the cursor only exists when the design was parsed
        # this time: the loader caches every design it reads under its path for
        # the life of the process, and a second import of the same file returns
        # the cached object without arming a cursor. Reading the cursor
        # therefore worked exactly once per session and left the hull silently
        # missing on every replay — which is a worse bug than the one it fixed,
        # because it only shows up the second time.
        #
        # The leading destroy matters as much as the trailing one: parse refuses
        # outright while a cursor exists (`if instance_exists(ctr_Spawner) then
        # return -4`), so one stranded cursor silently blocks every later import
        # in the room — which is exactly what a crash inside the spawner's own
        # alarm left behind while this was being tracked down. -4 is also what a
        # failed parse returns, hence the `>= 0` rather than a truth test.
        out = f"""{tgt} = noone;
if (file_exists("{path}")) {{
with (ctr_Spawner) instance_destroy();
global.{g}_imp = importShip("{path}",{team or 0},{sp["x"]},{sp["y"]});
with (ctr_Spawner) instance_destroy();
if (global.{g}_imp >= 0) {{
{tgt} = instance_create({sp["x"]},{sp["y"]},global.{g}_imp);
}}
}}"""
        if body:
            out += f"\nif (instance_exists({tgt})) {{ {body}; }}"
        return out

    def check_ship_file(self, path, where):
        """A referenced ship has to exist — for us now, and for a player later.

        "Exists" means *the game* can find it, which is stricter than the file
        being somewhere on this disk. This used to accept either copy, repo or
        install, and that `or` is what shipped a station the game could not
        load: the repo copy satisfied the linter, install() only ever copied
        GML, and the mission named a path that had never existed under the game
        directory. A silent build has to mean the hull will be there.
        """
        low = path.lower()
        if low.startswith("custom ships/"):
            name = low.split("/", 1)[1]
            if name not in self.STOCK_SHIPS:
                self.lint.warn(
                    f"{where}: '{path}' is not one of the eight designs that ship "
                    f"with v0.90d — it exists here but a player would not have it")
            return
        if not low.startswith("mods/ships/"):
            self.lint.warn(f"{where}: '{path}' is outside mods/ships/ and "
                           f"Custom Ships/, so nothing installs it")
            return
        # mods/ships/ is the one tree install() copies, so the repo copy is the
        # source of truth: it is what a fresh clone holds and what the installer
        # puts in front of the game. A file present only in the install is a
        # local leftover — it works in that one install and nowhere else.
        if not os.path.exists(os.path.join(REPO, path)):
            if os.path.exists(os.path.join(INSTALL, path)):
                self.lint.err(f"{where}: '{path}' is in the game directory but not "
                              f"in the repo, so nothing reinstalls it — a clone "
                              f"would name a ship that is not there")
            else:
                self.lint.err(f"{where}: no such ship file '{path}'")

    def gate_stmt(self, x, y):
        # `g` is declared once at the top of the ladder event
        return (f"g = instance_create({x},{y},MoveToArea); "
                f"g.l_target = global.{self.gid}_ship; showPing({x},{y})")

    #: `note:` is the one key that compiles to nothing. It carries why the beat
    #: is the way it is — a measurement, a rejected alternative, where a number
    #: came from — as *data* rather than as a `#` comment, because the editor
    #: parses this file into a model and writes it back out of that model: a
    #: comment survives until the next apply and then is gone with no trace.
    #: Stored as a list of lines, like the storm mask, so it diffs by the line.
    BEAT_KEYS = {"note", "start", "say", "objective", "gate", "gate_at", "wait",
                 "autosave", "music", "eerie", "meteors", "camera", "spawn",
                 "ping", "win", "exec", "interference"}

    # Verbs whose effect is persistent world state. Only these are replayed when
    # the editor fast-forwards (user event 1) — the rest are *events*, and a seek
    # that manufactured them would show panels nobody triggered, spawn gates the
    # player never has to fly to, and write autosaves. See tools/editor/DESIGN.md
    # decision 2.
    SEEKABLE = {"music", "eerie", "meteors", "camera", "spawn", "exec",
                "interference"}

    # An `exec:` line is opaque to the compiler, so it is replayed on a seek on
    # the assumption that raw GML is there to set up the world. When it clearly
    # is not, say so: a spurious panel during a seek is at least visible, but it
    # should not be a surprise.
    EXEC_NOT_STATE = re.compile(
        r"showMessage|showPing|missionSucc|missionFail|saveGame|MoveToArea")

    @staticmethod
    def onoff(v):
        """YAML 1.1 parses bare on/off as booleans — normalise both spellings."""
        if v is True:
            return "on"
        if v is False:
            return "off"
        return v

    def actions(self, b, where):
        """One beat -> [(verb, statement)], in the order the GML runs.

        Both ladders are derived from a single call per beat: `tvar` appends to
        self.texts, so asking twice would duplicate every dialogue global.
        """
        g = self.gid
        out = []
        for k in b:
            if k not in self.BEAT_KEYS:
                self.lint.err(f"{where}: unknown beat key '{k}'")
        if b.get("music") == "stop":
            out.append(("music", "stopMusic()"))
        elif b.get("music") == "theme":
            out.append(("music", "stopMusic(); bgm_Play(global.mus_theme,1)"))
        elif b.get("music") == "battle":
            out.append(("music", "stopMusic(); bgm_Play(global.mus_battle,1)"))
        elif "music" in b:
            self.lint.err(f"{where}: music must be stop|theme|battle")
        if self.onoff(b.get("eerie")) == "on":
            out.append(("eerie", "sound_loop(snd_eeriesound)"))
        elif self.onoff(b.get("eerie")) == "off":
            out.append(("eerie", "sound_stop(snd_eeriesound)"))
        if self.onoff(b.get("interference")) == "on":
            out.append(("interference", f"global.{g}_interf = 1"))
        elif self.onoff(b.get("interference")) == "off":
            out.append(("interference", f"global.{g}_interf = 0"))
        if b.get("autosave"):
            out.append(("autosave", "if (global.difficulty != World_Hard) saveGame()"))
        if "camera" in b:
            c = b["camera"]
            out.append(("camera", f"centreCamera({c['x']},{c['y']},{c.get('speed', 60)})"))
            out.append(("camera", f"global.lasteventx = {c['x']}; global.lasteventy = {c['y']}"))
        for sp in b.get("spawn", []):
            out.append(("spawn", self.spawn_stmt(sp, where)))
        if "ping" in b:
            at = ping_at(self.m, b)
            if at:
                out.append(("ping", f"showPing({at[0]},{at[1]})"))
        if self.onoff(b.get("meteors")) == "on":
            out.append(("meteors", f"global.{g}_meteors = 1; alarm[5] = 1"))
        elif self.onoff(b.get("meteors")) == "off":
            out.append(("meteors", f"global.{g}_meteors = 0"))
        if "objective" in b:
            ov = self.tvar(b["objective"], where)
            out.append(("objective", f'showMessage(0,c_red,"New Objective",{ov},spr_MesObj)'))
        if "say" in b:
            out.append(("say", self.say_stmt(b["say"], where)))
        if "gate" in b:
            gt = self.m["gates"][b["gate"]]
            out.append(("gate", self.gate_stmt(gt["x"], gt["y"])))
        if "gate_at" in b:
            out.append(("gate", self.gate_stmt(b["gate_at"]["x"], b["gate_at"]["y"])))
        if b.get("win"):
            out.append(("win", f"global.{g}_won = 1; missionSucc()"))
        for raw in b.get("exec", []):
            if self.EXEC_NOT_STATE.search(raw):
                self.lint.warn(f"{where}: exec is replayed on a seek, and this line "
                               f"does more than set up the world: {raw[:60]}")
            out.append(("exec", raw))
        return out

    # ---- assign counter numbers ------------------------------------------

    def number_beats(self):
        """Start beat runs from alarm 2 (counter stays 0). Every other beat
        claims the next counter; a message beat advances the counter by 1 when
        its panel closes; `wait: gate` reserves one extra slot so the gate's
        own +1 lands on the next beat regardless of message timing."""
        beats = self.m["beats"]
        if not beats or not beats[0].get("start"):
            self.lint.err("first beat must have start: true")
            return []
        numbered = []
        n = 1
        for i, b in enumerate(beats[1:], 1):
            msgs = ("say" in b) + ("objective" in b)
            if msgs > 1:
                self.lint.err(f"beat {i}: more than one message panel per beat")
            numbered.append((n, b))
            n += 1                       # this rung
            # A beat with no message auto-chains, and still occupies one slot —
            # so only `wait: gate` claims a second.
            if b.get("wait") == "gate":
                n += 1                   # absorber slot for the gate's +1
        return numbered

    # ---- the storm: file-scope field, then the two objects that use it ----

    def storm_field(self):
        """Plain file scope: the mask, and everything derived from it.

        Derived once per *load* rather than per mission entry, because a mission
        is re-entered on every apply and the decode is the one part that does not
        depend on anything in the room. The grid ends up a flat global array, so
        the damage test inside `with (ShipSection)` is a single array read — the
        reason a painted field is cheaper than the circles it replaced, not more
        expensive: five circles cost five distance tests per section per step.
        """
        g, st = self.gid, self.storm
        L = [f"""
// ------------------------------------------------------------------- storm
// The storm is a painted mask, one cell per {st.cell} world units: `#` damages,
// `@` damages harder, `.` is clear space. This is the only description of the
// storm in the file — the red wash, the gas clouds and the damage test are all
// read from these rows. What bites is the row, not the cloud: a puff is many
// cells wide, so the gas laps over clear space the mask says nothing about.
global.{g}_cellsz = {st.cell};
global.{g}_cols = {st.cols};
global.{g}_rows = {st.rows};
global.{g}_d1 = {st.dmg};
global.{g}_d2 = {st.hot};
global.{g}_dens = {st.density};"""]
        for r, row in enumerate(st.mask()):
            L.append(f'global.{g}_mrow[{r}] = "{row}";')
        L.append(f"""
var stx_r, stx_c, stx_ch, stx_v, stx_c0;
for (stx_r = 0; stx_r < global.{g}_rows; stx_r += 1) {{
    for (stx_c = 0; stx_c < global.{g}_cols; stx_c += 1) {{
        stx_ch = string_char_at(global.{g}_mrow[stx_r], stx_c + 1);
        stx_v = 0;
        if (stx_ch = "#") stx_v = 1;
        if (stx_ch = "@") stx_v = 2;
        global.{g}_g[stx_r * global.{g}_cols + stx_c] = stx_v;
    }}
}}
// Row runs. Nothing draws these — they are the sampling table a lightning
// strike picks its two endpoints from, which is why they are runs and not
// cells: one random pick lands anywhere in the storm, uniformly by area.
global.{g}_nsp = 0;
for (stx_r = 0; stx_r < global.{g}_rows; stx_r += 1) {{
    stx_c0 = -1;
    for (stx_c = 0; stx_c <= global.{g}_cols; stx_c += 1) {{
        stx_v = 0;
        if (stx_c < global.{g}_cols) stx_v = global.{g}_g[stx_r * global.{g}_cols + stx_c];
        if (stx_v > 0) {{
            if (stx_c0 < 0) stx_c0 = stx_c;
        }} else {{
            if (stx_c0 >= 0) {{
                global.{g}_spx[global.{g}_nsp] = stx_c0 * global.{g}_cellsz;
                global.{g}_spy[global.{g}_nsp] = stx_r * global.{g}_cellsz;
                global.{g}_spw[global.{g}_nsp] = (stx_c - stx_c0) * global.{g}_cellsz;
                global.{g}_nsp += 1;
                stx_c0 = -1;
            }}
        }}
    }}
}}""")
        return "\n".join(L)

    def storm_events(self):
        """The storm object's Create/Alarm0/Step/Draw and the cloud puff's."""
        g, st = self.gid, self.storm
        lo, hi = max(20, st.lightning // 2), max(1, st.lightning)

        # Create: scatter the gas clouds. Every boundary cell gets a puff far more
        # often than an interior one — the wash has hard 50-unit edges and the
        # clouds are what hides them, so the fringe is where they are needed.
        create = f"""
depth = 700;
l_bolt = 0; l_flash = 0; l_bn = 0;
var sr, sc, sv, se, pd, pf;
for (sr = 0; sr < global.{g}_rows; sr += 1) {{
for (sc = 0; sc < global.{g}_cols; sc += 1) {{
sv = global.{g}_g[sr * global.{g}_cols + sc];
if (sv > 0) {{
se = 0;
if (sr = 0) se = 1;
if (sc = 0) se = 1;
if (sr = global.{g}_rows - 1) se = 1;
if (sc = global.{g}_cols - 1) se = 1;
if (se = 0) {{
if (global.{g}_g[(sr - 1) * global.{g}_cols + sc] = 0) se = 1;
if (global.{g}_g[(sr + 1) * global.{g}_cols + sc] = 0) se = 1;
if (global.{g}_g[sr * global.{g}_cols + sc - 1] = 0) se = 1;
if (global.{g}_g[sr * global.{g}_cols + sc + 1] = 0) se = 1;
}}
pd = global.{g}_dens;
if (se = 1) pd = 0.5;
if (random(1) < pd) {{
pf = instance_create(sc * global.{g}_cellsz + random(global.{g}_cellsz), sr * global.{g}_cellsz + random(global.{g}_cellsz), global.{g}_puffobj);
if (sv = 2) pf.image_blend = make_color_rgb(255, 130 + random(60), 55 + random(45));
}}
}}
}}
}}
{f"alarm[0] = {lo} + random({hi});" if st.lightning else ""}
"""
        # Step: the damage test, and the two frame counters the Draw reads.
        # The pause guard is above them so a frozen storm stays frozen mid-bolt;
        # the edit-rules guard is below, so a mission being written still storms,
        # it just cannot kill you.
        #
        # ⚠ The hit goes through the game's own `damage(amount, target)` script,
        # never through `l_hp -=`, and the difference is the whole effect. In BSF
        # a section has no "am I dead?" test of its own — there is no `l_hp <= 0`
        # check anywhere in the game — so destruction is the *attacker's* job,
        # and `damage()` is where every weapon and every asteroid does it:
        #
        #     if target.l_hp <= amount  ->  target.instance_destroy(), and
        #                                   target.l_owner.l_syshp -= target.l_hp
        #     else                      ->  target.l_hp -= amount, and
        #                                   target.l_owner.l_syshp -= amount
        #
        # Subtracting from `l_hp` by hand skips both halves. The storm did that
        # until 2026-08-14, which made it decorative: no section it damaged could
        # ever be destroyed however long you sat in the gas, and the ship's system
        # bar (`l_syshp/l_maxsyshp`, the second HUD bar) never moved. Its one real
        # effect was invisible — `l_hp` went negative, so the next bullet to touch
        # that section one-shot it.
        #
        # Destroying inside `with (ShipSection)` is the pattern the stock
        # explosion code already runs — `with (ctr_Player) { ... if l_hp <= dmg
        # then instance_destroy() ... }` — and a section's Destroy event cascades
        # to its children from inside that same loop there too. Whatever GM7 does
        # about an instance the loop has yet to reach, the game has been doing it
        # since 0.90d.
        #
        # ⚠ The hull is a **separate pool and a separate hit**, and without it the
        # storm still could not kill: measured in-game on 2026-08-14, a Hestia
        # stripped to zero sections keeps flying, `global.<id>_failed` stays 0 and
        # the mission carries on. BSF ships carry two bars — `l_hp/l_maxhp` on the
        # ship instance and `l_syshp/l_maxsyshp` summed from the parts — and
        # `ctr_Ship` has no step that reads the second, so nothing about losing
        # every section destroys the ship. Only `damage(d, <the ship>)` does, and
        # that is what raises MISSION FAILED. Hence the second test below, on the
        # ship's own position: the sections are the parts you lose, the hull is
        # the thing that dies. `damage()` skips the `l_syshp` debit for anything
        # parented to `ctr_Ship`, so hitting the hull correctly does not also
        # discount the parts hanging off it.
        step = f"""
var sr, sc, sv;
if (global.ed_pause) exit;
if (l_bolt > 0) l_bolt -= 1;
if (l_flash > 0) l_flash -= 1;
if (global.ed_edit) exit;
if (instance_exists(global.{g}_ship)) {{
with (ShipSection) {{
if (l_owner = global.{g}_ship) {{
sr = floor(y / global.{g}_cellsz);
sc = floor(x / global.{g}_cellsz);
if (sr >= 0) {{ if (sr < global.{g}_rows) {{ if (sc >= 0) {{ if (sc < global.{g}_cols) {{
sv = global.{g}_g[sr * global.{g}_cols + sc];
if (sv = 1) damage(global.{g}_d1, id);
if (sv = 2) damage(global.{g}_d2, id);
}} }} }} }}
}}
}}
sr = floor(global.{g}_ship.y / global.{g}_cellsz);
sc = floor(global.{g}_ship.x / global.{g}_cellsz);
if (sr >= 0) {{ if (sr < global.{g}_rows) {{ if (sc >= 0) {{ if (sc < global.{g}_cols) {{
sv = global.{g}_g[sr * global.{g}_cols + sc];
if (sv = 1) damage(global.{g}_d1, global.{g}_ship);
if (sv = 2) damage(global.{g}_d2, global.{g}_ship);
}} }} }} }}
}}
"""
        # Alarm 0: one lightning strike. Both ends are picked from filled cells
        # that are on screen — a bolt struck somewhere in the room is a bolt
        # nobody sees, and a bolt with one end outside the cloud reads as a stray
        # line rather than as discharge inside gas. The pick is retried rather
        # than taken blind; with the view outside the storm entirely the alarm
        # simply reschedules and nothing flashes.
        alarm = f"""
var i, tries, sx, sy, ex, ey, nx, ny, dd, got, k;
alarm[0] = {lo} + random({hi});
if (global.ed_pause) exit;
if (global.{g}_nsp < 1) exit;
got = 0; sx = 0; sy = 0; ex = 0; ey = 0;
for (tries = 0; tries < 24; tries += 1) {{
if (got < 2) {{
i = floor(random(global.{g}_nsp));
nx = global.{g}_spx[i] + random(global.{g}_spw[i]);
ny = global.{g}_spy[i] + random(global.{g}_cellsz);
if (nx > view_xview[0]) {{ if (nx < view_xview[0] + view_wview[0]) {{
if (ny > view_yview[0]) {{ if (ny < view_yview[0] + view_hview[0]) {{
if (got = 0) {{ sx = nx; sy = ny; got = 1; }}
else {{
dd = point_distance(sx, sy, nx, ny);
if (dd > 150) {{ if (dd < 550) {{ ex = nx; ey = ny; got = 2; }} }}
}}
}} }} }} }}
}}
}}
if (got < 2) exit;
l_bn = 7;
l_bx[0] = sx; l_by[0] = sy;
for (k = 1; k < l_bn; k += 1) {{
l_bx[k] = sx + (ex - sx) * k / l_bn - 30 + random(60);
l_by[k] = sy + (ey - sy) * k / l_bn - 30 + random(60);
}}
l_bx[l_bn] = ex; l_by[l_bn] = ey;
l_bolt = 4 + random(3);
l_flash = 9;
"""
        # Draw: the flash a strike puts through the gas, and nothing else.
        #
        # There is deliberately no wash under the clouds. A rectangle per row run
        # is the obvious way to draw a masked field and it was the first thing
        # here, at every alpha from 0.075 down to 0.03 — and it is always wrong.
        # The runs are rectangles, neighbouring rows step by a whole cell, and
        # additive red over black renders that staircase perfectly: inside a
        # thick storm the clouds bury it, but a freshly painted stroke is a row of
        # visible blocks. It also earns nothing. Boundary cells get a cloud at
        # p=0.5 whatever `density` says, so a painted cell is never far from one,
        # and each cloud orbits its home rather than drifting off it — the thing
        # you can see stays where the thing that bites is.
        draw = f"""
var vx, vy, vw, vh;
if (l_flash < 1) exit;
vx = view_xview[0]; vy = view_yview[0]; vw = view_wview[0]; vh = view_hview[0];
draw_set_blend_mode(bm_add);
with (global.{g}_puffobj) {{
if (x > vx - 500) {{ if (x < vx + vw + 500) {{ if (y > vy - 500) {{ if (y < vy + vh + 500) {{
draw_sprite_ext(sprite_index,image_index,x,y,image_xscale,image_yscale,image_angle,merge_color(image_blend,c_white,0.35),image_alpha * other.l_flash * 0.12);
}} }} }} }}
}}
draw_set_alpha(1);
draw_set_blend_mode(bm_normal);
"""
        # A gas cloud. spr_Nebula is a palette mask, so image_blend is what makes
        # it red; the rest is ter_Nebula's own animation — alpha breathing and a
        # slow rotate on a 9-frame alarm — plus a curl, which is engine movement
        # and therefore free: `direction` turning a little every tick walks each
        # puff around a slow circle instead of blowing the cloud off the map.
        pcreate = """
var ran;
sprite_index = spr_Nebula;
ran = random(1.2);
image_xscale = 1 + ran;
image_yscale = 1 + ran;
image_angle = random(360);
image_alpha = 0.13 + random(0.15);
image_blend = make_color_rgb(180 + random(75), 26 + random(46), 26 + random(34));
l_lo = image_alpha;
l_hi = image_alpha + 0.15;
l_glow = 0.004 + random(0.006);
l_rotate = -0.25 + random(0.5);
l_curl = 0.4 + random(0.9);
if (random(1) < 0.5) l_curl = -l_curl;
direction = random(360);
speed = 0.02 + random(0.06);
depth = 150 + random(260);
alarm[0] = 1 + random(9);
"""
        palarm = """
image_alpha += l_glow;
if (image_alpha < l_lo) { image_alpha = l_lo; l_glow *= -1; }
if (image_alpha > l_hi) { image_alpha = l_hi; l_glow *= -1; }
image_angle += l_rotate;
direction += l_curl;
alarm[0] = 9;
"""
        # A puff is up to 700 units across, so the cull margin is not the game's
        # usual GUI_DrawRange — a cloud whose centre is off screen still covers
        # half the view.
        pdraw = """
if (x < view_xview[0] - 500) exit;
if (x > view_xview[0] + view_wview[0] + 500) exit;
if (y < view_yview[0] - 500) exit;
if (y > view_yview[0] + view_hview[0] + 500) exit;
draw_sprite_ext(sprite_index,image_index,x,y,image_xscale,image_yscale,image_angle,image_blend,image_alpha);
"""
        out = {"create": create, "step": step, "draw": draw,
               "pcreate": pcreate, "palarm": palarm, "pdraw": pdraw}
        if st.lightning:
            out["alarm"] = alarm
        return out

    # ---- whole-file emission ---------------------------------------------

    def check_bounds(self):
        """Nothing the ship has to reach may sit outside the room.

        The room size is editable in tools/editor now, and shrinking it is the
        one edit that can strand something: a beacon outside the room is a
        MoveToArea the ship can never enter, so the mission stalls on that rung
        forever, and a spawn outside it never joins the fight. Both are silent
        at runtime, which is exactly why they are errors here.
        """
        m = self.m
        w, h = m["room"]["width"], m["room"]["height"]
        where = f"the {w}x{h} room"
        out = lambda x, y: x < 0 or y < 0 or x > w or y > h  # noqa: E731
        if w < 1024 or h < 768:
            self.lint.warn(f"room is {w}x{h}, smaller than the 1024x768 view — it will not scroll")
        if out(m["player"]["x"], m["player"]["y"]):
            self.lint.err(f"player: start ({m['player']['x']}, {m['player']['y']}) is outside {where}")
        for i, gt in enumerate(m.get("gates", [])):
            if out(gt["x"], gt["y"]):
                self.lint.err(f"gates[{i}]: beacon ({gt['x']}, {gt['y']}) is outside {where} "
                              f"— the ship can never reach it")
        for i, b in enumerate(m["beats"]):
            for sp in b.get("spawn", []):
                if out(sp["x"], sp["y"]):
                    # spawn_label, not sp["object"] — a spawn may name a ship
                    # file instead, and this is reached only when the spawn is
                    # already out of bounds, so the KeyError hid behind the
                    # very condition it was meant to report.
                    self.lint.err(f"beat {i}: {spawn_label(sp)} spawns at "
                                  f"({sp['x']}, {sp['y']}), outside {where}")
            if "gate_at" in b and out(b["gate_at"]["x"], b["gate_at"]["y"]):
                self.lint.err(f"beat {i}: gate_at ({b['gate_at']['x']}, {b['gate_at']['y']}) is outside {where}")
            self.check_ping(i, b)

    #: How far a ping may sit from the thing it is announcing before it stops
    #: looking deliberate. A big hull is a few hundred units across, so this is
    #: loose enough that pointing at a station's origin passes wherever its art
    #: ends; the case it exists for was out by 926.
    PING_NEAR = 500

    def check_ping(self, i, b):
        """Both forms of `ping:`, and the drift the fixed one is prone to.

        A link that does not resolve is an error — the ping would be dropped
        entirely, and silently losing the thing that tells the player where to
        look is not something to discover in a playtest.

        A *fixed* ping sitting far from every spawn in its own beat is a
        warning, and the warning's job is to recommend the link rather than to
        recite coordinates. It cannot be an error: a ping at a place rather than
        a thing is perfectly legal, and nothing here can tell which was meant.
        """
        if "ping" not in b:
            return
        p = b["ping"]
        if not isinstance(p, (list, tuple)):
            anchors = ping_anchors(self.m)
            if str(p) not in anchors:
                named = ", ".join(sorted(anchors)) or "none"
                self.lint.err(f"beat {i}: ping follows '{p}', which is not a named "
                              f"spawn or 'player' (have: {named})")
            return
        if not b.get("spawn"):
            return
        px, py = p
        near = min(b["spawn"], key=lambda sp: math.hypot(sp["x"] - px, sp["y"] - py))
        d = math.hypot(near["x"] - px, near["y"] - py)
        if d > self.PING_NEAR:
            how = (f"follow it with `ping: {near['name']}`" if "name" in near
                   else "name that spawn and follow it")
            self.lint.warn(
                f"beat {i}: ping ({px}, {py}) is {int(d)} units from "
                f"{spawn_label(near)}, the nearest spawn in the same beat. If it is "
                f"meant to announce that spawn, {how} — a fixed pair does not move "
                f"when the spawn does")

    def build(self):
        m, g, lint = self.m, self.gid, self.lint
        self.check_bounds()
        numbered = self.number_beats()

        # One pass over the beats; both ladders read the same statements.
        acts = {n: self.actions(b, f"beat@{n}") for n, b in numbered}

        # -- ladder (user event 0)
        rungs = []
        for n, b in numbered:
            # The tracer the editor follows while the game is playing. Two
            # global writes per dialogue panel, so it stays in for real players
            # too rather than hiding behind an edit flag it would have to test.
            stmts = [f"global.ed_beat = {n}", "global.ed_beatseq += 1"]
            stmts += [s for _, s in acts[n]]
            has_msg = ("say" in b) or ("objective" in b)
            if not has_msg and not b.get("win"):
                stmts.append(f"l_messagecount = {n + 1}; event_user(0)")
            body = ";\n".join(stmts) + ";"
            rungs.append(f"if (l_messagecount = {n}) {{\n{body}\n}}")
        # `g` is the gate scratch, `s` the spawn scratch — see gate_stmt and
        # spawn_stmt. Declared once per event, unused ones cost nothing.
        ladder = "var g, s;\n" + "\nelse ".join(rungs)

        # -- seek ladder (user event 1): state-only, cumulative, delta-guarded
        # The ladder is not idempotent — seeking to 5 and then to 11 must not
        # re-run 1..5 and spawn everything twice — so each rung carries the lower
        # bound l_seek_from as well as the target. Only a forward seek is cheap;
        # backward is a warm re-entry, then forward from 0.
        seek_rungs = []
        for n, _ in numbered:
            stmts = [s for k, s in acts[n] if k in self.SEEKABLE]
            if not stmts:
                continue
            body = ";\n".join(stmts) + ";"
            seek_rungs.append(f"if (l_seek >= {n}) {{ if (l_seek_from < {n}) {{\n{body}\n}} }}")
        # Where play resumes. Rung numbers skip (a `wait: gate` beat reserves the
        # next slot for the gate's own +1), so l_seek + 1 would stall the mission
        # on a rung that does not exist — the compiler emits the real successor.
        nums = [n for n, _ in numbered]
        tail = [f"if (l_seek = {n}) l_messagecount = "
                f"{nums[i + 1] if i + 1 < len(nums) else n + 1};"
                for i, n in enumerate(nums)]
        seek = "var s;\n" + "\n".join(seek_rungs) + f"""
l_seek_from = l_seek;
global.ed_beat = l_seek;
global.ed_beatseq += 1;
{chr(10).join('else ' + t if i else t for i, t in enumerate(tail))}
"""

        # -- start beat (alarm 2)
        # Not part of the seek ladder: it fires from alarm[2] on entry, long
        # before any seek can be issued (the menu walk alone is far more than
        # its 45 frames), so a seek always starts from a mission that has run it.
        start = self.m["beats"][0]
        start_stmts = ["global.ed_beat = 0", "global.ed_beatseq += 1"]
        start_stmts += [s for _, s in self.actions(start, "beat@start")]
        start_code = "var s;\n" + ";\n".join(start_stmts) + ";"

        # -- create event
        p = m["player"]
        lint.resource(p["object"], "player")
        fail_t = self.tvar(m["fail"]["ship"], "fail.ship")
        storm = self.storm
        neb = m.get("scenery", {}).get("nebula", 0)
        # Every damaged hull's slot is declared here, empty. The tick reads the
        # whole table from the first frame but the spawns land beats later, so
        # each slot has to hold something instance_exists() can answer for —
        # `noone` — rather than being undefined, which is a read error per slot
        # per second and takes the rest of the event with it.
        # importShip is not self-contained: it caches every design it parses in
        # global.l_fnames / global.l_objects, and it reads that cache before it
        # checks whether it needs to build anything. Nothing creates the cache
        # except the controllers of the rooms that ship with the loader — the
        # sandbox, the testing room, the wave modes. A campaign room has none of
        # them, so importShip died on `Unknown variable l_fnames` inside
        # parseShipAllied and took the rest of the beat with it.
        #
        # This is the game's own initialiser, copied verbatim from those
        # controllers rather than reinvented. Its `variable_global_exists` guard
        # is also the game's; note that the career-reset path destroys the list
        # without clearing the variable, which would leave this guard satisfied
        # by a dangling id — a hazard the stock rooms carry too, and not one to
        # diverge from the engine over.
        # The second half is `global.jumpinships`. importShip does not place the
        # hull itself — it hands it to a ctr_Spawner, whose alarm 10 opens with
        # `if global.jumpinships && ...`. Undefined, that alarm throws, the
        # spawner never finishes, and the design silently never arrives: four
        # berthed hulls made of plain objects appeared while the one imported
        # design did not. Assigned rather than guarded, because it is a
        # statement about this room — a campaign station materialises, it does
        # not warp in — and because the sandbox sets it the same unconditional
        # way on entry, so nothing of the player's is being kept from them.
        # Asked of the mission, not tracked by a flag set while emitting. A flag
        # is only True here if the ladder happened to be built before this
        # block — true today, enforced by nothing. Reorder those two and the
        # initialiser silently vanishes, which does not fail loudly: importShip
        # dies on `Unknown variable l_fnames` inside parseShipAllied and takes
        # the rest of the beat with it. `damaged` genuinely needs emission-time
        # slot allocation; this does not.
        shipinit = ""
        if any("ship" in sp for b in m["beats"] for sp in b.get("spawn", [])):
            shipinit = ('if !variable_global_exists("l_fnames") then\n'
                        "{\n"
                        "global.l_fnames = ds_list_create();\n"
                        "global.l_objects[0] = -4;\n"
                        "}\n"
                        "global.jumpinships = false;")
        # No slot count global: the only reader is alarm 6's loop bound, emitted
        # by this same method with self.damaged in scope, so the literal goes
        # straight in. A runtime counter would be a third table to keep in step
        # with the two arrays, and a count that outran the declarations would
        # read an undefined array element — which in GM7 aborts the alarm and
        # silently stops holding every damaged hull, not just the extra one.
        dmginit = ""
        if self.damaged:
            dmginit = "\n".join(
                [f"global.{g}_dmg[{i}] = noone; global.{g}_dmgf[{i}] = {f};"
                 for i, f in enumerate(self.damaged)]
                + ["alarm[6] = 60;"])
        # The controller's depth is the stock mission controller's, so the
        # interference pass draws over the world the way ctr_Mission3's does.
        create = f"""
var s;
depth = -9;
global.gamecontroller = self.id;
l_messagecount = 0;
l_seek = 0; l_seek_from = 0;
l_temp = -4;
global.ed_beat = -1; global.ed_beatseq += 1;
global.{g}_won = 0; global.{g}_failed = 0; global.{g}_meteors = 0;
global.{g}_interf = 0;
{shipinit}
{dmginit}
global.World_MaxRangeSqr = sqr(World_MaxRange);
stopMusic();
s = instance_create({p['x']},{p['y']},{p['object']});
global.{g}_ship = s;
with (ShipSection) {{ if (l_owner = global.{g}_ship) l_hp = l_hp * {p.get('damage', 1)}; }}
repeat ({neb}) {{ instance_create(random(room_width),random(room_height),ter_Nebula); }}
{f"instance_create(0,0,global.{g}_stormobj);" if storm.any() else ""}
centreCamera({p['x']},{p['y']},0);
global.lasteventx = {p['x']}; global.lasteventy = {p['y']};
alarm[2] = 45;
"""
        # -- step: fail checks
        step = f"""
if (global.ed_edit) exit;
if (global.{g}_won = 0) {{
if (global.{g}_failed = 0) {{
if (!instance_exists(global.{g}_ship)) {{
global.{g}_failed = 1;
centreCamera(global.lasteventx,global.lasteventy,0);
missionFail({fail_t});
}}
}}
}}
"""
        # -- alarm 5: meteor spawner
        #
        # Two numbers, and between them they are the density. `cap` is the one
        # that sets it: a meteor lives until it leaves the room (obs_Meteor's own
        # alarm 2 computes the time to the edge from its velocity and alarm 1
        # destroys it there), which for a rock crossing EP9's 5000-unit room at
        # ~1.6 units/step is around a minute — long enough that the population
        # saturates at `cap` and stays there. `interval` is only the refill rate:
        # one rock per alarm, so an empty field reaches `cap` after cap*interval
        # frames and it wants to be well under the lifetime or the cap is never
        # reached. Scale the two together and the field gets denser at the same
        # ramp — 6x density is cap*6 with interval/6.
        #
        # The band is ahead of the ship (x + 500..800) and one view tall
        # (y ± 400), and `direction` 150..210 walks the rocks back through it, so
        # the author's density is what arrives head-on, not what exists somewhere
        # in the room.
        met = m.get("meteors", {})
        interval = met.get("interval", METEORS["interval"])
        cap = met.get("cap", METEORS["cap"])
        meteor = f"""
if (global.{g}_meteors = 1) {{
if (instance_number(obs_Meteor) < {cap}) {{
if (instance_exists(global.{g}_ship)) {{
var mm, px, py;
px = global.{g}_ship.x; py = global.{g}_ship.y;
mm = instance_create(px + 500 + random(300), py - 400 + random(800), obs_Meteor);
mm.direction = 150 + random(60);
mm.speed = 1 + random(1.2);
mm.image_xscale = 0.5 + random(0.4);
mm.image_yscale = mm.image_xscale;
}}
}}
alarm[5] = {interval};
}}
"""
        # -- alarm 6: hold the damaged hulls where the author put them
        #
        # See damage_stmt. The engine heals any section under half maximum once
        # a second and that same alarm is what trails the smoke, so the only way
        # to keep a wreck smoking is to keep pushing it back down. Clamping
        # rather than re-multiplying: multiplying compounds, and four seconds of
        # 0.3 would have the hull at 0.008 and dead.
        #
        # `var` on every temporary is not style — an undeclared name becomes an
        # instance variable and resolves against `other` inside `with`, which
        # here would silently read the section's own `k` and never match.
        # `l_syshp` is recomputed from the sections it is the sum of, because
        # the repair alarm adds to both and only the sections get clamped.
        dmghold = f"""
var i, k, f;
for (i = 0; i < {len(self.damaged)}; i += 1) {{
k = global.{g}_dmg[i];
f = global.{g}_dmgf[i];
if (instance_exists(k)) {{
k.l_syshp = 0;
with (ShipSection) {{
if (l_owner = k) {{
if (l_hp > l_maxhp * f) l_hp = l_maxhp * f;
k.l_syshp += l_hp;
}}
}}
}}
}}
alarm[6] = 60;
"""

        # -- interference (controller Draw)
        # Stock ctr_Mission3's Draw, generalised into a verb: while the storm is
        # interfering, every nebula is re-drawn additively with a random alpha
        # kick, and every ship section leaves a randomly-scaled half-alpha echo at
        # its previous position. It is the only stock effect in the game that
        # makes the *ships* look wrong, which is why it reads as interference and
        # not as weather.
        #
        # One deviation, measured: stock draws the echo exactly at (xprevious,
        # yprevious), so a ship holding position has the echo land on itself and
        # the effect all but vanishes — mission 3 never noticed because its
        # player ship is always under way. A few units of jitter makes a
        # stationary hull shimmer too, which is what a ship sitting inside a
        # storm should look like.
        interf_puffs = f"""
with (global.{g}_puffobj) {{
if (x > vx - 500) {{ if (x < vx + vw + 500) {{ if (y > vy - 500) {{ if (y < vy + vh + 500) {{
draw_sprite_ext(sprite_index,image_index,x,y,image_xscale,image_yscale,image_angle,image_blend,image_alpha * (0.6 + random(0.9)));
}} }} }} }}
}}""" if storm.any() else ""
        # The bolt is drawn from here rather than from the storm object because a
        # bolt has to be in *front* of the cloud it is inside: the storm sits at
        # depth 700 so its wash stays behind the puffs, and a bolt drawn there
        # comes out as a thin line glimpsed through the gas. Three passes — a wide
        # dim halo, a mid glow, a thin white core — because one line of any width
        # reads as a drawn line and not as light.
        bolt = f"""
with (global.{g}_stormobj) {{
if (l_bolt > 0) {{
draw_set_blend_mode(bm_add);
draw_set_color(make_color_rgb(255, 70, 55));
draw_set_alpha(0.20);
for (i = 0; i < l_bn; i += 1) {{ draw_line_width(l_bx[i], l_by[i], l_bx[i + 1], l_by[i + 1], 24); }}
draw_set_color(make_color_rgb(255, 140, 110));
draw_set_alpha(0.45);
for (i = 0; i < l_bn; i += 1) {{ draw_line_width(l_bx[i], l_by[i], l_bx[i + 1], l_by[i + 1], 8); }}
draw_set_color(make_color_rgb(255, 242, 228));
draw_set_alpha(0.95);
for (i = 0; i < l_bn; i += 1) {{ draw_line_width(l_bx[i], l_by[i], l_bx[i + 1], l_by[i + 1], 2); }}
draw_set_alpha(1);
draw_set_blend_mode(bm_normal);
}}
}}""" if storm.any() else ""
        cdraw = f"""
var vx, vy, vw, vh, i;
vx = view_xview[0]; vy = view_yview[0]; vw = view_wview[0]; vh = view_hview[0];{bolt}
if (global.{g}_interf = 0) exit;
draw_set_blend_mode(bm_add);
with (ter_Nebula) {{
draw_sprite_ext(sprite_index,image_index,x,y,image_xscale,image_yscale,image_angle,image_blend,image_alpha + random(0.4));
}}{interf_puffs}
draw_set_blend_mode(bm_normal);
with (ShipSection) {{
draw_sprite_ext(sprite_index,image_index,xprevious - 4 + random(8),yprevious - 4 + random(8),image_xscale * (1 + random(0.22)),image_yscale * (1 + random(0.22)),image_angle,l_colour,image_alpha / 2);
}}
"""

        # -- storm object events (one instance; the field, the clouds, the damage)
        scode = self.storm_events() if storm.any() else {}

        # lint every event string we are about to emit
        frags = [("ladder", ladder), ("seek", seek), ("start", start_code),
                 ("create", create), ("step", step), ("meteor", meteor),
                 ("cdraw", cdraw)]
        if self.damaged:
            frags.append(("dmghold", dmghold))
        frags += [(f"storm.{k}", v) for k, v in sorted(scode.items())]
        for name, frag in frags:
            lint.event_string(frag, name)

        r = m["room"]
        slot = self.room_slot
        texts = "\n".join(f'{n} = "{s}";' for n, s in self.texts)

        # Two halves, and the split is what makes the editor's reload safe.
        # GM7 has no room_delete and no way to un-add an object, so a second
        # room_add would leak a room per apply — the indices are therefore
        # claimed once and everything downstream re-binds onto them. The room's
        # creation code keeps naming a valid controller because that index never
        # changes. Unlimited reloads, nothing leaked.
        binds = []
        if storm.any():
            binds += [
                (f"global.{g}_stormobj", 0, 0, scode["create"]),
                (f"global.{g}_stormobj", 3, 0, scode["step"]),
                (f"global.{g}_stormobj", 8, 0, scode["draw"]),
                (f"global.{g}_puffobj", 0, 0, scode["pcreate"]),
                (f"global.{g}_puffobj", 2, 0, scode["palarm"]),
                (f"global.{g}_puffobj", 8, 0, scode["pdraw"]),
            ]
            if "alarm" in scode:
                binds.append((f"global.{g}_stormobj", 2, 0, scode["alarm"]))
        binds += [
            (f"global.{g}_ctr", 0, 0, create),
            (f"global.{g}_ctr", 2, 2, start_code),
            (f"global.{g}_ctr", 2, 5, meteor),
        ]
        if self.damaged:
            binds.append((f"global.{g}_ctr", 2, 6, dmghold))
        binds += [
            (f"global.{g}_ctr", 3, 0, step),
            (f"global.{g}_ctr", 7, 10, ladder),
            (f"global.{g}_ctr", 7, 11, seek),
            (f"global.{g}_ctr", 8, 0, cdraw),
        ]
        rebind = "\n".join(
            f"object_event_clear({obj}, {t}, {n2});\n"
            f"object_event_add({obj}, {t}, {n2},\n    {gml_quote_lines(code)});"
            for obj, t, n2, code in binds)

        out = f"""// GENERATED by campaign/build.py from campaign/missions/{m['_src']} — DO NOT EDIT.
// Act II Episode {m['episode']}: {m['title']}  (global.mission = {m['mission']})
//
// Loading this file a second time is safe, and is how the editor applies a
// change: the object and room indices are claimed once, everything else is
// re-bound. Re-entering the mission afterwards replays it from the new code.

// ---------------------------------------------------------------- dialogue
{texts}

// ------------------------------------------------------------ editor state
// Three flags the editor drives, all mission-independent on purpose: only one
// mission is loaded at a time, and a per-mission name would mean mods/editor.gml
// had to know which mission it is talking to before it could set anything.
//
//   ed_edit   0 is the real game — storm cells bite, a lost ship fails the
//             mission. The editor raises it so a mission cannot be lost while
//             it is being written, and lowers it to test failure deliberately.
//   ed_pause  the editor's freeze. The stock sandbox pattern stops ships,
//             turrets and actors; it knows nothing about the storm object this
//             compiler invents, and that is the one generated thing whose Step
//             changes the world.
//   ed_beat   the playhead tracer: which rung last fired, and a counter that
//             also ticks on a re-entry, so a repeat of a rung is
//             distinguishable from a stall.
//
// None of them is reset by a reload — the mode belongs to the session.
if (!variable_global_exists('ed_edit')) global.ed_edit = 0;
if (!variable_global_exists('ed_pause')) global.ed_pause = 0;
if (!variable_global_exists('ed_beat')) {{ global.ed_beat = -1; global.ed_beatseq = 0; }}

// Declared here rather than only in the controller's Create, because a hot
// reload re-binds the Draw event of a controller instance the *old* code
// created, and that instance never ran a Create that knew about this flag.
// Reading a global that does not exist aborts the action it is read in.
if (!variable_global_exists('{g}_interf')) global.{g}_interf = 0;

{self.storm_field() if storm.any() else ""}

// ------------------------------------------------------------- define once
// GM7 has no room_delete, so a room_add per reload would leak one every time.
//
// One guard per index rather than one around the lot: a mod that grows a new
// object has to be able to claim it in a session that is already running, and a
// single `if (!variable_global_exists(ctr))` around everything would skip the
// new line forever on exactly the reload that needed it.
{f"if (!variable_global_exists('{g}_stormobj')) global.{g}_stormobj = object_add();" if storm.any() else ""}
{f"if (!variable_global_exists('{g}_puffobj')) global.{g}_puffobj = object_add();" if storm.any() else ""}
if (!variable_global_exists('{g}_ctr')) {{
global.{g}_ctr = object_add();
global.act2_room{slot} = room_add();
room_set_code(global.act2_room{slot},
    'instance_create(0,0,ctr_GUI); instance_create(0,0,' + string(global.{g}_ctr) + ');');
// The view is authored once and never re-asserted. mods/resolution.gml rewrites
// every room's view port at startup to the picked resolution -- that is how the
// drawing region gets built at anything other than 1024x768 -- so a reload that
// set this again would drop the mission room, and only the mission room, back to
// 4:3 inside a widescreen window.
room_set_view(global.act2_room{slot}, 0, 1, 0, 0, 1024, 768, 0, 0, 1024, 768, 32, 32, -1, -1, -1);
room_set_view_enabled(global.act2_room{slot}, 1);
}}

// ------------------------------------------------------- re-bind every load
{rebind}

room_set_width(global.act2_room{slot}, {r['width']});
room_set_height(global.act2_room{slot}, {r['height']});
room_set_caption(global.act2_room{slot}, "{r.get('caption', m['title'])}");
room_set_background_color(global.act2_room{slot}, c_black, 1);
"""
        return out, numbered

    # (the act2.gml breadcrumb runs after execute_file of this mod returns, so
    #  a syntax error anywhere above leaves mods/act2.log unwritten)


# ----------------------------------------------------------------------------
# HTML viewer
# ----------------------------------------------------------------------------

def esc(s):
    return html.escape(str(s), quote=True)


def note_lines(v):
    """`note:` as a list of lines, however it was written.

    A list is the form the editor writes and the one that diffs by the line; a
    bare string is accepted because hand-editing a one-line note that way is the
    obvious thing to do and refusing it would be pedantry.
    """
    if v is None:
        return []
    return [str(x) for x in v] if isinstance(v, (list, tuple)) else [str(v)]


def spawn_label(sp):
    """What to call a spawn on the transcript and the map.

    A spawn names either a game object or a ship design file. The file reads
    better as its bare name than as the path the loader receives, which is long
    and identical in its leading half for every ship we ship.
    """
    if "ship" in sp:
        return sp["ship"].replace("\\", "/").rsplit("/", 1)[-1]
    return sp["object"]


def beat_html(n, b):
    trig = str(n)
    if b.get("start"):
        trig = "start"
    rows = []
    # First, because it is the reason for everything under it. The transcript is
    # where someone reads a mission end to end, which makes it the one place the
    # reasoning is worth as much as the dialogue.
    if "note" in b:
        txt = "<br>".join(esc(l) for l in note_lines(b["note"]))
        rows.append(f'<p class="note beatnote">{txt}</p>')
    for key in ("music", "eerie", "meteors", "interference"):
        # onoff(), because YAML 1.1 parses a bare `on` as True and the viewer
        # should print the word the mission file uses.
        if key in b:
            rows.append(f'<p class="note"><span class="tag">{key}: '
                        f'{esc(Emitter.onoff(b[key]))}</span></p>')
    if b.get("autosave"):
        rows.append('<p class="note"><span class="tag save">autosave</span></p>')
    if "camera" in b:
        c = b["camera"]
        rows.append(f'<p class="note">camera → ({c["x"]}, {c["y"]}) speed {c.get("speed", 60)}</p>')
    for sp in b.get("spawn", []):
        nm = f' as <code>{esc(sp["name"])}</code>' if "name" in sp else ""
        what = esc(spawn_label(sp))
        team = f' ({esc(sp["team"])})' if "ship" in sp else ""
        rows.append(f'<p class="note">spawn <code>{what}</code>{team} '
                    f'at ({sp["x"]}, {sp["y"]}){nm}</p>')
    if "objective" in b:
        rows.append(f'<p class="line obj"><span class="who">New Objective</span>'
                    f'<q>{esc(b["objective"]).replace("#", "<br>")}</q></p>')
    if "say" in b:
        s = b["say"]
        cls = {"red": "foe", "magenta": "alien", "white": "log"}.get(s.get("color", "green"), "hq")
        rows.append(f'<p class="line {cls}"><span class="who">{esc(s["who"])}</span>'
                    f'<q>{esc(s["text"]).replace("#", "<br>")}</q></p>')
    if "gate" in b:
        rows.append(f'<p class="note">spawn gate <strong>#{b["gate"] + 1}</strong></p>')
    if "gate_at" in b:
        ga = b["gate_at"]
        rows.append(f'<p class="note">spawn ad-hoc gate at ({ga["x"]}, {ga["y"]})</p>')
    if b.get("wait") == "gate":
        trig += f'<span class="cond">→ gate reach (slot {n + 1 if isinstance(n, int) else "?"} reserved)</span>'
    if b.get("win"):
        rows.append('<p class="note"><strong>Mission Accomplished.</strong></p>')
    return f'<div class="beat"><div class="trig">{trig}</div><div class="bd">{"".join(rows)}</div></div>'


def map_svg(m, storm=None):
    W, H = m["room"]["width"], m["room"]["height"]
    parts = [f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet" '
             f'style="width:100%;height:auto;background:#04070a;border:1px solid #1d2a2a;border-radius:2px">']
    # The storm is the mask, drawn as the runs the game itself fills.
    if storm:
        for x, y, w in storm.spans():
            parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{storm.cell}" '
                         f'fill="rgba(255,60,50,0.16)"/>')
    pts = [(m["player"]["x"], m["player"]["y"])] + [(gt["x"], gt["y"]) for gt in m.get("gates", [])]
    for b in m["beats"]:
        if "gate_at" in b:
            pts.append((b["gate_at"]["x"], b["gate_at"]["y"]))
    poly = " ".join(f"{x},{y}" for x, y in pts)
    parts.append(f'<polyline points="{poly}" fill="none" stroke="rgba(78,240,138,0.55)" '
                 f'stroke-width="6" stroke-dasharray="24 18"/>')
    px, py = pts[0]
    parts.append(f'<circle cx="{px}" cy="{py}" r="28" fill="#4ef08a"/>'
                 f'<text x="{px}" y="{py - 44}" fill="#4ef08a" font-size="52" '
                 f'text-anchor="middle" font-family="monospace">START</text>')
    for i, (x, y) in enumerate(pts[1:], 1):
        parts.append(f'<circle cx="{x}" cy="{y}" r="22" fill="none" stroke="#4ef08a" stroke-width="5"/>'
                     f'<text x="{x}" y="{y - 34}" fill="#8b9c95" font-size="44" '
                     f'text-anchor="middle" font-family="monospace">{i}</text>')
    for b in m["beats"]:
        for sp in b.get("spawn", []):
            parts.append(f'<rect x="{sp["x"] - 26}" y="{sp["y"] - 26}" width="52" height="52" '
                         f'fill="none" stroke="#ff5cff" stroke-width="5"/>'
                         f'<text x="{sp["x"]}" y="{sp["y"] - 38}" fill="#ff5cff" font-size="40" '
                         f'text-anchor="middle" font-family="monospace">'
                         f'{esc(spawn_label(sp))}</text>')
    parts.append("</svg>")
    return "".join(parts)


HTML_SHELL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  --ground:#06090a; --panel:#0c1214; --panel2:#101819; --rule:#1d2a2a; --rule-soft:#16201f;
  --ink:#c6d3cd; --ink-dim:#8b9c95; --ink-faint:#5d6d68;
  --phos:#4ef08a; --phos-hot:#00ff00; --hostile:#ff5a4d; --alien:#ff5cff; --log:#f2f7f4;
  --mono:ui-monospace,"SF Mono","Cascadia Mono","JetBrains Mono","DejaVu Sans Mono",Consolas,monospace;
  --serif:Charter,"Bitstream Charter","Iowan Old Style",Georgia,serif;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--ground); color:var(--ink); font:17px/1.62 var(--serif); }
.wrap { max-width:60rem; margin:0 auto; padding:2.5rem clamp(1rem,4vw,2.2rem) 5rem; }
h1,h2,h3 { font-family:var(--mono); margin:0; color:var(--log); }
.eyebrow { font-family:var(--mono); font-size:.68rem; letter-spacing:.22em; text-transform:uppercase; color:var(--phos); }
h1 { font-size:clamp(1.8rem,5vw,2.6rem); margin-top:.4rem; }
.meta { font-family:var(--mono); font-size:.73rem; letter-spacing:.09em; color:var(--ink-faint); text-transform:uppercase; margin-top:.5rem; }
h2 { font-size:.95rem; letter-spacing:.14em; text-transform:uppercase; color:var(--phos); margin:2.6rem 0 1rem; border-bottom:1px solid var(--rule); padding-bottom:.5rem; }
.briefing { background:var(--panel); border:1px solid var(--rule); border-left:3px solid var(--phos); border-radius:2px; padding:1.2rem 1.3rem; margin-top:1.6rem; max-width:66ch; }
.briefing p + p { margin-top:.7em; }
.beat { display:grid; grid-template-columns:6.5rem 1fr; gap:0 1.3rem; padding:.85rem 0; border-top:1px solid var(--rule-soft); }
.beat:last-child { border-bottom:1px solid var(--rule-soft); }
.trig { font-family:var(--mono); font-size:.7rem; color:var(--phos); text-align:right; padding-top:.28rem; }
.trig .cond { display:block; color:var(--ink-faint); }
.bd > * + * { margin-top:.55rem; }
.note { font-size:.92rem; color:var(--ink-dim); margin:0; max-width:66ch; }
/* An author's note is about the beat rather than part of it: set apart by a
   rule and quieter than the dialogue it explains, so reading the mission
   straight through is still reading the mission. */
.beatnote { border-left:2px solid var(--rule); padding:2px 0 2px 10px; margin:0 0 6px;
            color:var(--ink-faint); font-style:italic; }
.note strong { color:var(--ink); }
.line { font-family:var(--mono); font-size:.86rem; line-height:1.62; max-width:62ch; padding-left:.9rem; border-left:2px solid var(--rule); margin:0; }
.line .who { display:block; font-weight:700; letter-spacing:.1em; font-size:.72rem; text-transform:uppercase; margin-bottom:.15rem; }
.line q { quotes:none; color:var(--ink); }
.line.hq { border-left-color:rgba(78,240,138,.55); } .line.hq .who { color:var(--phos); }
.line.foe { border-left-color:rgba(255,90,77,.55); } .line.foe .who { color:var(--hostile); }
.line.alien { border-left-color:rgba(255,92,255,.6); } .line.alien .who { color:var(--alien); }
.line.log { border-left-color:rgba(242,247,244,.45); } .line.log .who { color:var(--log); }
.line.obj { border-left-color:rgba(255,90,77,.55); background:rgba(255,90,77,.07); padding:.5rem .9rem; }
.line.obj .who { color:var(--hostile); }
.tag { display:inline-block; font-family:var(--mono); font-size:.62rem; letter-spacing:.14em; text-transform:uppercase; padding:.16em .5em; border:1px solid var(--rule); border-radius:2px; color:var(--ink-faint); }
.tag.save { color:var(--phos); border-color:rgba(78,240,138,.4); }
code { font-family:var(--mono); font-size:.84em; background:var(--panel2); border:1px solid var(--rule-soft); border-radius:3px; padding:.08em .38em; }
.lintbox { font-family:var(--mono); font-size:.8rem; border:1px solid var(--rule); border-radius:2px; padding: .9rem 1.1rem; margin-top:1.4rem; }
.lintbox.bad { border-left:3px solid var(--hostile); color:var(--hostile); }
.lintbox.ok { border-left:3px solid var(--phos); color:var(--phos); }
footer { margin-top:4rem; padding-top:1.4rem; border-top:1px solid var(--rule); font-family:var(--mono); font-size:.72rem; color:var(--ink-faint); }
</style></head><body><div class="wrap">
__BODY__
</div></body></html>
"""


def build_html(m, numbered, lint, gml_path, storm=None):
    beats_html = [beat_html("start", m["beats"][0])]
    beats_html += [beat_html(n, b) for n, b in numbered]
    lint_html = ('<div class="lintbox ok">lint: clean</div>' if not lint.errors else
                 '<div class="lintbox bad">' +
                 "<br>".join(esc(e) for e in lint.errors) + "</div>")
    body = f"""
<div class="eyebrow">BSF Legacy · Act II · beat script</div>
<h1>Episode {m['episode']} — {esc(m['title'])}</h1>
<div class="meta">global.mission = {m['mission']} · room {m['room']['width']}×{m['room']['height']}
 · player: {esc(m['player']['object'])} at ({m['player']['x']}, {m['player']['y']})
 · section HP ×{m['player'].get('damage', 1)} · → <code>{esc(os.path.basename(gml_path))}</code></div>
{lint_html}
<h2>Route map</h2>
{map_svg(m, storm)}
<p class="note" style="margin-top:.6rem">Green dashes: the Ratlines (gates in order).
Red field: the storm mask. Magenta squares: scripted spawns.</p>
<h2>Beats</h2>
{''.join(beats_html)}
<footer>Generated by campaign/build.py from campaign/missions/{esc(m['_src'])} —
edit the YAML, not this file. GML output: <code>{esc(os.path.relpath(gml_path, REPO))}</code></footer>
"""
    return HTML_SHELL.replace("__TITLE__", f"EP{m['episode']} {m['title']} — beat script") \
                     .replace("__BODY__", body)


# ----------------------------------------------------------------------------
# driver
# ----------------------------------------------------------------------------

def build_one(path):
    m = yaml.safe_load(open(path))
    m["_src"] = os.path.basename(path)
    lint = Lint()
    em = Emitter(m, lint)
    gml, numbered = em.build()
    stem = os.path.splitext(os.path.basename(path))[0]
    gml_path = os.path.join(OUT_MODS, f"act2m{m['mission'] - 7}.gml")
    html_path = os.path.join(OUT_HTML, f"{stem}.html")
    os.makedirs(OUT_HTML, exist_ok=True)
    open(html_path, "w").write(build_html(m, numbered, lint, gml_path, em.storm))
    if lint.errors:
        print(f"✗ {stem}: {len(lint.errors)} lint error(s) — GML NOT written")
        for e in lint.errors:
            print("   ", e)
        print(f"  viewer (with errors): {html_path}")
        return False
    open(gml_path, "w").write(gml)
    print(f"✓ {stem}: {gml_path}")
    print(f"           {html_path}")
    for w in lint.warnings:
        print("   warn:", w)
    return True


def install():
    dst = os.path.join(INSTALL, "mods")
    if not os.path.isdir(dst):
        sys.exit(f"install dir not found: {dst}")
    for f in ["act2.gml"] + [f for f in os.listdir(OUT_MODS) if re.match(r"act2m\d+\.gml$", f)]:
        src = os.path.join(OUT_MODS, f)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dst, f))
            print(f"installed {f} -> {dst}")

    # The ship designs a mission names. `importShip` is handed a path relative
    # to the game directory, so a design that lives only in the repo does not
    # exist as far as the game is concerned — it returns a non-instance, the
    # next line assigns to it, and GM7 kills the whole code action, taking
    # every later spawn in that beat with it. Installing the GML and not the
    # hulls it loads is a half-install; this is the other half.
    #
    # `.shp` only: the game cannot read a `.sb4`, which is ShipMaker's source
    # format, and copying one over would just be dead weight in the game dir.
    ships = os.path.join(REPO, "mods", "ships")
    if os.path.isdir(ships):
        sdst = os.path.join(dst, "ships")
        os.makedirs(sdst, exist_ok=True)
        for f in sorted(os.listdir(ships)):
            if f.lower().endswith(".shp"):
                shutil.copy2(os.path.join(ships, f), os.path.join(sdst, f))
                print(f"installed ships/{f} -> {sdst}")
    init = os.path.join(dst, "init.gml")
    txt = open(init).read()
    if "act2.gml" not in txt:
        line = ("\n// Act II campaign (chained by build.py --install)\n"
                "if (file_exists('mods/act2.gml')) execute_file('mods/act2.gml');\n")
        open(init, "a").write(line)
        print("chained act2.gml from install init.gml")
    else:
        print("install init.gml already chains act2.gml")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    do_install = "--install" in sys.argv
    targets = sorted(
        os.path.join(MISSIONS, f) for f in os.listdir(MISSIONS)
        if f.endswith(".yaml") and (not args or os.path.splitext(f)[0] in args))
    if not targets:
        sys.exit("no mission yaml matched")
    ok = all(build_one(t) for t in targets)
    if do_install:
        if not ok:
            sys.exit("lint errors — not installing")
        install()


if __name__ == "__main__":
    main()

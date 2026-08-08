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

# The research checkout that holds the decrypted tree and the live install.
RESEARCH = os.path.expanduser("~/Documents/cursor/research/bsf")
INSTALL = os.path.join(RESEARCH, "battleshipsforeverv090d")

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
}


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
# GML assembly helpers
# ----------------------------------------------------------------------------

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

    def gate_stmt(self, x, y):
        # `g` is declared once at the top of the ladder event
        return (f"g = instance_create({x},{y},MoveToArea); "
                f"g.l_target = global.{self.gid}_ship; showPing({x},{y})")

    BEAT_KEYS = {"start", "say", "objective", "gate", "gate_at", "wait",
                 "autosave", "music", "eerie", "meteors", "camera", "spawn",
                 "ping", "win", "exec"}

    @staticmethod
    def onoff(v):
        """YAML 1.1 parses bare on/off as booleans — normalise both spellings."""
        if v is True:
            return "on"
        if v is False:
            return "off"
        return v

    def actions(self, b, where, include_say=True):
        g = self.gid
        out = []
        for k in b:
            if k not in self.BEAT_KEYS:
                self.lint.err(f"{where}: unknown beat key '{k}'")
        if b.get("music") == "stop":
            out.append("stopMusic()")
        elif b.get("music") == "theme":
            out.append("stopMusic(); bgm_Play(global.mus_theme,1)")
        elif b.get("music") == "battle":
            out.append("stopMusic(); bgm_Play(global.mus_battle,1)")
        elif "music" in b:
            self.lint.err(f"{where}: music must be stop|theme|battle")
        if self.onoff(b.get("eerie")) == "on":
            out.append("sound_loop(snd_eeriesound)")
        elif self.onoff(b.get("eerie")) == "off":
            out.append("sound_stop(snd_eeriesound)")
        if b.get("autosave"):
            out.append("if (global.difficulty != World_Hard) saveGame()")
        if "camera" in b:
            c = b["camera"]
            out.append(f"centreCamera({c['x']},{c['y']},{c.get('speed', 60)})")
            out.append(f"global.lasteventx = {c['x']}; global.lasteventy = {c['y']}")
        for sp in b.get("spawn", []):
            self.lint.resource(sp["object"], where)
            if "name" in sp:
                out.append(f"global.{g}_{sp['name']} = "
                           f"instance_create({sp['x']},{sp['y']},{sp['object']})")
            else:
                out.append(f"instance_create({sp['x']},{sp['y']},{sp['object']})")
        if "ping" in b:
            x, y = b["ping"]
            out.append(f"showPing({x},{y})")
        if self.onoff(b.get("meteors")) == "on":
            out.append(f"global.{g}_meteors = 1; alarm[5] = 1")
        elif self.onoff(b.get("meteors")) == "off":
            out.append(f"global.{g}_meteors = 0")
        if "objective" in b:
            ov = self.tvar(b["objective"], where)
            out.append(f'showMessage(0,c_red,"New Objective",{ov},spr_MesObj)')
        if include_say and "say" in b:
            out.append(self.say_stmt(b["say"], where))
        if "gate" in b:
            gt = self.m["gates"][b["gate"]]
            out.append(self.gate_stmt(gt["x"], gt["y"]))
        if "gate_at" in b:
            out.append(self.gate_stmt(b["gate_at"]["x"], b["gate_at"]["y"]))
        if b.get("win"):
            out.append(f"global.{g}_won = 1; missionSucc()")
        for raw in b.get("exec", []):
            out.append(raw)
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
            if b.get("wait") == "gate":
                n += 1                   # absorber slot for the gate's +1
            elif msgs == 0 and not b.get("win"):
                pass                     # auto-chained, still one slot
        return numbered

    # ---- whole-file emission ---------------------------------------------

    def build(self):
        m, g, lint = self.m, self.gid, self.lint
        numbered = self.number_beats()

        # -- ladder (user event 0)
        rungs = []
        for n, b in numbered:
            where = f"beat@{n}"
            stmts = self.actions(b, where)
            has_msg = ("say" in b) or ("objective" in b)
            if not has_msg and not b.get("win"):
                stmts.append(f"l_messagecount = {n + 1}; event_user(0)")
            body = ";\n".join(stmts) + ";"
            rungs.append(f"if (l_messagecount = {n}) {{\n{body}\n}}")
        ladder = "var g;\n" + "\nelse ".join(rungs)

        # -- start beat (alarm 2)
        start = self.m["beats"][0]
        start_stmts = self.actions(start, "beat@start")
        start_code = ";\n".join(start_stmts) + ";"

        # -- create event
        p = m["player"]
        lint.resource(p["object"], "player")
        fail_t = self.tvar(m["fail"]["ship"], "fail.ship")
        zone_lines = []
        for z in m.get("zones", []):
            zone_lines.append(
                f"z = instance_create({z['x']},{z['y']},global.{g}_zoneobj); "
                f"z.l_r = {z['r']}; z.l_dmg = {z['dmg']};")
        neb = m.get("scenery", {}).get("nebula", 0)
        create = f"""
var s, z;
global.gamecontroller = self.id;
l_messagecount = 0;
l_temp = -4;
global.{g}_won = 0; global.{g}_failed = 0; global.{g}_meteors = 0;
global.World_MaxRangeSqr = sqr(World_MaxRange);
stopMusic();
s = instance_create({p['x']},{p['y']},{p['object']});
global.{g}_ship = s;
with (ShipSection) {{ if (l_owner = global.{g}_ship) l_hp = l_hp * {p.get('damage', 1)}; }}
repeat ({neb}) {{ instance_create(random(room_width),random(room_height),ter_Nebula); }}
{chr(10).join(zone_lines)}
centreCamera({p['x']},{p['y']},0);
global.lasteventx = {p['x']}; global.lasteventy = {p['y']};
alarm[2] = 45;
"""
        # -- step: fail checks
        step = f"""
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
        met = m.get("meteors", {})
        interval = met.get("interval", 240)
        cap = met.get("cap", 8)
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
        # -- zone object events
        zcreate = "l_r = 200; l_dmg = 0.3; depth = 9000;"
        zstep = f"""
if (instance_exists(global.{g}_ship)) {{
with (ShipSection) {{
if (l_owner = global.{g}_ship) {{
if (point_distance(x,y,other.x,other.y) < other.l_r) {{
l_hp -= other.l_dmg;
}}
}}
}}
}}
"""
        zdraw = """
draw_set_blend_mode(bm_add);
draw_set_color(c_red);
draw_set_alpha(0.10);
draw_circle(x,y,l_r,0);
draw_set_alpha(0.30);
draw_circle(x,y,l_r,1);
draw_set_alpha(1);
draw_set_blend_mode(bm_normal);
"""

        # lint every event string we are about to emit
        for name, frag in [("ladder", ladder), ("start", start_code),
                           ("create", create), ("step", step),
                           ("meteor", meteor), ("zstep", zstep), ("zdraw", zdraw)]:
            lint.event_string(frag, name)

        r = m["room"]
        texts = "\n".join(f'{n} = "{s}";' for n, s in self.texts)
        out = f"""// GENERATED by campaign/build.py from campaign/missions/{m['_src']} — DO NOT EDIT.
// Act II Episode {m['episode']}: {m['title']}  (global.mission = {m['mission']})
if (variable_global_exists('{g}_init')) exit;
global.{g}_init = 1;

// ---------------------------------------------------------------- dialogue
{texts}

// ------------------------------------------------------------- storm cells
var zo;
zo = object_add();
global.{g}_zoneobj = zo;
object_event_add(zo, 0, 0, '{zcreate}');
object_event_add(zo, 3, 0,
    {gml_quote_lines(zstep)});
object_event_add(zo, 8, 0,
    {gml_quote_lines(zdraw)});

// -------------------------------------------------------------- controller
var c;
c = object_add();
global.{g}_ctr = c;
object_event_add(c, 0, 0,
    {gml_quote_lines(create)});
object_event_add(c, 2, 2,
    {gml_quote_lines(start_code)});
object_event_add(c, 2, 5,
    {gml_quote_lines(meteor)});
object_event_add(c, 3, 0,
    {gml_quote_lines(step)});
object_event_add(c, 7, 10,
    {gml_quote_lines(ladder)});

// -------------------------------------------------------------------- room
var r;
r = room_add();
room_set_width(r, {r['width']});
room_set_height(r, {r['height']});
room_set_caption(r, "{r.get('caption', m['title'])}");
room_set_background_color(r, c_black, 1);
room_set_view(r, 0, 1, 0, 0, 1024, 768, 0, 0, 1024, 768, 32, 32, -1, -1, -1);
room_set_view_enabled(r, 1);
room_set_code(r, 'instance_create(0,0,ctr_GUI); instance_create(0,0,' + string(c) + ');');
global.act2_room{self.room_slot} = r;
"""
        return out, numbered

    # (the act2.gml breadcrumb runs after execute_file of this mod returns, so
    #  a syntax error anywhere above leaves mods/act2.log unwritten)


# ----------------------------------------------------------------------------
# HTML viewer
# ----------------------------------------------------------------------------

def esc(s):
    return html.escape(str(s), quote=True)


def beat_html(n, b):
    trig = str(n)
    if b.get("start"):
        trig = "start"
    rows = []
    for key in ("music", "eerie", "meteors"):
        if key in b:
            rows.append(f'<p class="note"><span class="tag">{key}: {esc(b[key])}</span></p>')
    if b.get("autosave"):
        rows.append('<p class="note"><span class="tag save">autosave</span></p>')
    if "camera" in b:
        c = b["camera"]
        rows.append(f'<p class="note">camera → ({c["x"]}, {c["y"]}) speed {c.get("speed", 60)}</p>')
    for sp in b.get("spawn", []):
        nm = f' as <code>{esc(sp["name"])}</code>' if "name" in sp else ""
        rows.append(f'<p class="note">spawn <code>{esc(sp["object"])}</code> at ({sp["x"]}, {sp["y"]}){nm}</p>')
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


def map_svg(m):
    W, H = m["room"]["width"], m["room"]["height"]
    parts = [f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet" '
             f'style="width:100%;height:auto;background:#04070a;border:1px solid #1d2a2a;border-radius:2px">']
    for z in m.get("zones", []):
        parts.append(f'<circle cx="{z["x"]}" cy="{z["y"]}" r="{z["r"]}" '
                     f'fill="rgba(255,60,50,0.13)" stroke="rgba(255,90,77,0.5)" stroke-width="4"/>')
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
                         f'text-anchor="middle" font-family="monospace">{esc(sp["object"])}</text>')
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


def build_html(m, numbered, lint, gml_path):
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
{map_svg(m)}
<p class="note" style="margin-top:.6rem">Green dashes: the Ratlines (gates in order).
Red circles: storm cells. Magenta squares: scripted spawns.</p>
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
    open(html_path, "w").write(build_html(m, numbered, lint, gml_path))
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

# Mission editor

A beat editor for Act II missions, with the running game as its second screen.

```
python3 tools/editor/server.py                  # serves http://127.0.0.1:8777/
python3 tools/editor/server.py --res 2560x1440  # the game's window
python3 tools/editor/server.py --fullscreen     # give the game the whole monitor
```

A puppetted game is a second screen, not the thing you are looking at, so the
editor launches it **windowed at 1920×1080** rather than covering the monitor the
editor is on. Three things make that work, and all of them are worth knowing
about.

**The display settings are borrowed, not taken.** `mods/res.cfg` and
`mods/mode.cfg` are the *player's* — the game rewrites them itself whenever
someone picks a resolution or toggles Display — so the editor stashes the
originals in `mods/edit/display.saved`, writes its own, and hands them back when
the game is stopped, when the server exits, and on the next server start if
neither of those ran. Viewing a scenario never costs you your resolution.
Both files are read once at startup, so the setting applies to the next launch
and never to a running game.

**The game runs in its own wine prefix** — `~/.local/share/bsf-legacy/prefix`,
the same one `<Exe>_Linux.sh` makes, created on first launch if it is missing.
That is not tidiness: a wine **virtual desktop is a property of the prefix**
(`HKCU\Software\Wine\Explorer`), not of the command line, so a prefix that asks
for one wraps every game launched in it regardless of what you pass. The research
prefix still asks for a 3840×2160 desktop and the capture runbook depends on
that, so the editor stays out of it. `--prefix PATH` overrides. The startup
banner always prints which prefix is in use and whether it carries a desktop.

**The server hands wine its own `DISPLAY`**, so the editor has to be started
from the desktop session it is meant to draw on. Start it from somewhere that
carries a different one — another session, a detached shell, an agent — and
every launch dies in the wine loader before the game exists, with
`wine: Unhandled exception 0x0eedfade`. `launch` names it now: the API waits to
see whether the child is still there a moment after the spawn and, if it is not,
answers with wine's own last line and the `DISPLAY` it used, rather than
reporting the spawn as a success. `/tmp/bsf_editor_run.log` has the rest.

Ground truth comes from the game, not the window manager: the state line carries
`win=`, `region=` and `fs=`. The **region** is the drawing buffer, and only it
distinguishes a native 1080p render from an upscale — a window manager reports
reparented frames and decorations (1948×1146 for a 1920×1080 window here).

**The camera is held while the pointer is elsewhere.** Stock BSF edge-scrolls
whenever `mouse_x` is past the view edge, and a pointer parked over the editor is
past it permanently — so the camera used to slide away as soon as a seek's glide
finished. `mods/editor.gml` undoes that scroll while the pointer is outside the
game's client area, and yields to the arrow keys and to `centreCamera`'s own
glide. Put the pointer over the game and edge-scrolling works exactly as it does
for a player.

It **adopts** the camera rather than imposing on it: a room it has not seen
before, and any single-frame jump bigger than one edge-scroll step, are taken as
given. Without those two rules the hold started every room at (0, 0) — a mission
whose own opening `centreCamera` put the view somewhere else was dragged to the
room corner and held there, which reads as a mission bug and is not one.

**The storm is painted, and the brush is on the map.** A mission's storm is one
mask over the room — `.` clear, `#` damaging, `@` hot, one character per 50
world units — and `paint storm` (or `b`) turns the map into the surface you
paint it on. Drag to paint, alt or the right button to erase, `[` `]` for brush
size, `1` `2` `e` to pick the tool, `Esc` or `b` to put it away. One drag is one
undo step. The red gas clouds, the lightning and the HP the storm takes are all
read from the same cells, so what you paint is what bites — there is nothing
else to keep in step.

**Known, benign:** a fresh private prefix has no audio devices configured, so
`bgm_Play` fails and logs a blank-message non-fatal error to `game_errors.log`
each time a beat changes the music. It is the stock music path reporting through
`show_error(..., false)`, not the mission code — calling `bgm_Play` from any
object reproduces it.

The design and the reasoning behind it are in [DESIGN.md](DESIGN.md). This file
is how to use and how to work on it.

## What it is

The **timeline** shape with the **inspector** editing model, both chosen over
three alternatives each in `prototype/mission-editor/` (rationale in that
directory's `NOTES.md`):

* the map on top, drawn from the mission's own data — real game sprites, real
  hull geometry, the storm cells, the route through the beacons;
* an NLE-style transport under it with one lane per thing that *persists* across
  beats: gate waits, the meteor window, music beds, the always-on fail check.
  A mission's hard part is when those overlap, and only lanes show it;
* a compact read-only beat track, and a docked field rail on the right where one
  card per verb is edited. Structure on the track, content in the rail, nothing
  edited in two places;
* a `{ } yaml` drawer showing the DSL the model would save. If an edit cannot
  round-trip to YAML, it is not real.

**Scope: Act II YAML missions.** Act I is stock GML inside the exe with no
source, no seek ladder and no editor flags, so it is not listed.

**Where it listens.** Loopback, unless told otherwise — this process launches the
game, reads the exe and writes mission files, so anything that can reach the port
can do all three, and that is a decision rather than a default.

```
python3 tools/editor/server.py --host '*'         # every interface, v4 and v6
python3 tools/editor/server.py --host tailscale   # the tailnet address, only
python3 tools/editor/server.py --host lan         # the LAN address, only
python3 tools/editor/server.py --host <address>
```

`*` (or `any`) binds `::` with `IPV6_V6ONLY` off, so one socket answers on IPv6
*and* IPv4 — loopback, LAN and tailnet all at once, which a plain `0.0.0.0` does
not give you. A specific address answers on **that address alone**: `--host
tailscale` means `127.0.0.1` stops working and the local browser reaches the
editor on the tailnet address too. The banner prints every URL it can be
reached on, and the auto-opened tab uses one that will connect.

## Keys

| | |
|---|---|
| `←` `→` | previous / next beat |
| `ctrl/cmd-S` | save + apply |
| `ctrl/cmd-Z` | undo |
| `space` | pause / resume the game |
| `g` | ghost overlay |
| `m` | mission sheet |
| `b` | storm brush |
| `[` `]` | brush size (while painting) |
| `1` `2` `e` | cell / hot / erase (while painting) |
| `+` `-` | zoom the map, about its centre |
| `0` | back to the whole room |

Drag a block along the track to reorder it. `+` in any gap inserts a beat.
Click a portrait or a spawn's sprite to pick another from the tree.

**On the map:** drag a beacon, a scripted spawn, a `gate_at` or the player start
to move it. These are positions and nothing else, so the map is where they are
edited — the matching card carries the same x/y if you would rather type, and it
tracks the drag live. Two things worth knowing:

* `gates:` is a mission-level list and a beat refers to one by index, so moving
  beacon 2 moves it for **every** beat that waits on it. A spawn is the
  opposite — it belongs to one beat, and its label says which while you hold it.
* The map draws spawns from beats later than the playhead, dimmed. Those are
  draggable too; the alternative is a handle you can see and cannot use.

With the storm brush up the map is a paint surface instead and everything else
stays put. The camera frame is deliberately not draggable — its centre usually
sits on top of the very thing you are trying to grab.

**Zoom and pan.** The wheel zooms on whatever is under the pointer — that point
stays put, so you zoom *at* a thing rather than zoom and then go looking for it.
A trackpad pinch does the same. Once zoomed, drag the map to pan: the left
button when the press grabbed nothing else, the middle button always, including
while the brush is up. `0` returns to the whole room, which is also where the
wheel stops if you keep scrolling out, and the readout in the top-left corner
shows the factor while you are anywhere but there.

At the fit nothing changed: there is nothing to pan, so a left-drag on empty map
does what it always did, which is nothing. Zoom is a view, not an edit — it is
never saved, and changing mission resets it.

**Changing what a prop is** happens in the spawn card:

* Click the object's preview for a picker of every object the game has, drawn as
  itself, with a filter box. This is how you swap one station or ship design for
  another — the stock designs *are* objects (`SpaceStation`, `BattleStation`,
  `HestiaAlpha`, `EPirate06`…), so picking one is the whole of it.
* For objects the game draws as a plain sprite — `ter_Planet`, `ter_Sun`,
  `ter_Rock` and the rest of the scenery — the card also offers **sprite,
  scale, angle, frame and tint**. They compile to assignments made straight
  after `instance_create`, so they replace whatever the object chose for itself,
  and the map draws the result rather than the object's default. Leave a field
  blank and the key is not written at all. Tints are `#rrggbb` or one of
  `white red green blue amber magenta grey`.
* Designed ships do not get the look block: a hull draws its own sections and
  ignores `sprite_index`, so the field would be a control that does nothing.
  Written in by hand it is worse than nothing — the compiler drops it silently —
  so the lint now says so and names the keys.
* **Anything with a hull turns with `facing:`, and the map turns with it.** Both
  keys land on `image_angle` — `angle:` from the look block, `facing:` from the
  fixtures, which are emitted after it, so facing wins where a spawn carries
  both — and every section of a hull places itself at
  `l_offsetdir + l_owner.image_angle`. The map used to draw the design's own
  orientation whatever the mission said, which is how EP9's four berthed hulls
  came to lie nose-right beside the station on the map and nose-in to it in the
  game.
* `spawn:` is the one verb that is a **list**, so it has its own add and remove.
  Each prop gets a strip — `PROP 2 OF 3 · TER_PLANET` — with `remove ✕` on the
  right of it; `+ another prop` at the foot of the list adds one, offset from
  the last so it does not land underneath it; and the card's own `✕` still takes
  every prop off the beat at once. Removing the last one removes the key — an
  empty list would write a bare `spawn:` that reads back as null.

**Ship designs** are the hulls that exist as *files* rather than as objects. The
picker's `DESIGNS` section lists both roots, each drawn as itself:

* `mods/ships/` — the campaign's own, tracked in git and installed with the rest
  of `mods/`, so a mission that uses one works on a player's machine.
* `Custom Ships/` — the eight the game ships inside `bsf090d.zip`. Referenced in
  place and **never copied here**: a ship taken out of the game is extracted game
  data. Anything else in that folder exists only on your machine, and the lint
  says so.

A design spawn carries what the file cannot say — `team:` (required; there is no
safe default), `hold:` to still a station, `facing:` for a hull that will never
turn. The card shows the generation, section and mount counts, and where the
design comes from; when a `.sb4` sits newer beside the `.shp`, an amber note says
the game keeps loading the older file until it is re-exported.

The map draws a placed design from the same draw list `tools/bsf`'s renderer and
`ship serve` use, so the three cannot disagree about geometry.

**The mission sheet** (`m`) is everything in the file that is not a beat: the
title and subtitle, the **room's width and height**, its caption, where the
player starts and how damaged, the message shown when the ship is lost, the
nebula count, the meteor spawner's settings, the **camera limit** and the
**storm wall**. The room is the world — every
coordinate in the mission is measured against it, and the view scrolls over it:
768 world units tall and as wide as the display's aspect makes it, which is 1365
at 16:9 and more again zoomed out. Rooms are authored 1024×768 and no room is
ever *shown* at 1024×768 — `mods/resolution.gml` rewrites every port at startup,
and assuming otherwise is what had EP9's meteors spawning on screen.

The camera limit (`bounds: x2`) is how far right the view may look, clamped
exactly as the room's own right edge clamps it — the ship may still fly past it,
only the camera stops. Set it and the mission *starts* clamped, so the beat that
names it is normally the one that turns it **off**: that is what a reveal is.

The storm wall (`surge:`) is lit by a beat and is made of the storm — no painted
mask, no wall. Its eight settings are the one part of the sheet where **blank
means the compiler's default**, shown greyed in the box: every surge key already
has a default that behaves, so typing one writes one, and a file saying
`speed: 1.6` and nothing else is a file whose author changed the speed. That is
worth being able to read off the mission. Clearing the last field of either
block removes the block rather than leaving `surge:` with nothing under it,
which the compiler rejects.

The size is the one field in the editor that applies on **commit** (blur or
Enter) rather than per keystroke: the storm mask is sized from it, and typing
`3000` over `800` passes through `3`, `30` and `300`, each of which would refit
the mask to a grid it can never come back from. On commit the mask is squared up
to the new room, and if that cropped painted cells the toast says how many —
`ctrl-Z` puts them back. Shrinking a room can also strand a beacon or a spawn
outside it, which is a mission that cannot be finished; both the editor's lint
and `build.py` treat that as an error rather than letting it reach a playtest.

## The loop

Editing is local and instant; nothing leaves the browser until you apply.
**Apply is explicit and is also save.** `ctrl/cmd-S` lints, writes the YAML,
builds the GML, copies it into the install, reloads the mod, re-enters the
mission and seeks back to the beat you were on — about 1.6 s end to end. A lint
failure aborts before anything is written, so the game never runs a mission that
is not in the file.

**Launching installs first.** Starting the game builds every mission and copies
the result into the install — the GML *and* the `.shp` designs under
`mods/ships/` — so a game that was started rather than applied to is still the
mission that is on disk. It used to run whatever the last apply had left in the
game directory, which is mild while the difference is only text and not mild at
all when it is a hull: `importShip` reads a design from the game directory at
spawn time, so a design that has never been installed is simply absent from the
room, and an empty lane reads as a mission bug rather than as a stale install.
A mission with lint errors is not installed at all, so opening *that* mission is
refused — coming up on its previous build looks exactly like an edit that did
nothing.

With the game running, **control direction flips with the pause state**: paused,
selecting a beat seeks the game to it; playing, the playhead follows the game.
The **ghost overlay** (`g`) draws the game's own instance dump over the
prediction in the same coordinates — a matched instance sits on its prediction, a
missing one leaves a prediction with no ghost, a drifted one shows the offset as
a line.

**Editor rules** suppress storm-cell damage and `missionFail`, so a mission
cannot be lost while it is being written. The button toggles back to real rules
for testing the failure path deliberately.

## How it fits together

```
  browser  ── api/mission, api/apply ─────▶  server.py ──▶ campaign/build.py
     │                                          │              │
     │      ── api/goto, api/cmd ───────────▶    │              ▼
     │                                          │        mods/act2mN.gml
     │      ◀─ api/live (state + dump) ─────    │              │
     │                                          ▼              ▼
  core.js prediction                    mods/edit/cmd ──▶ the game under wine
                                        mods/edit/state ◀── mods/editor.gml
```

| file | what it is |
|---|---|
| `server.py` | the only thing that touches the machine: the art, the compiler, the install, the wine process and the channel |
| `assets.py` | the sprite extractor — decrypts the exe **into RAM** and serves frames on demand |
| `app/core.js` | the model: beat numbering, lint, the YAML reader/writer, the storm mask, the prediction renderer |
| `app/timeline.js` | the chrome: map, transport, ruler, lanes, playheads, source drawer |
| `app/inspector.js` | the beat track and the field rail |
| `app/live.js` | the running game: polling, control direction, the ghost overlay |
| `app/paint.js` | the storm brush: pointer to cell, one drag = one undo step |
| `app/handles.js` | what you can grab on the map — beacons, so far |
| `app/view.js` | zoom and pan: anchored to the pointer, and the pan nothing else claimed |
| `app/mission.js` | the mission sheet: the file's header, room size included |
| `app/ships.js` | ship designs: the scan, the scene, and the blit that keys their art |
| `app/app.js` | the shell: which mission, what is unsaved, who is driving |

## Rules that are not style preferences

* **Nothing derived from the game is written to disk.** The exe is decrypted into
  memory and frames are PNG-encoded on demand. This is what keeps extracted art
  out of the repository *by construction* — there is no file to commit by
  accident. Ship the extractor, never its output; the same goes for anything else
  computed from the game.
* **No CDN.** Plain `<script src>`, no modules, no build step.
* **The editor authors YAML, never GML.** The compiler owns the GML, including
  the seek ladder the editor drives.
* **The server lints with `build.py` itself**, imported rather than shelled out
  to, so the editor cannot disagree with the build about what is legal.

## Things that will bite

* **Never `width:auto` on a `<canvas>`.** It is a replaced element, so `auto`
  resolves to the backing-store width that the renderer itself sets from
  `clientWidth`, and the two feed each other until the map is twice the window.
* A grid item holding the scrolling track needs **`min-width:0`**, or the track's
  min-content width silently widens the whole grid.
* A drag must `preventDefault()` on `pointerdown` and hold a `user-select:none`
  class on `<body>` for its duration, or every drag paints a text selection
  across the page. Selection therefore happens on `pointerdown` too, rather than
  depending on which compatibility mouse events survive that.
* **The rail does not re-render for an edit that came from outside it.** It is
  built from the model on select and on reload, which is enough while every edit
  originates in the rail — the DOM already holds what you just typed. Dragging a
  beacon on the map was the first edit that did not, and its coordinates sat
  stale in the gate card until you reselected the beat. The fix is not a full
  `renderIns()`: that runs sixty times a second during a drag and eats the caret
  of whatever field has focus. `syncFields()` writes the values in place and
  skips `document.activeElement`.
* **Ship art carries no alpha.** `Custom sprites/*.png` are palette PNGs whose
  empty area is plain *black*, which the game hides by multiplying the sprite
  with the team colour. Blit one straight onto a canvas and you get an opaque
  80×80 square; twenty sections put a black slab over the map. Game Maker's key
  is **the bottom-left pixel** — anything equal to it is invisible — and a mask
  then flattens to two shades (47 fill, 255 edge, split at 140), which is what
  `tools/bsf/sprites.py` does and what the map must do to match it. The check
  that caught this was counting opaque pixels against the PIL renderer: 2.96×
  before, 1.06× after.
* **A control in the label column is not a control.** The rail is a two-column
  grid of label/value, so a `✕` appended to a label renders at whatever size the
  label text is — 6×11 px of `#33474a` on a near-black panel, which is
  indistinguishable from the panel. It was there, it worked, and it was reported
  as missing. List entries get a full-width strip and a control that says
  `remove ✕`; `renderIns` takes a null label to mean "span both columns".
* **One `focusin` listener per panel, scoped to that panel.** The rail's
  snapshot-on-focus listener sits on the whole stage, so it also saw focus
  events from the panels floating over the map — two snapshots per focus. That
  looks harmless until an edit commits on blur: tabbing out of the mission
  sheet's size field commits the resize *and then* focuses the next field, so
  the second snapshot records the state after the edit and `ctrl-Z` appears to
  do nothing. The rail's listener now ignores anything outside `.ins`.
* **A drag ends on the window, never on the element you pressed.**
  `setPointerCapture` promises the press target will see the `pointerup`
  wherever the button comes up, and it keeps that promise right up until it
  doesn't — released past the edge of the window, capture dropped, the window
  blurred mid-drag. Miss that one event and the drag never ends. For the storm
  brush that meant every later mouse move over the map kept painting with no
  button held. Listen on `window`, and treat a `pointermove` with `buttons === 0`
  as proof the drag is over.
* **The dev server sends `no-store`.** Chrome will happily serve the editor's own
  scripts out of its memory cache on a plain reload, so a fix in `app/*.js` can
  be invisible in a tab that looks reloaded — and the bug gets re-reported from
  it. Sprite frames keep their `max-age`; they are content-addressed by name.
* **Do not draw a masked field as rectangles.** Row runs are the obvious way to
  fill a painted mask and they are wrong at every alpha that is visible at all:
  neighbouring rows step by a whole cell, and additive red over black renders
  that staircase perfectly. It is buried inside a thick storm and glaring on a
  freshly painted stroke, which is exactly the case you are looking at while you
  paint. The clouds are the storm; there is no wash under them.
* `numberBeats()` gives each beat both `n` and `rung`. They are the same number
  except for the start beat, whose `n` is the string `'start'` — that is what the
  ruler prints. **Anything the game will see wants `rung`.**

# Mission editor — live game wiring

Decisions from the design session of 2026-08-08, on top of the mission-editor
design note (`/tmp/bsf-mission-editor-handoff/mission-editor-design.html`) and
the UI prototype in `prototype/mission-editor/`. Every engine claim below was
checked against the decrypted tree or the exe's symbol table, not assumed.

## What the editor is

The **inspector** shape from the prototype's round two (`?variant=1`): compact
read-only beat track over the lanes, map above, docked field rail on the right.
It is promoted here, to `tools/editor/`, as the mission editor.

**Scope: Act II YAML missions only.** Act I is `ctr_Mission0..7` — stock GML in
the exe with no source, no seek ladder and no editor flags. Those missions are
not listed. When one is transcribed it becomes an ordinary Act II-shaped mission
and appears like any other.

## What the runtime gives us

| capability | status | why it matters |
|---|---|---|
| `execute_string`, `execute_file` | present, 16 uses | commands can be code |
| `object_event_clear` | present | rebind a controller's ladder in place |
| `object_delete` | present | dynamic objects can be reclaimed |
| **`room_delete`** | **absent** | a dynamically added room leaks forever |
| `parameter_string` / `parameter_count` | present, used by `ctr_Testroom` | the game already opens a `.shp` from argv |
| `room_speed` toggle | `ctr_Testroom` key `9:122` | stock turbo: `999` / `30` |
| the sandbox freeze | `ctr_Testroom` alarm `2:0` | the game's own "keep all ships paused" |

Two traps that shaped everything:

- **The stock `P` pause is `keyboard_wait()`** in `GUI_MissionPause`'s Draw — it
  blocks the whole game loop, so the file channel dies with it. Unusable for an
  editor. The sandbox freeze does not block, and is what we copy.
- **GM7 syntax errors are silent** (`campaign/INTERNALS.md`). A malformed
  payload wedges the mission with no diagnostic, which is why the channel has a
  fixed verb grammar rather than raw GML.

## The twelve decisions

1. **Apply model — warm reload + fast-forward.** Rebuild, re-enter the mission
   through the real menu sequence, seek back to where you were. BSF never calls
   `randomize()`, so a re-entry replays identically and nothing can drift. Not
   hot-patching: a live-patched world is a state no playthrough reaches.
2. **Fast-forward is state-only.** Seeking runs spawns, camera, music and
   meteor flags; it does not create message panels, gates or autosaves.
3. **The seek ladder is generated.** `build.py` emits a second event — **User
   Event 1 (`7:11`, free; stock controllers use user 0 and user 15)** — holding
   the cumulative state-only statements, from the same emitter and the same
   YAML. The editor never authors GML for the game.
4. **Boot.** The editor's play button launches the game with
   `mission_editor <n>`; `patch_bsf.py`'s launcher gains `"$@"`. The module
   parses `parameter_string`, then drives the *existing* entry sequence
   (`global.mission = n` → `event_user(14)` → `rm_Briefing` → adv → adv) — never
   `room_goto` into a mission room, which leaves globals unset and makes the
   controller throw every frame. The same `open` verb works live, so switching
   mission in the editor switches it in the game without a relaunch.
5. **Pause is the sandbox freeze.** Ships/turrets: `speed = 0`, alarms zeroed,
   targets cleared, `l_holdposition = true` — plus our generated zone objects
   and the controller's `alarm[5]`, which the stock pattern does not cover.
   The loop keeps running and drawing, so the channel stays alive. Unfreeze
   re-arms exactly as `ctr_Testroom`'s `9:118` does.
6. **Channel.** One file, `mods/edit/cmd`, polled once per step — one
   `file_exists` no matter how many verbs exist. Fixed grammar:
   `open n · seek n · pause 0|1 · reload · dump · gml <...>`, with `gml` as the
   deliberate escape hatch, mirroring the DSL's own third tier. The game acks
   into `mods/edit/ack` with a sequence number and a result, so an unknown verb
   is reported rather than silently dropped.
7. **Reload shape — define once, re-bind always.** Because rooms cannot be
   deleted, `build.py` splits the mod: a guarded block creates the object and
   room on first load; everything after it re-binds on every load
   (`object_event_clear` + `object_event_add`, `room_set_width/height`). The
   room's creation code keeps pointing at a valid object because the index never
   changes. Unlimited reloads, nothing leaked.
8. **Apply is explicit and is also save.** `⌘S` writes the YAML, lints, builds,
   copies into the install, reloads and re-seeks (~1–3 s). Lint failure aborts
   before anything reaches the game, so the game never runs something that is
   not on disk. Editing is otherwise local and instant.
9. **Selecting a beat only seeks** (~one command), and pauses first.
10. **Control direction flips with the pause state.** Paused: editor → game.
    Playing: game → editor, with the `beatlog` tracer moving the playhead.
    Clicking a beat while playing pauses, then seeks — one rule.
11. **Truth loop is a ghost overlay.** After every settle, `guidump` is drawn
    over the prediction in the same coordinates: a matched instance sits on its
    prediction, a missing one leaves a prediction with no ghost, a drifted one
    shows the offset as a line. Toggle predicted / actual / both.
12. **Editor mode suppresses damage and failure** behind
    `if (global.<id>_edit)`, with a "real rules" toggle for testing the failure
    path deliberately. EP9's ship starts at `damage: 0.55` and its storm cells
    drain hull from the zone object's own Step — without this you lose the
    mission while typing.

## Known consequence: seeking is directional

The seek ladder is cumulative, so it is **not idempotent** — seeking to 5 and
then to 11 would re-run rungs 1–5 and duplicate every spawn. Rungs therefore
carry a lower bound, and only a forward seek is cheap:

```gml
// User Event 1 — run only the delta (l_seek_from, l_seek]
if (l_seek >= 11) { if (l_seek_from < 11) { …beat 11 state… } }
```

- **forward seek** — one command, ~one step.
- **backward seek** — warm re-entry, then seek forward from 0 (~1–3 s).

Other accepted consequences of state-only seeking: the ship stays at its spawn
point (so camera and ship disagree about where the mission is), autosaves do not
fire, and dialogue/gate verbs are not exercised — the live loop checks the
compiler for the state verbs only.

## What has to be built

| where | work | state |
|---|---|---|
| `campaign/build.py` | seek ladder (User Event 1) with delta guards; define-once / re-bind split; `ed_edit` guards on damage + `missionFail`; beat tracer per rung | **done** |
| `mods/editor.gml` (new) | parameter parse, entry driver, per-step command poller, freeze/unfreeze, seek, dump, ack, beat publisher | **done** |
| `tools/patch_bsf.py` | `"$@"` in the launcher | **done** |
| `tools/editor/` | promote the inspector; server owns the wine process, `build.py`, the install copy and the channel; ghost overlay; mission switcher; lint surface | **done** |

All four rows were verified against the running game, not just compiled:
launching with `mission_editor 8` walked the menu into EP9 by itself; the beat
tracer followed play rung by rung; `seek 16` spawned the station and the planet
at the YAML's coordinates and nothing else; a backward seek was refused with the
reason; and editing `ep9.yaml`, rebuilding, then `reload` → `open 8` → `seek 16`
put the moved planet at its new coordinates in the same room index — no leaked
room, no leaked object, and not one error from the editor object in the log.
The whole apply, from the browser's POST to the game showing the change, is
**1.6 s**.

Three things only the live loop could have found, all now fixed and all of the
same shape — a command that succeeds while achieving nothing:

- **A reload is not an apply.** Re-executing a mission mod re-binds its events;
  it cannot touch instances the old code already created, and the seek ladder's
  delta guard means seeking to where the game already is runs nothing. Both
  commands acked `ok` and the map showed the previous build. An apply now always
  forces the re-entry.
- **The published state outlives the process that wrote it.** `mods/edit/state`
  still described the old room, so the wait-for-mission check passed instantly
  and the seek landed in a briefing screen. The server now deletes it after an
  `open`, so the next answer can only be one the game wrote afterwards.
- **`numberBeats()` gives each beat both `n` and `rung`**, identical except for
  the start beat, whose `n` is the string `'start'`. Anything the game sees wants
  `rung`; using `n` made the playhead stop following at beat 0 and would have
  sent `seek start` down the channel.

## Settled by measurement

Built and verified against the running game on 2026-08-08. Everything below was
an open question in the paragraph above this one; each is now a number.

- **`file_exists` costs 80.6 µs a call under wine** (5,000 calls in 403 ms; a hit
  is 74.6 µs, the same loop doing nothing is under 0.2 µs). One poll a step is
  **0.24% of a 30 fps frame**, so the per-step poll stands — but only because the
  grammar puts every verb in one file. Eight files, the shape `mods/campaign.gml`
  uses, is 2% of a frame, which is why that file gates its polls on `ctick mod 6`.
  `mods/edit/stride` overrides the cadence if a slower machine needs it.
  `directory_exists` measured **7.6 µs**, a 10× cheaper doorbell to put in front
  of the read if the poll ever shows up in a profile.
- **`dump` writes 80–93 instances in 8–12 ms**, so it is cheap enough to fire
  after every settle rather than on request. It stays a verb; the editor decides
  when to call it.
- **`mods/campaign.gml` is superseded, not adopted.** `mods/editor.gml` carries
  its own entry driver — the same sequence, taken from the same stock handler —
  so the editor does not depend on a file that only exists in one install.
  `campaign.gml` stays in the research install as rendering instrumentation.
- **The `ed_*` state lives on a persistent object at depth −10000002.** It
  survives `event_user(14)` because the teardown fires user event 14 and the
  object has no such event; the globals themselves are file-scope and outlive
  every room.
- **`global.<id>_edit` became `global.ed_edit`** — one flag, not one per mission.
  Only one mission is loaded at a time, and a per-mission name would mean
  `editor.gml` had to know which mission it was talking to before it could set
  anything. `ed_pause` and `ed_beat` are mission-independent for the same reason.
- **The view is not 1024×768.** A dump from the live install came back
  `vieww=3140 viewh=1766` — the resolution mod rewrites the ports. The ghost
  overlay must take the view from the dump, never from the room's authored view.

## The puppetted game is windowed

The editor's second screen launches **windowed at 1920×1080** — verified from
inside the game, which reports `win=1920x1080 region=1920x1080 fs=0`. The region
is the load-bearing number: it is the drawing buffer, and only it separates a
native render from an upscale. A window manager cannot answer this — it reports
reparented frames, and gave 1948×1146 for the same window.

Three things this turned up:

- **A wine virtual desktop belongs to the prefix, not the command line.**
  `HKCU\Software\Wine\Explorer` names one and every app launched in that prefix
  gets it. The research prefix still asks for 3840×2160, and `bsf-capture`'s
  runbook depends on that, so the editor uses the private prefix the shipped
  `<Exe>_Linux.sh` launcher makes and leaves the capture prefix alone. This is
  exactly why that launcher makes its own.
- **`res.cfg` and `mode.cfg` are the player's settings**, not scratch state — the
  game rewrites them itself whenever someone picks a resolution. The editor
  stashes them, writes its own, and hands them back on stop, on exit, and on the
  next server start if it was killed instead.
- **The re-bind split had clobbered the resolution.** `mods/resolution.gml`
  rewrites every room's view port at startup, which is how the drawing region is
  built at anything but 1024×768; the generated mod re-asserting its authored
  view on every reload dropped the mission room, and only the mission room, back
  to 4:3 inside a widescreen window. The room's view is now authored once, in the
  define-once block, and never again.

### The camera followed the pointer

Stock BSF edge-scrolls: `ctr_GUI`'s End Step walks `l_viewx`/`l_viewy` toward
whichever edge `mouse_x`/`mouse_y` is past — and the test is against the **view**,
not the window, so a pointer that is not over the game at all still counts as
past the edge. A puppetted game is in that state permanently, because the pointer
lives over the editor. The symptom is a camera that slides away on its own the
moment a seek's `centreCamera` glide finishes: measured, the view origin walked
from 464 to the clamp at 0 in about two seconds.

`mods/editor.gml` appends an action to that same End Step. Appended actions run
*after* the stock ones, so the scroll cannot be prevented — it is undone. While
`window_mouse_get_x/y` report the pointer outside the client area the camera is
held at the last position it had while the pointer was inside, so nothing
accumulates however long it is left there. It yields to the arrow keys and to
`GUI_CamMover`, which is `centreCamera`'s own glide — that is what makes a seek's
camera move still land. Verified: eight seconds motionless at the beat's camera
position, where the same setup used to reach the clamp in two.

It is deliberately not a fix to the stock behaviour. For a player whose pointer
*is* over the game, edge-scrolling is the control scheme; this exists only while
the editor is attached. `window_mouse_get_x()` reads −1940 with the pointer
parked outside and 0 at the client edge, which is exactly the boundary the hold
turns on at.

## The storm: one painted mask, not five circles

A storm started as `zones: [{x, y, r, dmg}]` — circles, drawn as an additive red
disc and tested with `point_distance` per player section per circle per step.
Asking for a *painted* storm rules that out: a brush does not make circles, and
the point of painting is that the shape is arbitrary.

The replacement is a **mask over the room**, one character per 50 world units,
`.` clear, `#` damaging, `@` hot, stored in the YAML as what it is — a picture:

```yaml
storm:
  cell: 50
  dmg: 0.30
  hot: 0.40
  density: 0.18
  lightning: 90
  mask:
    - "..............##########.......######......................."
```

Three things fall out of that choice, and all three are why it is the right one.

**It is faster, not slower.** The mask is decoded once per *load* — in plain file
scope, not per mission entry — into a flat `global.<id>_g[]`. The damage test is
then `floor(y/cell) * cols + floor(x/cell)` and one array read, whatever the
shape. Five circles cost five `point_distance` calls per section per step; an
arbitrary painted region costs one lookup. Measured in the running mission: 29.9
steps/s against a room speed of 30, with the storm, ~100 gas clouds and the
interference pass all on.

**There is exactly one description of a storm.** The clouds you can see are
scattered over the cells that take your HP, so the picture cannot drift from the
danger; there is no second geometry to keep in step, and the editor's prediction
derives its clouds from the mask with the same rule the game does. That is the
whole reason the mask is the storm rather than a paint layer over the circles.

**A short mask is legal.** Nobody should pad forty rows of dots by hand, and the
compiler pads a ragged mask out. The writer trims trailing all-clear rows for the
same reason.

`zones:` still parses and is rasterised into the same field at build time, so a
hand-written mission keeps working. ep9 was migrated by rasterising its five
circles, which is why the mission plays identically to before.

### Rejected: a wash under the clouds

The mask's row runs make an obvious fill — a rectangle per run, additive red,
low alpha — and it was in the first three versions of this at 0.075, then 0.03.
It is wrong at every alpha that is visible at all. Runs are rectangles and
neighbouring rows step by a whole cell, so additive red over black renders the
staircase perfectly: inside a thick storm the clouds bury it, and on a freshly
painted stroke it is a row of visible blocks — which is precisely the case you
are looking at while you paint. It also earns nothing, because boundary cells get
a cloud at p=0.5 whatever `density` says, and each cloud *orbits* its home rather
than drifting off it (a slow `direction` curl on the same 9-frame alarm that
breathes its alpha, bounded at about ±50 units), so the thing you can see stays
where the thing that bites is. There is no wash. The clouds are the storm.

The runs are still computed — they are the table a lightning strike samples its
two endpoints from, which is why they are runs and not cells: one uniform pick
lands anywhere in the storm by area.

## Interference: a stock effect, and one measured deviation

Mission 3 of the stock campaign is the one where the nebulae jam the jump drive,
and its Draw event is the effect: every `ter_Nebula` redrawn additively with
`image_alpha + random(0.4)`, and every player ship redrawn at `xprevious,
yprevious` with `image_xscale * (1 + random(0.2))` at half alpha. That second
pass is the only thing in BSF that makes the *ships* look wrong, which is why it
reads as interference rather than as weather. It is now the beat verb
`interference: on|off`, and it is seekable — it is world state, not an event.

`l_emp = 0.4`, set in the same mission when the jamming starts, is **dead**:
nothing in the decrypted tree ever reads it. The jump lockout is fiction; the
distortion is the whole of what the effect ever was.

One deliberate deviation, and it is measurable. Stock draws the echo exactly at
the previous position, so a ship holding station has the echo land on itself and
the effect all but disappears — mission 3 never noticed, because its player ship
is always under way. A few units of jitter makes a stationary hull shimmer too,
which is what a ship sitting inside a storm should look like. Verified by
differencing two frames with the flag on and off: with the ship stationary and no
jitter the difference is confined to a faint rim; with it, the whole silhouette
moves.

The pass is emitted into the **controller's** Draw at depth −9, matching
`ctr_Mission3`, and the lightning bolt is drawn from there too — the storm object
sits at depth 700 so its own Draw stays behind the clouds, and a bolt drawn there
comes out as a line glimpsed *through* the gas instead of a discharge inside it.

## The brush

The map was the only surface in the editor already drawn in world coordinates, so
the brush lives on it and nowhere else. Two decisions worth keeping:

- **The brush is round in cells, not in pixels.** The mask is the unit of truth,
  so zooming must not change what a click does.
- **One drag is one undo step.** `Model.begin()` snapshots on `pointerdown` and
  the rest of the stroke only mutates; a stroke that changed nothing pops its own
  snapshot again. Otherwise ctrl-Z would walk back through a drag one
  `pointermove` at a time and never reach the state before it.
- **The stroke ends on the window, not on the canvas.** This shipped wrong and
  was reported as "you can't stop painting": the end listeners were on the canvas
  on the strength of `setPointerCapture`, which does deliver the `pointerup`
  there for a press-drag-release inside the page — every synthetic drag passed —
  but not for a release past the edge of the window, a capture dropped by a
  re-render, or a window blurred mid-drag. One missed event and the stroke stays
  open forever, so every later mouse move over the map paints with no button
  down. The ends now sit on `window`, the way the beat drag and the ruler scrub
  already did, capture is demoted to an optimisation, and the backstop needs no
  event at all: a `pointermove` reporting `buttons === 0` is proof the drag is
  over whatever became of the release. Reproduced and re-verified for all three
  cases plus toggling the tool off mid-stroke.

It is a mode with a visible panel rather than an invisible modifier because the
map is otherwise a read-only view: a stray click on it should never silently edit
a mission. The panel carries the storm's own numbers (`dmg`, `hot`, `density`,
`lightning`) because they are the rest of the storm, and the alternative was
hand-editing YAML for the two knobs that decide what it looks like.

## Beacons are dragged on the map

The map drew the mission's geometry from the beginning and let you touch none of
it. For beats that is right — a beat is a moment, and a moment is edited in the
rail — but it is wrong for the Ratlines. **A beacon is a position and has no
other property**, so reading its coordinates out of a dropdown label and typing
them into the YAML is not editing it; it is describing it. Beacons are therefore
draggable, and the gate card grew the same x/y for when a number is what you
actually have.

Two things this had to get right:

- **A beacon is not a per-beat value.** `gates:` is a mission-level list and a
  beat refers to one by index, so moving beacon 2 moves it for every beat that
  waits on it. The fields sit inside a beat's card, which makes that exactly the
  wrong thing to leave implied — the card says so. It is also why the edit does
  not go through `Model.poke`, which walks from `m.beats[i]` and cannot reach a
  beacon at all.
- **It must stand down for the brush.** While the storm brush is up every press
  on the map belongs to it. `handles.js` checks `Paint.state.on` first and does
  nothing, so the two never race for the same pointer.

The drag ends on the window with a `buttons === 0` backstop, for the reason the
brush's does — that bug is a property of pointer capture, not of one tool, and
the second tool to grab the map would have inherited it.

`handles.js` is named for the general case on purpose, and it now carries four
kinds: beacons, scripted spawns, `gate_at`, and the player start. Adding each was
adding a `pick` case, as intended. Three things the second pass settled:

- **Address, don't hold.** A drag carries `{kind, i|bi, si}` and re-resolves the
  live object on every move. Holding the object would work right up to an undo,
  which replaces the model's objects wholesale — after which the drag would go
  on quietly mutating an orphan while the map redrew from the real one.
- **A handle must be visible.** `gate_at` had no marker at all; the route line
  simply bent through a point with nothing drawn on it. That was survivable while
  it was read-only and is not once it can be grabbed, so it is marked now —
  square, where a `gates:` beacon is round, because it belongs to one beat.
- **Not the camera.** A 1024x768 rectangle centred on the station you are trying
  to drag is not a hit target, it is an ambush.

## The map zooms to the pointer

Everything above assumes you can *see* what you are grabbing, and at the fit the
map had shipped with, you frequently could not. A 5000x2000 room in a panel a
few hundred pixels tall draws at roughly a tenth scale: the four wrecks berthed
at the Bolthole gantry are 190 units long, which is two pixels each. They were
draggable and unaimable — the map had become a diagram of the mission rather
than a surface you work on.

The wheel zooms and the map pans, and almost none of that is new machinery.
`drawMap` already accepted `zoom` and `center` and already returned the
transform it drew with, and every tool that grabs anything goes through
`TL.world`, which inverts that same transform. So handles, the storm brush and
the ghost overlay all work zoomed with no change to their *geometry* — the one
place that needed a number it did not have is `drawMap`, which now returns the
*fit* scale alongside the final one, because a module that recomputed the fit
would be guessing at the padding its caller chose.

What zoom did cost the other tools is **arbitration**, and that is worth being
honest about rather than claiming an independence that does not exist. Three
tools now want the same pointer, and each asks about its peers directly:
`view.js` reads `Paint.state.on` and `Handles.state.drag` to decide a press is
a pan, and `handles.js` reads `View.panning()` so a pan does not light up every
handle it sweeps past. That is pairwise, it is why the mount order in
`inspector.js` is load-bearing, and it does not scale — a fourth map tool means
editing all three to say "…unless the new one has it". The generalisation is
for `TL` to own the claim as it already owns the transform, the drag flag and
the repaint, so each tool asks one question instead of N−1. Not built, because
three tools is where the pairwise version is still the smaller thing; the
fourth is where it stops being.

Four rules, and one of them is a correction:

- **Anchored to the pointer, not to the centre.** The world point under the
  cursor stays under the cursor. It is the only behaviour that lets you zoom
  *at* something rather than zoom and then go looking for where it went.
- **The clamp is a backstop and does not get to move what you aimed at.** The
  first version held the room *covering* the canvas, which is the obvious rule
  and is wrong here: a 5000x2000 room in a wide panel is letterboxed at the fit,
  so on the slack axis "cover the canvas" means "stay centred" — and the point
  under the cursor lurched sideways by the slack as it closed, measured at 160
  world units on the first notch. The rule now is that the *centre* stays inside
  the room: weak enough that the anchor holds exactly for any point in the room,
  strong enough that the mission cannot be flicked off the screen. Measured zero
  drift at all four room corners and the middle, from the fit to the ×24
  ceiling; aim at the letterbox *outside* the room and the clamp does win, which
  is the only case where it does and is the right answer to "centre me on
  something that is not the mission". The price is dead space along an edge when
  you pan into a corner, which is what every editor does.
- **Fit is the floor, and it is exactly the old framing.** At zoom 1 the centre
  is dropped entirely and `drawMap` takes its own fit path again, so zooming all
  the way back out lands on the view the map has always had — even if it was
  panned when it got there. `0` does it in one key, and the HUD says so while
  zoomed, because the wheel is discoverable and "how do I see all of it again"
  is not.
- **Panning is what nothing else claimed.** The brush owns the map while it is
  up; a press that grabbed a handle is a handle drag. What is left is a pan, and
  only while zoomed in — at the fit a left-drag on the map does nothing, exactly
  as before. `view.js` mounts *after* `paint.js` and `handles.js` so that by the
  time its `pointerdown` runs, a press either of them wanted has already said so.
  The middle button pans regardless, which is the way out of a corner without
  putting the brush away.

Two things measured rather than assumed. A trackpad pinch arrives as `ctrl` plus
a wheel event with a delta an order of magnitude smaller than a notch, so it
needs its own coefficient or a pinch moves nothing; and the listener is not
passive, because the same `ctrl`-wheel is the browser's own page zoom.

One trap worth recording, because it cost a wrong diagnosis: **Chrome truncates
`clientX`/`clientY` to integers on synthetic events.** The canvas sits at a
fractional `top`, so a test that dispatched a wheel at `rect.top + 300` had it
delivered as 299.01 — and the anchor appeared to drift by about a world unit per
notch. The drift was the harness. Send integer client coordinates and invert
them against the same fractional rect origin the handler uses, and what is left
is the real behaviour above: exactly zero inside the room, the clamp outside it.

## What a prop *is*, not just where

Dragging answers "where", which immediately raises "which". The spawn card had a
free-text object field and a preview that only looked at you, and there are 511
objects — a text field is not a way to answer a question with 511 answers in it.
So the preview is a picker, filtered, with every object drawn as itself.

That covers ships and stations completely, because **the stock designs are
objects**: `SpaceStation`, `BattleStation`, `HestiaAlpha`, `EPirate06`. There is
no file to choose. It does not cover scenery, because scenery is one object per
*kind* — `ter_Planet` is a single object and the game has several planets' worth
of art behind it — so a spawn also carries an optional look:

```yaml
- {object: ter_Planet, x: 2900, y: 860, sprite: spr_Planet2, scale: 1.8, angle: 20, tint: "#ff9944"}
```

which compiles to assignments *after* `instance_create`, i.e. after the object's
own Create event, so they replace what it set for itself. Three consequences
were designed for rather than discovered:

- **Blank means absent, not zero.** `scale: 0` is an invisible prop and
  `tint: ""` is not a colour, so `Model.poke` deletes on `undefined` and the
  rail's input handler sends `undefined` for an empty optional field. The key
  either exists or the compiler leaves the object alone.
- **The look block is offered only for sprite-drawn objects.** A designed ship
  draws its sections and ignores `sprite_index`; a sprite field on one would be
  a control that does nothing, which is worse than no control.
- **The prediction draws the override.** `drawActor` takes the look and skips the
  hull when a sprite is overridden, because otherwise the map would be showing a
  ship the game is not going to draw.
- **…including the rotation, which it did not.** `angle:` here and `facing:` in
  the fixtures both compile to `image_angle`, and a hull reads it — every section
  places itself at `l_offsetdir + l_owner.image_angle`. The hull branch passed
  neither, so a moored ship drew at its design orientation on the map and at its
  facing in the game; EP9's four berthed hulls lay nose-right against a station
  they are supposed to be nose-in to. There is now one answer, `imageAngle`, and
  it encodes the asymmetry rather than averaging it away: facing beats angle
  because the fixtures are emitted last, and a `ship:` spawn honours facing only
  because a design is loaded by `importShip` and never gets the look block at
  all. The lint says so where that used to be silent.

`tint` is written `#rrggbb`, which is a comment marker in YAML — so the writer
quotes any flow-map value that is not a plain scalar, and only those: `x: "2760"`
reads back as a string and everything downstream of it is arithmetic.

## The mission sheet, and the one field that commits on blur

The rail is beat-scoped and the map is the arrangement, which between them left
the mission's own header — `room:`, `player:`, `fail:`, the title — with nowhere
to live. It was YAML-only, in an editor that claims to own the file, and `room:`
is the worst thing on that list to leave out: it is the size of the world every
other coordinate in the mission is measured against, and the map had been
drawing it from the model all along without letting you touch it. So there is a
sheet, on `m`, floating over the map next to the brush.

**The room's width and height apply on commit — blur or Enter — and nothing else
in the editor does.** The rest of the editor applies on `input`, per keystroke,
because per-keystroke is free: the worst case is a repaint of a value you are
about to replace. Room size is not free. The storm mask is a grid sized from it,
so the mask is refitted when it changes, and typing `3000` over `800` passes
through `3`, `30` and `300` on the way. A refit to one column is not a view that
snaps back — it is the mask, and the other 59 columns are gone. Committing once,
when the number is finished, is the only reading of "apply as you type" that
does not destroy data.

Two supports fall out of that:

- **The crop is reported, not silent.** A commit that shrinks the room counts
  the painted cells that fell outside and says how many in the toast. The
  snapshot is taken in the commit, so one `ctrl-Z` is the whole resize —
  dimension and mask together.
- **Out-of-bounds is a lint error, in both linters.** Shrinking a room can
  strand a beacon or a spawn outside it. A `MoveToArea` out there is a rung the
  ship can never satisfy, so the mission hangs on it; a spawn out there never
  joins the fight. Both are silent at runtime, which is exactly why `core.js`
  and `build.py` both refuse them.

The sheet also exposed a defect that predated it. The rail's snapshot-on-focus
listener is bound to the whole stage, so it also fired for the panels floating
over the map, which take their own snapshots — two per focus. Harmless for a
field that applies per keystroke; not harmless for one that commits on blur,
because tabbing out commits the resize and *then* focuses the next field, and
that second snapshot records the state after the edit. `ctrl-Z` appeared to do
nothing. The rail's listener now ignores anything outside `.ins`.

## Ship designs, and the two roots

A stock hull is a Game Maker object, so the object picker already reached every
one of them. What it could not reach was a design that exists only as a *file* —
the campaign's own station, and the eight the game ships in `Custom Ships/`.
Those load through `importShip(file, team, x, y)`, the game's own loader.

The distribution question is the whole of the design. `mods/ships/` is ours: it
is now tracked (the `.gitignore` carve-out is scoped to that folder, and states
that a ship copied out of the game must never be put there), and the installer
already copies `mods/` wholesale, so a mission that uses one works on a player's
machine. `Custom Ships/` is the game's: its eight designs ship inside
`bsf090d.zip`, so they are referenced **in place** and never copied — copying one
would put extracted game data in the repo. Anything else in that folder is a file
on the author's machine only, and the lint warns rather than trusting it.

A design carries what a ship file cannot say. `team:` is required with no default
— the numbers come from sandbox call sites rather than any comment, and a hull on
the wrong side is invisible until it fires. `hold:` stills a station, because a
ship file records its own movement properties and the campaign's has `l_thrust
0.05`; the stock stations zero theirs in their own GML, but a mission is what
knows whether *this instance* is a fixture, and the same design may fly elsewhere.

**The map shares geometry, not the art pipeline.** The server hands the page the
same draw list `scene.py` builds for the PIL renderer and `ship serve`, so the
three cannot disagree about depth order, mirroring or turret pivots; only the
sprite reference is rewritten, because a filesystem path means nothing to a page.
Sprite *bytes* come from the editor's own reader, which is what keeps this
process's "nothing derived from the game is written to disk" true — `tools/bsf`'s
art path caches extracted frames in `.cache/`, which its own rules permit and
this one does not.

That split is also what caught the only real bug in the feature. Ship art is not
the exe's art: `Custom sprites/*.png` are palette PNGs with **no alpha**, whose
empty area is plain black that the game hides by multiplying with the team
colour. A canvas blit painted opaque squares, and twenty sections put a black
slab over the map. The fix is Game Maker's own rule — the bottom-left pixel is
the transparency key — plus the PIL renderer's two-shade mask flattening. Having
two renderers over one scene is what made it measurable: opaque pixels went from
2.96× the reference to 1.06×.

## Still open

- **Writing sh3 is blocked on its tier-2 records**, not on the format. Reading
  all four generations is done, so the editor can draw any design; but converting
  a `.sb4` into the `.shp` the game loads needs `nSec2b/2c/2d/2M/T`, which are
  round-tripped and not understood. Cloning them from the same ship's own export
  fails because nothing computable selects between its two variants (all six
  combinations of yscale and the two candidate fields occur), and fitting the
  permutation from Pendulum's pair is unfalsifiable on eight near-identical
  sections. Until this lands, or ShipMaker's own export is driven from a mod
  lever, `station_bolthole.shp` stays a 20-section hull against a 130-section
  source — which is why the drift warning exists rather than being a nicety.
- The unfreeze re-arms targeting timers with `random()`, exactly as the stock
  sandbox does. BSF never calls `randomize()`, so those draws shift every later
  draw in the run: a mission re-entered after a pause scatters its nebulae
  differently. Harmless for editing, and the reason the prediction calls scenery
  a prediction — but it means a paused session is not bit-comparable with an
  unpaused one.
- A `MoveToArea` gate still fires if the ship is frozen inside its radius: the
  advance lives in the stock object's own Step, and clearing that would mean
  editing a stock event rather than appending to one. Only reachable by pausing
  on top of a beacon.

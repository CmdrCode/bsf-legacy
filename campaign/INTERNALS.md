# Act II — game internals map

Everything Act II hooks into, verified against the decrypted v0.90d tree —
the research root `build.py` discovers, or `$BSF_BASE` (`objects.json`,
`scripts.json`, `dump/all_gml.txt`, `gmobj.walk_section()` for index-correct
names).
Modding rules of engagement are in `MODDING-GUIDE.md` there — append-only
events, no `&&` short-circuit, no string escapes, `var` before `with`.

## The campaign flow (stock)

1. **Career menu** is an overlay in `rm_MainMenu`, not a room.
   `GUI_MainCareer` alarm 0 (event `2:0`) destroys `ctr_MainMenu` and creates
   `GUI_MainBack`, `GUI_CarTitle`, and ten `GUI_CareerMission` slots in two
   columns (x 250/773, y 280..560 step 70). Slots 8/9 get
   `spr_carnotavailable`; slots 0–7 get `spr_car1..8`.
2. **`GUI_CareerMission`** (parent `ctr_MainMenu`): per-instance `l_mission` +
   `sprite_index`. Draw: `image_blend = c_dkgray` when `global.level <
   l_mission`. Click (only when `level >= l_mission`): `global.mission =
   l_mission`, `with (all) event_user(14)` (global teardown),
   `room_goto(rm_Briefing)` (mission 0 goes via `rm_ChooseColour`).
   Current slot (`level = l_mission`) is drawn 1.2×.
   `GUI_MainBack` click destroys `ctr_MainMenu` children + `GUI_CarTitle` and
   rebuilds the main buttons — **`GUI_CarTitle` existing ⇔ career overlay open**.
3. **Briefing**: `rm_Briefing` creation code makes `GUI_BriefingText` +
   `GUI_SecondBack`/`GUI_SecondDone`. `GUI_BriefingText` Create is an
   if/else ladder on `global.mission` setting `l_title`, `l_text`
   (`#` = line break) and the chooser slot counts `global.chooseBB/DD/PC`;
   mission ≥ 8 falls into "Work In Progress".
4. **Ship chooser**: `rm_ChooseShips`. `GUI_SecondDone`'s Create computes
   `l_nextroom`: in briefing → `rm_ChooseShips`; in chooser →
   `switch (global.mission)` → `rm_Mission0..7` (**cases 8/9 name rooms that
   do not exist in the tree** — dead code, errors only if executed).
5. **Mission room**: instances are scenery only (`ter_*`, `obs_*`,
   `Civilian`, `SpaceStation`). Creation code = depth-normalising `with`
   blocks + `instance_create(0,0,ctr_GUI)` +
   `instance_create(0,0,ctr_MissionX)`. Views enabled; camera is code-driven
   (`centreCamera`, `ctr_GUI`).
6. **Progression**: `GUI_MissionSucc` (from `missionSucc()`) on keypress:
   `global.mission += 1`; if `mission > level` → `level += 1` and rewrite
   `bfdat.sav` (10 bytes, `byte[3] = level`, rest random); deletes
   `bfsave.sav`; `with (all) event_user(14)`; `room_goto(rm_Briefing)` —
   the campaign **auto-advances to the next briefing**, which is how Act II
   picks up after EP8 with no extra glue.

## The mission controller contract

- Create: `global.gamecontroller = self.id`, `l_messagecount = 0`, spawn
  ships (`global.chosenships[0..global.chosenshipsnum-1]` for the chosen
  fleet, or scripted hulls directly), `centreCamera(x,y,0)`, music
  (`stopMusic()`, `bgm_Play(global.mus_briefing,1)`), `alarm[2] = 45` to fire
  the opening message.
- **Dialogue is the scheduler**: `showMessage(delay, colour, title, text,
  sprite [, nosound])` creates `GUI_Messager`; on its destroy it does
  `global.gamecontroller.l_messagecount += 1` + `event_user(0)`. The whole
  script is one `if/else if` ladder on `l_messagecount` in **User Event 0
  (event `7:10`)**.
- Non-dialogue triggers jump the counter directly then `event_user(0)`:
  Step (`3:0`) polls kill counts / zones / timers. `MoveToArea` (with
  `.l_target = <ship id>`) self-destructs within 100px of the target,
  increments the counter, and pops any open messager.
- Helpers: `showPing(x,y)`, `showHighlight(id[,colour])`,
  `centreCamera(x,y,speed)`, `missionFail("...")`, `missionSucc()`,
  `saveGame()` (= `ctr_GUI.alarm[4]`, writes `bfsave.sav`; gate on
  `global.difficulty != World_Hard`).
- Meteors: `instance_create(x,y,obs_Meteor)` + `direction/speed/image_*scale`,
  optional `(instance_create(0,0,GUI_AttackArrow)).l_target = obj`.
- Colours (GM BGR literals): friendly `$00FF00`, hostile/objective `c_red`,
  Nanz `$FF00FF`, log white. Portraits: `spr_MesHQ/MesCher/MesHong/MesNag/
  MesHint/MesObj/MesStation/MesMan1/MesMan2`.

## Act II wiring (what our mods do)

- `mods/act2.gml`: appends a rebuild to `GUI_MainCareer` alarm 0 → paged
  ACT I (8 slots) / ACT II (3 slots) menu via a runtime pager object;
  appends Act II briefings to `GUI_BriefingText` Create (`mission ≥ 8`);
  persistent Room Start interceptor bounces `rm_ChooseShips` →
  `global.act2_room[n]` when `gamemode = 0` and `mission ≥ 8` (Act II
  missions skip the chooser — fleets are scripted).
  Career screen layout = the campaign-screen mock (see `_local/mockups/`,
  main checkout): every slot's sprite is blanked to a click mask and the
  pager draws numbered labels (`1. MILK RUN` … `11. - - - - -`) valign-middle
  at the mock's rows, plus amber act-flip buttons on `spr_butGlow` frame 4;
  `GUI_CarTitle`'s draw is cleared and replaced with drawn CHOOSE MISSION at
  the mock size (+10/+20 bm_add echoes). Dev levers in the nav Step:
  `act2menu.req`, `act2page.req`, and `nobattle.on` (deactivates the menu
  battle + doodads for mock-comparison screenshots; delete to restore).
- `mods/act2m1.gml` (**generated — do not hand-edit**): authors the EP9 room
  (`room_add` + creation code) and controller object at init, ladder compiled
  from `campaign/missions/ep9.yaml` by `campaign/build.py`.
- Dialogue strings live as `global.a2m1_t<N>` assignments in the generated
  file (double-quoted plain source, apostrophes legal); event-code strings
  are single-quoted and reference the globals — no quote nesting anywhere.
- `spawn:` entries may carry a look — `sprite`, `scale`, `angle`, `frame`,
  `tint` — emitted as assignments *after* `instance_create`, so they land after
  the object's own Create event and replace what it chose. The instance is
  caught in the mission's global when the entry is `name`d and in the scratch
  `var s` otherwise; the ladder, the seek ladder and the start code all declare
  it. `tint` is authored as `#rrggbb` or a colour word and compiles to
  `make_color_rgb`, because `image_blend` literals are BGR and unreadable.
  Sprite overrides are for sprite-drawn objects (`ter_*`, obstacles): a designed
  ship draws its sections and ignores `sprite_index`.
- A `spawn:` entry may name a ship **design** instead of an object:
  `{ship: mods/ships/station_bolthole.shp, team: ally, hold: true, x: …, y: …}`.
  It compiles to `importShip(path, team, x, y)` — the game's own loader, and what
  the sandbox's spawn-ship uses — so the hull is built by the code that owns the
  format. The path is relative to the game directory and is the string the loader
  receives. Two roots are legal: `mods/ships/` (ours, installed with the mods)
  and `Custom Ships/` (the eight in the stock zip, present on every install).
  ⚠ The path is emitted **double-quoted**: event code is single-quoted GM, and an
  apostrophe inside it has no escape.
  `team:` maps to importShip's second argument — 0 player, 1 enemy, 2 ally, read
  off the sandbox call sites (only `1` is confirmed by a comment, `//SPAWN ENEMY
  SHHIP`) — and is **required**, because a hull on the wrong side looks right
  until it opens fire. `hold:` zeroes `l_thrust`, `l_maxspeed` and `l_turning`
  after the import: a ship file carries its own movement properties and the
  campaign station's are non-zero, so imported as-is it drifts and turns under
  AI. The stock stations solve this in their own GML instead (`Leviathan` is
  `l_thrust=0, l_maxspeed=0.01`).
- `room:` (width/height/caption) is emitted as `room_set_*` in the **re-bound**
  half of the file, not the define-once half, so editing the room size is a
  reload like any other edit. It lands on re-entry rather than immediately:
  `room_set_width` writes the room *resource*, and the running room copied its
  dimensions at room start. The editor's apply always re-enters (`force`), so
  in practice a resize is visible as soon as it is applied. The view is
  deliberately not re-asserted — `mods/resolution.gml` owns it.

## The storm (`storm:` in the mission YAML)

A storm is **one painted mask over the room**, not a list of circles: `.`
clear, `#` damaging, `@` hot, one character per `cell` world units. It is the
only description of the storm anywhere — the gas clouds you can see are
scattered over the same cells that take your HP, so no cell can be dangerous
without being marked. It does not follow that everything red is dangerous; see
below. `tools/editor` paints it.

- The mask rows are emitted as `global.<id>_mrow[N]` and **decoded once per
  load, in plain file scope**, into a flat `global.<id>_g[]` array. That makes
  the damage test inside `with (ShipSection)` a single array read — cheaper
  than the five `point_distance` calls the circles cost, at any shape.
- Row runs (`_spx/_spy/_spw`) are derived the same way. Nothing draws them;
  they are the table a lightning strike samples its two endpoints from, so one
  uniform pick lands anywhere in the storm by area.
- Two generated objects: a **storm** singleton (Create scatters the clouds,
  Step does the damage and counts the bolt/flash frames down, Alarm 0 sites a
  strike, Draw lights the clouds during one) and a **cloud puff**, which is
  `spr_Nebula` tinted red — the palette mask, so `image_blend` is the whole
  effect — animated with `ter_Nebula`'s own 9-frame alarm plus a slow curl that
  orbits each puff around its home instead of letting the cloud drift off the
  cells it is marking.
- Boundary cells get a puff at p=0.5 regardless of `density`, which is what
  keeps a painted edge legible without drawing an outline.
- `zones:` (the older `{x, y, r, dmg}` circles) still parses and is rasterised
  into the same mask at build time. The editor only ever writes a mask.

**The hit goes through `damage(amount, section)`, never through `l_hp -=`.**
BSF has no `l_hp <= 0` check anywhere — a section has no death test of its own,
so *destroying* it is the attacker's job, and `damage()` is where every weapon
and every asteroid does it: below one tick's worth of HP it calls
`instance_destroy()` and debits `l_owner.l_syshp` by what was left, otherwise it
subtracts from both. (Its body is not in the plaintext object tree; the exe's
script section is zlib'd and byte-substituted, and
`_local/research/SCRIPT-OBFUSCATION.md` is how it comes back out.)

Subtracting from `l_hp` by hand skips both halves, which is what the storm did
until 2026-08-14 and it made the storm **decorative**: no section it damaged
could ever be destroyed however long you sat in the gas, and the system bar
(`l_syshp/l_maxsyshp`, the second of the two the HUD draws) never moved. Its one
real effect was invisible — `l_hp` went negative, so the next bullet to touch
that section one-shot it.

**The hull is a second pool and needs its own hit.** A BSF ship draws two bars:
`l_hp/l_maxhp` on the ship instance, and `l_syshp/l_maxsyshp` summed from the
sections and turrets hanging off it. `ctr_Ship` has no step that reads the
second, so **losing every section does not destroy the ship** — measured in
game: a Hestia stripped to `sections = 0` kept flying, `global.<id>_failed`
stayed 0, and the mission carried on. Only `damage(d, <the ship>)` empties the
hull pool and raises MISSION FAILED. The Step therefore tests the ship's own
position as well as each section's. `damage()` skips the `l_syshp` debit for
anything parented to `ctr_Ship`, so the hull hit correctly does not also
discount the parts.

Verified in game on 2026-08-14, ship parked in a `#` cell: Δ`l_syshp` equalled
Δ(sum of section `l_hp`) at every sample, the hull fell at the same 0.3/step as
the sections, and raising `d1` to compress the exposure took the ship to the
MISSION FAILED screen through the shipped code path. No new lines in
`game_errors.log`, which is the only way to know a mod's GML compiled at all.

Two things the mask does *not* promise, both worth knowing before tuning it:

- **The picture is wider than the bite.** `spr_Nebula` is 400×400 with a centred
  origin, drawn at scale 1–2.2, and its radial intensity is half-peak out to
  69px and quarter-peak to 165px. So one puff marking a 50-unit cell reads as red
  out to 1.4–3 cells at half brightness and up to 9 at the faint edge. The cells
  a puff is *spawned* in always bite — the scatter loop only visits `sv > 0` and
  the Step reads the same array — but the converse does not hold, and gas visibly
  laps over clear space.
- **The storm is the player's alone.** The Step filters
  `if (l_owner = global.<id>_ship)`, so enemies and allies fly the same cells for
  free. That is a choice, not an oversight; it is also why the loop is cheap.

## Meteors (`meteors:` in the mission YAML, `meteors: on|off` on a beat)

Alarm 5 on the controller, gated by `global.<id>_meteors`: one `obs_Meteor` per
firing, into a band placed just outside the edge of the screen the rocks come in
by.

```yaml
meteors:
  interval: 35              # frames between spawn attempts while on
  cap: 48                   # max live obs_Meteor — this is the density
  from: top                 # edge they enter by: right | top | bottom | left
  spread: 60                # degrees of fan about straight across
  speed: {min: 1, max: 2.2} # units/step
  region: {x1: 0, x2: 2830} # rocks are only ever placed inside this
```

Everything but `region` has a default (`right`, 60, 1–2.2), so a mission that
writes only `interval` and `cap` gets exactly the field it always had. All of
them are on the editor's mission sheet (`m`).

### Where a rock is put

Two things decide it, and they are **unioned**: a band `500` ahead of the ship,
`300` deep and `400` to either side of it — the ship is what the rocks are aimed
at, and that stays true however the player has moved the camera — and the live
view rectangle, pushed out by `64`.

**Reading the view is the whole of what keeps a rock from being born on screen.**
The band's own numbers describe a 1024x768 view and no room is shown at
1024x768: `mods/resolution.gml` authors every view as `floor(768 * w / h)` by 768
world units, and `ctr_GUI` scales both by `l_zoom`. At 16:9 the view is 1365
wide, its half-width is 682, and `x + 500` is *inside the right-hand edge of the
screen* — rocks used to appear out of nothing in front of the player, worst in
EP9 where the field is dense. Measured in the mission room at 1920x1080: view
1365x768, ship at x 260, old band x 760–1060, and no rock in the room had ever
existed right of x 831.

The 64 is small deliberately. `spr_Meteor` is 32x32 about its centre and
`image_*scale` tops out at 0.9, so 64 units clears the sprite four times over,
and every unit past that is off-screen travel that holds a slot against `cap`
while the player sees nothing. Density is unaffected either way: the population
saturates at `cap`, and time on screen is a property of the crossing, not of
where the crossing began.

### `from` and `spread`

`from` names the edge rocks come **in** by, not the way they travel, and
everything else follows from it: the heading, which axis the band lies along,
and which side of the view it sits on. `top` is low y — GM7 headings put 90 up
and room y grows downward — so rocks entering there travel 270, fanned `spread`
degrees about it (`240..300` at the default 60).

Only the four cardinals are offered. That is a real limit rather than an
oversight: a diagonal heading wants the band spread across *two* edges in
proportion to their projected width, or the rocks bunch in the corner between
them, and no mission has asked for that.

### `region`

The stretch of room the field may fall in. Perpendicular to the drift it is
exact — it is where along the edge rocks may appear, and when the view stops
overlapping it the span goes empty and the field dries up on its own.

**Along** the drift it cannot be exact, and does not pretend to be: the band's
position on that axis is precisely what keeps a spawn off-screen, so it is not
the author's to move. There the region is applied to the *view* instead — no
rocks at all while the player is looking somewhere the region does not reach.

A corner left out is the room's own edge, so a mission constrains only what it
means to; EP9 writes `{x1: 0, x2: 2830}` and takes the room for y. Only the
halves that can actually bite are emitted — a clip against the room edge is a
test that cannot fail, and one sitting in the generated file would read like a
rule.

### `cap`, `interval` and `speed`

**`cap` is the density; `interval` is only the refill rate.** A rock lives until
it leaves the room — `obs_Meteor`'s Alarm 2 divides the distance to the edge by
its own speed and Alarm 1 destroys it there — which for EP9's 5000-unit room at
~1.6 units/step is about a minute. Long enough that the population saturates at
`cap` and sits there, so `interval` decides only how long an empty field takes to
fill (`cap * interval` frames), and it has to stay well inside that lifetime or
the cap is never reached. Scale the pair together — `cap` ×6, `interval` ÷6 — and
the field gets six times denser on the same ramp. Both are on the editor's
mission sheet (`m`), labelled *density* and *refill*.

The mission's own spawn overrides `direction`, `speed` and `image_*scale` after
`instance_create`; that lands before Alarm 2 first runs, so the lifetime is
computed from the mission's velocity and not from `obs_Meteor`'s own random one.

## Editing all of this

Every block and every beat verb below is editable in `tools/editor`, and that is
load-bearing rather than a convenience: **the editor rewrites the whole mission
file from its parsed model on every save, so anything its writer does not emit
is deleted.** `Core.toYaml` therefore writes each of them whether or not a panel
exists for it, and `Core.lint` mirrors `build.py`'s checks so the editor refuses
what the build would reject.

The mission blocks — `bounds:` and `surge:` — live in the mission sheet (`m`),
alongside `meteors:`. The beat verbs — `controls:`, `surge:`, `bounds:` — are
cards in the rail and icons on the beat track, so a beat that takes the helm
away or lights the wall says so where it happens. The map draws the camera
limit as the strip it forbids and the wall as the line it parks on; both are
otherwise invisible until the mission is played.

A save is a fixed point: the file the editor writes is the file it writes again.
That was not true until `reattach_comments` stopped padding with `ljust(22)` —
on a line already 22 wide it is a no-op, the `#` landed flush against the value,
`_split_comment` then refused to read it as a comment (it requires whitespace
before the `#`), and the next save put the space back. The file alternated
between the two forms forever. Pad to 21 and spell the space, exactly as
`Core.toYaml`'s `pad()` does.

## The camera limit (`bounds:`, and `bounds: on|off` on a beat)

```yaml
bounds: {x2: 3600}
```

How far right the camera may look. Clamped with BSF's own room-edge expression —
`bx2 + GUI_MinimapSize * l_zoom - view_wview[0]` — so a bound behaves exactly
like a room that got shorter, discounting the minimap column the same way. That
is what makes the *clear battlefield* stop on the line rather than the view
rectangle. Measured at 1920x1080: the camera shoved to x 5000 lands with its
clear right edge on 3600.00, and on 5600 (the room) with the bound off.

Two ⚠ that cost a build each:

* **Published as a delta**, `view_xview[0] += blim - l_viewx`, never as an
  assignment. `view_xview[0]` also carries the frame's screen shake, and
  assigning would silently cancel it — the same reason `mods/aspect.gml` does it
  this way.
* **Both hooks ask what room they are in.** `ctr_GUI` lives in every battle
  room, so without `if (room = global.act2_roomN)` a mission that ended with the
  bound up would clamp the next skirmish's camera and fog its minimap.

The hook is appended to `ctr_GUI` **once per session**, guarded by a global,
because `object_event_clear` on a stock object would take the game's own camera,
HUD anchoring and `aspect.gml` with it. Everything it does is read from globals,
so a re-apply is still free to change the numbers.

### The minimap half

Without it the limit hides nothing: `ctr_GUI` blips every `ctr_Ship` in the
room, so a station the camera cannot reach is still a cluster of squares in the
corner. A black rectangle past the same line, with the boundary drawn in the
minimap's own green, lifts on the same beat. It is also what stops the limit
reading as a bug — a camera that silently refuses to pan is broken; one that
stops at a line the map draws is a door.

⚠ The rect is **re-derived**, not read off `ctr_GUI`. `mapx1`/`mapx2`/`mapsize`
belong to **ctr_GUILow's** Create, not ctr_GUI's, so reading them from an action
appended to ctr_GUI is `Unknown variable mapx1`, 1321 times in one sitting.
(`mapsizew`/`mapsizeh` are ctr_GUI's own and *are* readable — the rule is per
variable, not per event.) The minimap is `GUI_MinimapSize * global.l_zoom`
square in the view's top-right corner, and everything else the fog needs comes
from globals — see below.

⚠ **The transform is `mods/minimap.gml`'s, not this file's.** The fog and the
map underneath it have to agree to the pixel, or the limit reads as a rendering
fault instead of a wall — so the scale and the letterbox offsets are read from
`global.bsf_mm_u` / `_ox` / `_oy`, guarded by `global.bsf_mm`, rather than
re-derived a second time. This is the same class of bug as the two install
discoveries and the four copies of the wine overrides: two answers to one
question means one drawer can move without the other.

The stock transform is the fallback, for a game with `mods/minimap.off` — and it
is *per axis*, `GUI_MinimapSize / room_width` and `GUI_MinimapSize / room_height`
separately, which is exactly the distortion `minimap.gml` exists to remove. That
is why `uy` is carried beside `u` instead of being assumed equal to it: the two
paths differ in whether the room keeps its aspect ratio, and a shared `u` would
quietly convert the fallback into a wrong answer rather than the stock one.

## The helm lock (`controls: on|off` on a beat)

Takes the ship and the camera away for a scripted stretch. EP9 opens with it
off: three beats set the scene — the nav computer, Helm on the storm wall, the
hint about cells and rocks — and none of them are worth reading while the player
is already flying away from them. It is handed back in the same beat as the
objective that says what to do with it.

* **The ship** stops being selectable (`l_myship = 0`), which is what stops
  orders: the game's own selection loop tests `if !l_myship then continue`.
  Any selection already made is dropped with `l_numselected = 0`, or the player
  keeps the ship they clicked before the lock came on. The End Step then also
  runs the engine's own **Stop Action** — the one the `S` key runs — on the
  hull every frame the helm is locked: `l_movetox`/`l_movetoy` to the hull's
  own position, `l_faceto = -1`, `l_target`/`l_facetarg` to `-4`, `alarm[8] = 0`
  and `l_holdposition = true`. That is belt-and-braces: selection is the gate
  every order path goes through, but a lock resting on one flag on one instance
  is one missed path from being no lock at all, and the failure is invisible
  until someone flies out of a cutscene. `l_holdposition` is released by the
  unlock, which is the only place that can clear it.

  ⚠ **A cleared move order is `l_movetox = x`, not `l_movetox = -4`.**
  `l_movetox > -4` is only how the engine *tests* for a live order; the value
  itself is a world coordinate, so writing `-4` does not clear the order, it
  issues one to the room's top-left corner — and `l_holdposition` does not stop
  a ship that already has somewhere to be. EP9's Hestia flew from (260, 1000)
  to the corner during its own locked introduction. Every place the engine
  wants a hull to stay put writes the hull's own position (`obj.l_movetox =
  obj.x`), which cannot move anything.
* **The camera** is pinned by the same appended `ctr_GUI` End Step as the limit.

  ⚠ **The pin latches from the live camera, never from a stored number.** It
  used to read `global.<gid>_clx`, which the load-time guard initialises to 0 —
  so a room that *starts* locked pinned the view to the room's own top-left
  corner and held it there. EP9 opens with `centreCamera(260, 1000, 0)` in
  Create and the player saw a patch of cloud 1000 units above the ship: the pin
  undid the centring on the very next End Step, every frame, for the whole
  introduction. The camera limit's own `bounds:` block was never involved, which
  is why the symptom looked like a mission-geometry problem rather than a lock.

  `<gid>_cll` is the latch. `0` means *tracking* — follow the camera wherever it
  goes and do not pin — and it is cleared on mission entry and by every
  `camera:` verb. Tracking ends the first frame no `GUI_CamMover` exists, which
  is what makes one rule cover both kinds of scripted move: `speed: 0` is
  instant and latches immediately, a slow pan keeps tracking until the mover
  dies and then latches on the destination. Releasing the lock leaves the camera
  where the script put it rather than snapping back.
* Zoom is deliberately not pinned. It changes what you see without letting you
  go anywhere, and pinning it would fight the reveal.

Whether the room *starts* locked is read off the opening beat rather than given
a key of its own: `alarm[2]` does not fire for 45 frames, and a mission that
opens `controls: off` must not leave a second and a half in which the player can
fly out of the shot.

⚠ `mods/editor.gml` has a camera hold of its own, and it used to make exactly
the same mistake this pin did: it re-asserted `ed_camx` every End Step while the
pointer was outside the game window, and `ed_camx` starts at 0 — so a room
entered with the pointer elsewhere was held at the room's top-left corner, which
is indistinguishable from the mission bug above. It now **adopts** rather than
imposes, on two rules: a room it has not seen before, and any single-frame jump
larger than `scrollspeed * zoom * 2` (edge scroll — the runaway the hold exists
to stop — can never move further than that in a frame, and an instant
`centreCamera(x, y, 0)` makes no `GUI_CamMover` for the older test to catch).
Both the pin and the limit can now be tested with the pointer anywhere.

## The storm wall (`surge:`, and `surge: on|off` on a beat)

```yaml
surge:
  back: 900     speed: 1.2    gap: 500     slack: 800
  rush: 2.2     stop: 3280    dmg: 2.5     shield: 88
```

A front that advances in +x from `back` behind the ship, filling real mask cells
to a third level as it crosses them, so it damages through the same array read
and the same `damage()` path as the painted field — at `dmg` rather than 0.3.
Measured: a parked ship at 55% hull loses all six sections in **2.4 s**, and the
mission fails through the shipped path (`MISSION FAILED — your ship was
destroyed`), so there is no hulk and no soft-lock.

**`speed` is a floor, never a rate.** The front never advances slower, so a ship
that stops is always caught and the wall is never seen *waiting* — the tell that
gives rubber-banding away. Past `slack` it closes at `rush` times speed until
the gap is back to `gap`; that is the whole of what keeps it in frame for a fast
player.

**`stop` is set by the cutscene, not by the scenery.** Reaching the last beacon
fires a dialogue sequence the player cannot fly out of, so the wall has to park
before the ship can be pinned in it. The gate fires within 100 units of the
beacon, so in EP9 the earliest the scene can start is x 3020 and a hull sitting
there reaches back to about 2945; `stop: 2900` leaves the wall at your heels
through the whole exchange and unable to touch you during it. Verified in the
room: the front parks on 2900, the cell under the beacon and the cell under the
trigger ring both read clear, and 2890 reads wall.

Gas is spawned per filled cell at the mask's own density and marked `l_wall`, so
the front can cull its own puffs 1500 behind itself without touching the
painted field's. Every puff carries the marker — including the painted ones,
set to 0 in the puff's Create — because the cull's `with` reads it on all of
them and reading an undefined variable aborts the action.

### Beacon shields

The wall would sweep the dead beacons, and the storm already spares them for
free (its Step filters `if (l_owner = global.<id>_ship)` — only the player is
ever damaged). The shields make that visible rather than mysterious.

**They are not part of the surge, and must not be.** Rocks arrive three beats
before the wall does, and a shield that cannot flare until the storm lights it
is a shield the player never sees do its job — which is exactly how the first
build shipped. The rock-stopping loop is standing machinery in the storm Step:
from the first frame, any `obs_Meteor` entering a bubble is destroyed and that
shield flares for `FLARE` frames.

`shon` is only the **steady** state — the storm having reached that beacon — and
the fill skips cells inside a lit bubble so the gas parts around it. The two
combine in the draw: a dormant shield draws *nothing*, a rock strike is a flash
that fades, and a beacon the storm has reached glows continuously and flashes on
top of that.

Drawn from the controller (depth -9) rather than the storm object (700), so the
bubble reads as being in front of the gas parting around it. A rim, not a disc:
`draw_circle_color` with a black centre under `bm_add` contributes nothing in
the middle and everything at the edge — the game's own shield idiom.

Three ⚠, one per failed build:

* **`draw_circle_color`, not `_colour`.** GM7's drawing API is American
  throughout, and an unknown function is a *compilation* error that fails the
  entire code action: the first build drew no bolt, no interference and no
  shields, and the mission room never finished loading. `Emitter.check_calls`
  now fails the build on any call the game itself never makes. It strips
  line-start `//` comments before scanning, and only those: the section header
  `// the helm lock (camera half)` otherwise matches the call pattern and fails
  the build on a function named `lock` — which is what it did the first time a
  mission used `controls:` without `bounds:`. Comments are stripped at line
  start only because dialogue is emitted as quoted strings on their own lines,
  and a blanket strip would eat the rest of any line of prose containing `//`,
  turning the gate silently into a pass. String *contents* are still scanned,
  and must be: the appended-event code lives inside `'...'` and is compiled.
* **Set alpha before each draw.** Alpha is global draw state, not an argument,
  so the fill inherited the 1.0 left by the previous draw and put an opaque
  milky ball over the beacon it was protecting.
* **48-segment circles.** GM7 draws 24 by default, which at this radius is a
  visible polygon.

## Interference (`interference:` on a beat)

```yaml
interference: on                        # both targets
interference: off                       # neither
interference: {ships: off, clouds: on}  # EP9 at Bolthole
```

Stock `ctr_Mission3`'s Draw event, lifted into a verb: while it is on, every
`ter_Nebula` is redrawn additively with `image_alpha + random(0.4)` and every
`ShipSection` leaves a randomly-scaled half-alpha echo near its previous
position. `l_emp = 0.4` in the stock mission is dead — nothing ever reads it —
so the "jump systems are down" is fiction and the distortion is the whole of
what the effect actually was.

**Two targets, because they are two statements.** `clouds` is the weather — the
nebula redraw, and the storm's own gas with it — and `ships` is the hull echo,
the only stock effect in the game that makes the *player* look wrong, which is
why the effect reads as interference and not as weather. Arriving somewhere safe
is exactly where they part company: the instruments clear, the storm outside
does not stop. EP9 turns `ships` off at Bolthole and leaves `clouds` running,
which is why the yard is drawn crisp against a sky that is still flaring.

They compile to a flag each — `<gid>_interf` for ships, `<gid>_interfc` for
clouds — and the Draw guards the two halves separately. `on`/`off` set both,
which is the whole vocabulary the verb had while the effect was one thing, so
every mission written against it keeps meaning what it meant.

⚠ **A block is the complete state, not a diff**: a target it does not name is
off, so `{ships: off}` stops the weather too. Both linters warn on an incomplete
block rather than letting that be silent — a beat says what the effect *is*
after it, never what it changed, and that is worth one warning to keep.

In `tools/editor` the card is a checkbox per target rather than an on/off
select, and the writer emits the shortest form that says it: a scalar when the
targets agree, the block when they do not. Ticking both gives back the plain
`interference: on` an author would have typed.

Emitted into the controller's **Draw (`8:0`)**, with the controller's depth set
to `-9` to match `ctr_Mission3`. The lightning bolt is drawn from there too:
the storm object sits at depth 700 so a bolt drawn there is a line glimpsed
*through* the gas rather than a discharge inside it.

## Dev install facts

- Live game: the `battleshipsforeverv090d/` install under that research root
  (patched exe, `mods/` chained from `mods/init.gml`; syntax errors are
  silent — check `game_errors.log`, healthy = 49 + one per menu visit).
- `mods/campaign.gml` (gate: `mods/campaign.on`) is the file-driven mission
  entry driver: `mods/mission <n>` → briefing, `mods/adv` → next screen,
  `mods/shotat <n>` → deterministic screenshot. Use it for smoke tests.
- The dev `bfdat.sav` is at `level = 8` — all of Act I complete, EP9
  unlocked.

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
firing into a band ahead of the ship (`x + 500..800`, `y ± 400` — one view tall),
`direction` 150–210 so the rocks come back through it head-on.

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

## Interference (`interference: on|off` on a beat)

Stock `ctr_Mission3`'s Draw event, lifted into a verb: while it is on, every
`ter_Nebula` is redrawn additively with `image_alpha + random(0.4)` and every
`ShipSection` leaves a randomly-scaled half-alpha echo near its previous
position. `l_emp = 0.4` in the stock mission is dead — nothing ever reads it —
so the "jump systems are down" is fiction and the distortion is the whole of
what the effect actually was.

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

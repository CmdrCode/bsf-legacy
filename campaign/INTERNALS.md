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
scattered over the same cells that take your HP, so there is no way for the
danger and the picture to disagree. `tools/editor` paints it.

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

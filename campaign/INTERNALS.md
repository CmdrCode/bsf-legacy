# Act II — game internals map

Everything Act II hooks into, verified against the decrypted v0.90d tree
(`~/Documents/cursor/research/bsf/`: `objects.json`, `scripts.json`,
`dump/all_gml.txt`, `gmobj.walk_section()` for index-correct names).
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

## Dev install facts

- Live game: `~/Documents/cursor/research/bsf/battleshipsforeverv090d/`
  (patched exe, `mods/` chained from `mods/init.gml`; syntax errors are
  silent — check `game_errors.log`, healthy = 49 + one per menu visit).
- `mods/campaign.gml` (gate: `mods/campaign.on`) is the file-driven mission
  entry driver: `mods/mission <n>` → briefing, `mods/adv` → next screen,
  `mods/shotat <n>` → deterministic screenshot. Use it for smoke tests.
- The dev `bfdat.sav` is at `level = 8` — all of Act I complete, EP9
  unlocked.

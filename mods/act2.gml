// Act II — campaign menu (ACT I / ACT II pages) + Act II routing + briefings.
//
// Chained from mods/init.gml. Everything here is append-only runtime GML per
// MODDING-GUIDE.md: stock events keep running first, our code runs after.
// campaign/INTERNALS.md maps every stock hook this file touches.
//
// GM 7 traps honoured throughout: no && short-circuit (nested ifs), var on
// every temporary that enters a with(), no apostrophes inside single-quoted
// event strings.
//
// Geometry: the widescreen mod widens rm_MainMenu and shifts every
// ctr_MainMenu child once by dx = (room_width - 1024) / 2. Instances we
// create at logical 1024-space coordinates get that shift for free; every
// draw_* and mouse zone below applies the same dx itself.
//
// The layout is the campaign-screen mock (_local/mockups/, main repo): text
// centres, cap heights and colours below are measured off its 1365x768
// render. Fonts draw with valign middle, so the y constants ARE the mock's
// text-centre rows; the act2_sc* factors size Visitor caps to the mock's
// (cap 15 headers, 14 slots, 6 captions). Slot labels are drawn text over
// blanked sprites -- spr_car1..8 stay on as click masks, so hit-testing and
// the stock click event never change. crisp.gml's replaced parent draw
// supplies the butGlow band behind every slot and skips the blank sprite.

if (variable_global_exists('act2_init')) exit;
global.act2_init = 1;

global.act2_page = 0;        // 0 = ACT I, 1 = ACT II — remembered across visits
global.act2_visited_menu = 0;
global.act2_room1 = -1;      // EP9 room id, set by mods/act2m1.gml (generated)
global.act2_room2 = -1;      // EP10 — not built yet
global.act2_room3 = -1;      // EP11 — not built yet
global.act2_tick = 0;        // pulse/breathe phase for the career screen

// Mock-calibrated text scales: Visitor TT1 at TextFontLarge size renders a
// 22px cap; the mock wants 15 (headers) and 14 (slots/arrows). TT2 at
// TextFont size gives 10; captions want 6.
global.act2_sc1 = 0.68;      // TextFontLarge -> header cap
global.act2_sc2 = 0.64;      // TextFontLarge -> slot/arrow cap
global.act2_sc3 = 0.60;      // TextFont -> caption cap

// Numbered mission labels (mock spec). Index = global.mission.
global.act2_lbl[0] = '1. MILK RUN';
global.act2_lbl[1] = '2. RAT HOLE';
global.act2_lbl[2] = '3. BUNKER';
global.act2_lbl[3] = '4. TITAN';
global.act2_lbl[4] = '5. SIEGE';
global.act2_lbl[5] = '6. SLAUGHTERHOUSE';
global.act2_lbl[6] = '7. GRAVEYARD';
global.act2_lbl[7] = '8. STRONGHOLD';
global.act2_lbl[8] = '9. BOLTHOLE';
global.act2_lbl[9] = '10. SACRED GROUND';
global.act2_lbl[10] = '11. - - - - -';
// Captions under the Act II slots (index = mission - 8; blank = none).
global.act2_sub[0] = '';
global.act2_sub[1] = 'WORK IN PROGRESS';
global.act2_sub[2] = 'WORK IN PROGRESS';

// --------------------------------------------------------------------------
// The pager: one runtime object that owns the career overlay's slot layout.
// Created by our append on GUI_MainCareer's alarm 0; dies with the overlay
// (GUI_CarTitle is the overlay's lifetime marker — Back destroys it).
// --------------------------------------------------------------------------
var pager;
pager = object_add();
global.act2_pager = pager;

// Create: pick the page and build the slots. The menu battle stays live
// behind the list, as stock.
object_event_add(pager, 0, 0,
    'depth = -100;' +
    'if (global.level >= 8) { if (global.act2_visited_menu = 0) { global.act2_page = 1; global.act2_visited_menu = 1; } }' +
    'event_user(0);');

// User Event 0 (7:10): (re)build the slot instances for global.act2_page.
// Logical 1024-space coordinates — the widescreen mod centres them. Slot rows
// are the mock's: ACT I at y 332 step 70, ACT II at y 360 step 90. Sprites
// are blanked and kept as masks so the pager can draw the numbered labels.
object_event_add(pager, 7, 10,
    'var b, i;' +
    'with (GUI_CareerMission) instance_destroy();' +
    'if (global.act2_page = 0) {' +
    '  for (i = 0; i < 4; i += 1) {' +
    '    b = instance_create(250, 332 + 70*i, GUI_CareerMission);' +
    '    b.l_mission = i;' +
    '    b.sprite_index = -1;' +
    '    if (i = 0) b.mask_index = spr_car1;' +
    '    if (i = 1) b.mask_index = spr_car2;' +
    '    if (i = 2) b.mask_index = spr_car3;' +
    '    if (i = 3) b.mask_index = spr_car4;' +
    '  }' +
    '  for (i = 0; i < 4; i += 1) {' +
    '    b = instance_create(773, 332 + 70*i, GUI_CareerMission);' +
    '    b.l_mission = 4 + i;' +
    '    b.sprite_index = -1;' +
    '    if (i = 0) b.mask_index = spr_car5;' +
    '    if (i = 1) b.mask_index = spr_car6;' +
    '    if (i = 2) b.mask_index = spr_car7;' +
    '    if (i = 3) b.mask_index = spr_car8;' +
    '  }' +
    '} else {' +
    '  for (i = 0; i < 3; i += 1) {' +
    '    b = instance_create(512, 360 + 90*i, GUI_CareerMission);' +
    '    b.l_mission = 8 + i;' +
    '    b.sprite_index = -1;' +
    '    b.mask_index = spr_carnotavailable;' +
    '  }' +
    '}' +
    'with (GUI_CareerMission) { if (global.level = l_mission) { image_xscale = 1.2; image_yscale = 1.2; } }');

// Step: page-arrow clicks, keyboard paging, lifetime, pulse phase.
// Arrow hit zones match the drawn buttons: centres (cx-292, 612) and
// (cx+292, 612), half-box 88 x 22.
object_event_add(pager, 3, 0,
    'if (!instance_exists(GUI_CarTitle)) { instance_destroy(); exit; }' +
    'global.act2_tick += 1;' +
    // Stock hover shimmer: mouse enter sets image_speed = 1 and GM wraps
    // image_index at the sprite frame count — but these slots have no sprite,
    // so the index grows without bound and the inherited butGlow draw
    // ((image_xscale + image_index/20)*4) smears across the screen. Emulate
    // the wrap the sprite would have provided.
    'with (GUI_CareerMission) { if (image_index >= l_glowmax) image_index -= l_glowmax; }' +
    'var mx, my, flip, dxx;' +
    'dxx = (room_width - 1024) / 2;' +
    'if (dxx < 0) dxx = 0;' +
    'mx = mouse_x - dxx; my = mouse_y; flip = 0;' +
    'if (keyboard_check_pressed(vk_right)) { if (global.act2_page = 0) flip = 1; }' +
    'if (keyboard_check_pressed(vk_left))  { if (global.act2_page = 1) flip = 1; }' +
    'if (mouse_check_button_pressed(mb_left)) {' +
    '  if (my > 589) { if (my < 635) {' +
    '    if (mx > 132) { if (mx < 308) { if (global.act2_page = 1) flip = 1; } }' +
    '    if (mx > 716) { if (mx < 892) { if (global.act2_page = 0) flip = 1; } }' +
    '  } }' +
    '}' +
    'if (flip = 1) {' +
    '  sound_play(snd_ClickButtonExit);' +
    '  if (global.act2_page = 0) global.act2_page = 1; else global.act2_page = 0;' +
    '  event_user(0);' +
    '}');

// Draw: act header, numbered slot labels + captions, amber page arrows.
// All text valign-middle at the mock's centre rows; slot text hangs off each
// instance (which already carries the widescreen shift), the rest off
// cx = 512 + dx. The arrow band is spr_butGlow subimage 4 — the sprite's own
// orange frame — untinted, breathing between 0.85 and 1.0 of alpha 0.30.
object_event_add(pager, 8, 0,
    'if (!instance_exists(GUI_CarTitle)) exit;' +
    'var dxx, cx, s1, s2, aa, hv, ax, tk;' +
    'dxx = (room_width - 1024) / 2;' +
    'if (dxx < 0) dxx = 0;' +
    'cx = 512 + dxx;' +
    'tk = global.act2_tick;' +
    's1 = global.act2_sc1;' +
    's2 = global.act2_sc2;' +
    'draw_set_alpha(1);' +
    'draw_set_font(TextFontLarge);' +
    'draw_set_halign(fa_center);' +
    'draw_set_valign(fa_middle);' +
    'draw_set_color($39FF34);' +
    'if (global.act2_page = 0) draw_text_transformed(cx, 264, "ACT I - PIRATE INCURSION", s1, s1, 0);' +
    'else draw_text_transformed(cx, 264, "ACT II - LEGACY OF THE FLEET", s1, s1, 0);' +
    'with (GUI_CareerMission) {' +
    '  var lbl, sub, lk, hv2, sc, yy, ea;' +
    '  lbl = global.act2_lbl[l_mission];' +
    '  lk = 0;' +
    '  if (global.level < l_mission) lk = 1;' +
    '  hv2 = 0;' +
    '  if (lk = 0) {' +
    '    if (abs(mouse_x - x) < 150 * image_xscale) { if (abs(mouse_y - y) < 25 * image_yscale) hv2 = 1; }' +
    '  }' +
    '  sub = "";' +
    '  if (l_mission >= 8) {' +
    '    sub = global.act2_sub[l_mission - 8];' +
    '    if (lk = 1) { if (l_mission = 8) sub = "COMPLETE ACT I TO BEGIN"; }' +
    '  }' +
    '  yy = y;' +
    '  if (sub != "") yy = y - 8;' +
    '  sc = global.act2_sc2 * image_xscale;' +
    '  if (lk = 1) draw_set_color($565E56);' +
    '  else { if (hv2 = 1) draw_set_color($8FFF8D); else draw_set_color($39FF34); }' +
    '  draw_text_transformed(x, yy, lbl, sc, sc, 0);' +
    '  ea = 0;' +
    '  if (lk = 0) {' +
    '    if (hv2 = 1) ea = 0.35;' +
    '    if (global.level = l_mission) { ea = 0.3 + 0.2 * sin(2 * pi * global.act2_tick / 66); if (hv2 = 1) ea = 0.55; }' +
    '  }' +
    '  if (ea > 0) {' +
    '    draw_set_blend_mode(bm_add);' +
    '    draw_set_alpha(ea);' +
    '    draw_text_transformed(x, yy, lbl, sc, sc, 0);' +
    '    draw_set_blend_mode(bm_normal);' +
    '    draw_set_alpha(1);' +
    '  }' +
    '  if (sub != "") {' +
    '    draw_set_font(TextFont);' +
    '    if (lk = 1) draw_set_color($4D564D); else draw_set_color($8B998B);' +
    '    draw_text_transformed(x, y + 12, sub, global.act2_sc3, global.act2_sc3, 0);' +
    '    draw_set_font(TextFontLarge);' +
    '  }' +
    '}' +
    'aa = 0.30 * (0.85 + 0.15 * sin(2 * pi * tk / 84));' +
    'if (global.act2_page = 1) {' +
    '  ax = cx - 292;' +
    '  hv = 0;' +
    '  if (abs(mouse_x - ax) < 88) { if (abs(mouse_y - 612) < 22) hv = 1; }' +
    '  draw_sprite_ext(spr_butGlow, 4, ax, 611, 1.7, 1.6, 0, c_white, aa);' +
    '  if (hv = 1) draw_set_color($79B0FF); else draw_set_color($307AFF);' +
    '  draw_text_transformed(ax, 611, "< ACT I", s2, s2, 0);' +
    '  if (hv = 1) {' +
    '    draw_set_blend_mode(bm_add);' +
    '    draw_set_alpha(0.35);' +
    '    draw_text_transformed(ax, 611, "< ACT I", s2, s2, 0);' +
    '    draw_set_blend_mode(bm_normal);' +
    '    draw_set_alpha(1);' +
    '  }' +
    '}' +
    'if (global.act2_page = 0) {' +
    '  ax = cx + 292;' +
    '  hv = 0;' +
    '  if (abs(mouse_x - ax) < 88) { if (abs(mouse_y - 612) < 22) hv = 1; }' +
    '  draw_sprite_ext(spr_butGlow, 4, ax, 611, 1.7, 1.6, 0, c_white, aa);' +
    '  if (hv = 1) draw_set_color($79B0FF); else draw_set_color($307AFF);' +
    '  draw_text_transformed(ax, 611, "ACT II >", s2, s2, 0);' +
    '  if (hv = 1) {' +
    '    draw_set_blend_mode(bm_add);' +
    '    draw_set_alpha(0.35);' +
    '    draw_text_transformed(ax, 611, "ACT II >", s2, s2, 0);' +
    '    draw_set_blend_mode(bm_normal);' +
    '    draw_set_alpha(1);' +
    '  }' +
    '}' +
    'draw_set_halign(fa_left);' +
    'draw_set_valign(fa_top);');

// Rebuild the overlay after stock builds it: stock alarm 0 runs first (ten
// slots at stock positions), then this — which hands layout to the pager.
object_event_add(GUI_MainCareer, 2, 0,
    'with (GUI_CareerMission) instance_destroy();' +
    'instance_create(0, 0, ' + string(pager) + ');');

// --------------------------------------------------------------------------
// CHOOSE MISSION: the stock bitmap (green slab + alpha letterforms, cap 22)
// is replaced with drawn text at the mock's size and row — same treatment
// crisp.gml gives GUI_OptTitle. The stock +10/+20 double echo is kept, at the
// mock's alphas, drawn bm_add: the stock body wrote draw_set_blend_mode(
// bm_zero), but bm_zero is an _ext constant whose value the simple call reads
// as bm_add — the faint green ghosts were additive all along. The instance
// itself stays: it is the career overlay's lifetime marker.
// --------------------------------------------------------------------------
object_event_clear(GUI_CarTitle, 8, 0);
object_event_add(GUI_CarTitle, 8, 0,
    'var dxx, cx, s1, p, o, a;' +
    'dxx = (room_width - 1024) / 2;' +
    'if (dxx < 0) dxx = 0;' +
    'cx = 512 + dxx;' +
    's1 = global.act2_sc1;' +
    'draw_set_font(TextFontLarge);' +
    'draw_set_halign(fa_center);' +
    'draw_set_valign(fa_middle);' +
    'draw_set_color($39FF34);' +
    'for (p = 0; p < 3; p += 1) {' +
    '  if (p = 0) { o = 20; a = 0.07; draw_set_blend_mode(bm_add); }' +
    '  if (p = 1) { o = 10; a = 0.14; draw_set_blend_mode(bm_add); }' +
    '  if (p = 2) { o = 0;  a = 1;    draw_set_blend_mode(bm_normal); }' +
    '  draw_set_alpha(a);' +
    '  draw_text_transformed(cx + o, 195 + o, "CHOOSE MISSION", s1, s1, 0);' +
    '}' +
    'draw_set_blend_mode(bm_normal);' +
    'draw_set_alpha(1);' +
    'draw_set_halign(fa_left);' +
    'draw_set_valign(fa_top);');

// --------------------------------------------------------------------------
// Act II briefings. Stock GUI_BriefingText Create runs its ladder first
// (mission >= 8 lands on "Work In Progress"); this append overrides it.
// l_counter was reset by stock, so the typewriter types our text.
// --------------------------------------------------------------------------
global.act2_brief1 = "Nineteen years have passed since Nagaya destroyed Fleet HQ. The Terran Federation is gone. What remains of the Fleet fights on from Project Bolthole, a hidden station and colony deep inside the Coalsack nebula, raiding Compact supply lines and rescuing who we can.# #You are returning from a raid with supplies we cannot afford to lose. The storms have flared and the outer Ratline beacons are dark. Jump navigation is impossible inside the nebula - you must fly the lanes by hand, as every captain before you has.# #Bring her home, Captain.# #OBJECTIVES# #- Reach Bolthole Station#- The critical supplies must survive#- Your ship must survive";

object_event_add(GUI_BriefingText, 0, 0,
    'if (global.gamemode = 0) {' +
    '  if (global.mission = 8) {' +
    '    l_title = "Bolthole";' +
    '    l_text = global.act2_brief1;' +
    '    global.chooseBB = 0; global.chooseDD = 0; global.choosePC = 0;' +
    '  }' +
    '  if (global.mission = 9) {' +
    '    l_title = "Sacred Ground";' +
    '    l_text = "Act II Episode 10 - Work In Progress";' +
    '    global.chooseBB = 0; global.chooseDD = 0; global.choosePC = 0;' +
    '  }' +
    '  if (global.mission = 10) {' +
    '    l_title = "Episode 11";' +
    '    l_text = "Act II Episode 11 - Work In Progress";' +
    '    global.chooseBB = 0; global.chooseDD = 0; global.choosePC = 0;' +
    '  }' +
    '}');

// --------------------------------------------------------------------------
// Act II navigation. Act II missions have scripted fleets, so the ship
// chooser is skipped.
// --------------------------------------------------------------------------
// Preferred path: the briefing's Done click. Stock 6:7 already issued
// room_goto(rm_ChooseShips); the LAST room_goto in a step wins, so this append
// re-routes without the chooser ever running (and without tripping the dead
// `case 8: rm_Mission8` line in its Create).
object_event_add(GUI_SecondDone, 6, 7,
    'if (image_blend = c_white) {' +
    '  if (global.gamemode = 0) {' +
    '    if (room = rm_Briefing) {' +
    '      if (global.mission = 8)  { if (global.act2_room1 >= 0) room_goto(global.act2_room1); else room_goto(rm_MainMenu); }' +
    '      if (global.mission = 9)  { if (global.act2_room2 >= 0) room_goto(global.act2_room2); else room_goto(rm_MainMenu); }' +
    '      if (global.mission = 10) { if (global.act2_room3 >= 0) room_goto(global.act2_room3); else room_goto(rm_MainMenu); }' +
    '    }' +
    '  }' +
    '}');

// Fallback for any route that still lands in the chooser (e.g. the campaign
// driver advances via l_nextroom directly, not via the button click).
var nav, i;
nav = object_add();
object_event_add(nav, 7, 4,
    'if (room = rm_ChooseShips) {' +
    '  if (global.gamemode = 0) {' +
    '    if (global.mission = 8)  { if (global.act2_room1 >= 0) room_goto(global.act2_room1); else room_goto(rm_MainMenu); }' +
    '    if (global.mission = 9)  { if (global.act2_room2 >= 0) room_goto(global.act2_room2); else room_goto(rm_MainMenu); }' +
    '    if (global.mission = 10) { if (global.act2_room3 >= 0) room_goto(global.act2_room3); else room_goto(rm_MainMenu); }' +
    '  }' +
    '}');
// Dev levers, file-driven like mods/campaign.gml: open the career overlay /
// flip the act page without a mouse (synthetic clicks never reach the game),
// and silence the menu battle while comparing screenshots against the mock
// (mods/nobattle.on; deactivation, not destruction — MainMenuShip's Destroy
// event respawns a replacement, so destroying is a treadmill).
object_event_add(nav, 3, 0,
    'if (room = rm_MainMenu) {' +
    '  if (file_exists("mods/act2menu.req")) {' +
    '    file_delete("mods/act2menu.req");' +
    '    with (GUI_MainCareer) { image_blend = c_white; alarm[0] = 1; }' +
    '  }' +
    '  if (file_exists("mods/act2page.req")) {' +
    '    file_delete("mods/act2page.req");' +
    '    if (global.act2_page = 0) global.act2_page = 1; else global.act2_page = 0;' +
    '    with (' + string(pager) + ') event_user(0);' +
    '  }' +
    '  if (file_exists("mods/nobattle.on")) {' +
    '    instance_deactivate_object(MainMenuShip);' +
    '    instance_deactivate_object(MainMenuEShip);' +
    '    instance_deactivate_object(ShipSection);' +
    '    instance_deactivate_object(EShipSection);' +
    '    instance_deactivate_object(ctr_Turrets);' +
    '    instance_deactivate_object(ctr_ETurrets);' +
    '    instance_deactivate_object(ctr_AllBullets);' +
    '    instance_deactivate_object(ctr_AllBeams);' +
    '    instance_deactivate_object(ctr_LowAllBullets);' +
    '    instance_deactivate_object(ctr_LowAllBeams);' +
    '    instance_deactivate_object(obs_Meteor);' +
    '    instance_deactivate_object(obs_StayMeteor);' +
    // Ship-attached doodads read rs_owner.* every End Step; once the owner is
    // deactivated that read throws per frame. Menu decor goes with them.
    '    instance_deactivate_object(ctr_Doodads);' +
    '  }' +
    '}');
i = instance_create(0, 0, nav);
i.persistent = true;

// Episodes (generated by campaign/build.py — do not hand-edit those files).
if (file_exists('mods/act2m1.gml')) execute_file('mods/act2m1.gml');

// Breadcrumb: this line only runs if everything above compiled and executed.
var lf;
lf = file_text_open_write('mods/act2.log');
file_text_write_string(lf, 'act2 ok  ep9room=' + string(global.act2_room1));
file_text_writeln(lf);
file_text_close(lf);

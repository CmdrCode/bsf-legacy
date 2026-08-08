// ShipMaker -- Factorio-style part picker: quickbar + hand (+ pipette and
// search inventory in later phases).
//
// The quickbar is 10 pages x 10 slots of LINKS to parts -- Factorio's model,
// not Minecraft's: a slot never contains anything, it names a part. Two pages
// are visible above the canvas bottom edge; digits 1-0 pick the top row's
// link into the HAND (pressing the same digit returns it), X rotates which
// page is on top, Shift+digit jumps that page to the top. The hand is
// independent of the quickbar and is drawn as a ghost at the cursor.
//
// -------------------------------------------------------------- key takeover
// Stock keys are per-object KeyPress events that object_event_add can only
// append to, so keys are taken by CAPTURE-THEN-CLEAR: read
// keyboard_check_pressed in Begin Step (GM runs it before all Keyboard
// events) and keyboard_clear() the key so the stock KeyPress never fires --
// verified live on this runner (phase-0 probe, 2026-08-08): stock Z stayed
// dead across 9 cleared presses and fired again with capture disabled, and
// keyboard_string still accumulates past cleared keys. Taken while the mod is
// on: plain digits 1-0 (stock 1-4 place/cycle the sidebar part), Shift+digits,
// tap-X (stock X is only a held wheel modifier -- never cleared while a wheel
// could be turning, only on tap frames), and Esc only when the hand is full.
// Ctrl+digit passes through to stock cycling.
//
// ------------------------------------------------------------------- state
// Durable state lives in a ds_grid because the stock undo (savestate() =
// game_save; Ctrl+Z / preview exit = game_load) round-trips instances AND
// globals but NOT ds structures: grid contents are undo-proof by
// construction, exactly like Factorio's quickbar surviving map edits. The
// grid id itself never changes after boot, so the restored global still
// points at the live grid. Cells are "kind|name|lname" strings (kind 0
// empty, 1 section, 2 weapon, 3 module, 4 doodad; name = palette list name /
// sprite resource name; lname = Custom sprites relpath, empty for embedded
// sprites). Meta row 10: [0]=top page, [1]=hand cell, [2]=generation counter
// that the per-instance sprite cache keys off, so a game_load that reverts
// the cache arrays rebuilds them on the next Step.
//
// The layout persists in mods/smpick.cfg (header + 100 cell lines), written
// on every mutation, loaded at boot -- so it also survives "New ship"
// (game_restart wipes every global and re-runs the module chain; the boot
// guard below tests the VALUE, see mods/sm.gml).
//
// ------------------------------------------------------------------ levers
// mods/pickreq (one command per line, deleted after read; the file is the
// only way to drive mouse-dependent paths under wine, where synthetic clicks
// never reach the game): digit N, sdigit N, x, esc, pipette, place, clear S,
// mopen, mclose, mquery TEXT, chipn N, nav N, enter, mclick, abind S, seed,
// write, rep. mods/capoff disables all key capture (control condition).
// mods/smpick.txt: state report every 60 steps under probe.on and after every
// lever batch. One slot/hand action per batch -- later lines overwrite the
// pending action of earlier ones.

var inited;
inited = 0;
if (variable_global_exists('bsf_smpick_init'))
    if (global.bsf_smpick_init)
        inited = 1;
if (inited) exit;
global.bsf_smpick_init = 1;

global.pp_grid = ds_grid_create(10, 11);
var c;
for (c = 0; c <= 9; c += 1) {
    var r2;
    for (r2 = 0; r2 <= 9; r2 += 1)
        ds_grid_set(global.pp_grid, c, r2, '0||');
}
ds_grid_set(global.pp_grid, 0, 10, 0);      // top page
ds_grid_set(global.pp_grid, 1, 10, '0||');  // hand
ds_grid_set(global.pp_grid, 2, 10, 1);      // generation

var m, i;
m = object_add();

// ------------------------------------------------------------------ Create
object_event_add(m, 0, 0,
    'tick = 0; repnow = 0; seeded = 0;' +
    'kdig = -1; kshift = 0; kx = 0; kesc = 0; kq = 0; kplace = 0;' +
    'kmodal = 0; kenter = 0; knav = 0; kclick = 0;' +
    'modal = 0; amode = 0; aslot = -1; apage = 0;' +
    'chip = 0; chiplast = -1; msel = 0; mscroll = 0; qlast = "##"; fcount = 0; hovt = -1;' +
    'catn = 0; justclosed = 0;' +
    'catcell[0] = ""; catdisp[0] = ""; catkind[0] = 0; catspr[0] = -1; catfit[0] = 1; fidx[0] = 0;' +
    'cgen = 0; hstr = "##"; handspr = -1; handkind = 0; handdisp = ""; handnm = ""; handlnm = "";' +
    'lastplaced = "";' +
    'wmap = -1; mmap = -1;' +
    // the mipdraw library instance (loaded before us in mods/sm.gml); -1 and
    // we fall back to single-tap linear shrinks
    'mlib = -1;' +
    'if (variable_global_exists("mip_obj")) mlib = global.mip_obj;' +
    'var s2;' +
    'for (s2 = 0; s2 <= 99; s2 += 1) { cspr[s2] = -1; ckind[s2] = 0; cdisp[s2] = ""; cfit[s2] = 1; cbig[s2] = 0; }' +
    'lastact = "boot";' +
    // Load the persisted layout. Strings only -- sprites resolve lazily in
    // Step once the palette lists are live.
    'if (file_exists("mods/smpick.cfg")) {' +
    '  var g, ln, p2, s3;' +
    '  g = file_text_open_read("mods/smpick.cfg");' +
    '  ln = file_text_read_string(g); file_text_readln(g);' +
    '  p2 = string_pos("=", ln);' +
    '  if (p2 > 0) ds_grid_set(global.pp_grid, 0, 10, real(string_delete(ln, 1, p2)));' +
    '  for (s3 = 0; s3 <= 99; s3 += 1) {' +
    '    if (file_text_eof(g)) break;' +
    '    ln = file_text_read_string(g); file_text_readln(g);' +
    '    if (ln != "") ds_grid_set(global.pp_grid, s3 mod 10, s3 div 10, ln);' +
    '  }' +
    '  file_text_close(g);' +
    '  seeded = 1;' +
    '}');

// ------------------------------------------------- Begin Step: key capture
object_event_add(m, 3, 1,
    'if (file_exists("mods/capoff")) exit;' +
    // Modal open: assert the stock "text field focused" gate (suppresses every
    // esel-gated handler, digits included -- they flow into keyboard_string as
    // search text), capture our nav keys, and clear the UNGATED sidebar
    // letters (Z picker toggle, S save dialog, M mirror...) so typing a part
    // name has zero stock side effects. E is NOT a close key here -- names
    // contain the letter. Esc / Enter / click close.
    'if (modal) {' +
    '  global.gui_esel = 1;' +
    '  if (keyboard_check_pressed(vk_enter)) kenter = 1;' +
    '  if (keyboard_check_pressed(vk_escape)) { kmodal = 1; keyboard_clear(vk_escape); }' +
    '  if (keyboard_check_pressed(vk_left)) knav = 1;' +
    '  if (keyboard_check_pressed(vk_right)) knav = 2;' +
    '  if (keyboard_check_pressed(vk_up)) knav = 3;' +
    '  if (keyboard_check_pressed(vk_down)) knav = 4;' +
    '  if (keyboard_check_pressed(33)) knav = 5;' +
    '  if (keyboard_check_pressed(34)) knav = 6;' +
    '  var d3;' +
    '  for (d3 = 65; d3 <= 90; d3 += 1) if (keyboard_check_pressed(d3)) keyboard_clear(d3);' +
    '  if (keyboard_check_pressed(32)) keyboard_clear(32);' +
    '  exit;' +
    '}' +
    'if (global.gui_esel) exit;' +
    'if (keyboard_check_pressed(69)) { kmodal = 1; keyboard_clear(69); }' +
    'var d, hand;' +
    'hand = ds_grid_get(global.pp_grid, 1, 10);' +
    'for (d = 48; d <= 57; d += 1) {' +
    '  if (keyboard_check_pressed(d)) {' +
    '    if (d >= 49 && d <= 52 && keyboard_check(vk_control)) d = d;' +   // pass Ctrl+1-4 to stock
    '    else {' +
    '      if (d == 48) kdig = 9; else kdig = d - 49;' +
    '      kshift = keyboard_check(vk_shift);' +
    '      keyboard_clear(d);' +
    '    }' +
    '  }' +
    '}' +
    'if (keyboard_check_pressed(88)) { kx = 1; keyboard_clear(88); }' +
    'if (keyboard_check_pressed(vk_escape)) {' +
    '  if (hand != "0||") { kesc = 1; keyboard_clear(vk_escape); }' +
    '}' +
    // Q is taken only when it has pipette work to do: hand full (empty it) or
    // a part under the cursor (grab its type). Stock Q (depth shuffle / scale
    // tweak on SELECTED parts) stays reachable with the cursor off parts.
    'if (keyboard_check_pressed(81)) {' +
    '  var tk;' +
    '  tk = 0;' +
    '  if (hand != "0||") tk = 1;' +
    '  else {' +
    '    event_user(5); event_user(4);' +
    '    if (global.pp_hcell != "") tk = 1;' +
    '  }' +
    '  if (tk) { kq = 1; keyboard_clear(81); }' +
    '}');

// --------------------------------------------------------------- Step
object_event_add(m, 3, 0,
    'tick += 1;' +
    'if (!instance_exists(obj_sidebar)) exit;' +
    'event_user(5);' +
    'var tp, hand, gen;' +
    'tp = ds_grid_get(global.pp_grid, 0, 10);' +
    'hand = ds_grid_get(global.pp_grid, 1, 10);' +
    'gen = ds_grid_get(global.pp_grid, 2, 10);' +

    // One-time default layout, once the stock palette lists are live: first
    // sections of group A, first weapons/modules/doodad -- all read from the
    // stock tables so the names are guaranteed resolvable.
    'if (!seeded && global.sec_num[1] >= 4 && global.doo_num >= 1) {' +
    '  seeded = 1;' +
    '  var s4;' +
    '  for (s4 = 0; s4 <= 3; s4 += 1)' +
    '    ds_grid_set(global.pp_grid, s4, 0, "1|" + string(ds_list_find_value(global.secg1_name, s4)) + "|" + string(ds_list_find_value(global.secg1_lname, s4)));' +
    '  ds_grid_set(global.pp_grid, 4, 0, "2|" + getweapon(0) + "|");' +
    '  ds_grid_set(global.pp_grid, 5, 0, "2|" + getweapon(1) + "|");' +
    '  ds_grid_set(global.pp_grid, 6, 0, "3|" + getmodule(0) + "|");' +
    '  ds_grid_set(global.pp_grid, 7, 0, "3|" + getmodule(1) + "|");' +
    '  ds_grid_set(global.pp_grid, 8, 0, "4|" + string(ds_list_find_value(global.doo_name, 0)) + "|" + string(ds_list_find_value(global.doo_lname, 0)));' +
    '  gen += 1; ds_grid_set(global.pp_grid, 2, 10, gen);' +
    '  event_user(1);' +
    '}' +

    // ------------------------------------------------------- lever: pickreq
    'if (tick mod 15 == 0 && file_exists("mods/pickreq")) {' +
    '  var g2, ln2, sp2, cmd, arg, args;' +
    '  g2 = file_text_open_read("mods/pickreq");' +
    '  while (!file_text_eof(g2)) {' +
    '    ln2 = file_text_read_string(g2); file_text_readln(g2);' +
    '    if (ln2 == "") continue;' +
    '    sp2 = string_pos(" ", ln2);' +
    // args stays a STRING here -- real() on a non-numeric string is a runtime
    // error that aborts Step mid-loop with the lever file still open (leaks a
    // handle per frame and wedges the module). Numeric commands convert below.
    '    if (sp2 > 0) { cmd = string_copy(ln2, 1, sp2 - 1); args = string_delete(ln2, 1, sp2); }' +
    '    else { cmd = ln2; args = ""; }' +
    '    arg = 0;' +
    '    if (args != "") if (string_digits(args) == args) arg = real(args);' +
    '    if (cmd == "digit") { kdig = arg; kshift = 0; }' +
    '    if (cmd == "sdigit") { kdig = arg; kshift = 1; }' +
    '    if (cmd == "x") kx = 1;' +
    '    if (cmd == "esc") kesc = 1;' +
    '    if (cmd == "clear") {' +
    '      ds_grid_set(global.pp_grid, arg, tp, "0||");' +
    '      gen += 1; ds_grid_set(global.pp_grid, 2, 10, gen);' +
    '      event_user(1); lastact = "clear " + string(arg);' +
    '    }' +
    '    if (cmd == "seed") seeded = 0;' +
    '    if (cmd == "write") event_user(1);' +
    '    if (cmd == "pipette") kq = 1;' +
    '    if (cmd == "place") kplace = 1;' +
    '    if (cmd == "mopen") { if (!modal) kmodal = 1; }' +
    '    if (cmd == "mclose") { if (modal) kmodal = 1; }' +
    '    if (cmd == "mquery") keyboard_string = args;' +
    '    if (cmd == "chipn") { chip = arg; }' +
    '    if (cmd == "nav") knav = arg;' +
    '    if (cmd == "enter") kenter = 1;' +
    '    if (cmd == "mclick") kclick = 1;' +
    '    if (cmd == "abind") { amode = 1; aslot = arg; apage = tp; kmodal = 1; }' +
    '  }' +
    '  file_text_close(g2); file_delete("mods/pickreq");' +
    '  repnow = 1;' +
    '}' +

    // ------------------------------------------------------- captured keys
    'if (kx) {' +
    '  kx = 0;' +
    '  tp = (tp + 1) mod 10;' +
    '  ds_grid_set(global.pp_grid, 0, 10, tp);' +
    '  event_user(1); lastact = "x -> page " + string(tp + 1);' +
    '}' +
    'if (kdig >= 0) {' +
    '  var cell;' +
    '  if (kshift) {' +
    '    tp = kdig; ds_grid_set(global.pp_grid, 0, 10, tp);' +
    '    event_user(1); lastact = "page " + string(tp + 1) + " to top";' +
    '  }' +
    '  else {' +
    '    cell = ds_grid_get(global.pp_grid, kdig, tp);' +
    '    if (string_char_at(cell, 1) != "0") {' +
    '      if (hand == cell) { hand = "0||"; lastact = "hand emptied"; }' +
    '      else { hand = cell; lastact = "picked slot " + string(kdig + 1); }' +
    '      ds_grid_set(global.pp_grid, 1, 10, hand);' +
    '    }' +
    '  }' +
    '  kdig = -1; kshift = 0;' +
    '}' +
    'if (kesc) {' +
    '  kesc = 0;' +
    '  hand = "0||"; ds_grid_set(global.pp_grid, 1, 10, hand);' +
    '  lastact = "hand emptied (esc)";' +
    '}' +

    // ------------------------------------------------------- Q pipette
    // Full hand: empty it (Factorio clear-hand). Empty hand: grab the type of
    // the part under the cursor. Hit order turret-first (weapons/modules/
    // doodads sit on hulls); obj_core is not an obj_section child, so the
    // core can never be grabbed.
    'if (kq) {' +
    '  kq = 0;' +
    '  if (hand != "0||") {' +
    '    hand = "0||"; ds_grid_set(global.pp_grid, 1, 10, hand);' +
    '    lastact = "pipette: hand emptied";' +
    '  }' +
    '  else {' +
    '    event_user(4);' +
    '    if (global.pp_hcell != "") {' +
    '      hand = global.pp_hcell; ds_grid_set(global.pp_grid, 1, 10, hand);' +
    '      lastact = "pipette: " + hand;' +
    '    }' +
    '    else lastact = "pipette: nothing grabbable";' +
    '  }' +
    '}' +

    // catalog + inventory modal live in user 6 (the Step string was
    // pushing 15KB in one expression, past what the GM7 compiler accepts)
    'event_user(6);' +

    // --------------------------------------------- mouse on the quickbar
    // Same geometry as Draw: integer screen-pixel offsets off the same
    // snapped anchors (see the Draw comment) -- the two blocks must stay
    // identical. Left press on a filled slot toggles it into the hand; on an
    // empty slot with a full hand it sets the link; right press clears it.
    'var z5, zy5, cx5, yb5, bx5, row5, sl5, rx5, ry5, hit5, hp5;' +
    'z5 = obj_sidebar.l_zoom;' +
    'if (view_wport[1] > 0) z5 = view_wview[1] / view_wport[1];' +
    'zy5 = z5;' +
    'if (view_hport[1] > 0) zy5 = view_hview[1] / view_hport[1];' +
    'cx5 = view_xview[1] + view_wview[1] / 2;' +
    'yb5 = view_yview[1] + (floor(view_hview[1] / zy5 + 0.25) - 12 + 0.03) * zy5 + 0.5 * (1 - zy5);' +
    'bx5 = view_xview[1] + (floor(view_wview[1] / (2 * z5) + 0.25) - 264 + 0.03) * z5 + 0.5 * (1 - z5);' +
    'hit5 = -1; hp5 = tp;' +
    'if (modal == 0 && justclosed == 0 && global.pp_overcv && global.pp_wx >= bx5 + 533 * z5 && global.pp_wx <= bx5 + 581 * z5) {' +
    '  if (global.pp_wy >= yb5 - 106 * zy5 && global.pp_wy <= yb5 - 58 * zy5) {' +
    '    if (mouse_check_button_pressed(mb_left)) kmodal = 1;' +
    '  }' +
    '}' +
    'if (modal == 0 && justclosed == 0 && global.pp_overcv && global.pp_wx >= bx5 && global.pp_wx <= bx5 + 530 * z5) {' +
    '  if (global.pp_wy >= yb5 - 106 * zy5 && global.pp_wy <= yb5 - 58 * zy5) hit5 = floor((global.pp_wx - bx5) / (53 * z5));' +
    '  if (global.pp_wy >= yb5 - 53 * zy5 && global.pp_wy <= yb5 - 5 * zy5) { hit5 = floor((global.pp_wx - bx5) / (53 * z5)); hp5 = (tp + 1) mod 10; }' +
    '}' +
    'if (hit5 >= 0 && hit5 <= 9) {' +
    '  if (mouse_check_button_pressed(mb_left)) {' +
    '    var cell5;' +
    '    cell5 = ds_grid_get(global.pp_grid, hit5, hp5);' +
    '    if (string_char_at(cell5, 1) != "0") {' +
    '      if (hand == cell5) hand = "0||"; else hand = cell5;' +
    '      ds_grid_set(global.pp_grid, 1, 10, hand);' +
    '      lastact = "click slot " + string(hit5 + 1) + " page " + string(hp5 + 1);' +
    '    }' +
    '    else if (hand != "0||") {' +
    '      ds_grid_set(global.pp_grid, hit5, hp5, hand);' +
    '      gen += 1; ds_grid_set(global.pp_grid, 2, 10, gen);' +
    '      event_user(1); lastact = "linked slot " + string(hit5 + 1);' +
    '    }' +
    '    else {' +
    '      amode = 1; aslot = hit5; apage = hp5; kmodal = 1;' +
    '      lastact = "link mode for slot " + string(hit5 + 1);' +
    '    }' +
    '  }' +
    '  if (mouse_check_button_pressed(mb_right)) {' +
    '    ds_grid_set(global.pp_grid, hit5, hp5, "0||");' +
    '    gen += 1; ds_grid_set(global.pp_grid, 2, 10, gen);' +
    '    event_user(1); lastact = "cleared slot " + string(hit5 + 1);' +
    '  }' +
    '}' +

    // ------------------------------------------ sprite cache maintenance
    'if (cgen != gen) event_user(0);' +
    'if (hstr != hand) {' +
    '  hstr = hand;' +
    '  handspr = -1; handkind = 0; handdisp = ""; handnm = ""; handlnm = "";' +
    '  if (string_char_at(hand, 1) != "0") {' +
    '    global.pp_rk = 0; global.pp_rspr = -1; global.pp_rdisp = ""; global.pp_rn = ""; global.pp_rlnm = "";' +
    '    global.pp_cell = hand; event_user(2);' +
    '    handkind = global.pp_rk; handspr = global.pp_rspr; handdisp = global.pp_rdisp;' +
    '    handnm = global.pp_rn; handlnm = global.pp_rlnm;' +
    '  }' +
    '}' +

    // ----------------------------------------------------- click-place
    // Left press over the canvas with a resolved hand places the part at the
    // cursor -- the stock space-place recipe, minus the drag: the hand
    // persists for repeat placement. Stock per-instance selection also runs
    // on the same click; the new part selects itself in its Create, so the
    // last write wins. Quickbar hits were consumed above (hit5 >= 0).
    'var wantpl;' +
    'wantpl = 0;' +
    'if (kplace) { kplace = 0; wantpl = 1; }' +
    'if (mouse_check_button_pressed(mb_left)) if (hit5 < 0) if (modal == 0) wantpl = 1;' +
    'if (justclosed) { justclosed = 0; wantpl = 0; }' +
    'if (wantpl && handkind > 0 && handspr >= 0) {' +
    '  var okpl, np;' +
    '  okpl = 1;' +
    '  if (!global.pp_overcv) okpl = 0;' +
    '  if (global.grouparrange) okpl = 0;' +
    '  if (global.gui_esel) okpl = 0;' +
    '  if (variable_global_exists("preview")) if (global.preview) okpl = 0;' +
    '  if (handkind == 4 && global.last_selected == obj_core.id) { okpl = 0; showHint("Doodads cannot attach to the core"); }' +
    '  if (okpl) {' +
    '    savestate();' +
    '    if (handkind == 1) {' +
    '      np = instance_create(global.pp_wx, global.pp_wy, obj_section);' +
    '      np.sprite_index = handspr; np.lname = handlnm;' +
    '    }' +
    '    if (handkind == 2) {' +
    '      np = instance_create(global.pp_wx, global.pp_wy, obj_weapon);' +
    '      np.sprite_index = handspr; np.l_type = handspr;' +
    '      with (np) event_user(1);' +
    '      with (np) wepSetDefvals();' +
    '      if (handnm == "Demeter" || handnm == "QuadBlaster" || handnm == "PointBeam" || handnm == "ParticleGun" || handnm == "PointMaser" || handnm == "PointRocket") np.arcrange = 180;' +
    '      if (handnm == "QuadBlaster") np.image_index = np.image_number - 1;' +
    '    }' +
    '    if (handkind == 3) {' +
    '      np = instance_create(global.pp_wx, global.pp_wy, obj_module);' +
    '      np.sprite_index = handspr;' +
    '      with (np) modSetDefvals();' +
    '    }' +
    '    if (handkind == 4) {' +
    '      np = instance_create(global.pp_wx, global.pp_wy, obj_doodad);' +
    '      np.sprite_index = handspr; np.lname = handlnm;' +
    '    }' +
    '    np.dragged = false;' +
    '    global.object_dragged = false;' +
    '    obj_sidebar.mxchange = 0; obj_sidebar.mychange = 0;' +
    '    obj_sidebar.mxprevious = mouse_x; obj_sidebar.myprevious = mouse_y;' +
    '    lastplaced = string(object_get_name(np.object_index)) + ":" + string(np.x) + "," + string(np.y);' +
    '    lastact = "placed " + handdisp;' +
    '  }' +
    '  else lastact = "place refused (overcv=" + string(global.pp_overcv) + ")";' +
    '}' +

    // ------------------------------------------------------------- report
    'if (repnow || (tick mod 60 == 0 && file_exists("mods/probe.on"))) {' +
    '  repnow = 0;' +
    '  var f6, s6, row6;' +
    '  f6 = file_text_open_write("mods/smpick.txt");' +
    '  file_text_write_string(f6, "tick=" + string(tick) + " toppage=" + string(tp + 1) + " gen=" + string(gen)); file_text_writeln(f6);' +
    '  file_text_write_string(f6, "hand=" + hand + " handspr=" + string(handspr) + " handdisp=" + handdisp); file_text_writeln(f6);' +
    '  row6 = "";' +
    '  for (s6 = 0; s6 <= 9; s6 += 1) row6 = row6 + cdisp[tp * 10 + s6] + ",";' +
    '  file_text_write_string(f6, "toprow=" + row6); file_text_writeln(f6);' +
    '  file_text_write_string(f6, "counts=" + string(instance_number(obj_section)) + "," + string(instance_number(obj_weapon)) + "," + string(instance_number(obj_module)) + "," + string(instance_number(obj_doodad))); file_text_writeln(f6);' +
    '  file_text_write_string(f6, "esel=" + string(global.gui_esel) + " secpicker=" + string(global.secpicker) + " zoom=" + string(obj_sidebar.l_zoom)); file_text_writeln(f6);' +
    '  file_text_write_string(f6, "placed=" + lastplaced + " w=" + string(round(global.pp_wx)) + "," + string(round(global.pp_wy)) + " win=" + string(round(global.pp_winx)) + "," + string(round(global.pp_winy)) + " overcv=" + string(global.pp_overcv) + " inst=" + string(instance_number(object_index))); file_text_writeln(f6);' +
    '  file_text_write_string(f6, "modal=" + string(modal) + " amode=" + string(amode) + " chip=" + string(chip) + " fcount=" + string(fcount) + " msel=" + string(msel) + " catn=" + string(catn) + " q=" + keyboard_string); file_text_writeln(f6);' +
    '  file_text_write_string(f6, "lastact=" + lastact); file_text_writeln(f6);' +
    '  file_text_close(f6);' +
    '}');

// -------------------------------------- user 0: rebuild the sprite cache
// Resolves every cell string to (kind, sprite handle, display name, fit
// scale). Weapon/module resource names are validated against the stock
// getweapon/getmodule tables BEFORE execute_string sees them -- an unknown
// identifier inside execute_string is a fatal compile error with SM's error
// dialogs on, and the cfg file is user-editable.
object_event_add(m, 7, 10,
    'if (global.sec_num[1] <= 0) exit;' +
    'if (wmap < 0) {' +
    '  var w7;' +
    '  wmap = ds_map_create(); mmap = ds_map_create();' +
    '  for (w7 = 0; w7 <= 45; w7 += 1) ds_map_add(wmap, getweapon(w7), 1);' +
    '  for (w7 = 0; w7 <= 19; w7 += 1) ds_map_add(mmap, getmodule(w7), 1);' +
    '}' +
    'var i7;' +
    'for (i7 = 0; i7 <= 99; i7 += 1) {' +
    '  global.pp_rk = 0; global.pp_rspr = -1; global.pp_rdisp = "";' +
    '  global.pp_cell = ds_grid_get(global.pp_grid, i7 mod 10, i7 div 10);' +
    '  event_user(2);' +
    '  ckind[i7] = global.pp_rk; cspr[i7] = global.pp_rspr; cdisp[i7] = global.pp_rdisp;' +
    '  cfit[i7] = 1; cbig[i7] = 0;' +
    '  if (cspr[i7] >= 0) {' +
    '    var mx7;' +
    '    mx7 = max(sprite_get_width(cspr[i7]), sprite_get_height(cspr[i7]));' +
    '    if (mx7 > 38) { cfit[i7] = 38 / mx7; cbig[i7] = 1; }' +
    '  }' +
    '}' +
    'cgen = ds_grid_get(global.pp_grid, 2, 10);' +
    'hstr = "##";');   // force hand re-resolve too

// ------------------------- user 2: resolve one cell (global.pp_cell) to
// global.pp_rk / pp_rspr / pp_rdisp. Shared by the cache rebuild and the
// hand resolver.
object_event_add(m, 7, 12,
    'var cl, p8, kd, rest, nm, lnm;' +
    'cl = global.pp_cell;' +
    'p8 = string_pos("|", cl);' +
    'if (p8 <= 0) exit;' +
    'kd = real(string_copy(cl, 1, p8 - 1));' +
    'rest = string_delete(cl, 1, p8);' +
    'p8 = string_pos("|", rest);' +
    'nm = string_copy(rest, 1, p8 - 1);' +
    'lnm = string_delete(rest, 1, p8);' +
    'if (kd <= 0) exit;' +
    'global.pp_rk = kd;' +
    'global.pp_rdisp = nm;' +
    'global.pp_rn = nm;' +
    'global.pp_rlnm = lnm;' +
    'if (kd == 1) {' +
    '  if (ds_list_find_index(global.secall_names, nm) >= 0) global.pp_rspr = variable_global_get(nm);' +
    '}' +
    'if (kd == 4) {' +
    '  if (ds_list_find_index(global.dooall_names, nm) >= 0) global.pp_rspr = variable_global_get(nm);' +
    '}' +
    'if (kd == 2) {' +
    '  if (wmap >= 0) {' +
    '    if (ds_map_exists(wmap, nm)) {' +
    '      global.pp_rn = nm; execute_string("global.pp_rspr = " + nm + ";");' +
    '      if (nm == "PointMaser") global.pp_rdisp = "Flak Gun";' +
    '      if (nm == "Laser") global.pp_rdisp = "Beamer";' +
    '    }' +
    '  }' +
    '}' +
    'if (kd == 3) {' +
    '  if (mmap >= 0) {' +
    '    if (ds_map_exists(mmap, nm)) execute_string("global.pp_rspr = " + nm + ";");' +
    '  }' +
    '}');

// ------------------------- user 3: reverse-map a Custom sprites relpath
// (global.pp_lnm) to its palette list name -> global.pp_fnm ("" = unknown).
// Sections live in one of the four group lists; doodads in the doo list.
object_event_add(m, 7, 13,
    'var g0, li, lid, nid;' +
    'global.pp_fnm = "";' +
    'for (g0 = 1; g0 <= 4; g0 += 1) {' +
    '  lid = variable_global_get("secg" + string(g0) + "_lname");' +
    '  li = ds_list_find_index(lid, global.pp_lnm);' +
    '  if (li >= 0) {' +
    '    nid = variable_global_get("secg" + string(g0) + "_name");' +
    '    global.pp_fnm = ds_list_find_value(nid, li);' +
    '    exit;' +
    '  }' +
    '}' +
    'li = ds_list_find_index(global.doo_lname, global.pp_lnm);' +
    'if (li >= 0) global.pp_fnm = ds_list_find_value(global.doo_name, li);');

// ------------------------- user 6: inventory catalog + spotlight modal.
// Called from Step. Re-reads the meta row itself (tp/hand/gen live in the
// grid, not in Step locals, precisely so helpers like this stay independent).
object_event_add(m, 7, 16,
    'var tp, hand, gen;' +
    'tp = ds_grid_get(global.pp_grid, 0, 10);' +
    'hand = ds_grid_get(global.pp_grid, 1, 10);' +
    'gen = ds_grid_get(global.pp_grid, 2, 10);' +
    // ------------------------------------------------- inventory catalog
    // Built once, after the palette lists and the weapon/module name maps are
    // live: sections (all four groups) + doodads from the ini lists, weapons +
    // modules from the stock name tables. ~170 entries.
    'if (catn == 0 && wmap >= 0 && global.sec_num[1] > 0) {' +
    '  var cg, cn2, cl2, nl2, cj, cm2;' +
    '  for (cg = 1; cg <= 4; cg += 1) {' +
    '    cn2 = global.sec_num[cg];' +
    '    nl2 = variable_global_get("secg" + string(cg) + "_name");' +
    '    cl2 = variable_global_get("secg" + string(cg) + "_lname");' +
    '    for (cj = 0; cj < cn2; cj += 1) {' +
    '      catcell[catn] = "1|" + string(ds_list_find_value(nl2, cj)) + "|" + string(ds_list_find_value(cl2, cj));' +
    '      catn += 1;' +
    '    }' +
    '  }' +
    '  for (cj = 0; cj < global.doo_num; cj += 1) {' +
    '    catcell[catn] = "4|" + string(ds_list_find_value(global.doo_name, cj)) + "|" + string(ds_list_find_value(global.doo_lname, cj));' +
    '    catn += 1;' +
    '  }' +
    '  for (cj = 0; cj <= 45; cj += 1) { catcell[catn] = "2|" + getweapon(cj) + "|"; catn += 1; }' +
    '  for (cj = 0; cj <= 19; cj += 1) { catcell[catn] = "3|" + getmodule(cj) + "|"; catn += 1; }' +
    '  for (cj = 0; cj < catn; cj += 1) {' +
    '    global.pp_rk = 0; global.pp_rspr = -1; global.pp_rdisp = ""; global.pp_rn = ""; global.pp_rlnm = "";' +
    '    global.pp_cell = catcell[cj]; event_user(2);' +
    '    catkind[cj] = global.pp_rk; catspr[cj] = global.pp_rspr; catdisp[cj] = global.pp_rdisp;' +
    // native 1:1 like the stock sidebar preview; shrink only past the
    // tile's sprite box (104x68, matching Draw's 116x96 tiles)
    '    catfit[cj] = 1;' +
    '    if (catspr[cj] >= 0) {' +
    '      var cw9, ch9;' +
    '      cw9 = sprite_get_width(catspr[cj]); ch9 = sprite_get_height(catspr[cj]);' +
    '      if (cw9 * catfit[cj] > 104) catfit[cj] = 104 / cw9;' +
    '      if (ch9 * catfit[cj] > 68) catfit[cj] = 68 / ch9;' +
    '    }' +
    '  }' +
    '  qlast = "##";' +
    '}' +

    // ------------------------------------------------- inventory modal
    'if (kmodal) {' +
    '  kmodal = 0;' +
    '  if (modal) {' +
    '    modal = 0; amode = 0; global.gui_esel = 0; global.pp_msnap = 0;' +
    '    lastact = "modal closed";' +
    '  }' +
    '  else {' +
    '    modal = 1; msel = 0; mscroll = 0; chip = 0; chiplast = -1; qlast = "##";' +
    '    keyboard_string = "";' +
    '    global.gui_esel = 1;' +
    '    global.pp_mscroll = 0;' +
    '    if (global.secpicker) {' +
    '      view_wport[1] += 240;' +
    '      view_visible[3] = false;' +
    '      global.pickerOff[global.sp_currgroup] = view_yview[3];' +
    '      global.secpicker = false;' +
    '    }' +
    '    lastact = "modal open";' +
    '    if (amode) lastact = "modal open (link mode)";' +
    '  }' +
    '}' +
    'if (modal) {' +
    '  var fc;' +
    '  fc = 0;' +
    '  if (global.hidegui) fc = 1;' +
    '  if (global.grouparrange) fc = 1;' +
    '  if (variable_global_exists("preview")) if (global.preview) fc = 1;' +
    '  if (fc) { modal = 0; amode = 0; global.gui_esel = 0; global.pp_msnap = 0; }' +
    '}' +
    'if (modal) {' +
    '  global.pp_mz = obj_sidebar.l_zoom;' +
    '  global.pp_mvx = view_xview[1]; global.pp_mvy = view_yview[1];' +
    '  global.pp_mvw = view_wview[1]; global.pp_mvh = view_hview[1];' +
    '  global.pp_msnap = 1;' +
    '  var q2, ql2, fj, ok2;' +
    '  q2 = keyboard_string;' +
    '  if (string_length(q2) > 24) { q2 = string_copy(q2, string_length(q2) - 23, 24); keyboard_string = q2; }' +
    '  if (qlast != q2 || chiplast != chip) {' +
    '    fcount = 0;' +
    '    ql2 = string_lower(q2);' +
    '    for (fj = 0; fj < catn; fj += 1) {' +
    '      ok2 = 1;' +
    '      if (chip > 0 && catkind[fj] != chip) ok2 = 0;' +
    '      if (ok2 && ql2 != "") { if (string_pos(ql2, string_lower(catdisp[fj])) <= 0) ok2 = 0; }' +
    '      if (ok2) { fidx[fcount] = fj; fcount += 1; }' +
    '    }' +
    '    qlast = q2; chiplast = chip;' +
    '    if (msel >= fcount) msel = 0;' +
    '    mscroll = 0;' +
    '  }' +
    '  var z8, px8, pt8, gy8, rv8, mrow, maxr;' +
    '  z8 = obj_sidebar.l_zoom;' +
    '  if (view_wport[1] > 0) z8 = view_wview[1] / view_wport[1];' +
    '  px8 = view_xview[1] + (floor(view_wview[1] / (2 * z8) - 346 + 0.25) + 0.03) * z8 + 0.5 * (1 - z8);' +
    '  pt8 = view_yview[1] + 40.03 * z8 + 0.5 * (1 - z8);' +
    '  gy8 = pt8 + 66 * z8;' +
    '  rv8 = floor((view_yview[1] + view_hview[1] - 40 * z8 - gy8) / (96 * z8));' +
    '  if (rv8 < 1) rv8 = 1;' +
    '  if (global.pp_mscroll != 0) { mscroll += global.pp_mscroll; global.pp_mscroll = 0; }' +
    '  if (knav > 0) {' +
    '    if (knav == 1) msel -= 1;' +
    '    if (knav == 2) msel += 1;' +
    '    if (knav == 3) msel -= 6;' +
    '    if (knav == 4) msel += 6;' +
    '    if (knav == 5) mscroll -= rv8;' +
    '    if (knav == 6) mscroll += rv8;' +
    '    knav = 0;' +
    '    if (msel >= fcount) msel = fcount - 1;' +
    '    if (msel < 0) msel = 0;' +
    '    mrow = msel div 6;' +
    '    if (mrow < mscroll) mscroll = mrow;' +
    '    if (mrow >= mscroll + rv8) mscroll = mrow - rv8 + 1;' +
    '  }' +
    '  maxr = ceil(fcount / 6) - rv8;' +
    '  if (maxr < 0) maxr = 0;' +
    '  if (mscroll > maxr) mscroll = maxr;' +
    '  if (mscroll < 0) mscroll = 0;' +
    '  hovt = -1;' +
    '  var mcx, mcy, hc, hr, hi;' +
    '  mcx = global.pp_wx; mcy = global.pp_wy;' +
    '  if (mcx >= px8 && mcx < px8 + 696 * z8 && mcy >= gy8) {' +
    '    hc = floor((mcx - px8) / (116 * z8));' +
    '    hr = floor((mcy - gy8) / (96 * z8));' +
    '    if (hc >= 0 && hc <= 5 && hr >= 0 && hr < rv8) {' +
    '      hi = (mscroll + hr) * 6 + hc;' +
    '      if (hi >= 0 && hi < fcount) { hovt = hi; msel = hi; }' +
    '    }' +
    '  }' +
    '  var clk, did, pidx, pcell;' +
    '  clk = 0;' +
    '  if (mouse_check_button_pressed(mb_left)) clk = 1;' +
    '  if (kclick) { clk = 1; kclick = 0; }' +
    '  if (kenter) { clk = 2; kenter = 0; }' +
    '  if (clk > 0) {' +
    '    did = 0;' +
    '    if (clk == 1 && mcy >= pt8 + 34 * z8 && mcy < pt8 + 58 * z8 && mcx >= px8 && mcx < px8 + 520 * z8) {' +
    '      chip = floor((mcx - px8) / (104 * z8));' +
    '      if (chip > 4) chip = 4;' +
    '      did = 1;' +
    '    }' +
    '    if (!did) {' +
    '      pidx = -1;' +
    '      if (clk == 2) pidx = msel;' +
    '      else if (hovt >= 0) pidx = hovt;' +
    '      if (pidx >= 0 && pidx < fcount) {' +
    '        pcell = catcell[fidx[pidx]];' +
    '        if (amode) {' +
    '          ds_grid_set(global.pp_grid, aslot, apage, pcell);' +
    '          gen += 1; ds_grid_set(global.pp_grid, 2, 10, gen);' +
    '          event_user(1);' +
    '          amode = 0;' +
    '          lastact = "linked " + pcell;' +
    '        }' +
    '        else {' +
    '          hand = pcell; ds_grid_set(global.pp_grid, 1, 10, hand);' +
    '          lastact = "inventory pick " + pcell;' +
    '        }' +
    '        modal = 0; global.gui_esel = 0; global.pp_msnap = 0; justclosed = 1;' +
    '        did = 1;' +
    '      }' +
    '    }' +
    '    if (!did && clk == 1) {' +
    '      if (mcx < px8 || mcx > px8 + 692 * z8 || mcy < pt8) {' +
    '        modal = 0; amode = 0; global.gui_esel = 0; global.pp_msnap = 0; justclosed = 1;' +
    '        lastact = "modal closed (click)";' +
    '      }' +
    '    }' +
    '  }' +
    '}');

// ------------------------- user 5: cursor -> view1 world coordinates.
// window_mouse_get_x/y + port math, NEVER mouse_x/mouse_y: GM translates
// mouse_x through whichever view the pointer is over, which flaps frame to
// frame near port edges (the smpan lesson). Client size via the editor's own
// WinAPI wrapper when it is live, window_get_width otherwise; window px ->
// region px -> view1 world. pp_overcv: pointer inside view1's port and not
// in the open picker band.
object_event_add(m, 7, 15,
    'var winx, winy, cw2, ch2, rw2, rh2;' +
    'winx = window_mouse_get_x(); winy = window_mouse_get_y();' +
    'cw2 = 0; ch2 = 0;' +
    'if (variable_global_exists("external_api_window_getclientwidth"))' +
    '  if (global.external_api_window_getclientwidth != 0) {' +
    '    cw2 = API_Window_GetClientWidth(window_handle());' +
    '    ch2 = API_Window_GetClientHeight(window_handle());' +
    '  }' +
    'if (cw2 <= 0) cw2 = window_get_width();' +
    'if (ch2 <= 0) ch2 = window_get_height();' +
    'rw2 = window_get_region_width(); rh2 = window_get_region_height();' +
    'if (cw2 > 0) winx = winx * rw2 / cw2;' +
    'if (ch2 > 0) winy = winy * rh2 / ch2;' +
    'global.pp_winx = winx; global.pp_winy = winy;' +
    'global.pp_overcv = 0; global.pp_wx = 0; global.pp_wy = 0;' +
    'if (view_wport[1] > 0 && view_hport[1] > 0) {' +
    '  global.pp_wx = view_xview[1] + (winx - view_xport[1]) * view_wview[1] / view_wport[1];' +
    '  global.pp_wy = view_yview[1] + (winy - view_yport[1]) * view_hview[1] / view_hport[1];' +
    '  if (winx >= view_xport[1] && winx < view_xport[1] + view_wport[1])' +
    '    if (winy >= view_yport[1] && winy < view_yport[1] + view_hport[1])' +
    '      global.pp_overcv = 1;' +
    '  if (global.secpicker && global.pp_wx >= 6144) global.pp_overcv = 0;' +
    '}');

// ------------------------- user 4: hit-test the cursor for a grabbable part
// -> global.pp_hcell (cell string, "" = none). Turret-first order; precise
// mask first, then a small collision circle -- the stock sprites use precise
// masks, so the geometric center of an L-shaped hull is a hole a pixel test
// would miss.
object_event_add(m, 7, 14,
    'var hh;' +
    'global.pp_hcell = "";' +
    'hh = instance_position(global.pp_wx, global.pp_wy, obj_weapon);' +
    'if (hh == noone) hh = collision_circle(global.pp_wx, global.pp_wy, 5, obj_weapon, true, false);' +
    'if (hh != noone) { global.pp_hcell = "2|" + sprite_get_name(hh.sprite_index) + "|"; exit; }' +
    'hh = instance_position(global.pp_wx, global.pp_wy, obj_module);' +
    'if (hh == noone) hh = collision_circle(global.pp_wx, global.pp_wy, 5, obj_module, true, false);' +
    'if (hh != noone) { global.pp_hcell = "3|" + sprite_get_name(hh.sprite_index) + "|"; exit; }' +
    'hh = instance_position(global.pp_wx, global.pp_wy, obj_doodad);' +
    'if (hh == noone) hh = collision_circle(global.pp_wx, global.pp_wy, 5, obj_doodad, true, false);' +
    'if (hh != noone) {' +
    '  global.pp_lnm = hh.lname; global.pp_fnm = "";' +
    '  event_user(3);' +
    '  if (global.pp_fnm != "") global.pp_hcell = "4|" + global.pp_fnm + "|" + hh.lname;' +
    '  exit;' +
    '}' +
    'hh = instance_position(global.pp_wx, global.pp_wy, obj_section);' +
    'if (hh == noone) hh = collision_circle(global.pp_wx, global.pp_wy, 8, obj_section, true, false);' +
    'if (hh != noone) {' +
    '  global.pp_lnm = hh.lname; global.pp_fnm = "";' +
    '  event_user(3);' +
    '  if (global.pp_fnm != "") global.pp_hcell = "1|" + global.pp_fnm + "|" + hh.lname;' +
    '}');

// --------------------------------------------- user 1: write mods/smpick.cfg
object_event_add(m, 7, 11,
    'var f9, s9;' +
    'f9 = file_text_open_write("mods/smpick.cfg");' +
    'file_text_write_string(f9, "smpickv1 toppage=" + string(ds_grid_get(global.pp_grid, 0, 10))); file_text_writeln(f9);' +
    'for (s9 = 0; s9 <= 99; s9 += 1) {' +
    '  file_text_write_string(f9, string(ds_grid_get(global.pp_grid, s9 mod 10, s9 div 10)));' +
    '  file_text_writeln(f9);' +
    '}' +
    'file_text_close(f9);');

// ------------------------------------------------------------------ Draw
// View1 pass only, every size scaled by l_zoom, per the house overlay recipe
// (mods/smzoom.gml / stock gui_hinter). Closed: quickbar bottom-center + hand
// ghost at the cursor. Open: the spotlight inventory -- dim plate, search
// line fed by keyboard_string, category chips, culled tile grid, footer.
object_event_add(m, 8, 0,
    'if (view_current != 1) exit;' +
    'if (!instance_exists(obj_sidebar)) exit;' +
    'if (global.hidegui) exit;' +
    'if (global.grouparrange) exit;' +
    'var pv;' +
    'pv = 0;' +
    'if (variable_global_exists("preview")) pv = global.preview;' +
    'if (pv) exit;' +
    // z: world units per screen pixel. NOT l_zoom -- the view rect is the
    // integer-rounded port*l_zoom, so l_zoom is off by up to ~0.0005 and the
    // error's sub-pixel phase moves with every zoom step: contents creep 1px
    // against their boxes. The view/port ratio is exact by definition.
    'var z, tp, hand;' +
    'z = obj_sidebar.l_zoom;' +
    'if (view_wport[1] > 0) z = view_wview[1] / view_wport[1];' +
    'tp = ds_grid_get(global.pp_grid, 0, 10);' +
    'hand = ds_grid_get(global.pp_grid, 1, 10);' +
    'draw_set_font(fnt_smalltext);' +
    // SM runs with texture interpolation ON; linear filtering smears bitmap
    // text drawn at fractional positions/scales. Nearest for the overlay,
    // restored before every way out of this event. Text only at integer
    // screen scales (1x, the E glyph 2x) -- bitmap fonts blur at any other.
    'texture_set_interpolation(0);' +
    // ambient state for mipdraw calls: our pass runs nearest, in view1 world
    // units where z world units = 1 screen px
    'global.mip_interp = 0; global.mip_px = z;' +

    'if (modal) {' +
    '  var px, pt, gy, rv, vj, vr, vc, ii, tx, ty, nm2, q3, cl3, k3, sca, loy2;' +
    '  loy2 = 0.5 * (z - 1);' +
    // floor(): center on a whole screen pixel; +0.5*(1-z) compensates GM7's
    // world-unit half-pixel projection term (see the quickbar anchors)
    '  px = view_xview[1] + (floor(view_wview[1] / (2 * z) - 346 + 0.25) + 0.03) * z + 0.5 * (1 - z);' +
    '  pt = view_yview[1] + 40.03 * z + 0.5 * (1 - z);' +
    '  gy = pt + 66 * z;' +
    '  rv = floor((view_yview[1] + view_hview[1] - 40 * z - gy) / (96 * z));' +
    '  if (rv < 1) rv = 1;' +
    '  draw_set_alpha(0.85); draw_set_color(c_black);' +
    '  draw_rectangle(view_xview[1], view_yview[1], view_xview[1] + view_wview[1], view_yview[1] + view_hview[1], 0);' +
    '  draw_set_alpha(1);' +
    '  draw_set_color(c_green);' +
    '  draw_rectangle(px + loy2, pt + loy2, px + 692 * z + loy2, pt + 28 * z + loy2, 1);' +
    '  q3 = keyboard_string;' +
    '  if ((tick div 15) mod 2 == 0) q3 = q3 + "_";' +
    '  if (keyboard_string == "") {' +
    '    draw_set_color(merge_color(c_ltgray, c_green, 0.5));' +
    '    if (amode) draw_text_transformed(px + 6 * z, pt + 6 * z, "choose a link for slot " + string(aslot + 1) + ", page " + string(apage + 1), z, z, 0);' +
    '    else draw_text_transformed(px + 6 * z, pt + 6 * z, "type a part name...", z, z, 0);' +
    '    draw_set_color(c_green);' +
    '  }' +
    '  if (keyboard_string != "") draw_text_transformed(px + 6 * z, pt + 6 * z, q3, z, z, 0);' +
    '  for (k3 = 0; k3 <= 4; k3 += 1) {' +
    '    cl3 = "ALL";' +
    '    if (k3 == 1) cl3 = "SECTIONS";' +
    '    if (k3 == 2) cl3 = "WEAPONS";' +
    '    if (k3 == 3) cl3 = "MODULES";' +
    '    if (k3 == 4) cl3 = "DOODADS";' +
    '    if (k3 == chip) draw_set_color(c_yellow);' +
    '    else draw_set_color(merge_color(c_ltgray, c_green, 0.5));' +
    '    draw_rectangle(px + k3 * 104 * z + loy2, pt + 34 * z + loy2, px + (k3 * 104 + 100) * z + loy2, pt + 58 * z + loy2, 1);' +
    '    draw_text_transformed(px + (k3 * 104 + 6) * z, pt + 38 * z, cl3, z, z, 0);' +
    '  }' +
    '  draw_set_color(c_green);' +
    '  draw_text_transformed(px + 532 * z, pt + 38 * z, string(fcount) + " parts", z, z, 0);' +
    '  for (vr = 0; vr < rv; vr += 1) {' +
    '    for (vc = 0; vc <= 5; vc += 1) {' +
    '      vj = (mscroll + vr) * 6 + vc;' +
    '      if (vj >= fcount) break;' +
    '      ii = fidx[vj];' +
    '      tx = px + vc * 116 * z; ty = gy + vr * 96 * z;' +
    '      if (vj == msel) draw_set_color(c_yellow);' +
    '      else draw_set_color(merge_color(c_ltgray, c_green, 0.5));' +
    '      draw_rectangle(tx + loy2, ty + loy2, tx + 112 * z + loy2, ty + 92 * z + loy2, 1);' +
    // native tiles stay nearest; shrunk ones go through the mipdraw library
    '      if (catspr[ii] >= 0) {' +
    '        if (catfit[ii] >= 1) draw_sprite_ext(catspr[ii], 0, tx + 56 * z, ty + 36 * z, z, z, 0, c_white, 1);' +
    '        else if (mlib >= 0) {' +
    '          global.mip_spr = catspr[ii]; global.mip_x = tx + 56 * z; global.mip_y = ty + 36 * z;' +
    '          global.mip_scale = catfit[ii] * z;' +
    '          with (mlib) event_user(0);' +
    '        }' +
    '        else {' +
    '          sca = catfit[ii] * z;' +
    '          texture_set_interpolation(1);' +
    '          draw_sprite_ext(catspr[ii], 0, tx + 56 * z, ty + 36 * z, sca, sca, 0, c_white, 1);' +
    '          texture_set_interpolation(0);' +
    '        }' +
    '      }' +
    '      nm2 = catdisp[ii];' +
    '      if (string_length(nm2) > 13) nm2 = string_copy(nm2, 1, 12) + ".";' +
    '      draw_set_color(c_white);' +
    '      draw_text_transformed(tx + 6 * z, ty + 74 * z, nm2, z, z, 0);' +
    '    }' +
    '  }' +
    '  draw_set_color(merge_color(c_ltgray, c_green, 0.5));' +
    '  draw_text_transformed(px, view_yview[1] + view_hview[1] - 30 * z, "arrows navigate   enter or click picks   esc closes   wheel or pgup/pgdn scrolls", z, z, 0);' +
    '  draw_set_color(c_white);' +
    '  texture_set_interpolation(1);' +
    '  exit;' +
    '}' +

    // Bar geometry: every offset is an INTEGER count of screen pixels (the
    // pre-1.2x constants times 1.2, rounded), horizontal ones scaled by z and
    // vertical ones by zy off pixel-snapped anchors.  Fractional offsets like
    // 52.8px change rounding phase per zoom step and the contents creep
    // against the boxes; integers render pixel-identically at every zoom.
    // Must stay equal to the Step hit-test constants.
    'var cx, yb, bx, zy, lox, loy, r, s, pg, i, x1, y1, cell, ish, sca;' +
    'cx = view_xview[1] + view_wview[1] / 2;' +
    // vertical anchor via the VERTICAL view/port ratio -- GM truncates wview
    // and hview to ints independently, so the two ratios differ in the 4th
    // decimal and a horizontal-ratio yb lands a fraction off.
    'zy = z;' +
    'if (view_hport[1] > 0) zy = view_hview[1] / view_hport[1];' +
    // loy: outline rects are D3D LINE primitives and horizontal lines do not
    // get the half-world projection offset that fills/text/sprites do (see
    // the anchor comment) -- their Y coords must shed the compensation or
    // the box tops sag up to 5px at deep zoom while the contents hold
    'lox = 0.5 * (z - 1); loy = 0.5 * (zy - 1);' +
    // +0.03: edges exactly on a pixel boundary flip D3D fill rules on float
    // noise; the bias keeps every edge strictly inside its pixel.
    // +0.5*(1-s): GM7 builds the D3D8 half-pixel correction in WORLD units
    // (screen = (world - view - 0.5)*(port/view) + 0.5), so an uncorrected
    // anchor lands 0.5*(1/z - 1) px up-left -- 2px at 20% zoom, the "bar
    // creeps as I zoom" bug. Offsets relative to the anchor cancel the
    // constant, so only the anchors carry the term.
    'yb = view_yview[1] + (floor(view_hview[1] / zy + 0.25) - 12 + 0.03) * zy + 0.5 * (1 - zy);' +
    'bx = view_xview[1] + (floor(view_wview[1] / (2 * z) + 0.25) - 264 + 0.03) * z + 0.5 * (1 - z);' +

    // opaque plate: icons and labels read against solid black
    'draw_set_color(c_black);' +
    'draw_rectangle(bx - 31 * z + lox, yb - 113 * zy + loy, bx + 586 * z + lox, yb + 2 * zy + loy, 0);' +
    'for (r = 0; r <= 1; r += 1) {' +
    '  pg = (tp + r) mod 10;' +
    '  y1 = yb + (r * 53 - 106) * zy;' +
    '  if (r == 0) draw_set_color(c_green); else draw_set_color(merge_color(c_ltgray, c_green, 0.5));' +
    '  draw_text_transformed(bx - 26 * z, y1 + 17 * zy, string(pg + 1), z, zy, 0);' +
    '  for (s = 0; s <= 9; s += 1) {' +
    '    i = pg * 10 + s;' +
    '    x1 = bx + s * 53 * z;' +
    '    cell = ds_grid_get(global.pp_grid, s, pg);' +
    '    ish = 0;' +
    '    if (string_char_at(cell, 1) != "0") if (cell == hand) ish = 1;' +
    '    if (ish) draw_set_color(c_yellow);' +
    '    else draw_set_color(merge_color(c_ltgray, c_green, 0.5));' +
    '    draw_rectangle(x1 + lox, y1 + loy, x1 + 48 * z + lox, y1 + 48 * zy + loy, 1);' +
    // small parts draw native 1:1 (nearest = pixel-exact); shrunk parts go
    // through the mipdraw library (box-filtered mip level computed in place,
    // over the black plate -- additive needs the dark ground)
    '    if (cspr[i] >= 0) {' +
    '      if (!cbig[i]) draw_sprite_ext(cspr[i], 0, x1 + 24 * z, y1 + 24 * zy, z, zy, 0, c_white, 1);' +
    '      else if (mlib >= 0) {' +
    '        global.mip_spr = cspr[i]; global.mip_x = x1 + 24 * z; global.mip_y = y1 + 24 * zy;' +
    '        global.mip_scale = cfit[i] * 1.2 * z;' +
    '        with (mlib) event_user(0);' +
    '      }' +
    '      else {' +
    '        sca = cfit[i] * 1.2 * z;' +
    '        texture_set_interpolation(1);' +
    '        draw_sprite_ext(cspr[i], 0, x1 + 24 * z, y1 + 24 * zy, sca, sca, 0, c_white, 1);' +
    '        texture_set_interpolation(0);' +
    '      }' +
    '    }' +
    '    if (r == 0) {' +
    '      draw_set_color(c_green);' +
    '      if (s == 9) draw_text_transformed(x1 + 2 * z, y1 + 1 * zy, "0", z, zy, 0);' +
    '      else draw_text_transformed(x1 + 2 * z, y1 + 1 * zy, string(s + 1), z, zy, 0);' +
    '    }' +
    '  }' +
    '}' +
    // the [E] lug: the mouse route into the inventory
    'draw_set_color(merge_color(c_ltgray, c_green, 0.5));' +
    'draw_rectangle(bx + 533 * z + lox, yb - 106 * zy + loy, bx + 581 * z + lox, yb - 58 * zy + loy, 1);' +
    // 3x3 grid pictogram: "browse all parts"
    'draw_set_color(c_green);' +
    'for (r = 0; r <= 2; r += 1)' +
    '  for (s = 0; s <= 2; s += 1)' +
    '    draw_rectangle(bx + (538 + s * 14) * z + lox, yb - (101 - r * 14) * zy + loy, bx + (548 + s * 14) * z + lox, yb - (91 - r * 14) * zy + loy, 0);' +
    'if (handspr >= 0) {' +
    '  draw_set_color(c_yellow);' +
    // off bx, not the raw view center: bx carries the projection correction
    '  draw_text_transformed(bx + (277 - 4 * string_length(handdisp)) * z, yb - 132 * zy, handdisp, z, zy, 0);' +
    // the ghost lives in world scale -- filter it like the canvas parts
    '  if (global.pp_overcv) {' +
    '    texture_set_interpolation(1);' +
    '    draw_sprite_ext(handspr, 0, global.pp_wx, global.pp_wy, 1, 1, 0, c_white, 0.6);' +
    '    texture_set_interpolation(0);' +
    '  }' +
    '}' +
    'draw_set_color(c_white);' +
    'texture_set_interpolation(1);');

i = instance_create(0, 0, m);
i.persistent = true;
i.depth = -10000000;

// While the inventory modal is open the wheel must scroll the part grid, not
// zoom the canvas -- but stock zoom lives in obj_sidebar's wheel events, which
// can only be appended to. House pattern (mods/smpan.gml): the controller
// snapshots l_zoom + view1's rect every Step while the modal is open, and the
// appended code below UNDOES whatever stock zoom just did, then feeds the
// wheel tick to the modal as a scroll step instead.
global.pp_msnap = 0;
global.pp_mz = 1; global.pp_mvx = 0; global.pp_mvy = 0;
global.pp_mvw = 0; global.pp_mvh = 0;
global.pp_mscroll = 0;
object_event_add(obj_sidebar, 6, 60,
    'if (global.pp_msnap) {' +
    '  l_zoom = global.pp_mz;' +
    '  view_wview[1] = global.pp_mvw; view_hview[1] = global.pp_mvh;' +
    '  view_xview[1] = global.pp_mvx; view_yview[1] = global.pp_mvy;' +
    '  global.pp_mscroll -= 1;' +
    '}');
object_event_add(obj_sidebar, 6, 61,
    'if (global.pp_msnap) {' +
    '  l_zoom = global.pp_mz;' +
    '  view_wview[1] = global.pp_mvw; view_hview[1] = global.pp_mvh;' +
    '  view_xview[1] = global.pp_mvx; view_yview[1] = global.pp_mvy;' +
    '  global.pp_mscroll += 1;' +
    '}');

// Ship decloak -- a pixel shader scoped to ONE ship's draws. Gated on
// mods/cloak.on. Demo/measurement; it changes nothing about how the game plays.
//
// Pair it with mods/battle.on and a one-ship mods/battle.cfg, which is what puts
// a ship in rm_Sandbox on a fixed step count (see battle.gml for the format):
//
//     2048 2048 120 12345 1          room w/h, enter at menu step 120, seed, 1 wave
//     10 Hecate 1 1024 1024 0 0      at sandbox step 10, one Hecate dead centre
//
// (one value per line, not two -- laid out here to fit).
//
// ------------------------------------------------------------------ the idea
// mods/shaderspr.gml showed a bracket around a single draw_sprite call scopes a
// shader exactly (0 differing pixels either side of it). A ship is not one draw
// though -- this Hecate is 69 instances: the hull, 16 ShipSections, 32 doodads
// and 20 turrets, each drawing its own sprite in its own Draw event. So the
// bracket has to be around a RANGE of draws, and in GML the only handle on draw
// order is `depth`.
//
// MEASURED (mods/cloak_census.txt, phase 1): every one of those 69 instances
// sits at the SAME depth, and nothing else in the room shares it -- the sandbox
// HUD is at -1 and below, our own controllers at 0 or +-1e7. BSF layers a ship's
// parts by creation order, not by depth, so forcing them all to one depth costs
// nothing and buys a band we can sandwich.
//
// ⚠ That depth is NOT a constant across launches -- it came out 0.10 in one run
// and 0.00 in the next. Reading it once and hardcoding it would have worked
// exactly as often as it did not, so this file OWNS the value instead: End Step
// forces every ship part to 0.5, the same way fastdraw.gml owns `visible`.
//
//   depth 0.6   binder    sets the constants, sh_set
//   depth 0.5   the ship   <- drawn by the game's own code, untouched
//   depth 0.4   resetter  sh_reset
//
// Everything outside that band -- starfield, HUD, cursor -- draws unshaded.
//
// ⚠ `id` is a built-in instance variable, and `var ..., id;` shadows it. That
// kills the file at the object_event_add that compiles the string: this file
// loaded, wrote its breadcrumb, and never reached instance_create. Nothing
// appeared and nothing was logged. Local names here are ugly (cid) on purpose.
//
// ⚠ Do not compare a depth with `!=`. The phase-1 census filtered on
// `depth != 0.1` and silently matched nothing on the run where the game had
// chosen 0.0 -- an empty result that looks exactly like an aborted action.
var ctl, bnd, rst, i;
if (!variable_global_exists('sh_ok')) exit;

global.dc_h    = -1;
global.dc_on   = 0;
global.dc_prog = 0;
global.dc_t    = 0;
global.dc_umax = 1;
global.dc_vmax = 1;
if (global.sh_ok >= 1) global.dc_h = external_call(global.sh_compile, 'mods/decloak.hlsl');

// ------------------------------------------------------------- the controller
ctl = object_add();
object_set_persistent(ctl, 1);
object_event_add(ctl, 0, 0, 'rtick = 0; measured = 0;');

// Progress and the capture schedule. T0 = 150, 120 ticks of transition at
// room_speed 30 -> a four-second decloak.
//
// screen_save in Step captures the frame drawn LAST tick (every Step runs before
// every Draw), so a capture at rtick N+1 is named for frame N.
object_event_add(ctl, 3, 0,
    'if (room != rm_Sandbox) exit;' +
    'rtick += 1;' +
    // one measurement of the UV rect, before anything is bound
    'if (rtick == 100 && !measured) {' +
    '  measured = 1;' +
    '  var cid, tx, u, v;' +
    '  for (i = 0; i < instance_count; i += 1) {' +
    '    cid = instance_id[i];' +
    '    if (cid.sprite_index < 0) continue;' +
    '    if (cid.depth <= -1) continue;' +
    '    tx = sprite_get_texture(cid.sprite_index, 0);' +
    '    u = texture_get_width(tx); v = texture_get_height(tx);' +
    '    if (u < global.dc_umax) global.dc_umax = u;' +
    '    if (v < global.dc_vmax) global.dc_vmax = v; } }' +
    // progress
    'if (rtick >= 150) {' +
    '  global.dc_on = 1;' +
    '  global.dc_prog = min((rtick - 150) / 120, 1); }' +
    'if (rtick >= 291) global.dc_on = 0;' +
    'global.dc_t = rtick / room_speed;' +
    // captures. A dense strip every 4 ticks across the whole transition (36
    // frames -> a filmstrip and a GIF), plus one adjacent PAIR at the end:
    // frame 290 with the shader still bound at prog = 1, frame 291 with it
    // dropped. Adjacent, because the ship idles -- turret sprites and engine
    // glows animate -- so any gap between the two frames shows up as a
    // difference that has nothing to do with the shader. dc_n0/dc_n1 are the
    // same pair taken before anything is bound: that is the noise floor.
    'if (rtick == 141) screen_save("mods/dc_n0.png");' +
    'if (rtick == 142) screen_save("mods/dc_n1.png");' +
    'if (rtick >= 149) { if (rtick <= 289) {' +
    '  if ((rtick - 149) mod 4 == 0)' +
    '    screen_save("mods/dcf" + string((rtick - 149) / 4) + ".png"); } }' +
    'if (rtick == 291) screen_save("mods/dc_bound.png");' +
    'if (rtick == 292) screen_save("mods/dc_off.png");' +
    'if (rtick == 295) {' +
    '  var f; f = file_text_open_write("mods/cloak.txt");' +
    '  file_text_write_string(f, "handle=" + string(global.dc_h)' +
    '    + " uvmax=" + string(global.dc_umax) + "," + string(global.dc_vmax)' +
    '    + " binds=" + string(external_call(global.sh_stat, 2))' +
    '    + " fails=" + string(external_call(global.sh_stat, 3))' +
    '    + " err=" + string(external_call(global.sh_err)));' +
    '  file_text_writeln(f); file_text_close(f); }' +
    'if (rtick == 310) game_end();');

// End Step, after the game has moved everything and before any Draw: own the
// depth. fastdraw.gml owns `visible` from the same event for the same reason --
// a Step-time write would be one frame stale.
object_event_add(ctl, 3, 2,
    'if (room != rm_Sandbox) exit;' +
    'with (all) {' +
    '  if (sprite_index >= 0) {' +
    '    if (depth > -1) depth = 0.5; } }');

// ------------------------------------------------------------ binder/resetter
// Two instances whose only job is where they sit in the draw order.
bnd = object_add();
object_set_persistent(bnd, 1);
object_event_add(bnd, 8, 0,
    'if (global.dc_on < 1) exit;' +
    'if (global.dc_h < 0) exit;' +
    'external_call(global.sh_const, 0, global.dc_prog, global.dc_t, 0.06, 0);' +
    'external_call(global.sh_const, 1, 0, 0, global.dc_umax, global.dc_vmax);' +
    'external_call(global.sh_set, global.dc_h);');

rst = object_add();
object_set_persistent(rst, 1);
object_event_add(rst, 8, 0,
    'if (global.dc_on < 1) exit;' +
    'if (global.dc_h < 0) exit;' +
    'external_call(global.sh_reset);');

i = instance_create(0, 0, ctl); i.depth = -10000005;
i = instance_create(0, 0, bnd); i.depth = 0.6;
i = instance_create(0, 0, rst); i.depth = 0.4;

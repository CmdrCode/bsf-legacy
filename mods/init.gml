// Mod loader + measurement probe.
//
// The bootstrap patched into the exe only ever runs mods/init.gml, so anything
// else has to be chained from here.
//
// Guard is load-bearing: the bootstrap lives in GUI_MainTitle's startup event
// and GUI_MainTitle lives in rm_MainMenu, so ANY reload of the menu re-runs this
// file. Without the guard, a mod that calls room_restart() restarts forever.
if (variable_global_exists('bsf_mods_init')) exit;
global.bsf_mods_init = 1;
global.bsf_ruler = file_exists('mods/ruler.on');   // measurement overlay, opt-in
global.bsf_probe = file_exists('mods/probe.on');   // measurement harness, opt-in

// The display modules: always on, and this order is load-bearing.
if (file_exists('mods/resolution.gml')) execute_file('mods/resolution.gml');
if (file_exists('mods/options.gml'))    execute_file('mods/options.gml');
if (file_exists('mods/aspect.gml'))     execute_file('mods/aspect.gml');
// Must follow resolution.gml: it re-centres the layout of the rooms that file
// hands a widened room to, and does nothing until one has been applied.
if (file_exists('mods/widescreen.gml')) execute_file('mods/widescreen.gml');

// ------------------------------------------------------------------- probe
// Measurement only, and gated like every other harness module in this file --
// its Step writes mods/probe.txt three times a second and reads mouse_x, the
// 176 us builtin the cursor cache exists to stop the game reading. Ungated, a
// player paid for the whole harness; `touch mods/probe.on` turns it back on.
//
// The ruler is ticked every 128 WORLD units, so its device spacing is the
// per-axis scale (equal on both axes = no stretch), and the red cross is drawn
// with draw_line, whose width is in DEVICE pixels -- 1 px means a native render,
// 2 px would mean an upscale. mods/ruler.on gates that overlay separately.
//
//   mods/goto.txt    room id to jump to
//   mods/shot.req -> mods/shot.png   (BMP; its size IS the drawing region)
//   mods/probe.txt   state report, rewritten every 10 steps
//   mods/rooms.txt   id -> name table, written once at startup

var o, i;
if (global.bsf_probe) {          // ... closes after instance_create, below
o = object_add();

object_event_add(o, 0, 0,
    'tick = 0;' +
    'var f, r;' +
    'f = file_text_open_write("mods/rooms.txt");' +
    'for (r = 0; r < 64; r += 1) {' +
    '  if (!room_exists(r)) continue;' +
    '  file_text_write_string(f, string(r) + " " + room_get_name(r)); file_text_writeln(f);' +
    '}' +
    'file_text_close(f);');

object_event_add(o, 3, 0,
    'tick += 1;' +
    'if (tick mod 10 == 0) {' +
    '  if (file_exists("mods/goto.txt")) {' +
    '    var g, t;' +
    '    g = file_text_open_read("mods/goto.txt"); t = real(file_text_read_string(g));' +
    '    file_text_close(g); file_delete("mods/goto.txt");' +
    '    if (room_exists(t) && t != room) room_goto(t);' +
    '  }' +
    '  if (file_exists("mods/vw")) {' +
    // Reproduces exactly what BSF's zoom controller does: slam the view back to
    // a 4:3 1024*l_zoom while the port stays 16:9.
    '    var g4;' +
    '    g4 = file_text_open_read("mods/vw");' +
    '    view_wview[0] = real(file_text_read_string(g4));' +
    '    file_text_close(g4); file_delete("mods/vw");' +
    '  }' +
    '  if (file_exists("mods/uiev")) {' +
    // Fires the options screen's own action handler directly. The wine virtual
    // desktop swallows synthetic input once focus leaves the game window, so
    // this is the only way to exercise the real handler deterministically.
    '    var g3, ev, d;' +
    '    g3 = file_text_open_read("mods/uiev");' +
    '    ev = real(file_text_read_string(g3)); file_text_readln(g3);' +
    '    d  = real(file_text_read_string(g3)); file_text_close(g3);' +
    '    file_delete("mods/uiev");' +
    '    with (global.mod_opt_ui) { dir = d; event_user(ev); }' +
    '  }' +
    '  if (file_exists("mods/optreq")) {' +
    // Runs the REAL menu button's action, so the hijack is exercised through the
    // exact stock code path -- no mouse synthesis, no focus fight.
    '    file_delete("mods/optreq");' +
    '    with (GUI_MainOptions) { image_blend = c_white; alarm[0] = 1; }' +
    '    var f2; f2 = file_text_open_write("mods/optreq.log");' +
    '    file_text_write_string(f2, "GUI_MainOptions instances=" + string(instance_number(GUI_MainOptions)));' +
    '    file_text_writeln(f2); file_text_close(f2);' +
    '  }' +
    '  if (file_exists("mods/shot.req")) { file_delete("mods/shot.req"); screen_save("mods/shot.png"); }' +
    '  var f;' +
    '  f = file_text_open_write("mods/probe.txt");' +
    '  file_text_write_string(f, "room=" + string(room) + " " + room_get_name(room)); file_text_writeln(f);' +
    '  file_text_write_string(f, "room_size=" + string(room_width) + "x" + string(room_height)); file_text_writeln(f);' +
    '  file_text_write_string(f, "port=" + string(view_wport[0]) + "x" + string(view_hport[0])); file_text_writeln(f);' +
    '  file_text_write_string(f, "view=" + string(view_wview[0]) + "x" + string(view_hview[0])); file_text_writeln(f);' +
    '  file_text_write_string(f, "win=" + string(window_get_width()) + "x" + string(window_get_height())); file_text_writeln(f);' +
    '  file_text_write_string(f, "region=" + string(window_get_region_width()) + "x" + string(window_get_region_height())); file_text_writeln(f);' +
    '  file_text_write_string(f, "mb=" + string(mouse_check_button(mb_left))); file_text_writeln(f);' +
    '  file_text_write_string(f, "mouse=" + string(mouse_x) + "," + string(mouse_y)); file_text_writeln(f);' +
    '  file_text_write_string(f, "display=" + string(display_get_width()) + "x" + string(display_get_height())); file_text_writeln(f);' +
    '  file_text_close(f);' +
    '}');

object_event_add(o, 8, 0,
    'if (!global.bsf_ruler) exit;' +
    'var bx, by, k;' +
    'if (view_visible[0]) { bx = view_xview[0]; by = view_yview[0]; }' +
    'else { bx = 0; by = 0; }' +
    'draw_set_font(-1); draw_set_halign(0);' +
    'draw_set_color(c_yellow);' +
    'for (k = 0; k <= view_wview[0]; k += 128) {' +
    '  draw_line(bx+k, by+30, bx+k, by+52); draw_text(bx+k+3, by+54, string(k)); }' +
    'for (k = 0; k <= view_hview[0]; k += 128) {' +
    '  draw_line(bx+30, by+k, bx+52, by+k); draw_text(bx+56, by+k-8, string(k)); }' +
    'draw_set_color(c_red);' +
    'var cx, cy; cx = bx + view_wview[0]/2; cy = by + view_hview[0]/2;' +
    'draw_line(cx-80, cy, cx+80, cy); draw_line(cx, cy-80, cx, cy+80);' +
    // Aspect test figures, in WORLD units: a circle and a square of the same
    // size. If the horizontal and vertical scales differ, the circle renders as
    // an ellipse and the square as a rectangle, and the ratio of their measured
    // device-pixel bounding boxes IS the distortion factor.
    'draw_set_color(c_aqua);' +
    'draw_circle(cx, cy, 100, 1);' +
    'draw_set_color(c_fuchsia);' +
    'draw_rectangle(cx-150, cy-150, cx+150, cy+150, 1);' +
    'draw_set_color(c_lime);' +
    'draw_text(bx+8, by+8, room_get_name(room) + "  port " + string(view_wport[0]) + "x" + string(view_hport[0]) +' +
    '  "  view " + string(view_wview[0]) + "x" + string(view_hview[0]) +' +
    '  "  win " + string(window_get_width()) + "  region " + string(window_get_region_width()));');

i = instance_create(0, 0, o);
i.persistent = true;
i.depth = -10000000;
}                                // end if (global.bsf_probe)

// ---------------------------------------------------------------- the chain
// bsf-legacy module table -- tools/cursorfix.py looks for this exact line to
// tell a full init.gml from a bare stub. A stub gets the cursor module appended
// as its own block; this table already has a row for it, so it must not.
//
// The optional modules, in LOAD ORDER -- the order of this table is the order
// they run in, and several entries depend on it (noted per row).
//
// Column 2 is the gate:
//     ""          always, if the .gml is present
//     "x.on"      only when mods/x.on exists            (opt-in)
//     "!x.off"    unless mods/x.off exists              (opt-out; on by default)
//
// Adding a module is one row. Marker names that differ from the module name are
// why this is a column rather than derived from the name.
var nm, mk, k, gate, last;
nm[ 0]='zoomprobe';  mk[ 0]='zoomlog.on';   // camera instrumentation
nm[ 1]='fastdraw';   mk[ 1]='!fastdraw.off';// draw-call cull; the measured perf fix, on for players
nm[ 2]='atlas';      mk[ 2]='atlas.on';     // batched atlas renderer, while validated against stock
nm[ 3]='native';     mk[ 3]='native.on';    // DLL ABI probe; LoadLibrary's a test DLL, stalls ~1s
nm[ 4]='perf';       mk[ 4]='perf.on';      // frame profiler; its own brackets are work
nm[ 5]='uiprobe';    mk[ 5]='uiprobe.on';
nm[ 6]='campaign';   mk[ 6]='campaign.on';  // file-driven mission entry; adds a Step poller
nm[ 7]='battle';     mk[ 7]='battle.on';    // scripted stress battle, for measurement
nm[ 8]='stepprof';   mk[ 8]='stepprof.on';  // (generated) per-object Step timer, ~290 events
nm[ 9]='turretprof'; mk[ 9]='turretprof.on';// (generated) MUST follow stepprof: replaces ctr_Turrets' Step
nm[10]='x3patch';    mk[10]='x3patch.on';   // (generated) MUST follow turretprof: same event, last wins
nm[11]='cursor';     mk[11]='cursor.on';    // cursor cache over the GetCursorPos import
nm[12]='guidump';    mk[12]='guidump.on';   // menu inventory, diagnostics only
nm[13]='logo';       mk[13]='logo.on';      // MUST precede legacy: CLEARS GUI_MainTitle's Draw
nm[14]='legacy';     mk[14]='legacy.on';    // appends one Draw to GUI_MainTitle
nm[15]='crisp';      mk[15]='crisp.on';     // menu label sprites -> drawn text
nm[16]='shader';     mk[16]='!shader.off';  // pixel shaders over the game's own draws: VISUAL
                                            //   EFFECTS, not performance. Needs bsfshader.dll and
                                            //   d3d8to9; without either it reports off and no-ops
nm[17]='shaderdemo'; mk[17]='shaderdemo.on';// MUST follow shader: uses its globals. Measurement
nm[18]='shaderspr';  mk[18]='shaderspr.on'; // MUST follow shader: per-sprite bracket test. Measurement
nm[19]='cloak';      mk[19]='!cloak.off';   // the Umbra Cloak: a new module type, and the
                                            //   cloak it drives. MUST follow shader (uses its
                                            //   globals) and MUST precede act2, which spawns hulls
                                            //   that mount it. Absorbed umbracloak.gml.
nm[20]='act2';       mk[20]='!act2.off';    // Act II campaign: paged career menu + episodes (chains act2m1.gml)
nm[21]='editor';     mk[21]='editor.on';    // MUST follow act2: mission-editor channel, drives its rooms
nm[22]='roomtest';   mk[22]='';             // LAST: probes for functions that may not exist, and a
last = 22;                                  // missing one silently aborts the rest of the file it is in

for (k = 0; k <= last; k += 1) {
    if (mk[k] == '')
        gate = true;
    else if (string_char_at(mk[k], 1) == '!')
        gate = !file_exists('mods/' + string_delete(mk[k], 1, 1));
    else
        gate = file_exists('mods/' + mk[k]);
    if (gate) {
        if (file_exists('mods/' + nm[k] + '.gml'))
            execute_file('mods/' + nm[k] + '.gml');
    }
}

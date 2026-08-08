// ShipMaker -- 1:1 resolution. The drawing region follows the window.
//
// Stock ShipMaker is a resizable window wrapped around a FIXED 1016x704 drawing
// region: GM 7.0 builds the region (the real backbuffer) when a room loads and
// nothing at runtime resizes it, so dragging the window bigger just stretches
// the same pixels (settings: scaling=0, "full scale"). This module makes the
// region track the window's CLIENT size instead, so one drawn pixel is one
// screen pixel at any window size -- more canvas, not bigger blur.
//
// -------------------------------------------------------------------- how
// The reload trick is ShipMaker's own: rm_main is PERSISTENT and the editor's
// gameLoaded() script already calls room_goto(rm_main) on itself to apply
// window/port changes -- a persistent room keeps every instance (the whole ship
// being edited) across the transition while GM rebuilds the region from the
// CURRENT view ports. So: watch the client size, and when it settles somewhere
// new, lay the ports out for it and room_goto(rm_main).
//
// The client size is read through the editor's own bundled WinAPI wrapper
// ("Max WinAPI 2.dll", API_Window_GetClientWidth) -- window_get_width() is the
// outer frame, and 1:1 means matching the client. The wrappers are defined by
// API_Init in obj_sidebar's Create, AFTER the bootstrap runs this file, so
// nothing here calls them until the first Step (by which time that Create has
// finished). The gate below tests the VALUE of the wrapper's define handle:
// ShipMaker runs with "uninitialized = 0" ON, which zero-registers every
// global at compile time, so existence alone proves nothing (see mods/sm.gml).
//
// ----------------------------------------------------------------- layout
// rm_main is one room, five working views; everything below asserts ports only
// and never touches view_visible (picker/arrange own that):
//   view0  UI chrome, 1:1 over room origin      -> port (0,0)-(W,H)
//   view1  ship canvas (zoom = l_zoom)          -> port (160,15)-(W,H), or
//          x0=0 when the GUI is hidden ("hide gui" toggles ports by +-160)
//   view2  topbar strip                         -> width follows W
//   view3-6 section picker panels               -> stock 240x689, hugging the
//          right edge: xport = W-240. Height stays stock because the picker's
//          hover-scroll zones are hardcoded to a 689-tall panel.
// The assert runs every step because stock code RESTORES hardcoded ports on
// picker close / arrange exit (856/776/240); one frame later this wins again.
// Group-arrange mode repurposes view3 for its own full-width layout, so the
// assert stands down entirely while global.grouparrange is set, and while the
// ship preview runs (global.preview).
//
// ------------------------------------------------------------------ quirks
// * gameLoaded() forces window_set_size(1016,704) on EVERY ship load. A one-
//   frame jump from the intended size to exactly 1016x704 is therefore treated
//   as that snap-back and undone, not honoured as a user resize.
// * The window size is persisted in mods/smres.cfg and re-applied on the first
//   step of a session; the snap-back undo then defends it through the initial
//   ship load.
// * The UI needs 1016x704, so the region never goes below it: a smaller window
//   falls back to GM's stock stretch instead of clipping the UI away. The
//   region is capped at 6144 -- past that the canvas view would run into the
//   picker's world-coordinate band (room x >= 6144) and phantom-scroll it.
// * mods/smsize.txt ("W<newline>H") resizes the window programmatically --
//   the deterministic lever for driving this under a wine virtual desktop,
//   where no window manager hands you the title bar.
// * On each apply (and every 60 steps when mods/probe.on exists) the state is
//   reported to mods/smres.txt for the measurement harness.

var inited;
inited = 0;
if (variable_global_exists('bsf_smres_init'))
    if (global.bsf_smres_init)
        inited = 1;
if (inited) exit;
global.bsf_smres_init = 1;

var m, i;
m = object_add();

object_event_add(m, 0, 0,
    'tick = 0;' +
    'aw = 1016; ah = 704;' +          // intended client size (snap-back undo target)
    'bw = 1016; bh = 704;' +          // region actually built by a room load
    'lw = -1; lh = -1; stab = 0;' +   // last observed size, frames unchanged
    'pw = -1; ph = -1;' +             // previous frame, for snap-back detection
    'repnow = 0;' +
    'cfgw = 0; cfgh = 0;' +
    'if (file_exists("mods/smres.cfg")) {' +
    '  var g;' +
    '  g = file_text_open_read("mods/smres.cfg");' +
    '  cfgw = real(file_text_read_string(g)); file_text_readln(g);' +
    '  cfgh = real(file_text_read_string(g));' +
    '  file_text_close(g);' +
    '}');

object_event_add(m, 3, 0,
    // Stand down until API_Init has resolved the client-size wrapper (and stay
    // down forever if the DLL is missing: the editor is stock either way).
    // Value test, not existence -- see the header.
    'var rdy;' +
    'rdy = 0;' +
    'if (variable_global_exists("external_api_window_getclientwidth"))' +
    '  if (global.external_api_window_getclientwidth != 0)' +
    '    rdy = 1;' +
    'if (!rdy) exit;' +
    'tick += 1;' +

    // Deterministic resize lever, for harnesses and scripts.
    'if (tick mod 30 == 0 && file_exists("mods/smsize.txt")) {' +
    '  var g2, tw2, th2;' +
    '  g2 = file_text_open_read("mods/smsize.txt");' +
    '  tw2 = real(file_text_read_string(g2)); file_text_readln(g2);' +
    '  th2 = real(file_text_read_string(g2)); file_text_close(g2);' +
    '  file_delete("mods/smsize.txt");' +
    '  if (tw2 >= 320 && th2 >= 240) window_set_size(tw2, th2);' +
    '}' +

    'var cw, ch, pv;' +
    'cw = API_Window_GetClientWidth(window_handle());' +
    'ch = API_Window_GetClientHeight(window_handle());' +
    'pv = 0;' +
    'if (variable_global_exists("preview")) pv = global.preview;' +

    // Re-apply the last session's window size once, on the first live step.
    // The editor's own startup will still force 1016x704 when the initial ship
    // loads; the snap-back undo below wins that exchange.
    'if (tick == 1 && cfgw >= 320 && cfgh >= 240 && (cfgw != cw || cfgh != ch)) {' +
    '  aw = cfgw; ah = cfgh;' +
    '  window_set_size(cfgw, cfgh);' +
    '}' +

    // gameLoaded() snaps the window back to 1016x704 on every ship load: a
    // one-frame jump there from the intended size is that snap-back, undone
    // here. A real user resize passes through intermediate sizes.
    'if (cw == 1016 && ch == 704 && pw == aw && ph == ah' +
    '    && (aw != 1016 || ah != 704)) {' +
    '  window_set_size(aw, ah);' +
    '}' +
    'pw = cw; ph = ch;' +

    // A new size must hold still for 8 frames (a drag in progress reports a
    // different size every frame) before it becomes the intended size.
    'if (cw != lw || ch != lh) { stab = 0; lw = cw; lh = ch; }' +
    'else stab += 1;' +
    'if (stab == 8 && !pv && cw >= 320 && ch >= 240) {' +
    '  aw = cw; ah = ch;' +
    '  if (aw != cfgw || ah != cfgh) {' +
    '    cfgw = aw; cfgh = ah;' +
    '    var f;' +
    '    f = file_text_open_write("mods/smres.cfg");' +
    '    file_text_write_string(f, string(aw)); file_text_writeln(f);' +
    '    file_text_write_string(f, string(ah)); file_text_writeln(f);' +
    '    file_text_close(f);' +
    '  }' +
    '  var rw, rh;' +
    '  rw = min(max(aw, 1016), 6144);' +
    '  rh = min(max(ah, 704), 6144);' +
    '  if (rw != bw || rh != bh) {' +
    '    bw = rw; bh = rh;' +
    '    repnow = 1;' +
    // The layout assert below sizes the ports for (bw,bh) before this step
    // ends, and the room transition rebuilds the region from those ports.
    // Persistent room: every instance -- the whole ship -- survives.
    '    room_goto(rm_main);' +
    '  }' +
    '}' +

    // ------------------------------------------------- per-step layout assert
    // Stock code restores hardcoded ports (856/776/240) on picker close and
    // arrange exit; asserting every step means those last one frame. Group-
    // arrange mode owns the views entirely, preview likewise.
    'if (!global.grouparrange && !pv) {' +
    '  var x0, z, tw, th, cx, cy, k;' +
    '  z = obj_sidebar.l_zoom;' +
    '  x0 = 160; if (global.hidegui) x0 = 0;' +
    '  view_xport[0] = 0; view_yport[0] = 0;' +
    '  view_wport[0] = bw; view_hport[0] = bh;' +
    '  view_wview[0] = bw; view_hview[0] = bh;' +
    '  view_xport[1] = x0; view_yport[1] = 15;' +
    '  tw = bw - x0; th = bh - 15;' +
    '  if (view_wport[1] != tw || view_hport[1] != th) {' +
    // Retake the port, preserving the view centre the way stock zoom code does.
    '    cx = view_xview[1] + view_wview[1] / 2;' +
    '    cy = view_yview[1] + view_hview[1] / 2;' +
    '    view_wport[1] = tw; view_hport[1] = th;' +
    '    view_wview[1] = tw * z; view_hview[1] = th * z;' +
    '    view_xview[1] = cx - view_wview[1] / 2;' +
    '    view_yview[1] = cy - view_hview[1] / 2;' +
    '    if (view_xview[1] < 160) view_xview[1] = 160;' +
    '    else if (view_xview[1] > 6144 - view_wview[1]) view_xview[1] = 6144 - view_wview[1];' +
    '    if (view_yview[1] < 15) view_yview[1] = 15;' +
    '    else if (view_yview[1] > room_height - view_hview[1]) view_yview[1] = room_height - view_hview[1];' +
    '  }' +
    '  view_xport[2] = 160; view_yport[2] = 0;' +
    '  view_wport[2] = bw - 160; view_wview[2] = bw - 160;' +
    '  for (k = 3; k <= 6; k += 1) {' +
    '    view_xport[k] = bw - 240; view_yport[k] = 15;' +
    '    view_wport[k] = 240; view_wview[k] = 240;' +
    '  }' +
    // The topbar close button sits at a stock 765 = 1016-251; keep it hugging
    // the right edge (hit-testing follows x, so this moves the hotspot too).
    '  if (instance_exists(gui_close)) gui_close.x = bw - 251;' +
    '}' +

    // ------------------------------------------------------------- reporting
    'if (repnow || (tick mod 60 == 0 && file_exists("mods/probe.on"))) {' +
    '  repnow = 0;' +
    '  var f2;' +
    '  f2 = file_text_open_write("mods/smres.txt");' +
    '  file_text_write_string(f2, "client=" + string(cw) + "x" + string(ch)); file_text_writeln(f2);' +
    '  file_text_write_string(f2, "win=" + string(window_get_width()) + "x" + string(window_get_height())); file_text_writeln(f2);' +
    '  file_text_write_string(f2, "region=" + string(window_get_region_width()) + "x" + string(window_get_region_height())); file_text_writeln(f2);' +
    '  file_text_write_string(f2, "intent=" + string(aw) + "x" + string(ah) + " built=" + string(bw) + "x" + string(bh)); file_text_writeln(f2);' +
    '  file_text_write_string(f2, "port0=" + string(view_xport[0]) + "," + string(view_yport[0]) + " " + string(view_wport[0]) + "x" + string(view_hport[0])); file_text_writeln(f2);' +
    '  file_text_write_string(f2, "port1=" + string(view_xport[1]) + "," + string(view_yport[1]) + " " + string(view_wport[1]) + "x" + string(view_hport[1])); file_text_writeln(f2);' +
    '  file_text_write_string(f2, "port3=" + string(view_xport[3]) + "," + string(view_yport[3]) + " " + string(view_wport[3]) + "x" + string(view_hport[3])); file_text_writeln(f2);' +
    '  file_text_write_string(f2, "view1=" + string(view_wview[1]) + "x" + string(view_hview[1]) + " at " + string(view_xview[1]) + "," + string(view_yview[1])); file_text_writeln(f2);' +
    '  file_text_write_string(f2, "zoom=" + string(obj_sidebar.l_zoom) + " hidegui=" + string(global.hidegui) + " arrange=" + string(global.grouparrange)); file_text_writeln(f2);' +
    '  file_text_write_string(f2, "tick=" + string(tick) + " stab=" + string(stab)); file_text_writeln(f2);' +
    '  file_text_close(f2);' +
    '}');

i = instance_create(0, 0, m);
i.persistent = true;
i.depth = -10000000;

// Backdrop extensions for the parts of the chrome that are fixed-size art:
// the stock topbar rectangle stops at a hardcoded 1016, and the sidebar panel
// background is 704 tall, so a bigger region shows bare room past both. Both
// fills are c_green, which is what the topbar strip itself is drawn in.
// Appended (never replaced -- object_event_add can only append), so this draws
// right after the stock chrome.
object_event_add(obj_sidebar, 8, 0,
    'if (view_current == 0) {' +
    '  draw_set_color(c_green);' +
    '  if (view_wview[0] > 1016) draw_rectangle(1016, 0, view_wview[0], 15, 0);' +
    '  if (view_hview[0] > 704) draw_rectangle(0, 704, 160, view_hview[0], 0);' +
    '  draw_set_color(c_white);' +
    '}');

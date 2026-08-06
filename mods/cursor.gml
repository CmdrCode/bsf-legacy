// Battleships Forever -- the cursor cache.
//
// Gated on mods/cursor.on, chained from init.gml.
//
// ------------------------------------------------------------------ the cost
// mouse_x is not a variable. It is a getter (0x00523DA0) whose implementation
// calls the cursor helper 0x00466414 TWICE -- once per coordinate -- and
// mouse_y repeats all of it independently, so reading the pair is FOUR cursor
// round-trips. The helper's first call is the GetCursorPos import thunk, and
// under wine every GetCursorPos is an unconditional wine_server_call: a
// wineserver IPC round-trip with no fast path, plus an X11 driver round-trip
// whenever the cursor has been IDLE for more than 100 ms. The 100 ms cache in
// wine is INVERTED -- a still cursor is the expensive case, which is the normal
// state while a player reads the screen.
//
// Measured: mouse_x 176 us a read, mouse_y 171, against 0.78 us for an ordinary
// global and 0.49 for mouse_check_button. BSF performs 453 per-frame reads
// across 75 events; ctr_GUI's Draw alone reads the pair 33 times.
//
// ------------------------------------------------- why this is not a GML mod
// object_event_add APPENDS to a stock event, it does not replace it. Verified
// in-game twice: two code actions added to one fresh Step event both run every
// frame, and an action appended to GUI_ExitIcon's STOCK
// Create event sees `offsetx` already set to 1008 by the stock body. So GML can
// only ever ADD work to an event -- it cannot remove the stock cursor reads,
// which are the entire cost.
//
// The cost is therefore removed one layer down, by hooking the GetCursorPos
// IMPORT in bsfnat.dll. That fixes every caller at once -- ctr_GUI's 33 reads,
// GUI_Mouse's 23, every selection icon, and the click handlers too -- and it
// caches only the expensive half: GM still applies its own view transform on
// every read, so mouse_x stays correct while the camera scrolls and zooms.
// Only the OS cursor position is held, and only until the next tick.
//
// -------------------------------------------------------------- where to tick
// Two ticks a frame, at the two points measured to be safe (rm_Blockade, 7
// selected, camera still / scrolling+zooming / shaking):
//
//   Begin Step   serves the simulation phase. Measured identical to a reading
//                taken in Step and in End Step -- 0 differing frames out of 240.
//   top of Draw  serves every Draw consumer, which is where the reads are.
//
// A single Begin Step tick would be enough for correctness -- the view
// transform is re-applied per read regardless -- but a second tick costs one
// GetCursorPos and keeps every hover test in the frame reading a cursor
// sampled at the start of that frame's drawing rather than one sampled a whole
// simulation phase earlier. That is the difference between "no visible lag" and
// "maybe a third of a frame of lag", for about 80 us.
//
// ---------------------------------------------------------------- fail safe
// external_define aborts the rest of the FILE if the DLL will not resolve, and
// this file contains nothing else, so a missing bsfnat.dll leaves the game
// exactly stock. If the hook cannot find or write the IAT slot it patches
// nothing and returns a negative code, which lands in mods/cursor.log; the
// tick instances are then inert and the game is still exactly stock.

if (variable_global_exists('bsf_cursor_init')) exit;
global.bsf_cursor_init = 1;

var lf, o, i, diag;

// The mods/cursor.txt reporter, the mods/curfix lever and the camera driver are
// the measurement harness, not the fix. Ungated they cost a file_exists EVERY
// frame plus ~16 DLL crossings and a file write every second -- on the one
// module whose entire purpose is deleting per-frame overhead. Gated on the same
// mods/probe.on marker init.gml uses, checked defensively so this file still
// runs standalone.
diag = 0;
if (variable_global_exists('bsf_probe')) diag = global.bsf_probe;

lf = file_text_open_write('mods/cursor.log');
file_text_write_string(lf, 'enter'); file_text_writeln(lf); file_text_close(lf);

global.cur_hook   = external_define('bsfnat.dll', 'nat_cursor_hook',   dll_cdecl, ty_real, 1, ty_real);
global.cur_enable = external_define('bsfnat.dll', 'nat_cursor_enable', dll_cdecl, ty_real, 1, ty_real);
global.cur_stcfn  = external_define('bsfnat.dll', 'nat_cursor_stc',    dll_cdecl, ty_real, 1, ty_real);
global.cur_tick   = external_define('bsfnat.dll', 'nat_cursor_tick',   dll_cdecl, ty_real, 0);
global.cur_stat   = external_define('bsfnat.dll', 'nat_cursor_stat',   dll_cdecl, ty_real, 1, ty_real);
global.cur_reset  = external_define('bsfnat.dll', 'nat_cursor_reset',  dll_cdecl, ty_real, 0);
global.cur_verify = external_define('bsfnat.dll', 'nat_cursor_verify', dll_cdecl, ty_real, 1, ty_real);

lf = file_text_open_append('mods/cursor.log');
file_text_write_string(lf, 'defined'); file_text_writeln(lf); file_text_close(lf);

// TTL is a safety net, not the mechanism: if the game stops ticking -- a room
// change, a modal dialog, a mod that failed to load -- the cursor must not
// freeze. 100 ms is three frames at the 30 Hz cap.
global.cur_ok = external_call(global.cur_hook, 100);

lf = file_text_open_append('mods/cursor.log');
file_text_write_string(lf, 'hook=' + string(global.cur_ok)
    + ' slots=' + string(external_call(global.cur_stat, 1))
    + ' stcslots=' + string(external_call(global.cur_stat, 2))
    + ' slotva=' + string(external_call(global.cur_stat, 7))
    + ' stcva=' + string(external_call(global.cur_stat, 10)));
file_text_writeln(lf); file_text_close(lf);

global.cur_n     = 0;
global.cur_win   = 30;
global.cur_note  = '-';
global.cur_drive = 0;

if (global.cur_ok > 0) {

    // ------------------------------------------------------------ tick: step
    // Begin Step runs in depth order, higher first, so a large depth puts this
    // ahead of every stock Begin Step.
    o = object_add();
    object_event_add(o, 3, 1, 'external_call(global.cur_tick);');
    if (diag) {
        object_event_add(o, 3, 1,
            'if (global.cur_drive) {' +
            '  if (instance_exists(ctr_GUI)) {' +
            '    with (ctr_GUI) {' +
            '      l_viewx += 6 * global.cur_drive;' +
            '      l_viewy += 4 * global.cur_drive;' +
            '      if (l_zoom >= l_zoomtar - 0.001) { l_zoomtar = l_zoom + 0.35; }' +
            '    }' +
            '  }' +
            '}');
    }
    i = instance_create(0, 0, o); i.persistent = true; i.depth = 16000000;

    // ------------------------------------------------------------ tick: draw
    // Depth 15990000: above every real drawer in the game (the highest stock
    // depth is GUI_Light at 9999) but BELOW perf.gml's +16000000 and hud.gml's
    // +16000001 brackets, so the one real GetCursorPos this costs is counted
    // INSIDE the measured draw phase rather than hidden in front of it.
    o = object_add();
    object_event_add(o, 8, 0, 'external_call(global.cur_tick);');
    i = instance_create(0, 0, o); i.persistent = true; i.depth = 15990000;

    // -------------------------------------------------------------- reporter
    // Harness only -- see `diag` above.
    if (diag) {
    o = object_add();
    object_event_add(o, 3, 2,
        'global.cur_n += 1;' +
        'if (global.cur_n >= global.cur_win) {' +
        '  var f, c, r;' +
        '  c = external_call(global.cur_stat, 3);' +
        '  r = external_call(global.cur_stat, 4);' +
        '  f = file_text_open_write("mods/cursor.txt");' +
        '  file_text_write_string(f, "frames=" + string(global.cur_n)' +
        '    + " gcp_calls=" + string(c / global.cur_n)' +
        '    + " gcp_real=" + string(r / global.cur_n)' +
        '    + " stc_calls=" + string(external_call(global.cur_stat, 5) / global.cur_n)' +
        '    + " stc_real=" + string(external_call(global.cur_stat, 6) / global.cur_n)' +
        '    + " enabled=" + string(external_call(global.cur_stat, 8))' +
        '    + " stc=" + string(external_call(global.cur_stat, 11))' +
        '    + " ttl=" + string(external_call(global.cur_stat, 9))' +
        '    + " slots=" + string(external_call(global.cur_stat, 1))' +
        // Verify mode: every cached return is checked against a live query.
        // ver_bad is the number that disagreed, ver_dx/dy the worst by how
        // much, in SCREEN pixels.
        '    + " ver_n=" + string(external_call(global.cur_stat, 12))' +
        '    + " ver_bad=" + string(external_call(global.cur_stat, 13))' +
        '    + " ver_dx=" + string(external_call(global.cur_stat, 14))' +
        '    + " ver_dy=" + string(external_call(global.cur_stat, 15))' +
        '    + " verify=" + string(external_call(global.cur_stat, 16))' +
        '    + " scrx=" + string(external_call(global.cur_stat, 17))' +
        '    + " scry=" + string(external_call(global.cur_stat, 18))' +
        '    + " mousex=" + string(mouse_x) + " mousey=" + string(mouse_y)' +
        '    + " note=" + string(global.cur_note));' +
        '  file_text_writeln(f); file_text_close(f);' +
        '  external_call(global.cur_reset);' +
        '  global.cur_n = 0;' +
        '}');

    // Own lever file, so flipping this cannot race perf.gml's pfset or
    // hud.gml's hset. `enable` is the A/B: the hook stays installed in both
    // arms and only the caching branch changes, so the two differ by one
    // predictable test and nothing else.
    object_event_add(o, 3, 2,
        'if (file_exists("mods/curfix")) {' +
        '  var g, key, val;' +
        '  g = file_text_open_read("mods/curfix");' +
        '  key = file_text_read_string(g); file_text_readln(g);' +
        '  val = real(file_text_read_string(g)); file_text_close(g);' +
        '  file_delete("mods/curfix");' +
        '  if (key == "enable") external_call(global.cur_enable, val);' +
        '  if (key == "stc")    external_call(global.cur_stcfn, val);' +
        '  if (key == "verify") external_call(global.cur_verify, val);' +
        '  if (key == "win")    global.cur_win = val;' +
        // Drive the camera through the game own scroll and zoom variables, so
        // verify mode is exercised with the view moving rather than parked.
        '  if (key == "camdrive") {' +
        '    global.cur_drive = val;' +
        '  }' +
        '  if (key == "selectn") {' +
        '    if (instance_exists(ctr_GUI)) {' +
        '      var sn;' +
        '      sn = 0;' +
        '      with (ctr_Ship) { if (sn < val) { global.selected[sn] = id; sn += 1; } }' +
        '      ctr_GUI.l_numselected = sn;' +
        '      with (ctr_GUI) { clearIcons(); createIcons(); }' +
        '    }' +
        '  }' +
        '  global.cur_note = key + "=" + string(val);' +
        '}');

    i = instance_create(0, 0, o); i.persistent = true; i.depth = -9000003;
    }                            // end if (diag)
}

lf = file_text_open_append('mods/cursor.log');
file_text_write_string(lf, 'live'); file_text_writeln(lf); file_text_close(lf);

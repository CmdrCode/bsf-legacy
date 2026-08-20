// Battleships Forever -- in-game resolution picker.
//
// Ships as a plain text mod: the exe is never patched for resolution. That
// matters because a patched-in resolution has to be chosen by whoever builds the
// patch, and they do not know the player's monitor.
//
// -------------------------------------------------------------------- how
// GM 7.0 builds the drawing region (the real backbuffer) when a room loads,
// from THAT room's authored view port. Nothing at runtime resizes an existing
// region -- window_set_region_size reports a new size while the backbuffer stays
// put, and view_wport is only a zoom inside the buffer that already exists.
//
// But `room_set_view` rewrites a room's authored port, it works on rooms that
// are not loaded, and the next load of that room builds the region at the new
// size. So: rewrite all 25 rooms, then room_restart(). Verified from 1280x720 up
// to 3840x2160 and back down, live, with no game restart -- screen_save returns
// the requested size and draw_line still measures 1 device pixel, which is what
// separates a native render from an upscale.
//
// ------------------------------------------------------------- aspect policy
// Every room authors view[0] as 1024x768 and several rooms are exactly 768 tall,
// so vertical is the binding constraint: view height stays 768 and the width
// opens up to the display aspect (1365x768 at 16:9). Battle rooms are 2000-2048
// wide and have the room to give. The 1024-wide menu rooms do not, so by default
// they keep a 4:3 view and get a 4:3 region, pillarboxed inside the 16:9 window
// rather than stretched to fill it.
//
// A menu room can escape the pillarbox by being WIDENED instead -- room_set_width
// plus a full-width view -- but only if something re-centres its 1024-authored
// layout afterwards. That is what wide_list is: the rooms widescreen.gml knows
// how to adapt. rm_MainMenu is there because its background is a live battle that
// BSF already drives off room_width; the rest stay pillarboxed.
//
// That pillarbox is NOT free, and assuming it was is what shipped a bug: GM's
// default region scaling is "stretch to fill the window", so a 2880x2160 region
// in a 3840x2160 window renders every menu 1.3333x too wide. Measured, not
// reasoned -- a 300x300 world-unit square is 844x844 in the region and
// 1125.5x844 on screen. window_set_region_scale(-1, 0) selects scale-to-fit-
// keeping-aspect and is a no-op in the gameplay rooms, whose region already
// equals the window.
//
// BSF's HUD is anchored to view_wview rather than to a hardcoded 1024, so the
// widened view gives genuinely more visible battlefield with the panels still
// stuck to the edges. That was checked, not assumed.
//
// ----------------------------------------------------------------- gotchas
// * rm_Options ships with views DISABLED, so its region comes from the room size
//   and it alone snaps back to 1024x768 -- on the very screen a picker belongs
//   on. room_set_view_enabled(r, 1) fixes it and is harmless on the other 24.
// * The mod bootstrap is injected into GUI_MainTitle's startup event, and
//   GUI_MainTitle lives in rm_MainMenu. room_restart() there re-runs the
//   bootstrap: fresh objects, fresh apply, another restart, forever. Hence the
//   global guard below. This is not hypothetical; it is what happened.
// * Room ids are not resource-tree order -- deleted slots leave gaps, so the
//   ids run 0..43 for 25 rooms. Iterate ids and test room_exists().

if (variable_global_exists('bsf_res_init')) exit;
global.bsf_res_init = 1;

var m, i;
m = object_add();

object_event_add(m, 0, 0,
    // Rooms whose width is 1024 and so cannot host a wider view.
    // rm_ChooseShips belongs here despite being an 1888-wide room: it drives its
    // OWN view. ctr_ChooseShips opens at view_wview 3712 and steps down 128 a frame
    // until it settles at exactly 1024, and its buttons, text and cursor are scaled
    // by view_wview[0]/1024 -- that factor is the intro animation, not a widescreen
    // layout, so it must reach 1 at rest. Give the room a 4:3 port and it does.
    'narrow_list = "|rm_Briefing|rm_Scores|rm_ChooseColour|rm_Options|rm_ChooseShips|";' +
    // Rooms whose 1024-wide layout `widescreen.gml` knows how to re-centre, so
    // they can take a full-width view and a WIDER ROOM instead of a 4:3 region.
    // The room width is the point: BSF's menu battle spawns, converges and
    // herds on room_width, so widening the room is what makes the fight fill
    // the screen. Nothing here works without the matching adapter.
    'wide_list = "|rm_MainMenu|";' +
    // Candidates are filtered against the actual monitor, because the list is
    // shipped to people whose screens we cannot know. Anything taller or wider
    // than the display is dropped (GM clamps the region to the display anyway,
    // so such an entry would silently resolve to something else), and an entry
    // equal to the display is dropped because the display is appended last --
    // otherwise the list contains the same size twice and one step of the cycle
    // does nothing, which reads as a dead keypress.
    'var k, dw, dh;' +
    'dw = display_get_width(); dh = display_get_height();' +
    'cand_w[0] = 1280; cand_h[0] =  720;' +
    'cand_w[1] = 1600; cand_h[1] =  900;' +
    'cand_w[2] = 1920; cand_h[2] = 1080;' +
    'cand_w[3] = 2560; cand_h[3] = 1440;' +
    'cand_w[4] = 3840; cand_h[4] = 2160;' +
    'nres = 0;' +
    'for (k = 0; k < 5; k += 1) {' +
    '  if (cand_w[k] > dw || cand_h[k] > dh) continue;' +
    '  if (cand_w[k] == dw && cand_h[k] == dh) continue;' +
    '  reslist_w[nres] = cand_w[k]; reslist_h[nres] = cand_h[k]; nres += 1;' +
    '}' +
    // The monitor itself is always offered, and is the default on first run.
    'reslist_w[nres] = dw; reslist_h[nres] = dh; nres += 1;' +
    'cur_w = 0; cur_h = 0; sel = nres - 1; lastroom = -1;' +
    'var g;' +
    'if (file_exists("mods/res.cfg")) {' +
    '  g = file_text_open_read("mods/res.cfg");' +
    '  pend_w = real(file_text_read_string(g)); file_text_readln(g);' +
    '  pend_h = real(file_text_read_string(g)); file_text_close(g);' +
    '} else { pend_w = display_get_width(); pend_h = display_get_height(); }');

// Everything a region rebuild resets, in one place, so Room Start and the Step
// guard below cannot drift apart.
//
// The scaling: -1 = scale up as far as the window allows while keeping the
// region's own aspect; 0 = do not resize the window to suit.
//
// The size: that `0` asks GM not to resize the window, and GM obeys it here --
// then resizes the window anyway when the NEXT room builds its region, because
// a fresh region takes the window with it. So a narrow room did not merely
// pillarbox inside the window the way the header above describes; it shrank the
// window to the pillarbox. Entering the briefing at 1920x1080 left a 1440x1080
// window with the desktop showing through where the game had been, and leaving
// it did not give the size back. Re-asserting the window is what makes the
// pillarbox live INSIDE the window, which was always the intent.
//
// Position is deliberately not touched: GM keeps the top-left corner when it
// resizes, so restoring the size alone puts the window back exactly where it
// was. window_center() here would drag a window the player had placed into the
// middle of the screen on every room change.
object_event_add(m, 7, 10,
    'window_set_region_scale(-1, 0);' +
    'if (cur_w <= 0) exit;' +                    // no resolution applied yet
    // Borderless fullscreen is options.gml's window, sized to the monitor and
    // re-asserted by its own watchdog. Two owners would fight every room load,
    // so this asks that owner to re-assert instead of setting the size here.
    // Worth asking: the watchdog holds a 60-frame cooldown after each apply, so
    // left alone it gives the monitor back a full two seconds after the room
    // shrank the window. mod_fs_apply is its "now, cooldown or not" input.
    'var fsw;' +
    'fsw = 0;' +
    'if (variable_global_exists("mod_fullscreen")) fsw = global.mod_fullscreen;' +
    'if (fsw) {' +
    '  if (variable_global_exists("mod_fs_apply")) global.mod_fs_apply = 1;' +
    '  exit;' +
    '}' +
    'if (window_get_width() == cur_w) { if (window_get_height() == cur_h) exit; }' +
    'window_set_size(cur_w, cur_h);');

// Room Start rather than Step: it runs after the room's region is built and
// before the first frame of that room is drawn, so the window is never seen at
// the wrong size. A persistent instance receives it on every room load,
// room_restart() included.
object_event_add(m, 7, 4, 'event_user(0);');

object_event_add(m, 3, 0,
    // Kept as the backstop Room Start cannot be: a window manager that meddles
    // after the room has loaded, and any path that rebuilds the region without
    // starting a room. Idempotent -- it exits when the window already fits.
    'if (room != lastroom) { lastroom = room; event_user(0); }' +
    // F11 / shift-F11 cycle. A real build would drive this from the Options
    // screen; the key is here so the feature is usable without touching BSF's UI.
    'if (keyboard_check_pressed(vk_f11)) {' +
    '  if (keyboard_check(vk_shift)) sel -= 1; else sel += 1;' +
    '  if (sel >= nres) sel = 0;' +
    '  if (sel < 0) sel = nres - 1;' +
    '  pend_w = reslist_w[sel]; pend_h = reslist_h[sel];' +
    '}' +
    'if (pend_w > 0) {' +
    '  var pw, ph, vw, mw, r, f;' +
    '  pw = pend_w; ph = pend_h; pend_w = 0; pend_h = 0;' +
    '  if (pw == cur_w && ph == cur_h) exit;' +          // never restart for a no-op
    '  cur_w = pw; cur_h = ph;' +
    '  vw = floor(768 * pw / ph);' +                     // widened view, 16:9 -> 1365
    '  mw = floor(ph * 1024 / 768);' +                   // 4:3 region for narrow rooms
    '  for (r = 0; r < 64; r += 1) {' +
    '    if (!room_exists(r)) continue;' +
    '    if (string_pos("|" + room_get_name(r) + "|", wide_list) > 0) {' +
    '      room_set_width(r, vw);' +
    '      room_set_view(r, 0, 1, 0, 0,   vw, 768, 0, 0, pw, ph, 32, 32, -1, -1, -1);' +
    '    } else if (string_pos("|" + room_get_name(r) + "|", narrow_list) > 0) {' +
    '      room_set_view(r, 0, 1, 0, 0, 1024, 768, 0, 0, mw, ph, 32, 32, -1, -1, -1);' +
    '    } else {' +
    '      room_set_view(r, 0, 1, 0, 0,   vw, 768, 0, 0, pw, ph, 32, 32, -1, -1, -1);' +
    '    }' +
    '    room_set_view_enabled(r, 1);' +
    '  }' +
    '  f = file_text_open_write("mods/res.cfg");' +
    '  file_text_write_string(f, string(pw)); file_text_writeln(f);' +
    '  file_text_write_string(f, string(ph)); file_text_writeln(f);' +
    '  file_text_close(f);' +
    '  room_restart();' +
    '}');

i = instance_create(0, 0, m);
i.persistent = true;
i.depth = -10000001;

// Published so the options screen can drive the picker instead of duplicating
// the resolution list and the apply logic.
global.bsf_res_mgr = i;

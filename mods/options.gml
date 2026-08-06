// Battleships Forever -- recreated Options screen with a resolution picker.
//
// ------------------------------------------------------------------ why
// Stock BSF has TWO options screens and neither is complete:
//   * from the main menu, GUI_MainOptions destroys the menu and builds 11
//     widgets as an OVERLAY inside rm_MainMenu -- it is not a room at all;
//   * from in-game, rm_Options is an empty room that builds itself from room
//     creation code, with Doodads/Surfaces/Particles/Colours commented out --
//     6 settings instead of 11.
// Both are authored for 1024x768, and neither can change the render resolution:
// the stock "Fullscreen"/"Widescreen" pair only calls display_set_size(1024,768)
// or (1280,960), and 1280x960 is 4:3 -- the "widescreen" option never was.
//
// This screen is one room, carries the union of all settings, is laid out from
// the live view width so it fills a widescreen display, and adds the real
// resolution picker (see resolution.gml).
//
// --------------------------------------------------------------- approach
// The stock widgets are REUSED, not reimplemented. Injected GML is compiled by
// the game's own compiler, so resource names like GUI_OptDoodads resolve exactly
// as they do in the game's own code -- `instance_create(x, y, GUI_OptDoodads)`
// gets the real widget with the real behaviour, writing the real bfconfig.ini
// keys. They are already known to be room-agnostic because stock BSF builds the
// same objects in two different rooms. Reimplementing them would have meant
// re-deriving eleven ini keys and their side effects (texture_set_interpolation,
// sound_global_volume, the Surfaces restart-and-relaunch) for no gain.
//
// Only the two genuinely new rows -- Resolution and Display Mode -- are ours,
// and they are drawn and hit-tested by hand. A stock widget's LABEL lives in its
// sprite (spr_optDoodads etc. are pictures of the words), and only the VALUE is
// drawn as text at (x+200, y-20). So a new row cannot borrow a stock sprite
// without borrowing the wrong label, and manual hit-testing avoids needing a
// sprite mask at all.

if (variable_global_exists('bsf_opt_init')) exit;
global.bsf_opt_init = 1;

var r, bg, ui, nav, i;

// ---------------------------------------------------------------- the room
// Wider and taller than any view we will hand it, so the layout is free to
// follow view_wview rather than being boxed in by room_width the way the stock
// 1024-wide menu rooms are.
r = room_add();
room_set_width(r, 2048);
room_set_height(r, 768);
room_set_caption(r, 'Options');
room_set_view(r, 0, 1, 0, 0, 1024, 768, 0, 0, 1024, 768, 32, 32, -1, -1, -1);
room_set_view_enabled(r, 1);
global.mod_opt_room = r;

// ------------------------------------------------------------- the screen
// Painted before anything else: a runtime-created room has GM's default grey
// background, and BSF's GUI_MainSquares grid is translucent white, so without
// this the whole screen washes out to pale grey. A drawing object rather than
// room_set_background_color -- no dependency on a function that may not exist,
// and it follows the view at any resolution.
bg = object_add();
object_event_add(bg, 8, 0,
    'draw_set_color(c_black); draw_set_alpha(1);' +
    'draw_rectangle(view_xview[0]-8, view_yview[0]-8,' +
    '               view_xview[0]+view_wview[0]+8, view_yview[0]+view_hview[0]+8, 0);');

ui = object_add();

// Create: build the screen from the live view size.
object_event_add(ui, 0, 0,
    'var vw, lx, rx, y0, dy, k, j, i, bk;' +
    'vw = view_wview[0];' +
    'sel = 0; hot = -1; dir = 0;' +
    // The desktop size cannot change while this screen is up, and under wine
    // display_get_* is a display-server query -- so it is read here rather than
    // twice a frame in the Draw. A resolution change re-runs Create.
    'dw = display_get_width(); dh = display_get_height();' +
    'lx = 190; rx = vw - 480; y0 = 200; dy = 68;' +
    'res_x = lx; res_y = y0; mode_x = lx; mode_y = y0 + dy;' +
    // authentic backdrop: the same objects rm_Options uses, but the square grid
    // is stepped across the ACTUAL view instead of a hardcoded 1024x768.
    'i = instance_create(0, 0, global.mod_opt_bg); i.depth = 1000000;' +
    'instance_create(0, 0, SFX_Transition);' +
    'instance_create(random(vw), random(768), GUI_Light);' +
    'for (k = -75; k < vw; k += 75) {' +
    '  for (j = -75; j < 768; j += 75) instance_create(k, j, GUI_MainSquares);' +
    '}' +
    'instance_create(vw/2, 100, GUI_OptTitle);' +
    'bk = instance_create(vw/2, 700, GUI_OptBack); bk.l_descript = 0;' +
    // Two columns placed off the live width. A stock widget draws its sprite at
    // x and its value text at x+200, so the right column needs 480px of room.
    'instance_create(lx, y0 + dy*2, GUI_OptInterpolate);' +
    'instance_create(lx, y0 + dy*3, GUI_OptGradients);' +
    'instance_create(lx, y0 + dy*4, GUI_OptDoodads);' +
    'instance_create(lx, y0 + dy*5, GUI_OptParticles);' +
    'instance_create(lx, y0 + dy*6, GUI_OptSurfaces);' +
    'instance_create(rx, y0,        GUI_OptDifficulty);' +
    'instance_create(rx, y0 + dy,   GUI_OptScrolling);' +
    'instance_create(rx, y0 + dy*2, GUI_OptSFXVol);' +
    'instance_create(rx, y0 + dy*3, GUI_OptMusic);' +
    // LAST in the column on purpose: GUI_OptColours creates three
    // GUI_OptSliderbar children at y+50, y+90 and y+130, so anything below it
    // gets drawn over. Stock BSF puts it at the bottom for the same reason.
    'instance_create(rx, y0 + dy*4, GUI_OptColours);');

// The two actions live in User Events so mouse and keyboard share one
// implementation, and so they can be fired directly for testing:
//     with (instance) event_user(0)
// which matters because a mod cannot be click-tested headlessly here -- see the
// note at the bottom of this file.
//
// event_user(0) = change resolution   (arg: dir, -1 or +1)
// event_user(1) = toggle display mode
object_event_add(ui, 7, 10,
    // The picker itself lives in resolution.gml; duplicating the list and the
    // apply logic here would give two things to keep in step. The manager does
    // the room_restart, and this room is simply rebuilt at the new size.
    'if (variable_global_exists("bsf_res_mgr")) {' +
    '  var d; d = dir;' +
    '  with (global.bsf_res_mgr) {' +
    '    sel += d;' +
    '    if (sel >= nres) sel = 0;' +
    '    if (sel < 0) sel = nres - 1;' +
    '    pend_w = reslist_w[sel]; pend_h = reslist_h[sel];' +
    '  }' +
    '}');

object_event_add(ui, 7, 11,
    'global.mod_fullscreen = 1 - global.mod_fullscreen;' +
    // No display_set_size here on purpose. The region is already the resolution
    // the player picked, so leaving the desktop mode alone gives borderless
    // fullscreen with GM scaling the region to the screen -- no mode switch, no
    // black-screen flicker, and other windows keep their positions. This is what
    // stock BSF gets wrong: its Fullscreen button changes the DESKTOP mode to
    // 1024x768 (or 1280x960 for "Widescreen", which is 4:3 anyway).
    'window_set_fullscreen(global.mod_fullscreen);' +
    'var f;' +
    'f = file_text_open_write("mods/mode.cfg");' +
    'file_text_write_string(f, string(global.mod_fullscreen)); file_text_writeln(f);' +
    'file_text_close(f);');

// Step: hover + click for our two rows, and keyboard for them as well. The
// eleven stock widgets keep their own native mouse handling, exactly as in stock
// BSF -- which is mouse-only.
object_event_add(ui, 3, 0,
    'var mx, my, w, h;' +
    'w = 570; h = 48;' +
    'mx = mouse_x; my = mouse_y;' +
    'hot = -1;' +
    'if (mx > res_x-140  && mx < res_x-140+w  && my > res_y-34  && my < res_y-34+h)  hot = 0;' +
    'if (mx > mode_x-140 && mx < mode_x-140+w && my > mode_y-34 && my < mode_y-34+h) hot = 1;' +
    'if (hot >= 0) sel = hot;' +                     // hovering moves the caret
    // keyboard: up/down pick a row, left/right change it, enter activates
    'if (keyboard_check_pressed(vk_up))   sel = 0;' +
    'if (keyboard_check_pressed(vk_down)) sel = 1;' +
    'dir = 0;' +
    'if (keyboard_check_pressed(vk_right) || keyboard_check_pressed(vk_enter)) dir =  1;' +
    'if (keyboard_check_pressed(vk_left)) dir = -1;' +
    'if (hot >= 0 && mouse_check_button_released(mb_left))  dir =  1;' +
    'if (hot >= 0 && mouse_check_button_released(mb_right)) dir = -1;' +
    'if (dir != 0 && sel == 0) event_user(0);' +
    'if (dir != 0 && sel == 1) event_user(1);' +
    'if (keyboard_check_pressed(vk_escape)) room_goto(global.lastroom);');

// Draw: our two rows, styled to sit alongside the stock sprite rows.
// The label goes in MainMenuFont to match the stock sprites (~34px per glyph, so
// "Resolution" alone runs to about x+200) and the VALUE in the smaller GUIFont
// further right -- at MainMenuFont a value like "1920 x 1080" simply collides
// with its own label, which is exactly what the first attempt did.
object_event_add(ui, 8, 0,
    'var bx, by, k, val, hi, rw, rh;' +
    'draw_set_font(MainMenuFont); draw_set_halign(0);' +
    'hi = make_color_rgb(120, 220, 255);' +
    // Read once: the render size is the same for the picker and the footer, and
    // both used to ask for it separately every frame.
    'rw = window_get_region_width(); rh = window_get_region_height();' +
    'for (k = 0; k < 2; k += 1) {' +
    '  if (k == 0) { bx = res_x; by = res_y; } else { bx = mode_x; by = mode_y; }' +
    '  draw_set_color(c_black); draw_set_alpha(0.5);' +
    '  draw_rectangle(bx-140, by-34, bx+430, by+14, 0);' +
    '  draw_set_alpha(1);' +
    '  if (sel == k) draw_set_color(hi); else draw_set_color(c_dkgray);' +
    '  draw_rectangle(bx-140, by-34, bx+430, by+14, 1);' +
    '  draw_set_font(MainMenuFont);' +
    '  if (sel == k) draw_set_color(hi); else draw_set_color(c_white);' +
    '  if (k == 0) draw_text(bx-130, by-26, "Resolution");' +
    '  else        draw_text(bx-130, by-26, "Display");' +
    '  draw_set_font(GUIFont);' +
    '  if (k == 0) val = "< " + string(rw) + " x " + string(rh) + " >";' +
    '  else if (global.mod_fullscreen) val = "< Fullscreen >";' +
    '  else val = "< Windowed >";' +
    '  draw_text(bx+215, by-20, val);' +
    '}' +
    // The render size is the thing everyone gets wrong about this game, so it is
    // stated outright rather than left to be inferred from the picker.
    'draw_set_font(DescriptFont); draw_set_color(c_gray);' +
    'draw_text(40, 726, "Rendering at " + string(rw) + "x" + string(rh) +' +
    '  "   view " + string(view_wview[0]) + "x" + string(view_hview[0]) +' +
    '  "   desktop " + string(dw) + "x" + string(dh) +' +
    '  "      arrows / click to change, Esc to go back");');

global.mod_opt_bg = bg;
global.mod_opt_ui = ui;
room_instance_add(r, 0, 0, ui);

// ------------------------------------------------------------ interception
// Both stock routes are taken over without patching a single call site.
nav = object_add();

// (a) In-game: room_goto(rm_Options). Room Start fires before the first Step and
//     before any Draw, so the stock screen never gets a frame.
object_event_add(nav, 7, 4,
    'if (room == 32) room_goto(global.mod_opt_room);');

// (b) From the main menu the stock screen is an OVERLAY, not a room, so there is
//     no room event to hook -- watch for its widgets instead. Begin Step runs
//     before every normal Step and before Draw, so again nothing of the stock
//     overlay reaches the screen.
object_event_add(nav, 3, 1,
    'if (room == 1 && instance_exists(GUI_OptDoodads)) {' +
    '  global.lastroom = 1;' +                       // GUI_OptBack returns here
    '  room_goto(global.mod_opt_room);' +
    '}');

i = instance_create(0, 0, nav);
i.persistent = true;

// Display mode is ours, so it needs its own persistence; every other setting on
// this screen is stock and already round-trips through bfconfig.ini.
global.mod_fullscreen = 0;
if (file_exists('mods/mode.cfg')) {
    var g;
    g = file_text_open_read('mods/mode.cfg');
    global.mod_fullscreen = real(file_text_read_string(g));
    file_text_close(g);
    window_set_fullscreen(global.mod_fullscreen);
}

// ---------------------------------------------------------------------- note
// Verifying this headlessly: the game receives mouse POSITION from synthetic X
// events but never the BUTTONS -- a 6-second held mouse-down reads
// mouse_check_button(mb_left) = 0 throughout while mouse_x/mouse_y track
// exactly. Keyboard events do get through. That is why the actions sit in User
// Events: `with (inst) event_user(0)` exercises the real handler without a
// click, and the keyboard path is testable end to end.

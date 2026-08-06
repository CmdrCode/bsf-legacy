// Battleships Forever -- widescreen main menu.
//
// The main menu is a live battle behind a button list. Everything else in the
// mod pillarboxes it to 4:3 (see resolution.gml) because the room is 1024 wide
// and its UI is authored around x=512. This file widens the ROOM instead, so
// the battle fills the screen, and moves the UI back to the middle.
//
// ------------------------------------------------------------- what adapts
// Read from BSF's own room-creation code -- most of it is already resolution-
// aware and needs nothing:
//
//   ships    spawn at -random(50) and room_width+random(50), converge on
//            (room_width/2, room_height/2), and are herded back to that centre
//            by ctr_MainMenu whenever they leave the room. All room_width.
//   meteors  400 + random(room_width-800).
//   credit   draw_text(room_width/2 - string_width(str)/2, room_height-32, ...).
//
// So widening the room moves the brawl to the new centre and makes the ships
// enter at the real screen edges, for free. What is hardcoded to 1024:
//
//   buttons        instance_create(512, ...) -- six of them, plus every submenu
//   GUI_MainSquares  for (i=-75; i<1024; i+=75) -- the grid stops at x=1050
//   GUI_Scribbler    room-editor instances, authored across 15..1017
//   Doodad(Add)      room-editor instances, -38..1050
//   GUI_Light        instance_create(random(1024), random(768))
//
// ---------------------------------------------------------------- the UI
// `ctr_MainMenu` is the PARENT of every menu button -- that is how BSF's own
// submenu handlers clear the screen (`with (ctr_MainMenu) instance_destroy()`).
// So one `with` moves the main list, the Skirmish list, the Custom list and the
// Career list, including buttons that do not exist yet. It has to run every
// frame rather than once, because those buttons are created and destroyed as
// you move between submenus; a per-instance marker keeps it idempotent.
//
// ⚠ The title is NOT moved by moving the instance. GUI_MainTitle's Draw event is
//
//     draw_sprite_ext(sprite_index, image_index, 532, 120, ...)   // shadow
//     draw_sprite_ext(sprite_index, image_index, 522, 110, ...)   // shadow
//     draw_sprite_ext(sprite_index, image_index, x, y, ...)       // the title
//
// -- two drop-shadow copies at literal coordinates. Shift `x` and the title
// slides out from under its own shadow. Shifting the SPRITE ORIGIN instead moves
// all three draws together, because every one of them resolves the origin. That
// is why this file touches `sprite_set_offset` and leaves GUI_MainTitle.x alone.
//
// ------------------------------------------------------------------ gotchas
// * The once-per-load work cannot key off `room != lastroom`: applying a
//   resolution calls room_restart() *in* rm_MainMenu, so the room reloads
//   without the room number changing and the authored grid comes back
//   unextended. A non-persistent sentinel instance is the signal instead --
//   GM destroys it on every room load, including a restart.
// * `var` locals survive into a `with` body, so `dx` and `sc` below resolve
//   against this object and not the with-target. An UNDECLARED name would not:
//   it would become an instance variable on the target. Keep them in the var
//   list.

if (variable_global_exists('bsf_ws_init')) exit;
global.bsf_ws_init = 1;

var w, i;

// No events, never persistent. Its absence means "this room just loaded".
global.bsf_ws_sen = object_add();

w = object_add();

object_event_add(w, 3, 0,
    'var dx, sc, gx, gy;' +
    'if (room != rm_MainMenu) exit;' +
    'dx = (room_width - 1024) / 2;' +
    'if (dx <= 0) exit;' +                       // 4:3, or resolution not applied yet
    // ---------------------------------------------------- once per room load
    'if (!instance_exists(global.bsf_ws_sen)) {' +
    '  instance_create(0, 0, global.bsf_ws_sen);' +
    '  sc = room_width / 1024;' +
    // Background scatter is spread proportionally rather than shifted -- it is
    // decoration authored across the whole width, not a centred layout.
    '  with (GUI_Scribbler) x *= sc;' +
    '  with (ctr_Doodads)   x *= sc;' +
    // The mesh is CULLED, not just tiled: each square draws only when
    // abs(x - GUI_Light.x) < 680 && abs(y - GUI_Light.y) < 680, and BSF drops
    // GUI_Light at random(1024), random(768) and then lets it WANDER. At 4:3 a
    // 1360-wide window over a 1024 room covers whatever it does, so the cull is
    // invisible; at 1365 it drags a black band hundreds of pixels wide across
    // the screen. The light is pinned to the middle below, every frame, and the
    // mesh re-tiled to sit inside the window it lights.
    '  with (GUI_MainSquares) instance_destroy();' +
    '  for (gx = room_width / 2 - 679; gx < room_width; gx += 75) {' +
    '    for (gy = -75; gy < 768; gy += 75) {' +
    '      instance_create(gx, gy, GUI_MainSquares);' +
    '    }' +
    '  }' +
    '}' +
    // ------------------------------------------------------------ every frame
    // Buttons are created and destroyed as you move between the main list and
    // its submenus, so this cannot be a one-shot either.
    'with (ctr_MainMenu) {' +
    '  if (!variable_local_exists("bsf_ws_x")) { bsf_ws_x = 1; x += dx; }' +
    '}' +
    // Titles move by their SPRITE ORIGIN, not their x -- see the header. Both
    // titles that appear in this room are handled: GUI_MainTitle is always here,
    // GUI_CarTitle only once you are in Career, and it is NOT a ctr_MainMenu
    // child (BSF destroys it by name), so the block above never reaches it.
    // Re-applied every frame rather than latched: the value is always recomputed
    // from the stored original, so it cannot accumulate and it self-corrects
    // after a resolution change.
    'global.bsf_ws_spr = -1;' +
    'if (instance_exists(GUI_MainTitle)) with (GUI_MainTitle) global.bsf_ws_spr = sprite_index;' +
    'if (global.bsf_ws_spr >= 0) {' +
    '  if (!variable_global_exists("bsf_ws_toff"))' +
    '    global.bsf_ws_toff = sprite_get_xoffset(global.bsf_ws_spr);' +
    '  sprite_set_offset(global.bsf_ws_spr, global.bsf_ws_toff - dx,' +
    '                    sprite_get_yoffset(global.bsf_ws_spr));' +
    '}' +
    'global.bsf_ws_spr = -1;' +
    'if (instance_exists(GUI_CarTitle)) with (GUI_CarTitle) global.bsf_ws_spr = sprite_index;' +
    'if (global.bsf_ws_spr >= 0) {' +
    '  if (!variable_global_exists("bsf_ws_coff"))' +
    '    global.bsf_ws_coff = sprite_get_xoffset(global.bsf_ws_spr);' +
    '  sprite_set_offset(global.bsf_ws_spr, global.bsf_ws_coff - dx,' +
    '                    sprite_get_yoffset(global.bsf_ws_spr));' +
    '}');

// The light wanders under its own speed/direction, so holding it still is a
// per-frame job -- and it belongs in END Step, because GM applies built-in
// movement after the Step events and before End Step. Pinning it in Step leaves
// it one frame of drift off-centre, which is enough to cull the last mesh column.
object_event_add(w, 3, 2,
    'if (room != rm_MainMenu) exit;' +
    'if (room_width <= 1024) exit;' +
    'with (GUI_Light) { x = room_width / 2; y = room_height / 2; }');

i = instance_create(0, 0, w);
i.persistent = true;
i.depth = -10000003;

// Battleships Forever -- a minimap that shows the room's real shape.
//
// ============================================================ 1. the squash
// The minimap is a GUI_MinimapSize (160) square in the top-right corner, and
// BSF scales the room into it on each axis independently:
//
//     mapsizew = GUI_MinimapSize / room_width       // ctr_GUI, Room Start
//     mapsizeh = GUI_MinimapSize / room_height
//
// so ANY room that is not itself square is drawn distorted -- stretched along
// whichever axis is shorter, by exactly the room's aspect ratio. Every blip
// goes through those two numbers, and so does the white view rectangle, which
// re-derives the same transform inline:
//
//     viewrectx = view_xview[0] / room_width  * GUI_MinimapSize
//     viewrecty = view_yview[0] / room_height * GUI_MinimapSize
//     draw_rectangle(viewrectx, viewrecty,
//         viewrectx + (view_wview[0] - GUI_MinimapSize) / room_width  * GUI_MinimapSize,
//         viewrecty +  view_hview[0]                    / room_height * GUI_MinimapSize, 1)
//
// The map is therefore self-consistent and still wrong about the world, and the
// view rectangle is where that reads as a bug, because it is the one thing on
// the map the player can check against the screen in front of them.
//
// Measured in EP9 (Bolthole), room 5600 x 2000, at 1920x1080 and l_zoom 1: the
// clear battlefield is 1205 x 768 world units -- landscape, 1.57:1 -- and the
// rectangle drawn for it is 34 x 61 map units, PORTRAIT, 0.56:1. Off by 2.80x,
// which is the room's aspect ratio, exactly. The stock skirmish maps are close
// enough to square that this never had to be noticed; a 2.8:1 campaign room
// makes it the first thing you see.
//
// This module gives the map ONE scale for both axes, so a wide room draws as a
// wide strip and the view rectangle is landscape when the view is landscape:
//
//     u  = min(GUI_MinimapSize / room_width, GUI_MinimapSize / room_height)
//     ox = (GUI_MinimapSize - room_width  * u) / 2      // letterbox, centred
//     oy = (GUI_MinimapSize - room_height * u) / 2
//
// On a square room u, ox and oy come out at the stock values and nothing moves.
//
// ============================================== 2. why it redraws everything
// The map is rasterised into ctr_GUI's `l_hudsurf` during its End Step, as one
// action this mod cannot edit -- and `object_event_clear` on ctr_GUI is not an
// option, since that event is also the camera controller, the HUD anchoring and
// what mods/aspect.gml appends to. So the correction is an appended action that
// runs after it, re-targets the same surface, wipes the map box and draws it
// again with the single scale.
//
// Fixing only the view rectangle and leaving the stock blips alone is not
// possible in the other direction either: `mapsizew`/`mapsizeh` ARE writable
// from outside, so the blips can be corrected in place, but the rectangle
// re-derives its transform from room_width/room_height inline and would still
// be drawn at the old aspect, on top of correct blips. One or the other has to
// be redrawn; redrawing wins because it also lets the room be centred, which a
// bare scale factor cannot express -- there is no additive term in `x*mapsizew`.
//
// The cost is a second pass over the blips -- a few dozen draw calls beside the
// thousands the battlefield already issues. It is not in the same class as the
// per-frame work mods/fastdraw.gml exists to remove.
//
// ⚠ The wipe is a REPLACE, `draw_set_blend_mode_ext(bm_one, bm_zero)`, not a
// black rectangle. Stock ends its surface pass by forcing the whole column
// opaque (a bm_src_color/bm_src_alpha mask over spr_EmptyMask), and this action
// runs after that, so a normal blend would compose against an already-opaque
// box and a translucent one would not clear it. Replace writes the pixel
// outright and cannot drift whatever the stock pass left behind.
//
// ⚠ Every name the drawing touches is in the `var` list. A `var` local survives
// into a `with` body; an UNDECLARED one becomes an instance variable on the
// with-target instead, so `xx1` inside `with (ctr_Ship)` would silently be
// written onto the ship. Same trap mods/aspect.gml documents for `d`.
//
// ⚠ `l_hudsurf` is read off the instance, which is legitimate here and is not
// legitimate for `mapx1`/`mapx2`/`mapsize`: those three belong to ctr_GUILow's
// Create, not ctr_GUI's, and an appended action reading them reports "Unknown
// variable mapx1" every frame (see campaign/build.py, which re-derives instead).
// `l_hudsurf` and `mapsizew`/`mapsizeh` are ctr_GUI's own.
//
// ================================================= 3. the view rectangle, late
// The rectangle is drawn from the appended DRAW action rather than into the
// surface with everything else, because the numbers it needs are only final by
// then. ctr_GUI's End Step is not the last word on the camera: mods/aspect.gml
// re-asserts the view width from an instance at depth -10000002 (End Steps run
// high depth first, so it runs last), and a campaign `bounds:` limit clamps
// l_viewx from its own appended End Step. Drawing the rectangle in Draw picks
// all of that up in the same frame instead of trailing it by one, which is what
// stock does.
//
// It is the CLEAR battlefield that gets a rectangle, not the whole view: the
// HUD column covers GUI_MinimapSize * l_zoom of the view's right-hand side and
// the player cannot see the room through it. Stock meant the same thing and
// subtracted a bare GUI_MinimapSize -- true at l_zoom 1 and 60 world units short
// at the zoom-out limit, since the column scales with the zoom and the constant
// does not. That term is `* l_zoom` here.
//
// ================================================== 4. what else reads the map
// The transform is published as globals, because a campaign `bounds:` limit
// draws its own fog rectangle over this map and has to agree with it to the
// pixel. Consumers work in view coordinates:
//
//     mw = GUI_MinimapSize * global.l_zoom
//     bx = view_xview[0] + view_wview[0] - mw ; by = view_yview[0]
//     screen = (bx + (global.bsf_mm_ox + wx * global.bsf_mm_u) * global.l_zoom,
//               by + (global.bsf_mm_oy + wy * global.bsf_mm_u) * global.l_zoom)
//
// `global.bsf_mm` is the flag that says the corrected map is live at all, so a
// consumer can fall back to the stock transform when this module is off.
//
// ============================================================ 5. the low path
// Deliberately untouched. `global.highquality = 0` makes ctr_GUI's Create
// `instance_change(ctr_GUILow, 1)`, and ctr_GUILow -- a child of ctr_GUI --
// carries its OWN End Step and Draw, so it inherits none of these appends and
// keeps stock behaviour end to end. It also draws its map straight to the back
// buffer rather than to a surface, where the box is translucent over the
// battlefield and there is no exact colour to restore it to; a takeover there
// would have to repaint the box opaque and change how the HUD looks. Correcting
// the surface path and leaving the fallback alone is the honest split.

if (variable_global_exists('bsf_mm_init')) exit;
global.bsf_mm_init = 1;
global.bsf_mm = 0;
global.bsf_mm_u = 0;
global.bsf_mm_ox = 0;
global.bsf_mm_oy = 0;

// ------------------------------------------------------- the map, redrawn
object_event_add(ctr_GUI, 3, 2,
    'var mms, mmu, mmox, mmoy, mmw, mmh, k, sh, xx1, yy1;' +
    // ctr_GUILow does not inherit this event, so this is belt-and-braces --
    // and free, next to being wrong about which object owns l_hudsurf.
    'if (object_index != ctr_GUI) exit;' +
    'if (room_width <= 0) exit;' +
    'if (room_height <= 0) exit;' +
    'if (!variable_local_exists("l_hudsurf")) exit;' +
    'if (!surface_exists(l_hudsurf)) exit;' +
    'mms = GUI_MinimapSize;' +
    'mmu = mms / room_width;' +
    'if (mms / room_height < mmu) mmu = mms / room_height;' +
    'mmw = room_width * mmu; mmh = room_height * mmu;' +
    'mmox = (mms - mmw) / 2; mmoy = (mms - mmh) / 2;' +
    'global.bsf_mm = 1; global.bsf_mm_u = mmu;' +
    'global.bsf_mm_ox = mmox; global.bsf_mm_oy = mmoy;' +
    'surface_set_target(l_hudsurf);' +
    // ---- wipe. Replace-blend, so the box is exactly opaque black whatever the
    // stock pass and its alpha mask left in it. See the ⚠ in the header.
    'draw_set_blend_mode_ext(bm_one, bm_zero);' +
    'draw_set_color(c_black); draw_set_alpha(1);' +
    'draw_rectangle(0, 0, mms, mms, 0);' +
    'draw_set_blend_mode(bm_normal);' +
    // ---- the box, in the map's own green, exactly where stock draws it.
    'draw_set_color($00FF00);' +
    'draw_rectangle(0, 0, mms, mms, 1);' +
    // ---- the room inside it, dimmer, so the letterbox bands read as "not room"
    // rather than as an empty map. Suppressed when the room fills the box.
    'if (mmox + mmoy > 0.5) {' +
    '  draw_set_color($008800);' +
    '  draw_rectangle(mmox, mmoy, mmox + mmw, mmoy + mmh, 1);' +
    '}' +
    // ---- the blips, in stock order so the same things end up on top.
    'draw_set_color(c_dkgray);' +
    'with (ctr_Obstructions) draw_point(mmox + x * mmu, mmoy + y * mmu);' +
    'with (ctr_EShip) {' +
    '  draw_set_color(l_colour);' +
    '  xx1 = mmox + x * mmu; yy1 = mmoy + y * mmu;' +
    '  draw_rectangle(xx1 - 1, yy1 - 1, xx1 + 1, yy1 + 1, 0);' +
    '}' +
    'with (ctr_Ship) {' +
    '  draw_set_color(l_colour);' +
    '  xx1 = mmox + x * mmu; yy1 = mmoy + y * mmu;' +
    '  draw_rectangle(xx1 - 1, yy1 - 1, xx1 + 1, yy1 + 1, 0);' +
    '}' +
    'with (SFX_Jumper) {' +
    '  draw_set_color($00FFFF);' +
    '  draw_circle(mmox + x * mmu, mmoy + y * mmu, 2, 1);' +
    '}' +
    'with (ctr_Powerups) {' +
    '  draw_set_color($00FFFF);' +
    '  xx1 = mmox + x * mmu; yy1 = mmoy + y * mmu;' +
    '  draw_line(xx1 - 1, yy1, xx1 + 1, yy1);' +
    '  draw_line(xx1, yy1 - 1, xx1, yy1 + 1);' +
    '}' +
    'draw_set_color($FFFFFF);' +
    'for (k = 0; k < l_numselected; k += 1) {' +
    '  sh = global.selected[k];' +
    '  if (!instance_exists(sh)) continue;' +
    '  xx1 = mmox + sh.x * mmu; yy1 = mmoy + sh.y * mmu;' +
    '  draw_rectangle(xx1 - 1, yy1 - 1, xx1 + 1, yy1 + 1, 0);' +
    '}' +
    // ⚠ The ping is redrawn, never re-performed. Its own user event is what
    // animates it -- `l_rad += 1` at the end -- and stock already ran it this
    // frame, into the pixels the wipe above just replaced. Calling it again
    // would advance the ring twice as fast and halve the ping's life.
    'with (GUI_MapPing) {' +
    '  draw_set_color($00FFFF);' +
    '  xx1 = mmox + x * mmu; yy1 = mmoy + y * mmu;' +
    '  draw_circle(xx1, yy1, 3, 1);' +
    '  draw_circle(xx1, yy1, l_rad, 1);' +
    '}' +
    'with (GUI_AttackArrow) {' +
    '  if (instance_exists(l_target)) {' +
    '    draw_set_color(l_colour);' +
    '    draw_circle(mmox + l_target.x * mmu, mmoy + l_target.y * mmu, 3, 1);' +
    '  }' +
    '}' +
    'with (GUI_ExclaimArrow) {' +
    '  draw_set_color(l_colour);' +
    '  draw_circle(mmox + l_tarx * mmu, mmoy + l_tary * mmu, 3, 1);' +
    '}' +
    'with (GUI_MoveToArrow) {' +
    '  draw_set_color(l_colour);' +
    '  draw_circle(mmox + l_tarx * mmu, mmoy + l_tary * mmu, 3, 1);' +
    '}' +
    'surface_reset_target();' +
    'draw_set_color(c_white); draw_set_alpha(1);');

// ------------------------------------------------- the view rectangle, in Draw
object_event_add(ctr_GUI, 8, 0,
    'var mms, mmu, mmox, mmoy, z, bx, by, vx1, vy1, vx2, vy2;' +
    'if (object_index != ctr_GUI) exit;' +
    'if (global.bsf_mm != 1) exit;' +
    'if (room_width <= 0) exit;' +
    'if (room_height <= 0) exit;' +
    'mms = GUI_MinimapSize;' +
    'z = global.l_zoom;' +
    'mmu = global.bsf_mm_u; mmox = global.bsf_mm_ox; mmoy = global.bsf_mm_oy;' +
    // The surface is blitted at the view's top-right corner, at l_zoom, so a
    // surface pixel p sits at bx + p*z. Same origin the map itself uses.
    'bx = view_xview[0] + view_wview[0] - mms * z;' +
    'by = view_yview[0];' +
    // The clear battlefield -- the HUD column is not room the player can see.
    'vx1 = view_xview[0]; vx2 = vx1 + view_wview[0] - mms * z;' +
    'vy1 = view_yview[0]; vy2 = vy1 + view_hview[0];' +
    // A room smaller than the view, or a frame of screen shake, can push the
    // view past the room; the rectangle is what is visible OF THE ROOM.
    'if (vx1 < 0) vx1 = 0;' +
    'if (vy1 < 0) vy1 = 0;' +
    'if (vx2 > room_width) vx2 = room_width;' +
    'if (vy2 > room_height) vy2 = room_height;' +
    'if (vx2 <= vx1) exit;' +
    'if (vy2 <= vy1) exit;' +
    'draw_set_color(c_white); draw_set_alpha(1);' +
    'draw_rectangle(bx + (mmox + vx1 * mmu) * z, by + (mmoy + vy1 * mmu) * z,' +
    '               bx + (mmox + vx2 * mmu) * z, by + (mmoy + vy2 * mmu) * z, 1);');

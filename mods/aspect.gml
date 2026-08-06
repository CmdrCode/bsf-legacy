// Battleships Forever -- widescreen camera: correct aspect, and a zoom that
// actually holds the point under the cursor.
//
// =========================================================== 1. the stretch
// resolution.gml widens each room's AUTHORED view to the display aspect, which
// is correct and holds in menus, the sandbox and any static screen. It does not
// survive gameplay: BSF's zoom controller assigns
//
//     view_wview[0] = 1024 * l_zoom
//     view_hview[0] =  768 * l_zoom
//
// in its Step event, hardcoding 4:3. The moment the player zooms -- mouse wheel,
// which in this game is constant -- the widened view is slammed back to 4:3
// while the port stays 16:9, and everything on screen stretches horizontally by
// 4:3 / 16:9 = 1.3333x. Measured on a 300x300 world-unit square at 3840x2160:
// 1124 x 844 device pixels, a 1.3318x stretch. Ships look fat.
//
// This is easy to miss, because a screen that never zooms looks perfect: the
// same square measured 844 x 844 in the sandbox before any zoom happened.
//
// End Step (event type 3, subtype 2) runs after EVERY normal Step -- including
// the zoom controller's -- and before any Draw, so re-asserting the width there
// is the last word and nothing incorrect is ever rasterised. Patching the four
// GML sites in the resource tree would also work (1024 and 1365 are both four
// characters, so it is a same-length edit) but it would bake in one aspect
// ratio, and the whole point of resolution.gml is that the player picks.
//
// =========================================================== 2. the drift
// Widening alone fixes the stretch and introduces something worse, because the
// zoom controller does not merely WRITE the view -- it READS it back into its
// own state. Its recentre-while-zooming step is
//
//     xx = viewcentre_x()                 // reads view_xview[0] and view_wview[0]
//     view_wview[0] = 1024 * l_zoom       // narrows
//     l_viewx += xx - viewcentre_x()      // reads them again
//
// and viewcentre_x() -- a SCRIPT resource, so tokenised in the exe with no
// source to read; recovered by measuring it live -- is
//
//     view_xview[0] + (view_wview[0] - GUI_MinimapSize * l_zoom) / 2
//     view_yview[0] +  view_hview[0] / 2
//
// The two calls straddle the width change, so the widening does not cancel
// between them and lands in l_viewx as real camera displacement -- every frame
// the zoom is in flight. The error per frame works out to exactly
// (want - 1024*l_zoom)/2, ~170*l_zoom px at 16:9 and 0 at 4:3. Measured at
// 1920x1080, one zoom from l_zoom 1.0 to 0.5 (13 frames):
//
//     frame   l_zoom   error   l_viewx   d(l_viewx)   predicted
//      1042    0.96    163.5    577.58        -            -
//      1043    0.92    157.5    747.22     169.64       166.40
//      1044    0.88    150.4    911.47     164.25       161.00
//      ...                                (then pinned to the right-edge clamp)
//      1054    0.50     85.5   1616.00
//
// The camera slid 0 -> 1616 px across a 2048 px room during a single zoom-out.
//
// y is unaffected: viewcentre_y() has no minimap term and nothing here changes
// view_yview, so its two calls cancel. The bug is horizontal-only, which is
// exactly how it reads in play.
//
// ==================================================== 3. why left-aligned
// Splitting the extra width evenly (view_xview[0] = l_viewx - halfdelta) looks
// like the obvious presentation choice and is wrong, because BSF reads l_viewx
// as the view's true left edge in code this mod cannot patch:
//
//   edge scrolling   mouse_x > l_viewx + view_wview[0] - World_ScrollBorder
//   room clamp       l_viewx > room_width - view_wview[0] + GUI_MinimapSize*l_zoom
//   minimap click    l_viewx = T - (view_wview[0] - GUI_MinimapSize*l_zoom)/2
//
// All three use the REAL view_wview[0], so all three are exact as long as
// view_xview[0] == l_viewx, and all three are off by the half-delta if it is
// not: right-edge scrolling stops triggering, and clicking the minimap centres
// ~170 px left of where you clicked. Keeping the view left-aligned also removes
// the regime change -- an offset that appeared only while the controller was
// narrowing the view produced an 11%-of-screen sideways snap at both ends of
// every zoom -- and stops the map edge revealing void.
//
// So: l_viewx stays the left edge, the extra width extends right, and the only
// thing corrected is the zoom controller's own 4:3 arithmetic.
//
// ============================================= 4. zoom-to-cursor, exactly
// With the drift gone, what is left is BSF's own contextual zoom, which is an
// approximation rather than an anchor: it eases the view centre 1/20 of the way
// toward the cursor per frame. Over a 13-frame zoom that closes (19/20)^13 =
// 51.3% of the gap where holding the cursor's world point needs exactly 50%, so
// the point under the cursor always slides. It is not a widescreen bug -- it is
// stock, and measurable at 4:3 too (8.4% of the view width, against 8.8% at
// 16:9) -- but it is a real one, so this fixes it rather than reproducing it.
//
// Begin Step records where the cursor is as a fraction of the view and what
// world point sits under it; End Step, after the zoom has been applied and the
// view re-widened, solves for the l_viewx that puts that world point back under
// that fraction. The cursor's world position is then invariant across the zoom
// by construction, at any resolution and any aspect. When a mission turns
// contextual zoom off (global.contextzoom = 0) only the drift fix runs, so the
// camera holds its centre, which is what stock does.
//
// Begin Step is the right place for the snapshot because GM runs every Begin
// Step before any Step, so it is guaranteed to be pre-controller no matter how
// the instances are ordered.
//
// Detecting "the recentre ran" is exact rather than heuristic: every branch
// inside that block assigns l_zoom and the block is guarded by
// l_zoom != l_zoomtar, so it ran if and only if l_zoom changed across the Step.

if (variable_global_exists('bsf_aspect_init')) exit;
global.bsf_aspect_init = 1;

var a, i;
a = object_add();

object_event_add(a, 0, 0,
    'prevzoom = -1;' +   // l_zoom as it stood before the controller's Step
    'afx = 0.5; afy = 0.5;' +
    'anchorx = 0; anchory = 0;');

object_event_add(a, 3, 1,
    'prevzoom = -1;' +
    'if (!instance_exists(ctr_GUI)) exit;' +
    'if (view_wview[0] <= 0 || view_hview[0] <= 0) exit;' +
    'prevzoom = ctr_GUI.l_zoom;' +
    'var mmf;' +
    // Cursor position as a fraction of the view that is currently on screen.
    'afx = (mouse_x - view_xview[0]) / view_wview[0];' +
    'afy = (mouse_y - view_yview[0]) / view_hview[0];' +
    'if (afx < 0) afx = 0;' +
    'if (afx > 1) afx = 1;' +
    'if (afy < 0) afy = 0;' +
    'if (afy > 1) afy = 1;' +
    // Don't anchor on the minimap strip; a cursor parked there would haul the
    // camera to the map's right edge on every notch.
    'mmf = GUI_MinimapSize * ctr_GUI.l_zoom / view_wview[0];' +
    'if (afx > 1 - mmf) afx = 1 - mmf;' +
    // Re-derived from the clamped fraction, so anchor and fraction always agree.
    'anchorx = view_xview[0] + afx * view_wview[0];' +
    'anchory = view_yview[0] + afy * view_hview[0];');

object_event_add(a, 3, 2,
    // `d` MUST be in this list. An undeclared name becomes an instance variable,
    // and inside `with (ctr_Icon)` that resolves against the icon, not this
    // object -- "Unknown variable d" every frame. `var` locals survive `with`.
    'var want, narrow, rw, rh, z, lvx0, lvy0, hi, d, dx, dy;' +
    'rw = window_get_region_width(); rh = window_get_region_height();' +
    'if (!view_visible[0] || rh <= 0 || view_hview[0] <= 0) exit;' +
    'want   = round(view_hview[0] * rw / rh);' +
    'narrow = round(view_hview[0] * 1024 / 768);' +
    // ---- the stretch fix. Gated on ctr_GUI, and the order matters: the only
    // thing that narrows the view is ctr_GUI's own zoom controller, so a room
    // without one needs no correction -- and asserting a width there would stomp
    // a room that drives its own view. rm_ChooseShips does exactly that (opens
    // at 3712, steps down 128 a frame to exactly 1024), and forcing the width
    // killed the animation and froze it mid-stretch. Such rooms belong in
    // resolution.gml's narrow list instead, so their port matches the view they
    // settle on. On a 4:3 display want equals narrow and this is a no-op --
    // deliberately not skipped, because the zoom-to-cursor fix is wanted at 4:3.
    'if (!instance_exists(ctr_GUI)) exit;' +
    'view_wview[0] = want;' +
    // ---- re-anchor the HUD. ctr_GUI repositions every clickable HUD instance
    // as `x = view_xview[0] + offsetx * global.l_zoom` -- LEFT-anchored off the
    // creation x, which for all of them is a literal expressed against a
    // 1024-wide view (864/914/964 for the command icons, 1008 for the exit
    // button, 614..862 for the sandbox toolbar). The HUD column they belong to
    // is drawn RIGHT-anchored at view_xview[0]+view_wview[0]-GUI_MinimapSize*z,
    // so the two agree only at 4:3 and are (want - narrow) = 341*l_zoom apart at
    // 16:9 -- the whole HUD detaches and floats over the battlefield, hitboxes
    // with it. Adding the delta turns the formula into the right-anchored
    // equivalent, x = view_xview[0] + view_wview[0] - (1024 - offsetx)*l_zoom,
    // which is identical to stock at 4:3. Idempotent: ctr_GUI rewrites x from
    // offsetx every Step, which is also why this must be inside the ctr_GUI
    // guard and must run every frame, not only while zooming. Applied at the end
    // of this event -- see the HUD block below.
    'd = want - narrow;' +
    'lvx0 = ctr_GUI.l_viewx; lvy0 = ctr_GUI.l_viewy;' +
    'z = ctr_GUI.l_zoom;' +
    'if (prevzoom >= 0) {' +
    ' if (z != prevzoom) {' +          // the recentre ran this Step
    // ---- undo the 4:3 assumption baked into the recentre.
    'ctr_GUI.l_viewx -= (want - narrow) / 2;' +
    // ---- put the cursor's world point back under the cursor.
    'if (variable_global_exists("contextzoom")) {' +
    ' if (global.contextzoom == 1) {' +
    '  ctr_GUI.l_viewx = anchorx - afx * want;' +
    '  ctr_GUI.l_viewy = anchory - afy * view_hview[0];' +
    ' }' +
    '}' +
    // ---- re-clamp: BSF clamped against the narrow width, and the anchor solve
    // ignores clamps entirely, so neither has kept the view inside the room.
    'hi = room_width + GUI_MinimapSize * z - want;' +
    'if (hi < 0) hi = 0;' +
    'if (ctr_GUI.l_viewx > hi) ctr_GUI.l_viewx = hi;' +
    'if (ctr_GUI.l_viewx < 0) ctr_GUI.l_viewx = 0;' +
    'hi = room_height - view_hview[0];' +
    'if (hi < 0) hi = 0;' +
    'if (ctr_GUI.l_viewy > hi) ctr_GUI.l_viewy = hi;' +
    'if (ctr_GUI.l_viewy < 0) ctr_GUI.l_viewy = 0;' +
    // ---- publish as a delta, not an assignment: view_xview[0] also carries
    // this frame's screen-shake offset and that has to survive.
    'view_xview[0] += ctr_GUI.l_viewx - lvx0;' +
    'view_yview[0] += ctr_GUI.l_viewy - lvy0;' +
    ' }' +
    '}' +
    // ---- HUD, last, because it has to absorb this frame's camera correction as
    // well as the re-anchor. ctr_GUI positioned every icon during its Step, from
    // the l_viewx that was current THEN; the zoom fix above has since moved the
    // camera, so without the (l_viewx - lvx0) term the whole HUD lags the view by
    // one frame for the ~13 frames a zoom is in flight and then snaps into place.
    // `d` is the re-anchor and applies only to right-anchored icons; `dx`/`dy`
    // are this frame's camera correction and apply to all of them.
    'dx = ctr_GUI.l_viewx - lvx0;' +
    'dy = ctr_GUI.l_viewy - lvy0;' +
    'if (d != 0 || dx != 0 || dy != 0) {' +
    ' with (ctr_Icon)         { if (offsetx >= 512) x += d; x += dx; y += dy; }' +
    ' with (ctr_TestRoomIcon) { if (offsetx >= 512) x += d; x += dx; y += dy; }' +
    ' with (GUI_ExitIcon)     { if (offsetx >= 512) x += d; x += dx; y += dy; }' +
    ' with (GUI_CloseMenu)    { if (offsetx >= 512) x += d; x += dx; y += dy; }' +
    '}');

i = instance_create(0, 0, a);
i.persistent = true;
i.depth = -10000002;

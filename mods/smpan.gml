// ShipMaker -- middle-mouse drag pan.
//
// Stock ShipMaker's only middle-button binding is obj_sidebar's global middle
// RELEASE event (the whole editor has no other): it recentres the canvas view
// on the click point -- a teleport, not a pan. This module replaces it with
// the standard drag pan: hold the middle button and the canvas follows the
// cursor from where you grabbed it.
//
// -------------------------------------------------------------------- how
// A controller object watches the middle button in its Step event and scrolls
// view1 (the ship canvas) by the cursor's device-pixel delta each frame.
// The cursor is read with window_mouse_get_x/y -- window coordinates, so the
// arithmetic never feeds back through the view it is moving (mouse_x would);
// stock uses the same calls for its frame capture. A window pixel converts to
// world units via l_zoom (view1's world-units-per-port-pixel), times
// region/client when the two differ -- that is GM's stock stretch mode, which
// only happens with smres off or below its 1016x704 floor; with the 1:1
// region they cancel exactly. The client size comes through the editor's own
// WinAPI wrapper, gated the same way smres.gml gates it (value test, not
// existence -- see mods/sm.gml on "uninitialized = 0"). Clamps mirror the
// stock wheel zoom's (160 / 6144-wview / 15 / room_height-hview).
//
// The stock teleport cannot be removed -- object_event_add only appends -- so
// it is undone instead: the controller snapshots view1's position every Step,
// and code appended AFTER the stock action in the same release event restores
// the snapshot. Net effect: middle release does nothing. global.smpan_have
// gates the restore; it is (re)zeroed by any game_restart ("New ship" wipes
// every global), so a release can never restore a stale snapshot before the
// reinstalled controller's first Step.

var inited;
inited = 0;
if (variable_global_exists('bsf_smpan_init'))
    if (global.bsf_smpan_init)
        inited = 1;
if (inited) exit;
global.bsf_smpan_init = 1;

global.smpan_have = 0;

var m, i;
m = object_add();

object_event_add(m, 0, 0,
    'panning = 0; lx = 0; ly = 0;');

object_event_add(m, 3, 0,
    'if (!instance_exists(obj_sidebar)) exit;' +

    'if (mouse_check_button_pressed(mb_middle)) {' +
    '  panning = 1;' +
    '  lx = window_mouse_get_x();' +
    '  ly = window_mouse_get_y();' +
    '}' +
    'if (!mouse_check_button(mb_middle)) panning = 0;' +

    'if (panning) {' +
    '  var wx, wy, z, sx, sy, rdy, cw, ch;' +
    '  wx = window_mouse_get_x();' +
    '  wy = window_mouse_get_y();' +
    '  z = obj_sidebar.l_zoom;' +
    '  sx = 1; sy = 1;' +
    '  rdy = 0;' +
    '  if (variable_global_exists("external_api_window_getclientwidth"))' +
    '    if (global.external_api_window_getclientwidth != 0)' +
    '      rdy = 1;' +
    '  if (rdy) {' +
    '    cw = API_Window_GetClientWidth(window_handle());' +
    '    ch = API_Window_GetClientHeight(window_handle());' +
    '    if (cw > 0 && ch > 0) {' +
    '      sx = window_get_region_width() / cw;' +
    '      sy = window_get_region_height() / ch;' +
    '    }' +
    '  }' +
    // Content follows the cursor: mouse right = camera left.
    '  view_xview[1] -= (wx - lx) * z * sx;' +
    '  view_yview[1] -= (wy - ly) * z * sy;' +
    '  lx = wx; ly = wy;' +
    '  if (view_xview[1] < 160) view_xview[1] = 160;' +
    '  else if (view_xview[1] > 6144 - view_wview[1]) view_xview[1] = 6144 - view_wview[1];' +
    '  if (view_yview[1] < 15) view_yview[1] = 15;' +
    '  else if (view_yview[1] > room_height - view_hview[1]) view_yview[1] = room_height - view_hview[1];' +
    '}' +

    'global.smpan_vx = view_xview[1];' +
    'global.smpan_vy = view_yview[1];' +
    'global.smpan_have = 1;');

// The undo of the stock centre-on-click, appended after it in the same event.
object_event_add(obj_sidebar, 6, 58,
    'if (global.smpan_have) {' +
    '  view_xview[1] = global.smpan_vx;' +
    '  view_yview[1] = global.smpan_vy;' +
    '}');

i = instance_create(0, 0, m);
i.persistent = true;
i.depth = -10000000;

// ShipMaker -- zoom readout, canvas bottom-right.
//
// The wheel zooms the canvas (obj_sidebar.l_zoom, 0.2..2.4 in 0.1 steps) but
// nothing shows the current level. This draws it as a percentage: l_zoom is
// world-units-per-pixel, so 100/l_zoom is the familiar figure -- 100% at 1:1,
// 500% at full magnification.
//
// Drawn the way the editor draws its own canvas overlays (see gui_hinter):
// during view1's pass, positioned off view1's edges, every size multiplied by
// l_zoom and the text through draw_text_transformed -- the view scales world
// units back down by 1/l_zoom, so it lands on screen at 1:1 regardless of
// zoom. view0 would be the natural home for chrome, but its port is painted
// over by the canvas view's pass (the sidebar only survives because view1's
// port starts at x=160). Hidden in hide-GUI (F12 is the screenshot mode),
// preview, and group-arrange, matching smres.gml's stand-down list.

var inited;
inited = 0;
if (variable_global_exists('bsf_smzoom_init'))
    if (global.bsf_smzoom_init)
        inited = 1;
if (inited) exit;
global.bsf_smzoom_init = 1;

var m, i;
m = object_add();

object_event_add(m, 8, 0,
    'if (view_current != 1) exit;' +
    'if (!instance_exists(obj_sidebar)) exit;' +
    'if (global.hidegui || global.grouparrange) exit;' +
    'var pv;' +
    'pv = 0;' +
    'if (variable_global_exists("preview")) pv = global.preview;' +
    'if (pv) exit;' +

    'var z, s, sw, sh, x2, y2;' +
    'z = obj_sidebar.l_zoom;' +
    'if (z <= 0) exit;' +
    'draw_set_font(fnt_smalltext);' +
    's = string(round(100 / z)) + "%";' +
    'sw = string_width(s) * z;' +
    'sh = string_height(s) * z;' +
    'x2 = view_xview[1] + view_wview[1] - 6 * z;' +
    'y2 = view_yview[1] + view_hview[1] - 6 * z;' +
    'draw_set_alpha(0.5);' +
    'draw_set_color(c_black);' +
    'draw_rectangle(x2 - sw - 8 * z, y2 - sh - 4 * z, x2, y2, 0);' +
    'draw_set_alpha(1);' +
    'draw_set_color(c_white);' +
    'draw_text_transformed(x2 - sw - 4 * z, y2 - sh - 2 * z, s, z, z, 0);');

i = instance_create(0, 0, m);
i.persistent = true;
i.depth = -10000000;

// Title-screen "LEGACY!" splash -- the Minecraft-style tag on the logo's corner.
//
// GUI_MainTitle OWNS its Draw event (8:0), so object_event_add APPENDS and the
// stock body still runs: the logo is drawn first and this lands on top. Adding a
// Draw to an object that merely INHERITED one would shadow the parent's and blank
// the logo entirely.
//
// Geometry is measured from the sprite at draw time rather than hardcoded, so the
// widescreen mod's re-centring and any resolution change carry through. At
// 1365x768 the logo box is 358,38 .. 1008,163.
//
// Placement was settled by measurement, not eye: dilating the FOREVER-orange mask
// and counting tag pixels inside it gives 0 contact at 0.98*lh, 663 at 0.80, 789
// at 0.78 and 891 at 0.76 -- and at 0.76 the R stopped being readable and the
// title read "FOREVE". 0.78 sits just under that, so the tag clips the R's
// lower-right corner while the word survives.
//
// The two bm_zero passes are the logo's own drop-shadow recipe (bm_zero ZEROES
// the destination, punching a dark silhouette rather than compositing a grey
// one). They are load-bearing here: the tag sits over the animated background
// battle, and without the dark plate underneath it washes out whenever a beam or
// a ship drifts behind it.
//
// Remove mods/legacy.on to disable.

object_event_add(GUI_MainTitle, 8, 0,
    'var lx, ly, lw, lh, st, sc5, ang, sx5, sy5, pass5, o5, a5;' +
    'lw = sprite_get_width(sprite_index) * image_xscale;' +
    'lh = sprite_get_height(sprite_index) * image_yscale;' +
    'lx = x - sprite_get_xoffset(sprite_index) * image_xscale;' +
    'ly = y - sprite_get_yoffset(sprite_index) * image_yscale;' +

    // Minecraft pulses ~10% on a ~1 Hz sine. current_time is one of the few
    // builtins that is genuinely cheap under wine (0.24 us); mouse_x is 176.
    'sc5 = 0.68 * (1 + 0.06 * abs(sin((current_time / 1000) * 3.14159)));' +
    'ang = 20;' +
    // Shifted left by 5% of the view width rather than a fixed pixel count.
    'sx5 = lx + 0.845 * lw - 0.05 * view_wview[0];' +
    'sy5 = ly + 0.78 * lh;' +

    'st = "LEGACY!";' +
    'draw_set_font(MainMenuFont);' +
    'draw_set_halign(fa_center); draw_set_valign(fa_middle);' +
    'for (pass5 = 0; pass5 < 3; pass5 += 1) {' +
    ' if (pass5 == 0) { o5 = 8; a5 = 0.12; draw_set_blend_mode(bm_zero); }' +
    ' if (pass5 == 1) { o5 = 4; a5 = 0.22; draw_set_blend_mode(bm_zero); }' +
    ' if (pass5 == 2) { o5 = 0; a5 = 1.00; draw_set_blend_mode(bm_normal); }' +
    ' draw_set_alpha(a5);' +
    // BGR, not RGB -- this is #40F0F0. Written RGB-wise it comes out orange.
    ' draw_set_color($F0F040);' +
    ' draw_text_transformed(sx5 + o5, sy5 + o5, st, sc5, sc5, ang);' +
    '}' +
    'draw_set_blend_mode(bm_normal); draw_set_alpha(1);' +
    'draw_set_halign(fa_left); draw_set_valign(fa_top);');

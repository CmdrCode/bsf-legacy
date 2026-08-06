// Title logo as drawn text over a Gaussian-blurred copy of itself.
//
// ------------------------------------------------------------------- why
// The logo is a 650x125 bitmap shown at ~1827x351 (view 1365x768 in a 3840x2160
// port = 2.81x magnification). ~50% of its letterform pixels are intermediate
// values -- invented by the filter. MainMenuFont is the SAME typeface the logo
// art was set in, so the words can be drawn instead of blitted.
//
// ------------------------------------------------------- why not a shader
// The HWVP patch changed vertex processing, not shader capability, and GM 7.0's
// GML has no shader API at any DirectX version -- shaders arrived with GameMaker:
// Studio. The blur is therefore done by hand, with surface passes.
//
// ------------------------------------------------------------------- how
// A true separable Gaussian, computed ONCE at load:
//   sa = the two words drawn as text on transparent
//   sb = sa blurred horizontally   (2R+1 weighted taps)
//   sc = sb blurred vertically     (2R+1 weighted taps)
// Separating the 2D kernel makes it 2*(2R+1) taps instead of (2R+1)^2 -- 66
// instead of 1089 at R=16 -- and since the logo never changes, the cost is paid
// once at startup, not per frame. Each frame draws sc underneath and the crisp
// glyphs on top: one blurred layer, not a stack of expanded copies.
//
// Two earlier attempts are recorded because both look plausible and are wrong:
//   * additively re-drawing the TEXT at 1.05x/1.13x/1.26x -- a scaled copy of a
//     word is a bigger SHARP word, so it reads as a ghosted second logo;
//   * magnifying a quarter-scale raster -- that IS a blur, but a box-ish one, and
//     at 168px wide a glyph stroke is ~2 pixels, so the halo came out as soft
//     rectangles rather than following the letterforms.
//
// Blending, and this is the whole difficulty. Every pass uses
// draw_set_blend_mode_ext(bm_one, bm_one), and each tap's WEIGHT is carried in
// the COLOUR argument as a grey, not in the alpha argument:
//   * bm_one/bm_one does not modulate RGB by the vertex alpha, so passing the
//     weight as alpha adds every tap at FULL strength -- 33 taps saturate and the
//     logo comes back as solid white and yellow blocks;
//   * plain bm_add (SRCALPHA/ONE) does modulate by alpha, but it modulates by the
//     SURFACE's alpha too, and the alpha channel accumulates wrongly across the
//     first pass, so the second pass reads a corrupted weight;
//   * the colour argument multiplies the texture RGB, which is exactly a weight.
// sa is cleared with draw_clear_alpha(c_black, 0), so its transparent pixels are
// RGB 0 and contribute nothing, and its edge pixels are already premultiplied.
// 8-bit quantisation of the weights costs ~1% on the summed kernel -- the peak
// weight is only 17/255, but the per-tap rounding errors are independent and
// partly cancel over 33 taps.
//
// ----------------------------------------------------------------- the trap
// Every surface is built HERE, at load, and never inside the Draw event.
// surface_reset_target() restores a default projection that discards this build's
// window_set_region_scale port mapping, so doing it mid-Draw corrupts the
// projection for everything drawn afterwards -- the logo, every menu button and
// the credit line all collapsed into the top-left corner at about quarter size.
// The symptom looks like a layout bug and has nothing to do with layout.
//
// If the device ever drops the surface the frame falls back to additive ring
// taps, which need no surface and cannot touch the render target.
//
// -------------------------------------------------------------- metrics
// Measured off a rendered frame, core ink only (glow spill excluded):
//   BATTLESHIPS  x 417..936  w 519  cy 72.8   #6FFE27
//   FOREVER      x 513..840  w 327  cy 125.8  #F35400
// Both are the same 39-unit cap height on the same centre x=676.5, and the
// per-character advance agrees to 1% (47.2 vs 46.7), so one scale serves both.
// Scale is derived from WIDTH: the font being the logo's own typeface means the
// height comes out right by itself. Colours are BGR in GM -- written RGB-wise
// the green comes out blue.
//
// MUST be chained BEFORE legacy.gml: this CLEARS GUI_MainTitle's Draw, and
// object_event_clear would take the appended LEGACY splash with it.
//
// Remove mods/logo.on to disable.

global.logo_bx = 358;   global.logo_by = 38;
global.logo_bw = 650;   global.logo_bh = 125;
global.logo_surf = -1;
global.logo_cansurf = 0;
// Glow strength of the blurred layer, applied as a grey colour multiplier.
global.logo_glow = 200;

// ---- build the blurred layer, once ----------------------------------------
// Straight-line so a missing surface function aborts THIS file at the failing
// call rather than silently emptying the Draw event.
var SW, SH, R, SIG, sa, sb, sc, wt, sum, k, i;
SW = global.logo_bw;  SH = global.logo_bh;   // 1:1 with room units
R  = 16;              SIG = 6;

// ---- the logo table, measured once ----------------------------------------
// All three draw paths below read these: the surface build, the no-surface ring
// fallback, and the words themselves. One place to change a colour or a metric,
// and string_width -- a full text measure -- is paid here at load instead of
// twice per frame in GUI_MainTitle's Draw.
global.logo_cx = 676.5;
draw_set_font(MainMenuFont);
global.logo_str[0] = 'BATTLESHIPS'; global.logo_cy[0] = 72.8;
global.logo_w[0]   = 519;           global.logo_col[0] = $27FE6F;
global.logo_str[1] = 'FOREVER';     global.logo_cy[1] = 125.8;
global.logo_w[1]   = 327;           global.logo_col[1] = $0054F3;
for (i = 0; i < 2; i += 1)
    global.logo_sc[i] = global.logo_w[i] / string_width(global.logo_str[i]);

sa = surface_create(SW, SH);
sb = surface_create(SW, SH);
sc = surface_create(SW, SH);

if (surface_exists(sa) && surface_exists(sb) && surface_exists(sc)) {

    // Gaussian weights, normalised so the taps sum to exactly 1 and the blur
    // neither brightens nor dims the layer.
    sum = 0;
    for (k = -R; k <= R; k += 1) {
        wt[k + R] = exp(-(k * k) / (2 * SIG * SIG));
        sum += wt[k + R];
    }
    for (k = 0; k <= 2 * R; k += 1) wt[k] = wt[k] / sum;

    // --- sa: the words, on transparent, in surface-local coordinates ---------
    surface_set_target(sa);
    draw_clear_alpha(c_black, 0);
    draw_set_blend_mode(bm_normal);
    draw_set_font(MainMenuFont);
    draw_set_halign(fa_center);
    draw_set_valign(fa_middle);
    draw_set_alpha(1);
    for (i = 0; i < 2; i += 1) {
        draw_set_color(global.logo_col[i]);
        draw_text_transformed(global.logo_cx - global.logo_bx,
            global.logo_cy[i] - global.logo_by,
            global.logo_str[i], global.logo_sc[i], global.logo_sc[i], 0);
    }
    surface_reset_target();

    // --- sb: horizontal pass -------------------------------------------------
    surface_set_target(sb);
    draw_clear_alpha(c_black, 0);
    draw_set_blend_mode_ext(bm_one, bm_one);
    for (k = -R; k <= R; k += 1) {
        i = round(wt[k + R] * 255);
        if (i > 0) draw_surface_ext(sa, k, 0, 1, 1, 0, make_colour_rgb(i, i, i), 1);
    }
    draw_set_blend_mode(bm_normal);
    surface_reset_target();

    // --- sc: vertical pass ---------------------------------------------------
    surface_set_target(sc);
    draw_clear_alpha(c_black, 0);
    draw_set_blend_mode_ext(bm_one, bm_one);
    for (k = -R; k <= R; k += 1) {
        i = round(wt[k + R] * 255);
        if (i > 0) draw_surface_ext(sb, 0, k, 1, 1, 0, make_colour_rgb(i, i, i), 1);
    }
    draw_set_blend_mode(bm_normal);
    surface_reset_target();

    draw_set_halign(fa_left);
    draw_set_valign(fa_top);
    draw_set_alpha(1);

    surface_free(sa);
    surface_free(sb);
    global.logo_surf = sc;
    global.logo_cansurf = 1;
}

object_event_clear(GUI_MainTitle, 8, 0);
object_event_add(GUI_MainTitle, 8, 0,
    'var i, sc, pass, rr, a, ring, ang, ok;' +
    'draw_set_font(MainMenuFont);' +
    'draw_set_halign(fa_center); draw_set_valign(fa_middle);' +

    'ok = 0;' +
    'if (global.logo_cansurf) { if (surface_exists(global.logo_surf)) ok = 1; }' +

    // ---- the blurred layer, underneath ---------------------------------------
    'if (ok) {' +
    ' draw_set_blend_mode_ext(bm_one, bm_one);' +
    ' draw_surface_ext(global.logo_surf, global.logo_bx, global.logo_by, 1, 1, 0,' +
    '  make_colour_rgb(global.logo_glow, global.logo_glow, global.logo_glow), 1);' +
    ' draw_set_blend_mode(bm_normal);' +
    '} else {' +
    // No surface: additive ring taps. Never touches the render target.
    ' draw_set_blend_mode(bm_add);' +
    ' for (i = 0; i < 2; i += 1) {' +
    '  sc = global.logo_sc[i];' +
    '  draw_set_color(global.logo_col[i]);' +
    '  for (pass = 0; pass < 3; pass += 1) {' +
    '   if (pass == 0) { rr = 3;  a = 0.16; }' +
    '   if (pass == 1) { rr = 7;  a = 0.10; }' +
    '   if (pass == 2) { rr = 12; a = 0.06; }' +
    '   draw_set_alpha(a);' +
    '   for (ring = 0; ring < 8; ring += 1) {' +
    '    ang = ring * 45;' +
    '    draw_text_transformed(global.logo_cx + lengthdir_x(rr, ang),' +
    '     global.logo_cy[i] + lengthdir_y(rr, ang),' +
    '     global.logo_str[i], sc, sc, 0);' +
    '   }' +
    '  }' +
    ' }' +
    ' draw_set_blend_mode(bm_normal);' +
    '}' +

    // ---- the words themselves ------------------------------------------------
    'draw_set_alpha(image_alpha);' +
    'for (i = 0; i < 2; i += 1) {' +
    ' sc = global.logo_sc[i];' +
    ' draw_set_color(global.logo_col[i]);' +
    ' draw_text_transformed(global.logo_cx, global.logo_cy[i],' +
    '  global.logo_str[i], sc, sc, 0);' +
    '}' +
    'draw_set_alpha(1);' +
    'draw_set_halign(fa_left); draw_set_valign(fa_top);' +

    // --- stock body below this line, reproduced unchanged --------------------
    // chr(34) supplies the quotes around th15: the outer event body is a
    // single-quoted GML string, so a nested literal cannot use single quotes,
    // and the credit line itself contains double ones.
    'draw_set_font(TextFont);' +
    'draw_set_color(c_gray);' +
    'var str;' +
    'str = "Created by Sean " + chr(34) + "th15" + chr(34) +' +
    ' " Chan @ http://www.wyrdysm.com Copyright 2007-2009";' +
    'draw_text(room_width/2 - string_width(str)/2, room_height-32, str);' +

    'if (l_visit) {' +
    ' draw_clear(c_black);' +
    ' draw_set_font(TextFontLarge);' +
    ' draw_set_color($FFFFFF);' +
    ' draw_text_transformed(view_xview[0]+350, view_yview[0] + view_hview[0]/2 - 150,' +
    '  "Opening website...", 1, 1, 0);' +
    ' draw_set_color($FFFFFF);' +
    ' draw_set_font(TextFont);' +
    ' draw_text_transformed(view_xview[0]+350, view_yview[0] + view_hview[0]/2 + 150,' +
    '  "Your web browser will be opened to www.wyrdysm.com", 1, 1, 0);' +
    ' screen_refresh();' +
    ' execute_shell("http://www.wyrdysm.com", "");' +
    ' l_visit = 0;' +
    '}');

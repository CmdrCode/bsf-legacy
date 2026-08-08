// bsf-legacy -- mipdraw: mip-filtered sprite drawing for everyone.
//
// GM7 has no mipmaps: every draw samples the full-resolution texture, so a
// minified sprite loses its 1px lines (point filtering drops them, a single
// bilinear tap averages only 2x2 texels and washes them out).  This module is
// the shared fix: draw the sprite with a kernel matched to the shrink ratio.
// It exists because the obvious alternative -- pre-shrinking into captured
// sprites via sprite_create_from_screen -- throws a runtime error under wine
// the moment the window is occluded, and a GM error dialog on ShipMaker's
// off-screen helper window is invisible: they stack forever and eat all input.
// Pure drawing cannot fail that way.
//
// GML has no user-defined functions a mod can add at runtime (scripts are exe
// resources), so the library is the house convention: an invisible object
// whose user events are the entry points and whose arguments travel in
// globals.  Callers do:
//
//     global.mip_spr   = <sprite handle>;      // required, every call
//     global.mip_x     = <x>;                  // required, every call
//     global.mip_y     = <y>;                  // required, every call
//     global.mip_scale = <scale>;              // required, every call
//     global.mip_img   = <subimage>;           // optional, default 0
//     global.mip_rot   = <degrees>;            // optional, default 0
//     global.mip_col   = <color blend>;        // optional, default c_white
//     global.mip_alpha = <alpha>;              // optional, default 1
//     with (global.mip_obj) event_user(0);
//
// The optional arguments reset to their defaults after every call, so a call
// only ever inherits what it set itself.  Two more are ambient (set once per
// draw pass, never reset):
//     global.mip_interp  the texture-interpolation state the caller's pass
//                        runs under (stock 1; smpick's overlay pass 0),
//                        restored after filtered draws
//     global.mip_px      world units per screen pixel in the caller's view
//                        (obj_sidebar.l_zoom for a ShipMaker overlay; 1 in
//                        an unzoomed view).  mip_scale is the WORLD scale;
//                        the kernel is chosen by the on-screen shrink
//                        mip_scale / mip_px, so the same call keeps working
//                        at any camera zoom.
//
// Kernel by on-screen shrink r = scale / px:
//     r >  0.999  plain draw, caller's ambient filter state (native/magnify)
//     r >= 0.5    one bilinear tap -- its 2x2 footprint already covers 1/r
//     r <  0.5    4 additive bilinear taps at half-texel offsets, 25% alpha
//                 each: a box-filtered mip level computed in place.  Additive
//                 blending needs a dark ground to read as opaque -- draw over
//                 a plate or the void of space, not over bright content.
//                 Below r ~ 0.25 even this kernel undersamples; nothing drawn
//                 through it shrinks that far on screen today.
var booted;
booted = 0;
if (variable_global_exists('bsf_mipdraw_init'))
    if (global.bsf_mipdraw_init)
        booted = 1;
if (booted) exit;
global.bsf_mipdraw_init = 1;

var m, i;
m = object_add();
object_event_add(m, 7, 10,
    'var s9, a9, x9, y9, r9, c9, f9, d9, k9;' +
    's9 = global.mip_scale; a9 = global.mip_alpha;' +
    'x9 = global.mip_x; y9 = global.mip_y;' +
    'r9 = global.mip_rot; c9 = global.mip_col; f9 = global.mip_img;' +
    'k9 = s9;' +
    'if (global.mip_px > 0) k9 = s9 / global.mip_px;' +
    'if (k9 > 0.999) {' +
    '  draw_sprite_ext(global.mip_spr, f9, x9, y9, s9, s9, r9, c9, a9);' +
    '}' +
    'else if (k9 >= 0.5) {' +
    '  texture_set_interpolation(1);' +
    '  draw_sprite_ext(global.mip_spr, f9, x9, y9, s9, s9, r9, c9, a9);' +
    '  texture_set_interpolation(global.mip_interp);' +
    '}' +
    'else {' +
    '  d9 = 0.70711 * s9;' +
    '  texture_set_interpolation(1);' +
    '  draw_set_blend_mode(bm_add);' +
    '  draw_sprite_ext(global.mip_spr, f9, x9 + lengthdir_x(d9, r9 + 45), y9 + lengthdir_y(d9, r9 + 45), s9, s9, r9, c9, 0.25 * a9);' +
    '  draw_sprite_ext(global.mip_spr, f9, x9 + lengthdir_x(d9, r9 + 135), y9 + lengthdir_y(d9, r9 + 135), s9, s9, r9, c9, 0.25 * a9);' +
    '  draw_sprite_ext(global.mip_spr, f9, x9 + lengthdir_x(d9, r9 + 225), y9 + lengthdir_y(d9, r9 + 225), s9, s9, r9, c9, 0.25 * a9);' +
    '  draw_sprite_ext(global.mip_spr, f9, x9 + lengthdir_x(d9, r9 + 315), y9 + lengthdir_y(d9, r9 + 315), s9, s9, r9, c9, 0.25 * a9);' +
    '  draw_set_blend_mode(bm_normal);' +
    '  texture_set_interpolation(global.mip_interp);' +
    '}' +
    // self-cleaning: optionals back to defaults so no call inherits another's
    'global.mip_img = 0; global.mip_rot = 0; global.mip_col = c_white; global.mip_alpha = 1;');

i = instance_create(0, 0, m);
i.persistent = true;

global.mip_obj = i;
global.mip_img = 0; global.mip_rot = 0; global.mip_col = c_white; global.mip_alpha = 1;
global.mip_interp = 1; global.mip_px = 1;

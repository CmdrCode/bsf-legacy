// Prototype: can a pixel shader be scoped to ONE sprite draw?
//
// Gated on mods/shaderspr.on.  Measurement only -- it draws four copies of the
// same sprite over four black patches and captures frames; it changes nothing
// about how the game plays.
//
// The question.  mods/shaderdemo.gml proved a shader can be bound at all, but it
// bound one globally and left it bound, so every draw in the frame went through
// it.  A visual effect wants the opposite: this ship cloaked, that one burning,
// the rest untouched.  Whether that is reachable comes down to one engine fact
// -- the runner issues one DrawPrimitiveUP per sprite (D3D8-INTEROP 4;
// HWVP-VERIFICATION counted 806,759 of them, every one a user-pointer
// TRIANGLEFAN of two triangles).  Nothing is batched and nothing is deferred, so
// the pixel-shader slot at the instant of a draw is the slot that draw uses,
// which would make sh_set/sh_reset a bracket around an individual sprite.
//
// The run captures four comparable frames, all with the same three boxes:
//
//   spr_ctrl    A | B | C | D   all plain, nothing bound      (control)
//   spr_test    A | B | C | D   B bracketed with the heat shader,
//                               C bracketed with the cloak shader
//   spr_bleed   A | B | C | D   all plain, one shader left bound globally
//   spr_clean   A | B | C | D   all plain again after sh_reset (== spr_ctrl)
//
// plus spr_base, drawn before the boxes appear, for context.
//
// Read them REGION BY REGION, control against test -- never region against
// region.  The four boxes sit over different parts of the menu, so A and D are
// not each other's control even though the sprite in them is identical.
//
//   A_test  == A_ctrl    the draw before the first bracket is untouched
//   B_test  != B_ctrl    heat
//   C_test  != C_ctrl    cloak -- a DIFFERENT shader, same frame, next draw
//   D_test  == D_ctrl    the draw after the last sh_reset is untouched again
//   *_bleed != *_ctrl    all four, because device state persists
//   *_clean == *_ctrl    and stops persisting when told to
//
// spr_bleed is the control that gives the equalities their teeth: it shows the
// shader really does stay bound across every later draw, so A_test == A_ctrl can
// only be the bracket and not the shader quietly failing to bind.
//
// ⚠ The black patches are not decoration.  The main menu animates hard enough
// that a frame-to-frame RMSE of 0.09 over an EMPTY 307x302 box is just the
// background moving -- larger than the effect being measured.  An opaque patch
// under each sprite makes the box's content entirely ours, identical in every
// frame, and drops the noise floor to ~0 so the comparison means something.
var o;
if (!variable_global_exists('sh_ok')) exit;

global.spr_h  = -1;   // heat
global.spr_h2 = -1;   // cloak
if (global.sh_ok >= 1) {
    global.spr_h  = external_call(global.sh_compile, 'mods/shaderdemo.hlsl');
    global.spr_h2 = external_call(global.sh_compile, 'mods/shadercloak.hlsl');
}

o = object_add();
object_set_persistent(o, 1);   // resolution.gml's room_restart() would eat it otherwise

// depth is assigned rather than set through object_set_depth: a builtin that
// turns out not to exist aborts the whole file silently, and a plain variable
// cannot. -10000 puts us after the menu, so the menu is never inside our
// bracket and the only sprite the shader can reach is the one we aimed it at.
object_event_add(o, 0, 0, 'tick = 0; mode = 0; depth = -10000;');

object_event_add(o, 3, 0,
    'tick += 1;' +
    'if (tick == 60)  screen_save("mods/spr_base.png");' +
    'if (tick == 70)  mode = 1;' +
    'if (tick == 100) screen_save("mods/spr_ctrl.png");' +
    'if (tick == 105) mode = 2;' +
    'if (tick == 135) screen_save("mods/spr_test.png");' +
    'if (tick == 140) mode = 1;' +
    'if (tick == 140 && global.spr_h >= 0) {' +
    '  external_call(global.sh_const, 0, 1, 0, 0, 0);' +
    '  external_call(global.sh_set, global.spr_h); }' +
    'if (tick == 170) screen_save("mods/spr_bleed.png");' +
    'if (tick == 175 && global.spr_h >= 0) external_call(global.sh_reset);' +
    'if (tick == 205) screen_save("mods/spr_clean.png");' +
    'if (tick == 215) {' +
    '  var f; f = file_text_open_write("mods/shaderspr.txt");' +
    '  file_text_write_string(f, "ok=" + string(global.sh_ok)' +
    '    + " heat=" + string(global.spr_h)' +
    '    + " cloak=" + string(global.spr_h2)' +
    '    + " binds=" + string(external_call(global.sh_stat, 2))' +
    '    + " fails=" + string(external_call(global.sh_stat, 3)));' +
    '  file_text_writeln(f);' +
    '  file_text_write_string(f, "err=" + string(external_call(global.sh_err)));' +
    '  file_text_writeln(f); file_text_close(f); }' +
    'if (tick == 225) game_end();');

// mode 1 and mode 2 run the SAME eight draws; the only difference between the
// two frames is the two brackets. Positions are fractions of the view, which
// makes the crop boxes in the captured frame the same fractions of the image --
// no pixel coordinates to keep in sync.
//
// The blend mode is forced to 0 (bm_normal, spelled as its value so a missing
// constant cannot kill the file): the menu leaves additive blending on in
// places, and a black rectangle drawn additively is a no-op -- the patch would
// silently not be there and the noise floor would come back.
object_event_add(o, 8, 0,
    'if (mode > 0) {' +
    '  var vx, vy, vw, vh, bx, by, bw, bh, i, br, h;' +
    '  br = 0; if (mode == 2) br = 1;' +
    '  if (global.spr_h < 0) br = 0;' +
    '  vx = 0; vy = 0; vw = room_width; vh = room_height;' +
    '  if (view_enabled) {' +
    '    vx = view_xview[0]; vy = view_yview[0];' +
    '    vw = view_wview[0]; vh = view_hview[0]; }' +
    '  bw = vw*0.16; bh = vh*0.28; by = vy + vh*0.36;' +
    '  draw_set_blend_mode(0); draw_set_alpha(1); draw_set_color(c_black);' +
    '  for (i = 0; i <= 3; i += 1) {' +
    '    bx = vx + vw*(0.06 + 0.24*i);' +
    '    draw_rectangle(bx, by, bx + bw, by + bh, 0); }' +
    '  for (i = 0; i <= 3; i += 1) {' +
    '    bx = vx + vw*(0.06 + 0.24*i);' +
    '    h = -1;' +
    '    if (br) { if (i == 1) h = global.spr_h; if (i == 2) h = global.spr_h2; }' +
    '    if (h >= 0) {' +
    '      external_call(global.sh_const, 0, 1, 0, 0, 0);' +
    '      external_call(global.sh_set, h); }' +
    '    draw_sprite_stretched_ext(spr_butGlow, 4, bx, by, bw, bh, c_white, 1);' +
    '    if (h >= 0) external_call(global.sh_reset); }' +
    '}');

instance_create(0, 0, o);

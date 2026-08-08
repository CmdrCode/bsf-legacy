// Crisp menu text -- replaces the menu's text SPRITES with drawn text.
//
// ------------------------------------------------------------------- why
// The menu labels are bitmaps authored for a 1024x768 layout. The view is
// 1365x768 inside a 3840x2160 port, so world space is magnified 2.81x and every
// label is a ~300px bitmap stretched to ~840px. Measured on a 4K frame, ~47% of
// each sprite letterform's pixels are intermediate values -- the filter inventing
// detail that was never in the source. Text drawn from a font measures 2-10% on
// the same metric. The game's own drawn text (the copyright line, and the option
// VALUES) was already crisp; only the labels were bitmaps.
//
// -------------------------------------------------------------- how it works
// Every menu button descends from ctr_MainMenu, whose Draw is:
//     glow sprite -> label sprite -> hover tooltip
// Only the middle call is a bitmap of a word, so the event is cleared and re-added
// with that one line swapped for drawn text. Everything else -- position, mouse
// events, alarms, the disabled tint, the tooltip -- is untouched, and crucially
// the SPRITE STAYS ASSIGNED, so the collision mask that hit-tests the button is
// exactly what it always was. Nothing about clicking changes.
//
// The option widgets (GUI_OptMusic, GUI_OptDoodads, ...) own a Draw of their own
// but every one of them ends with event_inherited(), so they render their label
// through the same parent event and are fixed by the same change.
//
// Nine of them ALSO blit the label themselves before inheriting, which would show
// the bitmap underneath the text. Rather than rewriting those nine bodies -- which
// meant generating a file from the game's own source, and so a derivative work
// that could not be redistributed -- the instance's sprite_index is set to -1 and
// mask_index is pointed at the original sprite:
//
//   * draw_sprite_ext(-1, ...) is a no-op, verified, so their self-blit draws
//     nothing and their value readout and event_inherited() still run;
//   * mouse events hit-test against mask_index, so hover, click and the tooltip
//     behave exactly as before;
//   * the label lookup and text sizing read mask_index instead, so the sprite is
//     still the source of both the name and the box to fit.
//
// This is why a fresh clone works with no generation step.
//
// Labels are keyed by SPRITE name, not object name: three different objects share
// spr_mainBack and all three say BACK, so the sprite is the right key. A sprite
// with no entry falls through to the stock bitmap draw, which makes this additive
// -- an unknown screen renders exactly as it does today.
//
// GML traps this file is written around, all of which fail SILENTLY:
//   * no ternary operator -- `a ? b : c` is a syntax error
//   * `pi` is a built-in constant; using it as a variable kills the whole file
//   * non-ASCII bytes anywhere in the file do the same
//   * sprite_get_name(-1) aborts, and buttons with no sprite do exist
//     (GUI_CareerMission, GUI_CustomCheckbox)
//
// Remove mods/crisp.on to disable.

if (variable_global_exists('bsf_crisp')) exit;
global.bsf_crisp = 1;

// Sampled off a rendered frame rather than guessed: the menu ink is #34FF39.
// GM colours are BGR, so that is $39FF34 -- written RGB-wise it comes out blue.
global.crisp_col = $39FF34;

global.crisp_lbl = ds_map_create();

// --- main menu -------------------------------------------------------------
ds_map_add(global.crisp_lbl, 'spr_mainCareer',     'CAREER');
ds_map_add(global.crisp_lbl, 'spr_mainSkirmish',   'SKIRMISH');
ds_map_add(global.crisp_lbl, 'spr_mainCustom',     'CUSTOM GAME');
ds_map_add(global.crisp_lbl, 'spr_mainOptions',    'OPTIONS');
ds_map_add(global.crisp_lbl, 'spr_mainInfo',       'GAME INFO');
ds_map_add(global.crisp_lbl, 'spr_mainExit',       'EXIT');
ds_map_add(global.crisp_lbl, 'spr_mainBack',       'BACK');
ds_map_add(global.crisp_lbl, 'spr_secondDone',     'DONE');

// --- skirmish sub-menu -----------------------------------------------------
ds_map_add(global.crisp_lbl, 'spr_skirmGrinder',   'GRINDER');
ds_map_add(global.crisp_lbl, 'spr_skirmBlockade',  'BLOCKADE');
ds_map_add(global.crisp_lbl, 'spr_skirmRaid',      'RAID');
ds_map_add(global.crisp_lbl, 'spr_skirmLeviathan', 'LEVIATHAN');

// --- custom game sub-menu --------------------------------------------------
ds_map_add(global.crisp_lbl, 'spr_skirmSandbox',   'SANDBOX');
ds_map_add(global.crisp_lbl, 'spr_skirmPlayEnc',   'PLAY ENCOUNTER');
ds_map_add(global.crisp_lbl, 'spr_skirmLoadEnc',   'LOAD ENCOUNTER');
ds_map_add(global.crisp_lbl, 'spr_skirmMakeEnc',   'MAKE ENCOUNTER');

// --- options screen --------------------------------------------------------
ds_map_add(global.crisp_lbl, 'spr_optInterpolate', 'INTERPOLATE');
ds_map_add(global.crisp_lbl, 'spr_optGradients',   'GRADIENTS');
ds_map_add(global.crisp_lbl, 'spr_optDoodads',     'DOODADS');
ds_map_add(global.crisp_lbl, 'spr_optParts',       'PARTICLES');
ds_map_add(global.crisp_lbl, 'spr_optSurfaces',    'SURFACES');
ds_map_add(global.crisp_lbl, 'spr_optDifficulty',  'DIFFICULTY');
ds_map_add(global.crisp_lbl, 'spr_optScrolling',   'SCROLLING');
ds_map_add(global.crisp_lbl, 'spr_optSound',       'SOUND VOL');
ds_map_add(global.crisp_lbl, 'spr_optMusic',       'MUSIC VOL');
ds_map_add(global.crisp_lbl, 'spr_optColours',     'COLOURS');
ds_map_add(global.crisp_lbl, 'spr_optFullscreen',  'FULLSCREEN');
ds_map_add(global.crisp_lbl, 'spr_optWide',        'WIDESCREEN');
// NOT listed on purpose: spr_optSlider is a slider BAR, not a word, and
// spr_mainTitle is the logo -- GUI_MainTitle does not descend from ctr_MainMenu
// so it never reaches this code, but the omission is the belt and braces.

// ---------------------------------------------------------------------------
// ctr_MainMenu Draw -- the one event every menu button renders through.
// object_event_clear removes the stock body; object_event_add would only APPEND
// to it, leaving the bitmap label drawn underneath the text.
object_event_clear(ctr_MainMenu, 8, 0);
object_event_add(ctr_MainMenu, 8, 0,
    'var lbl, sw, sh, sc, col, key, lsp;' +
    // The backing glow is not text; kept exactly as stock.
    'draw_sprite_ext(spr_butGlow, l_glowmax - image_index, x, y,' +
    ' (image_xscale + image_index/20)*4, image_yscale*3, image_angle, image_blend, image_alpha/4);' +

    // The label sprite is mask_index once this instance has been blanked, and
    // sprite_index before that. Both the name lookup and the box to fit come
    // from it, so everything downstream is unaffected by the swap.
    'lsp = sprite_index;' +
    'if (mask_index >= 0) lsp = mask_index;' +
    'lbl = "";' +
    'if (lsp >= 0) {' +
    ' if (sprite_exists(lsp)) {' +
    '  key = sprite_get_name(lsp);' +
    '  if (ds_map_exists(global.crisp_lbl, key)) lbl = ds_map_find_value(global.crisp_lbl, key);' +
    ' }' +
    '}' +

    'if (lbl == "") {' +
    // Unknown sprite: stock behaviour, unchanged — but guard the blank case.
    // A button that was born with sprite_index = -1 (act2.gml's Act II slots
    // carry only a mask and draw their labels themselves) must not reach
    // draw_sprite_ext(-1, ...): despite the header note above, the runner
    // throws "Trying to draw non-existing sprite" for it, once per frame.
    ' if (sprite_index >= 0) {' +
    '  draw_sprite_ext(sprite_index, image_index, x, y, image_xscale, image_yscale,' +
    '   image_angle, image_blend, image_alpha);' +
    ' }' +
    '} else {' +
    // Blank the sprite so a child that blits its own label draws nothing, and
    // keep the original as the collision mask so hit-testing is untouched.
    // Done here rather than in Create because not every child calls
    // event_inherited() from Create, whereas every child that renders reaches
    // this event. Costs one frame during which the old bitmap is still shown.
    ' if (sprite_index >= 0) { mask_index = sprite_index; sprite_index = -1; }' +
    ' sw = sprite_get_width(lsp) * image_xscale;' +
    ' sh = sprite_get_height(lsp) * image_yscale;' +
    ' draw_set_font(MainMenuFont);' +
    // Size to the sprite box the label used to occupy, then clamp so a long
    // label (PLAY ENCOUNTER) cannot spill outside the button it belongs to.
    ' sc = (sh * 0.62) / string_height(lbl);' +
    ' if (string_width(lbl) * sc > sw * 0.92) sc = (sw * 0.92) / string_width(lbl);' +
    // image_blend is the button state: c_white is enabled, anything else is the
    // greyed/disabled tint the stock art was modulated by. Honour it.
    ' col = global.crisp_col;' +
    ' if (image_blend != c_white) col = image_blend;' +
    ' draw_set_halign(fa_center); draw_set_valign(fa_middle);' +
    ' draw_set_alpha(image_alpha); draw_set_color(col);' +
    ' draw_text_transformed(x, y, lbl, sc, sc, image_angle);' +
    // Stock hover is an animated glow strip cycling through image_index. With no
    // strip to cycle, the same cue is an additive re-draw that rises with it.
    ' if (image_index > 0 && l_glowmax > 0) {' +
    '  draw_set_blend_mode(bm_add);' +
    '  draw_set_alpha(image_alpha * (image_index / l_glowmax) * 0.7);' +
    '  draw_text_transformed(x, y, lbl, sc, sc, image_angle);' +
    '  draw_set_blend_mode(bm_normal);' +
    ' }' +
    ' draw_set_alpha(1);' +
    ' draw_set_halign(fa_left); draw_set_valign(fa_top);' +
    '}' +

    // Hover tooltip, reproduced from the stock body -- with the one change that
    // the stock block measures `words` FOUR times per frame and the answer cannot
    // differ between the four. Measured once into hh; nothing else is touched.
    'if (l_descript) {' +
    ' var words, xx, yy, hh;' +
    ' words = l_text;' +
    ' draw_set_alpha(0.75); draw_set_color(c_black); draw_set_font(DescriptFont);' +
    ' hh = string_height_ext(words,-1,190);' +
    ' xx = mouse_x; yy = mouse_y;' +
    ' if (xx + 201 > room_width) xx = room_width - 201;' +
    ' if (yy + 11 + hh > room_height) yy = room_height - hh - 11;' +
    ' draw_rectangle(xx, yy, xx+200, yy+10+hh, 0);' +
    ' draw_set_alpha(1); draw_set_color($00FF00);' +
    ' draw_rectangle(xx, yy, xx+200, yy+10+hh, 1);' +
    ' draw_set_color(c_white);' +
    ' draw_text_ext(xx+5, yy+5, words, -1, 190);' +
    '}');

// No per-widget patching is needed: the nine self-blitting widgets are handled
// by the sprite_index/mask_index swap in the event above, so their bodies -- and
// the three-way difficulty branch, the rounded volumes, the On/Off tints -- are
// never touched, and nothing has to be generated from the game's source.

// ---------------------------------------------------------------------------
// GUI_OptTitle is the "GAME OPTIONS" heading. It does not descend from
// ctr_MainMenu, so it needs its own replacement. It carries the logo's two
// bm_zero shadow passes; those are reproduced, but at offsets RELATIVE to the
// instance rather than the stock body's hardcoded 532,120 / 522,110, which are
// absolute coordinates left over from the 1024-wide layout and land in the wrong
// place once the widescreen mod re-centres the room.
object_event_clear(GUI_OptTitle, 8, 0);
object_event_add(GUI_OptTitle, 8, 0,
    'var t, sh, sc, pass, o, a;' +
    't = "GAME OPTIONS";' +
    'sh = sprite_get_height(sprite_index) * image_yscale;' +
    'draw_set_font(MainMenuFont);' +
    'sc = (sh * 0.62) / string_height(t);' +
    'draw_set_halign(fa_center); draw_set_valign(fa_middle);' +
    'for (pass = 0; pass < 3; pass += 1) {' +
    // Softer than the logo's 20/10: this heading is a third the logo's size, and
    // at that scale the stock offsets read as a second ghosted copy of the word
    // rather than as depth.
    ' if (pass == 0) { o = 8; a = 0.10; draw_set_blend_mode(bm_zero); }' +
    ' if (pass == 1) { o = 4; a = 0.20; draw_set_blend_mode(bm_zero); }' +
    ' if (pass == 2) { o =  0; a = 1.00; draw_set_blend_mode(bm_normal); }' +
    ' draw_set_alpha(a * image_alpha);' +
    ' draw_set_color(global.crisp_col);' +
    ' draw_text_transformed(x + o, y + o, t, sc, sc, image_angle);' +
    '}' +
    'draw_set_blend_mode(bm_normal); draw_set_alpha(1);' +
    'draw_set_halign(fa_left); draw_set_valign(fa_top);');

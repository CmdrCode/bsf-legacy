// Umbra Cloak -- a new module type, and the first part in this repo that is not
// something the game already had.
//
// Canon: EP9's Admiral Hong hands the player a destroyer whose cloak was
// "drawn from Nanz wreckage" (mods/act2m1.gml, t15). The game shipped no cloak
// of any kind -- the string does not occur anywhere in its GML -- so the device
// has to be built, not configured.
//
// ---------------------------------------------------------------------------
// How a new module type is possible at all
// ---------------------------------------------------------------------------
// Read off the decrypted object tree (tools/gmobj.py), not guessed:
//
//   * Every weapon AND module parents straight to `ctr_Turrets`, which is where
//     the whole mount apparatus lives -- owner, hp, energy fields, positioning,
//     triggers, death. Deflector[228], NanoMatrix[227], Booster[369],
//     Impeder[593] and Blaster[91] are all direct children of it. So a new
//     module is `object_add()` + `object_set_parent(o, ctr_Turrets)` and
//     nothing more exotic.
//
//   * `ctr_Turrets`' Step is the *weapon firing* logic. A module must not run
//     it. NanoMatrix is the pattern: it defines its own Step and does NOT call
//     `event_inherited()`, so the firing step is shadowed outright. That is the
//     one place the modding guide's rule 2 -- "a created event shadows the
//     parent's" -- is the behaviour you want rather than the trap it usually
//     is. Our Create does the opposite and calls `event_inherited()` first,
//     because the base initialisation is exactly what we do want.
//
//   * `ctr_Turrets`' Draw is inherited untouched: it draws `sprite_index` at
//     `image_alpha`, which is all a module needs.
//
//   * Energy regen is per-module, not in the base -- Deflector regenerates in
//     its own Draw. So this file does its own.
//
// ---------------------------------------------------------------------------
// How a .shp can name an object that did not exist when it was written
// ---------------------------------------------------------------------------
// A `.shp` is compiled, not parsed: `nTur2,x,y,UmbraCloak,...` is rebuilt as
// `nTur2(x,y,UmbraCloak,...)` and installed as the ship object's Create event,
// so `UmbraCloak` is evaluated as a GML expression in the ship instance's
// scope. A runtime-created object has no resource name to resolve against, so
// the name has to be *in scope on the ship* by the time that line runs.
//
// It is, because every hull's Create opens with `event_inherited()`. That runs
// `ctr_Ship`'s Create -- including anything appended to it -- before the rest of
// the hull's own Create. Appending here is the modding guide's rule 1 (safe:
// the object already has a Create, so we are added after the stock body, not
// shadowing a parent), verified against the object tree: `ctr_Ship`[1] and
// `ctr_EShip`[56] both carry a `0:0`.
//
// ⚠ UNVERIFIED IN-GAME. `ship check` is offline and cannot see any of this
// (D19a). Nothing below has been run under wine yet.

if (variable_global_exists('bsf_umbracloak')) exit;
if (!file_exists('mods/spr_UmbraCloak.png')) exit;

var spr, cre, stp, o, eo;

// `transparent=1` keys on the bottom-left pixel, which tools/mkmodart.py fills
// with the stock turret key (0,128,64). Origin is the centre of a 15x15 plate.
spr = sprite_add('mods/spr_UmbraCloak.png', 1, 1, 1, 0, 1, 7, 7);

// -- Create -----------------------------------------------------------------
// Shaped like Deflector's, because the loader's `nMod2` tests every one of
// these against -1 before assigning (D19e) and a mount written entirely in -1s
// then fights exactly as the object does. Anything left unset here is a zero
// somebody did not mean.
//
//   l_owner     noone until the ship assigns it, so it is never read undefined
//   l_threshold the hysteresis floor -- see the Step
//   l_special1  the alpha the hull settles at, cloaked
//   l_special2  alpha change per step, so the fade is about 40 steps
//
// The last two are `l_special` slots rather than names of our own because that
// is what `nMod2` can reach: a mount can retune the cloak without editing this
// file.
cre =
  'event_inherited();' +
  'module = 1;' +
  'l_owner = noone;' +
  'l_target = -4;' +
  'c_target = -4;' +
  'l_name = "Umbra Cloak";' +
  'l_size = 10;' +
  'l_hp = 40; l_maxhp = l_hp;' +
  'l_maxeng = 1800; l_eng = l_maxeng;' +
  'l_engregen = 1.5;' +
  'l_engcost = 3; l_cost = l_engcost;' +
  'l_threshold = l_maxeng/2;' +
  'l_range = 0;' +
  'l_iconsprite = spr_IcoDeflector;' +
  'l_iconspritesml = spr_IcoDeflectorsml;' +
  'l_special1 = 0.18;' +
  'l_special2 = 0.02;' +
  'uc_on = 1; uc_alpha = 1; uc_last = -1;';

// -- Step -------------------------------------------------------------------
// No `event_inherited()`: see the header. Every guard is nested rather than
// `&&`-ed, because GM 7 evaluates both operands of `&&` and a dead `l_owner`
// would throw once a frame forever.
//
// The mechanic: the cloak runs until the reserve is empty, then browns out and
// has to charge back past half before it will re-engage. That hysteresis is
// what stops it flickering on the boundary, and it is the same energy grammar
// the stock modules use.
//
// The hull is only walked on a frame where the alpha actually moved -- settled,
// at either end, this Step is four comparisons. `instance_exists` guards each
// part because a blown-off section leaves a stale id in the ship's array.
//
// Every comment stays *outside* the concatenations below. A syntax slip in this
// file is silent -- `execute_file` on a file that fails to compile does nothing
// at all, no dialog and no log line -- so it is not worth the risk of finding
// out whether a comment between `+` and its operand parses.
stp =
  'if (online == 0) exit;' +
  'if (uc_on) {' +
  '  if (l_eng > 0) { l_eng -= l_engcost; } else { uc_on = 0; }' +
  '} else {' +
  '  if (l_eng < l_maxeng) { l_eng += l_engregen; }' +
  '  if (l_eng >= l_threshold) { uc_on = 1; }' +
  '}' +
  'var tgt, stepa;' +
  'tgt = 1; if (uc_on) { tgt = l_special1; }' +
  'stepa = l_special2;' +
  'if (uc_alpha < tgt) { uc_alpha += stepa; if (uc_alpha > tgt) { uc_alpha = tgt; } }' +
  'if (uc_alpha > tgt) { uc_alpha -= stepa; if (uc_alpha < tgt) { uc_alpha = tgt; } }' +
  'if (uc_alpha != uc_last) {' +
  '  uc_last = uc_alpha;' +
  '  if (instance_exists(l_owner)) {' +
  '    var i, a, p;' +
  '    a = uc_alpha;' +
  '    l_owner.image_alpha = a;' +
  '    for (i = 0; i <= l_owner.l_sectionnum; i += 1) {' +
  '      p = l_owner.l_section[i];' +
  '      if (instance_exists(p)) { p.image_alpha = a; }' +
  '    }' +
  '    for (i = 0; i <= l_owner.l_weaponnum; i += 1) {' +
  '      p = l_owner.l_weapon[i];' +
  '      if (instance_exists(p)) { p.image_alpha = a; }' +
  '    }' +
  '  }' +
  '}';

// -- the object, and its enemy-side twin ------------------------------------
// Every stock module has an `E`-prefixed counterpart on `ctr_ETurrets`, and the
// loader concatenates the mount's object name through verbatim (`parseReadParams`
// does no team rewriting), so an enemy hull naming this part would reach the
// same object. Both are built anyway, for the same reason the stock set has
// both: the two turret bases are separate objects and only one of them is a
// friendly.
o = object_add();
object_set_parent(o, ctr_Turrets);
object_set_sprite(o, spr);
object_event_add(o, 0, 0, cre);
object_event_add(o, 3, 0, stp);
global.bsf_umbracloak = o;

eo = object_add();
object_set_parent(eo, ctr_ETurrets);
object_set_sprite(eo, spr);
object_event_add(eo, 0, 0, cre);
object_event_add(eo, 3, 0, stp);
global.bsf_eumbracloak = eo;

// -- put the names in scope for compiled hulls ------------------------------
// Rule 1 append: both objects already carry a Create, so this lands after the
// stock body and before the hull's own code resumes from `event_inherited()`.
object_event_add(ctr_Ship,  0, 0, 'UmbraCloak = global.bsf_umbracloak;' +
                                  'EUmbraCloak = global.bsf_eumbracloak;');
object_event_add(ctr_EShip, 0, 0, 'UmbraCloak = global.bsf_eumbracloak;' +
                                  'EUmbraCloak = global.bsf_eumbracloak;');

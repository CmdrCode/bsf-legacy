// The Umbra Cloak -- the module, and the cloak it drives.
//
// Absorbs what was mods/umbracloak.gml (the mount) and what was this file (the
// shader demo). Gated `!cloak.off`: this is gameplay now, on by default.
//
// Canon: EP9's Admiral Hong hands the player a destroyer whose cloak was "drawn
// from Nanz wreckage" (mods/act2m1.gml, t15). The game shipped no cloak of any
// kind, so the device is built rather than configured.
//
// A ship is cloak-CAPABLE iff it mounts an UmbraCloak. The module owns the
// rule; a mission may override any ship through three variables it writes on
// the hull:
//
//   l_cloak_want   0/1    the module writes it; a mission may override
//   l_cloak_lock   0/1    mission holds the wheel, the module stops writing
//   l_cloak_now    0..1   the rendered state. 1 = solid, 0 = fully cloaked
//   l_cloak_hidden 0/1    untargetable. Flips at the START of either transition
//
// ---------------------------------------------------------------------------
// THREE THINGS THE DESIGN NOTE GOT WRONG, ALL READ OFF THE OBJECT TREE
// ---------------------------------------------------------------------------
// (tools/gmobj.py over the decrypted tree; none of this was guessed.)
//
//  1. `ctr_Ship` Create is `depth = (id mod 1000)/10000`, NOT `/1000`. Hulls sit
//     0.0001 apart, so a sandwich sized for 0.001 spans two or three of them.
//
//  2. THERE IS NO PER-SHIP DRAW BAND. `ShipSection`, `ctr_Turrets` and the
//     doodads all keep their object depth -- 0 for everything, 1 for
//     `ctr_ETurrets`. `depth = l_owner.depth` occurs in nineteen alarm[10]
//     bodies, none of them a section or a turret, and in none of the 203
//     scripts. Only the HULL takes a per-ship depth. Every ship's parts are
//     therefore commingled at depth 0, and the old demo only worked because the
//     sandbox held exactly one ship.
//
//     So the band has to be TAKEN, not found: a cloaked ship is given a slot,
//     and every one of its parts is forced to that slot's depth from End Step,
//     the way fastdraw.gml owns `visible`. Flattening a ship's parts to one
//     depth is safe -- BSF layers them by creation order, not by depth.
//
//  3. The `l_ailevel = 1` branch does NOT bypass the target map. It ends
//     `ds_map_add(l_targets, dis, tar)` exactly like the other branch, so ONE
//     append after the stock alarm[0] blinds both.
//
// ---------------------------------------------------------------------------
// NOT IMPLEMENTED, and why
// ---------------------------------------------------------------------------
// The design asked for the HUD chrome -- selection ring, HP and energy bars,
// turret arcs -- to dim to ~0.45 alongside the hull, on a separate alpha path.
// It is not here, and not because it was skipped.
//
// That chrome is drawn by ctr_GUI at depth -10, outside any band this file can
// take, and it is drawn by ctr_GUI's OWN Draw event. object_event_add can only
// APPEND to that event, never wrap or replace it (MODDING-GUIDE.md 4, rule 1),
// so there is no point at which a per-ship alpha could be applied to it and no
// way to scope a shader to one ship's chrome rather than the whole HUD. The
// levers that do exist are both wrong: shading ctr_GUI's depth dims every
// ship's chrome at once, and hiding it removes the ship from the player's
// control surface, which is the one thing the design says must not happen.
//
// So a cloaked player ship currently reads as a dim hull with a full-strength
// selection ring. Fixing it properly needs a lever below GML.
//
// ---------------------------------------------------------------------------
// Traps this file is written around (MODDING-GUIDE.md 4, 14)
// ---------------------------------------------------------------------------
//   * `&&` and `||` NEVER short-circuit. Every guard here is nested.
//   * `var` every temp that a `with` block touches, or it becomes an instance
//     variable and resolves against the wrong instance.
//   * `id` is a built-in variable; `var ..., id;` kills the whole file at the
//     object_event_add that compiles the string. Locals here are ugly on
//     purpose (sid, mid, pid).
//   * `exit` inside a `with` ends the EVENT, not the iteration -- so every
//     early-out below is a nested `if`, never an `exit`.
//   * Never compare a depth with `!=`.
//   * Comments stay OUTSIDE the string concatenations. A file that fails to
//     compile does nothing at all, silently.
//   * `ctr_Ship`'s Create ends `if room != rm_ChooseShips then exit`, so an
//     appended Create is not a reliable place to initialise anything for
//     gameplay. Ship state is initialised lazily instead, under
//     `variable_local_exists`.

if (variable_global_exists('bsf_cloak')) exit;
if (!file_exists('mods/spr_UmbraCloak.png')) exit;
global.bsf_cloak = 1;

// ------------------------------------------------------------------ tunables
// Steps, not seconds, because everything here runs per step. room_speed is 30.
global.ck_drain = 0.4;      // budget per step while moving and cloaked
global.ck_regen = 0.8;      // budget per step once the dwell is served
global.ck_dwell = 60;       // steps of holding still before regen starts
global.ck_reeng = 35;       // budget needed to re-engage after a brown-out
global.ck_trans = 60;       // steps for a full transition, either way
global.ck_lock  = 120;      // steps a detection or a trigger pins visible
global.ck_ghost = 0.25;     // what the player's own cloaked ship fades to
global.ck_slow  = 0.30;     // speed below which a ship counts as holding still
global.ck_ripple = 0.06;    // shader warp amplitude, UV units at full cloak
global.ck_umax  = 1;
global.ck_vmax  = 1;

// -------------------------------------------------------------------- slots
// A cloaked ship takes a slot; the slot is a depth band. Between the hull pack
// (0 .. 0.0999) and ctr_GUI (-10), so nothing else is ever inside one.
//   binder   D + eps    sets the constants, sh_set
//   the ship D          drawn by the game's own code, untouched
//   resetter D - eps    sh_reset
// eps is well under half a slot, so no band can reach into its neighbour.
global.ck_nslot = 16;
global.ck_dbase = -0.5;
global.ck_dstep = 0.01;
global.ck_deps  = 0.002;

var i;
for (i = 0; i < global.ck_nslot; i += 1) {
    global.ck_ship[i] = noone;
    global.ck_prog[i] = 1;
}

// ------------------------------------------------------------------- shader
// Optional. With no DLL, no d3d8to9 or a shader that will not compile, ck_h
// stays -1 and every ship falls back to the plain image_alpha path below.
global.ck_h = -1;
global.ck_time = 0;
if (variable_global_exists('sh_ok')) {
    if (global.sh_ok >= 1) {
        global.ck_h = external_call(global.sh_compile, 'mods/decloak.hlsl');
    }
}

// =========================================================================
// 1. THE MOUNT
// =========================================================================
// Read off the decrypted object tree: every weapon AND module parents straight
// to ctr_Turrets, which is where the mount apparatus lives -- owner, hp, energy,
// positioning, death. So a new module is object_add() + object_set_parent().
//
// ctr_Turrets' Step is the WEAPON FIRING logic and a module must not run it.
// NanoMatrix is the pattern: it defines its own Step and does NOT call
// event_inherited(), shadowing the firing step outright. Our Create does the
// opposite and calls event_inherited() first, because the base initialisation is
// exactly what we want.
var spr, cre, o, eo;

// transparent=1 keys on the bottom-left pixel, which tools/mkmodart.py fills
// with the stock turret key (0,128,64). Origin is the centre of a 15x15 plate.
spr = sprite_add('mods/spr_UmbraCloak.png', 1, 1, 1, 0, 1, 7, 7);

// Shaped like Deflector's, because the loader's nMod2 tests every one of these
// against -1 before assigning and a mount written entirely in -1s then fights
// exactly as the object does.
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
  'l_special2 = 0.02;';

// No event_inherited(): see above. The module is a passive capability token --
// all the cloak logic lives in the controller, in one place, so that the order
// this Step runs in relative to the ship's own never matters.
o = object_add();
object_set_parent(o, ctr_Turrets);
object_set_sprite(o, spr);
object_event_add(o, 0, 0, cre);
global.bsf_umbracloak = o;

eo = object_add();
object_set_parent(eo, ctr_ETurrets);
object_set_sprite(eo, spr);
object_event_add(eo, 0, 0, cre);
global.bsf_eumbracloak = eo;

// A .shp is COMPILED, not parsed: `nTur2,x,y,UmbraCloak,...` is rebuilt as
// `nTur2(x,y,UmbraCloak,...)` and installed as the ship object's Create, so
// `UmbraCloak` is evaluated as a GML expression in the ship instance's scope.
//
// The binding has to be PER INSTANCE, because the two teams map the same name
// to different objects: a hull under ctr_Ship means the friendly object, the
// same name under ctr_EShip means the enemy twin. `globalvar UmbraCloak` was
// tried here and is wrong for exactly that reason -- it makes every assignment
// write one global, so the last hull created decides what the name means for
// every hull already built, and a friendly spawned after an enemy arms the
// wrong object.
//
// VERIFY THIS FIRST IN-GAME. ctr_Ship's Create ends `if room != rm_ChooseShips
// then exit`, and whether that `exit` stops a later appended action or only its
// own is NOT measured. If it stops the append, `UmbraCloak` is not in scope when
// the compiled .shp evaluates it, and the mount fails with an unknown-variable
// line in game_errors.log -- loud, but only if you look.
object_event_add(ctr_Ship,  0, 0, 'UmbraCloak = global.bsf_umbracloak;' +
                                  'EUmbraCloak = global.bsf_eumbracloak;');
object_event_add(ctr_EShip, 0, 0, 'UmbraCloak = global.bsf_eumbracloak;' +
                                  'EUmbraCloak = global.bsf_eumbracloak;');

// =========================================================================
// 2. THE CONTROLLER
// =========================================================================
var ctl, body, bnd, rst, n, ins;

ctl = object_add();
object_set_persistent(ctl, 1);

// --- the per-ship pass -----------------------------------------------------
// Written once and installed twice, once per module object, with OBJ replaced.
// End Step: after the game has moved everything and before any Draw, which is
// where fastdraw.gml owns `visible` for the same reason -- a Step-time write
// would be one frame stale.
body =
  'with (OBJ) {' +
  '  if (instance_exists(l_owner)) {' +
  '    var sh, mid;' +
  '    mid = id;' +
  '    sh = l_owner;' +
  '    with (sh) {' +

// ---- lazy init. ctr_Ship's Create exits before an append in gameplay rooms,
//      so the state is created the first time it is needed instead.
  '      if (!variable_local_exists("l_cloak_now")) {' +
  '        l_cloak_now = 1; l_cloak_want = 1; l_cloak_lock = 0;' +
  '        l_cloak_hidden = 0;' +
  '        ck_bud = 100; ck_dw = 0; ck_lk = 0; ck_slot = -1;' +
  '        ck_np = 0; ck_rescan = 0; ck_seen = 0; ck_hd = depth;' +
  '        ck_ft = 0; ck_eg = 0; ck_hp2 = 0; ck_live = 0;' +
  '        ck_ft0 = 0; ck_eg0 = 0; ck_hp0 = 0; ck_live0 = 0;' +
  '      }' +

// ---- the part list. Every part of a ship carries l_owner pointing at it --
//      initSections, initWeapons and initDoodad all set it -- so that is the
//      discriminator. Rescanned only while fully visible, because the stored
//      depth would otherwise be one we had already taken over.
  '      ck_rescan -= 1;' +
  '      if (ck_rescan <= 0) {' +
  '        if (l_cloak_now >= 1) {' +
  '          ck_rescan = 30;' +
  '          ck_np = 0; ck_hd = depth;' +
  '          var sid;' +
  '          sid = id;' +
  '          with (all) {' +
  '            if (variable_local_exists("l_owner")) {' +
  '              if (l_owner == sid) {' +
  '                if (sid.ck_np < 200) {' +
  '                  sid.ck_part[sid.ck_np] = id;' +
  '                  sid.ck_pd[sid.ck_np] = depth;' +
  '                  sid.ck_np += 1;' +
  '                }' +
  '              }' +
  '            }' +
  '          }' +
  '        }' +
  '      }' +

// ---- census: hp, firing timers and energy across the parts. l_firingtimer
//      only ever counts DOWN, and firing resets it upward, so a rise in the sum
//      is a shot. Energy only falls when something is spent. The cloak's own
//      module is excluded or its drain would read as a module being used.
  '      var k, pid, sid2;' +
  '      sid2 = id;' +
  '      ck_ft = 0; ck_eg = 0; ck_hp2 = 0; ck_live = 0;' +
  '      for (k = 0; k < ck_np; k += 1) {' +
  '        pid = ck_part[k];' +
  '        if (instance_exists(pid)) {' +
  '          if (pid != mid) {' +
  '            with (pid) {' +
  '              sid2.ck_live += 1;' +
  '              if (variable_local_exists("l_hp")) sid2.ck_hp2 += l_hp;' +
  '              if (variable_local_exists("l_firingtimer")) sid2.ck_ft += l_firingtimer;' +
  '              if (variable_local_exists("l_eng")) sid2.ck_eg += l_eng;' +
  '            }' +
  '          }' +
  '        }' +
  '      }' +

// ---- the four decloak triggers. Firing, taking damage, colliding and using a
//      module. A collision registers through the damage it does, which is also
//      what keeps a nudge that costs no hull from strobing the ship.
  '      var trig;' +
  '      trig = 0;' +
  '      if (ck_seen == 1) {' +
  '        if (l_hp + ck_hp2 < ck_hp0 - 0.001) trig = 1;' +
  '        if (ck_live < ck_live0) trig = 1;' +
  '        if (ck_ft > ck_ft0 + 0.5) trig = 1;' +
  '        if (ck_eg < ck_eg0 - 0.5) trig = 1;' +
  '      }' +
  '      ck_seen = 1;' +
  '      ck_hp0 = l_hp + ck_hp2; ck_live0 = ck_live;' +
  '      ck_ft0 = ck_ft; ck_eg0 = ck_eg;' +

// ---- proximity, and it is fully symmetric. A cloaked ship with a hostile
//      inside THAT HOSTILE's ai_range is forced visible, whichever team it is
//      on -- so closing the distance is the counter, and no detector had to be
//      invented. The lockout is what stops a patrol skimming the radius edge
//      from strobing the ship.
  '      var det, sx, sy;' +
  '      det = 0; sx = x; sy = y;' +
  '      if (l_targettype >= 0) {' +
  '        with (l_targettype) {' +
  '          if (point_distance(x, y, sx, sy) <= ai_range) det = 1;' +
  '        }' +
  '      }' +
  '      if (det == 1) ck_lk = global.ck_lock;' +
  '      if (trig == 1) ck_lk = global.ck_lock;' +
  '      if (det == 0) { if (trig == 0) { if (ck_lk > 0) ck_lk -= 1; } }' +

// ---- the budget. Drains while moving, regenerates only after holding still
//      for the dwell. Zero forces a decloak and the cloak cannot re-engage
//      until it climbs back past the threshold, so running dry in a patrol lane
//      is a real crisis and freezing is a real tactic.
  '      var mov;' +
  '      mov = 0;' +
  '      if (speed > global.ck_slow) mov = 1;' +
  '      if (mov == 1) ck_dw = 0;' +
  '      if (mov == 0) { if (ck_dw < global.ck_dwell) ck_dw += 1; }' +
  '      if (l_cloak_now < 1) { if (mov == 1) ck_bud -= global.ck_drain; }' +
  '      if (ck_dw >= global.ck_dwell) ck_bud += global.ck_regen;' +
  '      if (ck_bud < 0) ck_bud = 0;' +
  '      if (ck_bud > 100) ck_bud = 100;' +

// ---- want, unless a mission has taken the wheel
  '      if (l_cloak_lock == 0) {' +
  '        if (ck_bud <= 0) l_cloak_want = 0;' +
  '        if (ck_bud >= global.ck_reeng) l_cloak_want = 1;' +
  '      }' +

// ---- what the ship is actually doing this frame
  '      var eng;' +
  '      eng = l_cloak_want;' +
  '      if (ck_lk > 0) eng = 0;' +
  '      if (ck_bud <= 0) eng = 0;' +

// ---- the transition, symmetric and two seconds either way. Targetability
//      flips at the START of either one: vulnerable the instant a decloak
//      begins, untargetable the instant a re-cloak begins while still visibly
//      fading in. That is the generous direction, and worth watching in play.
  '      var tgt, stp2;' +
  '      tgt = 1; if (eng == 1) tgt = 0;' +
  '      stp2 = 1 / global.ck_trans;' +
  '      if (l_cloak_now < tgt) { l_cloak_now += stp2; if (l_cloak_now > tgt) l_cloak_now = tgt; }' +
  '      if (l_cloak_now > tgt) { l_cloak_now -= stp2; if (l_cloak_now < tgt) l_cloak_now = tgt; }' +
  '      l_cloak_hidden = 0;' +
  '      if (tgt < 0.5) l_cloak_hidden = 1;' +

// ---- how it renders. The player keeps a dim ghost and stays commandable;
//      everyone else goes all the way out. A settled invisible ship needs no
//      shader and no slot -- `visible` is exact and free -- so a slot is only
//      ever held by a ship mid-transition or by the player's own ghost.
  '      var vis, need;' +
  '      vis = l_cloak_now;' +
  '      if (l_myship == 1) { if (vis < global.ck_ghost) vis = global.ck_ghost; }' +
  '      need = 0;' +
  '      if (vis < 1) need = 1;' +
  '      if (l_myship == 0) { if (l_cloak_now <= 0) need = 0; }' +
  '      if (global.ck_h < 0) need = 0;' +

// ---- claim or release the slot
  '      if (need == 1) {' +
  '        if (ck_slot < 0) {' +
  '          var q;' +
  '          for (q = 0; q < global.ck_nslot; q += 1) {' +
  '            if (ck_slot < 0) {' +
  '              if (global.ck_ship[q] == noone) { global.ck_ship[q] = sid2; ck_slot = q; }' +
  '            }' +
  '          }' +
  '        }' +
  '      } else {' +
  '        if (ck_slot >= 0) { global.ck_ship[ck_slot] = noone; ck_slot = -1; }' +
  '      }' +

// ---- and apply it. Three cases, and every one of them writes every part, so
//      nothing is left holding a value from the case before.
  '      var D, al, vsb, k2, p2;' +
  '      if (ck_slot >= 0) {' +
  '        D = global.ck_dbase - ck_slot * global.ck_dstep;' +
  '        global.ck_prog[ck_slot] = vis;' +
  '        al = 1; vsb = 1;' +
  '      } else {' +
  '        D = -1000000;' +
  '        al = vis; vsb = 1;' +
  '        if (l_myship == 0) { if (l_cloak_now <= 0) vsb = 0; }' +
  '      }' +
  '      if (D > -999999) depth = D; else depth = ck_hd;' +
  '      image_alpha = al;' +
  '      visible = vsb;' +
  '      for (k2 = 0; k2 < ck_np; k2 += 1) {' +
  '        p2 = ck_part[k2];' +
  '        if (instance_exists(p2)) {' +
  '          if (D > -999999) p2.depth = D; else p2.depth = ck_pd[k2];' +
  '          p2.image_alpha = al;' +
  '          p2.visible = vsb;' +
  '        }' +
  '      }' +
  '    }' +
  '  }' +
  '}';

object_event_add(ctl, 3, 2, string_replace(body, 'OBJ', 'global.bsf_umbracloak'));
object_event_add(ctl, 3, 2, string_replace(body, 'OBJ', 'global.bsf_eumbracloak'));

// --- slot sweep ------------------------------------------------------------
// A ship that dies takes its module with it, so nothing above ever runs again
// for that slot and the band would be held forever. Rule 3 puts this in its own
// action: if the pass above throws, this still runs.
object_event_add(ctl, 3, 2,
    'global.ck_time += 1/room_speed;' +
    'var s;' +
    'for (s = 0; s < global.ck_nslot; s += 1) {' +
    '  if (global.ck_ship[s] != noone) {' +
    '    if (!instance_exists(global.ck_ship[s])) global.ck_ship[s] = noone;' +
    '  }' +
    '}');

// =========================================================================
// 3. AI BLINDNESS
// =========================================================================
// One append, after the stock alarm[0] has built l_targets. Both of that
// event's branches populate the same map -- the l_ailevel = 1 branch ends
// `ds_map_add(l_targets, dis, tar)` -- so this covers both, and every turret on
// the ship pulls from l_owner.l_targets on the following step and therefore
// reads the cleaned version.
//
// Keys are collected before anything is deleted: mutating a ds_map while
// iterating it with find_first/find_next is not safe.
//
// KNOWN LIMIT: shipAI() runs at the end of the stock body, so the ship's own
// movement AI sees one stale tick before this runs. Turret targeting -- the half
// that actually shoots -- does not.
var blind;
blind =
  'var mk, mv, dn, dl, j;' +
  'if (l_targets >= 0) {' +
  '  dn = 0;' +
  '  mk = ds_map_find_first(l_targets);' +
  '  while (!is_undefined(mk)) {' +
  '    mv = ds_map_find_value(l_targets, mk);' +
  '    if (instance_exists(mv)) {' +
  '      if (mv.l_cloak_hidden_ok == 1) {' +
  '        if (mv.l_cloak_hidden == 1) { dl[dn] = mk; dn += 1; }' +
  '      }' +
  '    }' +
  '    mk = ds_map_find_next(l_targets, mk);' +
  '  }' +
  '  for (j = 0; j < dn; j += 1) ds_map_delete(l_targets, dl[j]);' +
  '}' +
  'if (instance_exists(l_target)) {' +
  '  if (l_target.l_cloak_hidden_ok == 1) {' +
  '    if (l_target.l_cloak_hidden == 1) l_target = -4;' +
  '  }' +
  '}';
object_event_add(ctr_Ship,  2, 0, blind);
object_event_add(ctr_EShip, 2, 0, blind);

// Every hull carries the flag, so the map walk above can read it without a
// variable_local_exists per entry per tick. Set from the controller rather than
// from a Create append, for the rm_ChooseShips reason.
object_event_add(ctl, 3, 2,
    'with (ctr_Ship)  { if (!variable_local_exists("l_cloak_hidden_ok")) { l_cloak_hidden_ok = 1; l_cloak_hidden = 0; } }' +
    'with (ctr_EShip) { if (!variable_local_exists("l_cloak_hidden_ok")) { l_cloak_hidden_ok = 1; l_cloak_hidden = 0; } }');

// --- engaging the cloak clears every hostile lock pointing at you -----------
// A turret holds its own c_target / l_target and keeps firing while in range,
// so blinding the map alone leaves existing locks live. Bullets already in
// flight keep their heading and still collide, and the AI keeps shooting the
// last known point for a beat, which is the intended read.
object_event_add(ctl, 3, 2,
    'with (ctr_Turrets) {' +
    '  if (variable_local_exists("c_target")) {' +
    '    if (instance_exists(c_target)) {' +
    '      if (c_target.l_cloak_hidden_ok == 1) { if (c_target.l_cloak_hidden == 1) c_target = -4; }' +
    '    }' +
    '  }' +
    '}' +
    'with (ctr_ETurrets) {' +
    '  if (variable_local_exists("c_target")) {' +
    '    if (instance_exists(c_target)) {' +
    '      if (c_target.l_cloak_hidden_ok == 1) { if (c_target.l_cloak_hidden == 1) c_target = -4; }' +
    '    }' +
    '  }' +
    '}');

// =========================================================================
// 4. THE SANDWICH
// =========================================================================
// One binder and one resetter per slot, pre-created at fixed depths so that
// nothing is created or destroyed while the draw order is being walked. Each
// reads its own slot number off itself; an unused slot costs one comparison.
bnd = object_add();
object_set_persistent(bnd, 1);
object_event_add(bnd, 8, 0,
    'if (global.ck_h >= 0) {' +
    '  if (global.ck_ship[ckn] != noone) {' +
    '    external_call(global.sh_const, 0, global.ck_prog[ckn], global.ck_time, global.ck_ripple, 0);' +
    '    external_call(global.sh_const, 1, 0, 0, global.ck_umax, global.ck_vmax);' +
    '    external_call(global.sh_set, global.ck_h);' +
    '  }' +
    '}');

rst = object_add();
object_set_persistent(rst, 1);
object_event_add(rst, 8, 0,
    'if (global.ck_h >= 0) {' +
    '  if (global.ck_ship[ckn] != noone) external_call(global.sh_reset);' +
    '}');

ins = instance_create(0, 0, ctl);
ins.persistent = true;
ins.depth = -10000005;

for (n = 0; n < global.ck_nslot; n += 1) {
    ins = instance_create(0, 0, bnd);
    ins.persistent = true;
    ins.ckn = n;
    ins.depth = global.ck_dbase - n * global.ck_dstep + global.ck_deps;

    ins = instance_create(0, 0, rst);
    ins.persistent = true;
    ins.ckn = n;
    ins.depth = global.ck_dbase - n * global.ck_dstep - global.ck_deps;
}

// =========================================================================
// 5. THE REGRESSION RIG
// =========================================================================
// The demo this file used to be is the only thing that verifies bsfshader.c and
// the HLSL after a change, so it is kept rather than deleted -- behind its own
// marker, so it costs a player nothing. `touch mods/cloak_demo.on` with
// mods/battle.on and a one-ship mods/battle.cfg puts a ship in rm_Sandbox on a
// fixed step count and captures a 36-frame strip across one forced transition,
// a noise-floor pair, an adjacent bound/unbound pair, and mods/cloak.txt.
//
// screen_save in Step captures the frame drawn LAST tick (every Step runs before
// every Draw), so a capture at rtick N+1 is named for frame N.
if (file_exists('mods/cloak_demo.on')) {
    var dmo, dins;
    dmo = object_add();
    object_set_persistent(dmo, 1);
    object_event_add(dmo, 0, 0, 'rtick = 0;');
    object_event_add(dmo, 3, 0,
        'if (room == rm_Sandbox) {' +
        '  rtick += 1;' +
        '  if (rtick == 150) {' +
        '    with (ctr_Ship) { l_cloak_lock = 1; l_cloak_want = 0; l_cloak_now = 0; }' +
        '  }' +
        '  if (rtick == 151) { with (ctr_Ship) l_cloak_want = 1; }' +
        '  if (rtick == 141) screen_save("mods/dc_n0.png");' +
        '  if (rtick == 142) screen_save("mods/dc_n1.png");' +
        '  if (rtick >= 149) { if (rtick <= 289) {' +
        '    if ((rtick - 149) mod 4 == 0)' +
        '      screen_save("mods/dcf" + string((rtick - 149) / 4) + ".png"); } }' +
        '  if (rtick == 291) screen_save("mods/dc_bound.png");' +
        '  if (rtick == 292) screen_save("mods/dc_off.png");' +
        '  if (rtick == 295) {' +
        '    var f;' +
        '    f = file_text_open_write("mods/cloak.txt");' +
        '    file_text_write_string(f, "handle=" + string(global.ck_h)' +
        '      + " slots=" + string(global.ck_nslot)' +
        '      + " binds=" + string(external_call(global.sh_stat, 2))' +
        '      + " fails=" + string(external_call(global.sh_stat, 3))' +
        '      + " err=" + string(external_call(global.sh_err)));' +
        '    file_text_writeln(f); file_text_close(f);' +
        '  }' +
        '  if (rtick == 310) game_end();' +
        '}');
    dins = instance_create(0, 0, dmo);
    dins.persistent = true;
    dins.depth = -10000006;
}

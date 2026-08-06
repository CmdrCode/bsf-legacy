// Battleships Forever -- view-frustum cull for the battle rooms.
//
// Chained from init.gml. Unlike the rest of the mod this changes what the game
// does rather than how it is presented, so it is opt-out via mods/fastdraw.off.
//
// ------------------------------------------------------------------ why
// Not fill rate, and not the interpreter. An empty 4000-iteration GML loop does
// not register at 1 ms resolution, and with the camera pinned so the draw-call
// count provably does not move, cutting rasterised pixels 70x moves draw_ms by
// under 1 ms at 3840x2160. A 20-ship fight is ~250 sections, ~240 turrets and
// ~280 doodads, and BSF processes every one of them whether or not it is on
// screen. Skipping the off-screen ones is the only lever that scales with the
// problem; the stock quality switches (gradients, shimmer, particles) all
// measured inside run-to-run noise.
//
// !! WHAT it saves was revised, and the earlier answer is worth recording because
// it was measured and still wrong. This file originally claimed a draw call costs
// ~15 us (draw_sprite_ext 14.75, draw_sprite_general 14.25) and that the frame is
// therefore draw-CALL bound. Those numbers were taken on an unpatched SWVP device,
// where wined3d turns every DrawPrimitiveUP into two synchronous command-stream
// round-trips -- so they measured the SWVP tax, not the draw call. On the patched
// HWVP device a draw call is 1.3 us. Splitting ctr_Turrets' Draw over 7 reps:
//
//   the draw_sprite_ext itself     1.14 ms/frame   1.3 us per turret
//   GM's per-instance dispatch     4.44 ms/frame   5.0 us per turret
//   whole event                    5.58 ms/frame   6.3 us per turret
//
// ~80% of the cost is GM getting to the event. The cull still earns its keep, but
// because `visible = 0` skips a DISPATCH, not because it skips a graphics call.
//
// -------------------------------------------------------------- what it skips
// Hull sections, turrets and doodads -- objects whose Draw event only draws.
//
// NOT projectiles or beams, deliberately. At least one beam counts its lifetime
// down inside its Draw event and destroys itself there, so an off-screen beam
// that stopped drawing would also stop expiring. Anything whose Draw has side
// effects has to keep drawing.
//
// ---------------------------------------------------------------- `visible`
// The cull owns `visible` outright and recomputes it every frame from scratch.
// That is only safe because BSF barely uses it: the whole game contains five
// assignments to `visible`, all but one in a Create event, and a census of a live
// 16-ship battle found every section, turret and doodad visible. The one authored
// `visible = 0` is a structural section that carries children and draws nothing,
// and those are excluded here by having no sprite rather than by remembering
// per-instance state.
//
// ⚠ Two approaches to remembering that state were tried and both cost more than
// the cull saved, or worse:
//
//   * `variable_local_exists("fd_last")` per instance per frame -- 23 ms of extra
//     step time on its own. BSF instances carry well over a hundred instance
//     variables and the lookup is not free at that size. Anything running once
//     per instance per frame has to be arithmetic, not a name lookup.
//   * seeding the variables from `object_event_add(obj, ev_create, 0, ...)` on the
//     stock section/turret objects -- this does not append to a stock object's
//     Create the way it appends to one built by object_add(). The ships' own
//     initialisation stopped running and the run produced 610,000 errors.

if (variable_global_exists('bsf_fastdraw')) exit;
global.bsf_fastdraw = 1;

var c, i, cull;

// sprite_index < 0 is a section that exists to hold children, not to be seen.
// The margin covers the largest section half-extent, so a sprite whose origin has
// just left the view is still drawn while part of it is on screen.
cull = 'visible = (sprite_index >= 0)' +
       ' && (x > vx) && (x < vr) && (y > vy) && (y < vb);';

c = object_add();

// End Step: after GM has applied built-in movement, before any Draw runs. A
// Step-time cull would be one frame stale, which pops sections at the screen edge.
object_event_add(c, 3, 2,
    'if (!view_visible[0]) exit;' +
    'var vx, vy, vr, vb;' +
    'vx = view_xview[0] - 160;' +
    'vy = view_yview[0] - 160;' +
    'vr = view_xview[0] + view_wview[0] + 160;' +
    'vb = view_yview[0] + view_hview[0] + 160;' +
    'with (ShipSection)  {' + cull + '}' +
    'with (EShipSection) {' + cull + '}' +
    'with (ctr_Turrets)  {' + cull + '}' +
    'with (ctr_ETurrets) {' + cull + '}' +
    'with (ctr_Doodads)  {' + cull + '}');

i = instance_create(0, 0, c);
i.persistent = true;
i.depth = -10000006;

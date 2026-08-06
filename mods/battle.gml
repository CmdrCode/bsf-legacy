// Scripted, repeatable battle -- the standing stress test.
//
// Chained from init.gml when mods/battle.on exists. Instrumentation only: it
// spawns stock objects into the stock sandbox room and touches nothing else.
//
//   mods/battle.cfg    the scenario (format below)
//   mods/battle.txt    state, rewritten every 10 steps
//   mods/battle.log    breadcrumb, appended as this file loads
//
// ------------------------------------------------------------- why not a timer
// Everything here is scheduled on a ROOM-RELATIVE STEP COUNT, never on wall
// clock, and the generator is seeded explicitly on arrival. Three things:
//
//   * BSF's GML contains ZERO references to current_time (grep: 0 hits across
//     all 3.4 MB of it), so the simulation is a pure fixed-step machine. A frame
//     that took 66 ms and a frame that took 33 ms advance it identically. That
//     is what lets a 15 fps scene be compared against a 30 fps one at all.
//   * `enter` fixes the menu dwell in STEPS. The menus draw from the generator
//     every step they exist, so dwelling for a wall-clock-dependent number of
//     steps would start the battle at a different point in the sequence.
//   * `seed` is set on arrival in the battle room.
//
// ⚠ That last one is not belt-and-braces, it is the load-bearing part, and it
// contradicts what campaign.gml and gameplay.py assert. Their premise is that
// GM 7's generator is unseeded -- BSF calls no randomize() -- so the sequence is
// fixed from process start and a battle replays on its own. MEASURED: three
// launches, `random_get_seed()` read at step 5 of rm_MainMenu, gave 1832298077,
// -358166832 and -239021209. The state is NOT fixed across launches, whatever
// the GML does or does not call, so scheduling alone buys a battle that
// reproduces its load to a couple of percent and nothing tighter. Seeding
// explicitly is what actually makes it replay.
//
// ---------------------------------------------------------------- cfg format
// One value per line, in this order:
//
//   room_w        rm_Sandbox width  in world units (stock sandbox is 2048)
//   room_h        rm_Sandbox height
//   enter         step of rm_MainMenu at which to jump into the sandbox.
//                 0 leaves entry to the harness's `sandbox` lever, which is
//                 NOT deterministic -- use it only when exploring.
//   seed          random_set_seed() value, applied on the first step in the
//                 battle room. 0 = leave the generator alone.
//   nwaves
//   then nwaves blocks of SEVEN lines:
//     step        room-relative step at which the wave first fires
//     object      object name, e.g. Hecate or EPirate05
//     count       how many
//     cx, cy      centre of the block, in world units
//     spread      spacing between neighbours in the block
//     period      0 = fire once; >0 = refire every `period` steps, forever
//
// `period` is what makes the load STATIONARY. A one-shot fleet fight decays --
// 10 v 10 Hecates against EPirate05 falls from 1041 instances to 750 in thirty
// seconds and the numbers measured on the way down belong to no particular
// scene. A reinforcement cadence tuned near the death rate holds the population
// on a plateau, which is the only regime in which an A/B of two configs a few
// seconds apart means anything.
//
// ⚠ Placement is a fixed grid, never random(). A spawner that draws from the
// generator would advance it by a count that depends on how many ships happen to
// be alive, and the replay guarantee above would be worth nothing.

if (variable_global_exists('bsf_battle')) exit;
global.bsf_battle = 1;

var o, i, lf;

lf = file_text_open_write('mods/battle.log');
file_text_write_string(lf, 'start'); file_text_writeln(lf); file_text_close(lf);

o = object_add();

object_event_add(o, 0, 0,
    'bstep = 0; broom = -1; bloaded = 0; bn = 0; benter = 0; bfired = 0;' +
    'brw = 2048; brh = 2048; bwaves = 0; bspawned = 0; bseed = 0; bseeded = 0;');

// ------------------------------------------------------------------ cfg load
object_event_add(o, 3, 1,
    'if (bloaded) exit;' +
    'if (!file_exists("mods/battle.cfg")) exit;' +
    'var g, j, k, nm, oid;' +
    'g = file_text_open_read("mods/battle.cfg");' +
    'brw    = real(file_text_read_string(g)); file_text_readln(g);' +
    'brh    = real(file_text_read_string(g)); file_text_readln(g);' +
    'benter = real(file_text_read_string(g)); file_text_readln(g);' +
    'bseed  = real(file_text_read_string(g)); file_text_readln(g);' +
    'bn     = real(file_text_read_string(g)); file_text_readln(g);' +
    'for (j = 0; j < bn; j += 1) {' +
    '  bw_step[j]  = real(file_text_read_string(g)); file_text_readln(g);' +
    '  bw_name[j]  =      file_text_read_string(g);  file_text_readln(g);' +
    '  bw_count[j] = real(file_text_read_string(g)); file_text_readln(g);' +
    '  bw_cx[j]    = real(file_text_read_string(g)); file_text_readln(g);' +
    '  bw_cy[j]    = real(file_text_read_string(g)); file_text_readln(g);' +
    '  bw_sp[j]    = real(file_text_read_string(g)); file_text_readln(g);' +
    '  bw_per[j]   = real(file_text_read_string(g)); file_text_readln(g);' +
    '  bw_next[j]  = bw_step[j];' +
    '  bw_oid[j]   = -1;' +
    '}' +
    'file_text_close(g);' +
    // Resolve every name to an object id ONCE. Doing it per wave would put a
    // 1200-iteration scan inside the spawn frame, which is exactly the kind of
    // hitch that lands in whatever window the profiler happens to be closing.
    'for (k = 0; k < 1200; k += 1) {' +
    '  if (!object_exists(k)) continue;' +
    '  nm = object_get_name(k);' +
    '  for (j = 0; j < bn; j += 1) { if (bw_name[j] == nm) bw_oid[j] = k; }' +
    '}' +
    'bloaded = 1;' +
    'var lg; lg = file_text_open_append("mods/battle.log");' +
    'file_text_write_string(lg, "cfg " + string(bn) + " waves room " + string(brw) + "x" + string(brh));' +
    'file_text_writeln(lg);' +
    'for (j = 0; j < bn; j += 1) {' +
    '  file_text_write_string(lg, "  wave " + string(j) + " " + bw_name[j] + " oid=" + string(bw_oid[j]) +' +
    '    " x" + string(bw_count[j]) + " @" + string(bw_step[j]) + " per=" + string(bw_per[j]));' +
    '  file_text_writeln(lg);' +
    '}' +
    'file_text_close(lg);');

// -------------------------------------------------------------- step counter
// Room-relative, reset on every transition, so a wave's `step` means the same
// thing however long the launch spent in the menus.
object_event_add(o, 3, 1,
    'if (room != broom) { broom = room; bstep = 0; bfired = 0; bspawned = 0; bseeded = 0; }' +
    'else bstep += 1;');

// -------------------------------------------------------------------- seed
// Re-applied on the first Begin Step of EVERY room, not just the battle room.
//
// ⚠ Seeding only on arrival in rm_Sandbox is not enough, and the reason is not
// the generator. rm_MainMenu runs its own ship battle, which creates and destroys
// instances from an unseeded sequence, so the instance-ID watermark handed to the
// next room differs between launches -- and BSF's target selection resolves ties
// in ID order. Measured: seeding at the sandbox only took the worst run-to-run
// spread from 181 instances to 113, not to 0.
//
// What this still cannot cover is a room's own construction: instances placed in
// the room and their Create events run before any Begin Step, so a creation-time
// draw is made from whatever state the previous room left.
object_event_add(o, 3, 1,
    'if (!bloaded) exit;' +
    'if (bseed == 0) exit;' +
    'if (bseeded) exit;' +
    'bseeded = 1;' +
    'random_set_seed(bseed);');

// ------------------------------------------------------------------ seed log
// random_get_seed() READS the generator without drawing from it, so this is free
// and cannot itself perturb a replay. Logged because the replay premise -- "BSF
// calls no randomize(), so the sequence is fixed from process start" -- is a
// claim about BSF's GML, not about what the GM 7 runner does before any GML runs.
// Two launches reporting two seeds settles it in one line.
object_event_add(o, 3, 1,
    'if (bstep != 5) exit;' +
    'var sl; sl = file_text_open_append("mods/battle.log");' +
    'file_text_write_string(sl, "seed " + string(random_get_seed()) + " room " + room_get_name(room));' +
    'file_text_writeln(sl); file_text_close(sl);');

// -------------------------------------------------------------- deterministic entry
// Replicates perf.gml's `sandbox` lever verbatim -- itself a transcription of the
// stock Sandbox menu button -- but fires it on a step count instead of on a file
// appearing, so the generator is at the same position every launch.
object_event_add(o, 3, 1,
    'if (!bloaded) exit;' +
    'if (benter <= 0) exit;' +
    'if (bfired) exit;' +
    'if (room != rm_MainMenu) exit;' +
    'if (bstep < benter) exit;' +
    'bfired = 1;' +
    'sound_stop_all();' +
    'global.l_width = brw; global.l_height = brh;' +
    'global.gamemode = 5;' +
    'with (all) { event_user(14); }' +
    'room_set_width(rm_Sandbox, brw);' +
    'room_set_height(rm_Sandbox, brh);' +
    'room_goto(rm_Sandbox);');

// -------------------------------------------------------------------- waves
// Fired from Step (not Begin Step) so the instances created here get their own
// Begin Step on the following frame rather than a half-frame of this one.
object_event_add(o, 3, 0,
    'if (!bloaded) exit;' +
    'if (room != rm_Sandbox) exit;' +
    'var j, k, cols, rows, cc, rr, sx, sy;' +
    'for (j = 0; j < bn; j += 1) {' +
    '  if (bw_oid[j] < 0) continue;' +
    '  if (bw_next[j] < 0) continue;' +
    '  if (bstep < bw_next[j]) continue;' +
    '  cols = ceil(sqrt(bw_count[j]));' +
    '  if (cols < 1) cols = 1;' +
    '  rows = ceil(bw_count[j] / cols);' +
    '  for (k = 0; k < bw_count[j]; k += 1) {' +
    '    rr = floor(k / cols); cc = k - rr * cols;' +
    '    sx = bw_cx[j] + (cc - (cols - 1) / 2) * bw_sp[j];' +
    '    sy = bw_cy[j] + (rr - (rows - 1) / 2) * bw_sp[j];' +
    '    instance_create(sx, sy, bw_oid[j]);' +
    '    bspawned += 1;' +
    '  }' +
    '  if (bw_per[j] > 0) bw_next[j] = bstep + bw_per[j]; else bw_next[j] = -1;' +
    '}');

// -------------------------------------------------------------------- report
object_event_add(o, 3, 2,
    'if (bstep mod 10 != 0) exit;' +
    'var bf;' +
    'bf = file_text_open_write("mods/battle.txt");' +
    'file_text_write_string(bf, "room=" + room_get_name(room)' +
    '  + " step=" + string(bstep)' +
    '  + " spawned=" + string(bspawned)' +
    '  + " ships=" + string(instance_number(ctr_Ship))' +
    '  + " eships=" + string(instance_number(ctr_EShip))' +
    '  + " sections=" + string(instance_number(ShipSection) + instance_number(EShipSection))' +
    '  + " turrets=" + string(instance_number(ctr_Turrets) + instance_number(ctr_ETurrets))' +
    '  + " bullets=" + string(instance_number(ctr_AllBullets))' +
    '  + " beams=" + string(instance_number(ctr_AllBeams))' +
    '  + " doodads=" + string(instance_number(ctr_Doodads))' +
    '  + " instances=" + string(instance_count));' +
    'file_text_writeln(bf); file_text_close(bf);');

i = instance_create(0, 0, o);
i.persistent = true;
i.depth = -10000003;

lf = file_text_open_append('mods/battle.log');
file_text_write_string(lf, 'ok'); file_text_writeln(lf); file_text_close(lf);

// The mission editor's channel into a running game.  Gate: mods/editor.on
//
// The editor is a browser app with a dev server beside it; this is the half that
// lives inside the game. It does four things: boot into a mission named on the
// command line, take commands from a file, freeze and unfreeze the world, and
// publish enough state back that the editor can draw a playhead and a ghost
// overlay over its own prediction.
//
// ---------------------------------------------------------------- the channel
//
//   mods/edit/cmd     in    two lines: a sequence number, then one command
//   mods/edit/ack     out   "<seq> ok|err <message>" for the command just run
//   mods/edit/state   out   room / mission / beat / pause, every 10 steps and
//                           immediately whenever the beat changes
//   mods/edit/dump    out   every live instance, written by the `dump` verb
//
// Commands, and nothing else is accepted:
//
//   open <n>     enter mission n through the real menu sequence
//   seek <n>     fast-forward the mission controller to rung n (forward only)
//   pause 0|1    unfreeze / freeze the world
//   edit 0|1     real rules / editor rules (no storm damage, no missionFail)
//   reload       re-execute the current mission mod after a rebuild
//   dump         write mods/edit/dump
//   gml <code>   execute_string, the deliberate escape hatch
//
// ⚠ The command file must be written atomically -- write mods/edit/cmd.tmp and
// rename it over mods/edit/cmd. A poll landing mid-write reads half a command,
// and a half-command is a GM7 syntax error, which is silent.
//
// ⚠ Why one file with a verb rather than one file per command. `file_exists`
// costs 80.6 us a call under wine on the reference setup (measured: 5,000
// calls in 403 ms, against 0 ms for the same loop doing nothing). One poll a
// step is 0.24% of a 30 fps frame and is affordable; eight would not be, which
// is why mods/campaign.gml gates its polls on `ctick mod 6`. If the poll ever
// does show up in a profile, `directory_exists` measured 7.6 us and would serve
// as a cheaper doorbell in front of the read.
//
// ⚠ This supersedes mods/campaign.gml's `mission` / `adv` pokes for Act II. That
// file stays in the research install as rendering instrumentation; the editor
// does not depend on it, because it is not in this repository.
//
// ⚠ Build the line, then open the file. A GML error aborts the action where it
// stands, so anything that can throw between file_text_open_* and file_text_close
// leaks the handle -- and once about thirty have leaked GM reports "File is not
// opened for reading", an error about a file, nowhere near the cause. Reading an
// engine global that does not exist yet is the usual way to throw: `global.mission`
// is unset until a mission has been entered, which is why every global here that
// this file did not itself declare goes through variable_global_exists.
//
// ⚠ Entry is the game's own sequence -- global.mission, the global teardown,
// then rm_Briefing -- and never room_goto into a mission room. Jumping straight
// in leaves the globals the controller reads unset, so it throws every frame and
// half the scene never spawns.

if (variable_global_exists('ed_on')) exit;
global.ed_on = 1;

directory_create('mods/edit');

var lf;
lf = file_text_open_write('mods/edit/editor.log');
file_text_write_string(lf, 'start'); file_text_writeln(lf); file_text_close(lf);

// Shared with the generated mission mods, which declare them under the same
// guard -- whichever file loads first wins and the other leaves them alone.
if (!variable_global_exists('ed_edit')) global.ed_edit = 0;
if (!variable_global_exists('ed_pause')) global.ed_pause = 0;
if (!variable_global_exists('ed_beat')) { global.ed_beat = -1; global.ed_beatseq = 0; }

global.ed_arg = 0;              // the numeric argument of the command in hand
global.ed_ok = 0;
global.ed_res = '';
global.ed_next = -1;
global.ed_boot = -1;            // mission to enter at startup, from the argv
global.ed_stride = 1;           // steps between channel polls

// ------------------------------------------------------------------ the argv
// `<game> mission_editor 8` boots straight into EP9. ctr_Testroom already reads
// a .shp path out of the argv the same way, so the launcher only had to start
// forwarding arguments.
//
// ⚠ real() on a non-numeric string aborts the rest of the file, silently. The
// argument is checked before it is converted, never after.
var pk, pc, ps;
pc = parameter_count();
for (pk = 1; pk <= pc; pk += 1) {
    if (parameter_string(pk) == 'mission_editor') {
        if (pk < pc) {
            ps = parameter_string(pk + 1);
            if (string_length(ps) > 0) {
                if (string_digits(ps) == ps) global.ed_boot = real(ps);
            }
        }
    }
}

// Poll cadence, if the machine this runs on turns out to be slower than the one
// the 80.6 us above was measured on.
if (file_exists('mods/edit/stride')) {
    var sf, sv;
    sf = file_text_open_read('mods/edit/stride');
    sv = file_text_read_string(sf);
    file_text_close(sf);
    if (string_length(sv) > 0) {
        if (string_digits(sv) == sv) global.ed_stride = max(1, real(sv));
    }
}

var o, ii;
o = object_add();

object_event_add(o, 0, 0,
    'estep = 0; eroom = -1; ewalk = 0; efired = 0; epub = 0; elastseq = -1;');

// ------------------------------------------------------- room bookkeeping
// Kept in its own action, and ahead of everything else: a room_goto only takes
// effect at the END of the step that issued it, so `efired` has to be cleared by
// noticing that the room actually changed rather than by the code that asked.
object_event_add(o, 3, 0,
    'if (room != eroom) { eroom = room; estep = 0; efired = 0; }' +
    'estep += 1;');

// ------------------------------------------------------------- boot + walk
// One shot, from the argv. The dwell before entering is not politeness: the main
// menu has to finish building before the global teardown will find anything to
// tear down.
object_event_add(o, 3, 0,
    'if (global.ed_boot < 0) exit;' +
    'if (room != rm_MainMenu) exit;' +
    'if (estep < 60) exit;' +
    'global.ed_arg = global.ed_boot;' +
    'global.ed_boot = -1;' +
    'event_user(0);');

// The briefing leg of the walk. For an Act II mission this is the only leg:
// mods/act2.gml intercepts Room Start in rm_ChooseShips and bounces it to the
// generated room, because Act II fleets are scripted and there is nothing to
// choose. An Act I mission would stop in the chooser with no fleet picked, which
// is why the editor lists Act II missions only.
object_event_add(o, 3, 0,
    'if (ewalk == 0) exit;' +
    'if (efired) exit;' +
    'if (room != rm_Briefing) exit;' +
    'if (estep < 20) exit;' +
    'if (!instance_exists(GUI_SecondDone)) exit;' +
    'efired = 1; ewalk = 0;' +
    'global.ed_next = -1;' +
    'with (GUI_SecondDone) global.ed_next = l_nextroom;' +
    'with (all) { event_user(14); }' +
    'if (global.ed_next >= 0) room_goto(global.ed_next);');

// ------------------------------------------------------------- the channel
object_event_add(o, 3, 0,
    'if (global.ed_stride > 1) { if ((estep mod global.ed_stride) != 0) exit; }' +
    'if (!file_exists("mods/edit/cmd")) exit;' +
    'var cf, cseq, cline, cverb, carg, csp, af;' +
    'cf = file_text_open_read("mods/edit/cmd");' +
    'cseq = file_text_read_string(cf); file_text_readln(cf);' +
    'cline = file_text_read_string(cf);' +
    'file_text_close(cf);' +
    'file_delete("mods/edit/cmd");' +
    'csp = string_pos(" ", cline);' +
    'if (csp == 0) { cverb = cline; carg = ""; }' +
    'else { cverb = string_copy(cline, 1, csp - 1); carg = string_delete(cline, 1, csp); }' +
    'global.ed_arg = 0;' +
    'if (string_length(carg) > 0) {' +
    '  if (string_digits(carg) == carg) global.ed_arg = real(carg);' +
    '}' +
    'global.ed_ok = 0;' +
    'global.ed_res = "unknown verb: " + cverb;' +
    'if (cverb == "open") {' +
    '  event_user(0);' +
    '  global.ed_ok = 1; global.ed_res = "entering mission " + string(global.ed_arg);' +
    '}' +
    'else if (cverb == "seek")   event_user(1);' +
    'else if (cverb == "pause")  event_user(2);' +
    'else if (cverb == "reload") event_user(3);' +
    'else if (cverb == "dump")   event_user(4);' +
    'else if (cverb == "edit") {' +
    '  global.ed_edit = global.ed_arg;' +
    '  global.ed_ok = 1;' +
    '  global.ed_res = "edit rules " + string(global.ed_edit);' +
    '}' +
    'else if (cverb == "gml") {' +
    // GM7 reports nothing back from execute_string -- a syntax error in the
    // payload is silent -- so the ack says only that it was handed over, and
    // never that it worked. That asymmetry is the whole reason the other six
    // verbs exist instead of this one.
    '  execute_string(carg);' +
    '  global.ed_ok = 1; global.ed_res = "handed to execute_string";' +
    '}' +
    'af = file_text_open_write("mods/edit/ack");' +
    'file_text_write_string(af, cseq + " ");' +
    'if (global.ed_ok) file_text_write_string(af, "ok ");' +
    'else file_text_write_string(af, "err ");' +
    'file_text_write_string(af, global.ed_res);' +
    'file_text_writeln(af); file_text_close(af);');

// -------------------------------------------------------- state publisher
// Every ten steps, and at once when a beat fires, so the playhead moves with the
// game rather than up to a third of a second behind it.
//
// ⚠ The whole line is built BEFORE the file is opened, and every global that is
// not ours is read through variable_global_exists. Those two rules are the same
// bug seen from both ends: `global.mission` does not exist until a mission has
// been entered, reading it aborts the action, and an abort between open and
// close leaks the handle. Ten steps later it leaks another, and about thirty
// steps after that GM runs out and starts reporting "File is not opened for
// reading" -- an error about a file, nowhere near the variable that caused it.
object_event_add(o, 3, 0,
    'epub += 1;' +
    'if (global.ed_beatseq != elastseq) { elastseq = global.ed_beatseq; epub = 999; }' +
    'if (epub < 10) exit;' +
    'epub = 0;' +
    'var pf, pmc, psf, pgc, pms, pline;' +
    'pmc = -1; psf = -1; pgc = 0; pms = -1;' +
    'if (variable_global_exists("mission")) pms = global.mission;' +
    'if (variable_global_exists("gamecontroller")) {' +
    '  if (instance_exists(global.gamecontroller)) {' +
    '    pgc = 1;' +
    '    with (global.gamecontroller) {' +
    '      pmc = l_messagecount;' +
    '      if (variable_local_exists("l_seek_from")) psf = l_seek_from;' +
    '    }' +
    '  }' +
    '}' +
    'pline = "room=" + room_get_name(room)' +
    '  + " roomw=" + string(room_width) + " roomh=" + string(room_height)' +
    // What the game actually got, as opposed to what mods/res.cfg asked for. The
    // window is the frame the compositor shows; the REGION is the drawing buffer,
    // and only the region says whether this is a native render or an upscale.
    // Reading it from the WM instead gives you decorations and reparenting.
    '  + " win=" + string(window_get_width()) + "x" + string(window_get_height())' +
    '  + " region=" + string(window_get_region_width())' +
    '    + "x" + string(window_get_region_height())' +
    '  + " fs=" + string(window_get_fullscreen())' +
    '  + " step=" + string(estep)' +
    '  + " mission=" + string(pms)' +
    '  + " ctr=" + string(pgc)' +
    '  + " count=" + string(pmc)' +
    '  + " seekfrom=" + string(psf)' +
    '  + " beat=" + string(global.ed_beat)' +
    '  + " beatseq=" + string(global.ed_beatseq)' +
    '  + " pause=" + string(global.ed_pause)' +
    '  + " edit=" + string(global.ed_edit)' +
    '  + " instances=" + string(instance_count)' +
    '  + " ships=" + string(instance_number(ctr_Ship))' +
    '  + " sections=" + string(instance_number(ShipSection) + instance_number(EShipSection));' +
    'pf = file_text_open_write("mods/edit/state");' +
    'file_text_write_string(pf, pline);' +
    'file_text_writeln(pf); file_text_close(pf);');

// ------------------------------------------------------------ camera hold
// Stock BSF edge-scrolls: ctr_GUI's End Step walks l_viewx/l_viewy toward
// whichever edge mouse_x/mouse_y is past, then assigns view_xview from them.
// The test is against the VIEW, not the window, so a pointer that is not over
// the game at all still counts as "past the edge" -- and a puppetted game is
// exactly that, permanently, because the pointer lives over the editor. The
// symptom is a camera that slides away on its own the moment a seek's
// centreCamera glide finishes.
//
// Appended actions run after the stock ones, so the scroll cannot be prevented;
// it is undone instead. While the pointer is outside the window the camera is
// held at the last position it had while the pointer was inside, which is why
// nothing accumulates however long it is left there.
//
// Deliberately not a fix to the stock behaviour: for a player whose pointer IS
// over the game, edge-scrolling is the control scheme. This only exists while
// the editor is attached, and it yields to everything that is a real camera
// command -- the arrow keys, and centreCamera's own GUI_CamMover.
global.ed_camx = 0;
global.ed_camy = 0;
object_event_add(ctr_GUI, 3, 2,
    'var mx, my, hold;' +
    'mx = window_mouse_get_x(); my = window_mouse_get_y();' +
    'hold = 0;' +
    'if (mx < 0) hold = 1;' +
    'if (my < 0) hold = 1;' +
    'if (mx >= window_get_width()) hold = 1;' +
    'if (my >= window_get_height()) hold = 1;' +
    'if (keyboard_check(vk_left)) hold = 0;' +
    'if (keyboard_check(vk_right)) hold = 0;' +
    'if (keyboard_check(vk_up)) hold = 0;' +
    'if (keyboard_check(vk_down)) hold = 0;' +
    'if (instance_exists(GUI_CamMover)) hold = 0;' +
    'if (hold == 0) { global.ed_camx = l_viewx; global.ed_camy = l_viewy; exit; }' +
    'l_viewx = global.ed_camx; l_viewy = global.ed_camy;' +
    'view_xview[0] = global.ed_camx; view_yview[0] = global.ed_camy;');

// ------------------------------------------------- user 0: enter a mission
// Verbatim from the stock GUI_CareerMission click handler. event_user(14) is the
// game's global teardown and is not optional: it is what destroys the previous
// scene's controllers, and without it the new room inherits live instances.
object_event_add(o, 7, 10,
    'sound_stop_all();' +
    'global.ed_pause = 0;' +
    'global.gamemode = 0;' +
    'global.mission = global.ed_arg;' +
    'if (variable_global_exists("level")) {' +
    '  if (global.level < global.ed_arg) global.level = global.ed_arg;' +
    '}' +
    'else global.level = global.ed_arg;' +
    'with (all) { event_user(14); }' +
    'room_goto(rm_Briefing);' +
    'ewalk = 1; efired = 0;');

// --------------------------------------------------------- user 1: seek
// The generated seek ladder is cumulative, so it is not idempotent: seeking to 5
// and then to 11 would re-run rungs 1 to 5 and duplicate every spawn. The rungs
// carry the lower bound themselves, which makes a forward seek one step and a
// backward seek impossible from here. Backward is the editor's job: re-enter the
// mission and seek forward from zero.
object_event_add(o, 7, 11,
    'global.ed_ok = 0;' +
    'global.ed_res = "no mission controller";' +
    'if (!variable_global_exists("gamecontroller")) exit;' +
    'if (!instance_exists(global.gamecontroller)) exit;' +
    'global.ed_res = "this mission has no seek ladder";' +
    'with (global.gamecontroller) {' +
    '  if (variable_local_exists("l_seek_from")) {' +
    '    if (global.ed_arg < l_seek_from) {' +
    '      global.ed_res = "backward seek from " + string(l_seek_from)' +
    '        + ": re-enter the mission and seek forward";' +
    '    }' +
    '    else {' +
    '      l_seek = global.ed_arg;' +
    '      event_user(1);' +
    '      global.ed_ok = 1;' +
    '      global.ed_res = "at rung " + string(l_seek)' +
    '        + ", next " + string(l_messagecount);' +
    '    }' +
    '  }' +
    '}');

// ------------------------------------------------- user 2: freeze / unfreeze
// The stock P pause is keyboard_wait() inside GUI_MissionPause s Draw -- it
// blocks the whole game loop, and a blocked loop is a dead channel. This is the
// sandbox freeze instead (ctr_Testroom alarm 0), which stops the world while the
// loop keeps running and drawing.
//
// Three things the stock pattern does not cover and this does:
//   * obs_Meteor is not under ctr_Ship, ctr_EShip or ctr_Actors -- its parent
//     chain is object728 -> ctr_GUI -- so the sandbox freeze leaves meteors
//     drifting through a paused mission;
//   * the mission controller's own alarms, above all alarm[5], the meteor
//     spawner, and alarm[2], the opening beat;
//   * the zone objects this campaign compiler invents, which read global.ed_pause
//     at the top of their Step.
//
// Speed and l_holdposition are saved and restored rather than zeroed and left,
// which is what the sandbox does -- there, unfreezing into "everything holds
// position" is the point, and here it would strand the player's ship.
//
// ⚠ The stock re-arm draws from random() to stagger the targeting timers. BSF
// never calls randomize(), so those draws shift every later draw in the run: a
// mission re-entered after a pause scatters its nebulae differently. Harmless,
// but it is why the prediction calls scenery a prediction and not a layout.
object_event_add(o, 7, 12,
    'var ek, skip;' +
    'if (global.ed_arg) {' +
    '  global.ed_pause = 1;' +
    '  with (ctr_Ship) {' +
    '    ed_spd = speed; ed_hold = l_holdposition; ed_saved = 1;' +
    '    alarm[0] = 0; alarm[8] = 0; alarm[9] = 0; alarm[11] = 0;' +
    '    l_holdposition = true; l_facetarg = -4; l_faceto = image_angle; speed = 0;' +
    '  }' +
    '  with (ctr_EShip) {' +
    '    ed_spd = speed; ed_hold = l_holdposition; ed_saved = 1;' +
    '    alarm[0] = 0; alarm[8] = 0; alarm[9] = 0; alarm[11] = 0;' +
    '    l_holdposition = true; l_facetarg = -4; l_faceto = image_angle; speed = 0;' +
    '  }' +
    '  with (ctr_Turrets) {' +
    '    skip = 0;' +
    '    if (object_index == AegisDeflector) skip = 1;' +
    '    if (object_index == Deflector) skip = 1;' +
    '    if (object_index == Booster) { c_target = -4; skip = 1; }' +
    '    if (object_index == BoosterLow) { c_target = -4; skip = 1; }' +
    '    if (skip == 0) {' +
    '      l_target = -4; c_target = -4;' +
    '      alarm[0] = 0; alarm[2] = 0; alarm[10] = 0; alarm[11] = 0;' +
    '      ai_offset = 0; l_mode = 3;' +
    '      image_angle = l_owner.image_angle + l_arcoffset;' +
    '    }' +
    '  }' +
    '  with (ctr_ETurrets) {' +
    '    skip = 0;' +
    '    if (object_index == EAegisDeflector) skip = 1;' +
    '    if (object_index == EDeflector) skip = 1;' +
    '    if (object_index == EBooster) { c_target = -4; skip = 1; }' +
    '    if (object_index == EBoosterLow) { c_target = -4; skip = 1; }' +
    '    if (skip == 0) {' +
    '      l_target = -4; c_target = -4;' +
    '      alarm[0] = 0; alarm[2] = 0; alarm[10] = 0; alarm[11] = 0;' +
    '      ai_offset = 0; l_mode = 3;' +
    '      image_angle = l_owner.image_angle + l_arcoffset;' +
    '    }' +
    '  }' +
    '  with (ctr_Actors) alarm[9] = 0;' +
    '  with (obs_Meteor) {' +
    '    ed_spd = speed; ed_saved = 1;' +
    '    speed = 0; alarm[1] = 0; alarm[2] = 0;' +
    '  }' +
    '  with (SFX_Jumper) alarm[0] = 999;' +
    '  if (variable_global_exists("gamecontroller")) {' +
    '    if (instance_exists(global.gamecontroller)) {' +
    '      with (global.gamecontroller) {' +
    '        for (ek = 0; ek < 12; ek += 1) { ed_alarm[ek] = alarm[ek]; alarm[ek] = 0; }' +
    '        ed_saved = 1;' +
    '      }' +
    '    }' +
    '  }' +
    '  global.ed_ok = 1; global.ed_res = "frozen";' +
    '  exit;' +
    '}' +
    'global.ed_pause = 0;' +
    'with (ctr_Ship) {' +
    '  alarm[0] = 1 + floor(random(70)); alarm[11] = 1 + floor(random(7));' +
    '  if (variable_local_exists("ed_saved")) { speed = ed_spd; l_holdposition = ed_hold; }' +
    '}' +
    'with (ctr_EShip) {' +
    '  alarm[0] = 1 + floor(random(70)); alarm[11] = 1 + floor(random(7));' +
    '  if (variable_local_exists("ed_saved")) { speed = ed_spd; l_holdposition = ed_hold; }' +
    '}' +
    'with (ctr_Turrets) {' +
    '  alarm[2] = 1; alarm[10] = 1;' +
    '  if (l_maxeng > 0) l_eng = l_maxeng;' +
    '  l_mode = 0;' +
    '  if (object_index == PointMaser) l_mode = 2;' +
    '  if (object_index == PointBeam) l_mode = 2;' +
    '  if (object_index == ParticleGun) l_mode = 2;' +
    '  if (object_index == Deflector) l_mode = 3;' +
    '  if (object_index == Booster) { l_mode = 3; if (instance_exists(l_target)) c_target = l_target; }' +
    '  if (object_index == BoosterLow) { l_mode = 3; if (instance_exists(l_target)) c_target = l_target; }' +
    '}' +
    'with (ctr_ETurrets) {' +
    '  alarm[2] = 1; alarm[10] = 1;' +
    '  if (l_maxeng > 0) l_eng = l_maxeng;' +
    '  l_mode = 0;' +
    '  if (object_index == EPointMaser) l_mode = 2;' +
    '  if (object_index == EPointBeam) l_mode = 2;' +
    '  if (object_index == EParticleGun) l_mode = 2;' +
    '  if (object_index == EDeflector) l_mode = 3;' +
    '  if (object_index == EBooster) { l_mode = 3; if (instance_exists(l_target)) c_target = l_target; }' +
    '  if (object_index == EBoosterLow) { l_mode = 3; if (instance_exists(l_target)) c_target = l_target; }' +
    '}' +
    'with (ctr_Actors) alarm[9] = 1 + random(60);' +
    'with (obs_Meteor) {' +
    '  if (variable_local_exists("ed_saved")) speed = ed_spd;' +
    '  alarm[2] = 1;' +
    '}' +
    'with (SFX_Jumper) alarm[0] = 160 + random(40);' +
    'if (variable_global_exists("gamecontroller")) {' +
    '  if (instance_exists(global.gamecontroller)) {' +
    '    with (global.gamecontroller) {' +
    '      if (variable_local_exists("ed_saved")) {' +
    '        for (ek = 0; ek < 12; ek += 1) alarm[ek] = ed_alarm[ek];' +
    '      }' +
    '    }' +
    '  }' +
    '}' +
    'global.ed_ok = 1; global.ed_res = "running";');

// ------------------------------------------------- user 3: reload the mod
// Re-executing a generated mission mod re-binds every event onto the object and
// room indices it claimed the first time. The reload alone changes nothing that
// is already running -- Create has already run -- so the editor follows it with
// an `open` and a `seek`.
object_event_add(o, 7, 13,
    'var rp;' +
    'global.ed_ok = 0;' +
    'global.ed_res = "no mission is loaded";' +
    'if (!variable_global_exists("mission")) exit;' +
    'rp = "mods/act2m" + string(global.mission - 7) + ".gml";' +
    'if (file_exists(rp)) {' +
    '  execute_file(rp);' +
    '  global.ed_ok = 1; global.ed_res = "reloaded " + rp;' +
    '}' +
    'else {' +
    '  global.ed_ok = 0; global.ed_res = "no such mod: " + rp;' +
    '}');

// ------------------------------------------------------------ user 4: dump
// Ground truth for the ghost overlay: every live instance in the room, in the
// room's own coordinates, so a predicted position and an actual one can be drawn
// on top of each other and the difference read off directly.
//
// ⚠ sprite_get_name is guarded by sprite_exists, not by an index test. An object
// can carry a sprite index whose sprite no longer exists, and the unguarded call
// aborts the action mid-loop -- which leaves the text handle open and unflushed,
// so the symptom is a missing file rather than a short one.
object_event_add(o, 7, 14,
    'var df, dj, ds, dn, dt0;' +
    'dt0 = current_time;' +
    'df = file_text_open_write("mods/edit/dump");' +
    'file_text_write_string(df, "room=" + room_get_name(room)' +
    '  + " roomw=" + string(room_width) + " roomh=" + string(room_height)' +
    '  + " viewx=" + string(view_xview[0]) + " viewy=" + string(view_yview[0])' +
    '  + " vieww=" + string(view_wview[0]) + " viewh=" + string(view_hview[0])' +
    '  + " beat=" + string(global.ed_beat) + " count=" + string(instance_count));' +
    'file_text_writeln(df);' +
    'for (dj = 0; dj < instance_count; dj += 1) {' +
    '  with (instance_id[dj]) {' +
    '    ds = sprite_index;' +
    '    dn = "-";' +
    '    if (ds >= 0) { if (sprite_exists(ds)) dn = sprite_get_name(ds); }' +
    '    file_text_write_string(df, object_get_name(object_index)' +
    '      + " " + string(x) + " " + string(y)' +
    '      + " " + string(image_angle)' +
    '      + " " + string(image_xscale) + " " + string(image_yscale)' +
    '      + " " + dn' +
    '      + " " + string(image_blend) + " " + string(image_alpha)' +
    '      + " " + string(depth) + " " + string(visible));' +
    '    file_text_writeln(df);' +
    '  }' +
    '}' +
    'file_text_close(df);' +
    'global.ed_ok = 1;' +
    'global.ed_res = "dumped " + string(instance_count) + " instances in "' +
    '  + string(current_time - dt0) + " ms";');

ii = instance_create(0, 0, o);
ii.persistent = true;
ii.depth = -10000002;

lf = file_text_open_append('mods/edit/editor.log');
file_text_write_string(lf, 'loaded ok  boot=' + string(global.ed_boot) +
    ' stride=' + string(global.ed_stride));
file_text_writeln(lf); file_text_close(lf);

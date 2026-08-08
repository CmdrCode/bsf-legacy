// Battleships Forever ShipMaker -- mod entry point.
//
// The bootstrap patched into ShipMaker.exe (tools/patch_bsf.py) runs this file
// from obj_sidebar's Create event -- the editor's master init, so this executes
// once at startup, BEFORE the editor's own WinAPI init. A module must therefore
// not call the API_* wrapper scripts at load time; wait for its first Step.
//
// The guard matters for "New ship": that path calls game_restart(), which wipes
// every global and re-runs obj_sidebar's Create -- so this file runs again with
// a fresh namespace and must re-install everything exactly once.
//
// ⚠ The guard tests the VALUE, not just existence. ShipMaker ships with "treat
// uninitialized variables as 0" ON (the game has it off), and under that
// setting a global assigned ANYWHERE in a compiled file is registered -- and
// zero-initialised -- the moment the file compiles, so variable_global_exists
// is already true on the line above its own first assignment. The plain
// existence guard the game's init.gml uses therefore exits on the very first
// run here. Nested ifs because GML's && does not short-circuit and the read
// must not happen when the global was never registered.
var booted;
booted = 0;
if (variable_global_exists('bsf_sm_init'))
    if (global.bsf_sm_init)
        booted = 1;
if (booted) exit;
global.bsf_sm_init = 1;

// ---------------------------------------------------------------- the chain
// bsf-legacy ShipMaker module table -- same shape as the game's mods/init.gml.
//
// Column 2 is the gate:
//     ""          always, if the .gml is present
//     "x.on"      only when mods/x.on exists            (opt-in)
//     "!x.off"    unless mods/x.off exists              (opt-out; on by default)
var nm, mk, k, gate, last;
nm[0]='smres';   mk[0]='!smres.off';  // 1:1 resolution: the region follows the window
nm[1]='mipdraw'; mk[1]='';            // mip-filtered sprite drawing library (smpick uses it)
nm[2]='smpick';  mk[2]='!smpick.off'; // Factorio-style part picker: quickbar + pipette + search
nm[3]='cursor';  mk[3]='cursor.on';   // cursor cache over the GetCursorPos import
last = 3;

for (k = 0; k <= last; k += 1) {
    if (mk[k] == '')
        gate = true;
    else if (string_char_at(mk[k], 1) == '!')
        gate = !file_exists('mods/' + string_delete(mk[k], 1, 1));
    else
        gate = file_exists('mods/' + mk[k]);
    if (gate) {
        if (file_exists('mods/' + nm[k] + '.gml'))
            execute_file('mods/' + nm[k] + '.gml');
    }
}

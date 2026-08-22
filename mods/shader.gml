// The GML side of bsfshader.dll -- pixel shaders over the game's own draws.
//
// For VISUAL EFFECTS -- damage states, cloak, shield hits, a colour grade per
// faction.  Not performance: nothing here changes how many draw calls the game
// makes.
//
// Needs d3d8to9 as the loaded d3d8, which tools/wineenv.py arranges on every
// launch path.  Where it is missing sh_init returns -1 and every later call is a
// harmless no-op, so the game runs exactly as before with effects off.
//
// external_define aborts the rest of the FILE if the DLL will not resolve, so
// this file is the defines and one init call and nothing else -- a missing
// bsfshader.dll leaves the game running normally.
global.sh_init       = external_define('bsfshader.dll', 'sh_init',       dll_cdecl, ty_real, 0);
global.sh_compile    = external_define('bsfshader.dll', 'sh_compile',    dll_cdecl, ty_real, 1, ty_string);
global.sh_compile_as = external_define('bsfshader.dll', 'sh_compile_as', dll_cdecl, ty_real, 2, ty_string, ty_string);
global.sh_set        = external_define('bsfshader.dll', 'sh_set',        dll_cdecl, ty_real, 1, ty_real);
global.sh_reset      = external_define('bsfshader.dll', 'sh_reset',      dll_cdecl, ty_real, 0);
global.sh_const      = external_define('bsfshader.dll', 'sh_const',      dll_cdecl, ty_real, 5, ty_real, ty_real, ty_real, ty_real, ty_real);
global.sh_const_col  = external_define('bsfshader.dll', 'sh_const_col',  dll_cdecl, ty_real, 3, ty_real, ty_real, ty_real);
global.sh_free       = external_define('bsfshader.dll', 'sh_free',       dll_cdecl, ty_real, 1, ty_real);
global.sh_err        = external_define('bsfshader.dll', 'sh_err',        dll_cdecl, ty_string, 0);
global.sh_stat       = external_define('bsfshader.dll', 'sh_stat',       dll_cdecl, ty_real, 1, ty_real);

global.sh_ok = external_call(global.sh_init);

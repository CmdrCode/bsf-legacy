// Stage 3 demo + test.  Gated on mods/shaderdemo.on.  Measurement only.
//
// Captures three frames in one run:
//   sh_a  no shader bound            (baseline)
//   sh_b  shader bound, p.x = 0      (must match sh_a -- the correctness test)
//   sh_c  shader bound, p.x = 1      (must differ)
var o;
if (!variable_global_exists('sh_ok')) exit;

global.sh_h = -1;
if (global.sh_ok >= 1) global.sh_h = external_call(global.sh_compile, 'mods/shaderdemo.hlsl');

o = object_add();
object_set_persistent(o, 1);   // resolution.gml's room_restart() would eat it otherwise
object_event_add(o, 0, 0, 'tick = 0; hot = 0;');
object_event_add(o, 3, 0,
    'tick += 1;' +
    'if (tick == 120) screen_save("mods/sh_a.png");' +
    'if (tick >= 121 && global.sh_h >= 0) {' +
    '  external_call(global.sh_set, global.sh_h);' +
    '  external_call(global.sh_const, 0, hot, 0, 0, 0); }' +
    'if (tick == 122) screen_save("mods/sh_b.png");' +
    'if (tick == 180) hot = 1;' +
    'if (tick == 182) screen_save("mods/sh_c.png");' +
    'if (tick == 190) {' +
    '  var f; f = file_text_open_write("mods/shaderdemo.txt");' +
    '  file_text_write_string(f, "ok=" + string(global.sh_ok)' +
    '    + " handle=" + string(global.sh_h)' +
    '    + " dev=" + string(external_call(global.sh_stat, 0))' +
    '    + " compiles=" + string(external_call(global.sh_stat, 1))' +
    '    + " binds=" + string(external_call(global.sh_stat, 2))' +
    '    + " fails=" + string(external_call(global.sh_stat, 3)));' +
    '  file_text_writeln(f);' +
    '  file_text_write_string(f, "err=" + string(external_call(global.sh_err)));' +
    '  file_text_writeln(f); file_text_close(f); }' +
    'if (tick == 200) game_end();');
instance_create(0, 0, o);

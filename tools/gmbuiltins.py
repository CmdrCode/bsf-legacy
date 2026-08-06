#!/usr/bin/env python3
"""Resolve GM 7.0 builtin name -> (argc, thunk VA) from the runner's registration code.

The registry is built by straight-line code, not a data table:
    push <flag> ; mov edx,<impl> ; mov ecx,<argc> ; mov eax,<name str> ; call RegisterBuiltin
The `mov eax,<name>` belongs to the PRECEDING `mov edx,<impl>` -- off-by-one here costs a function.
"""
import struct, re, sys
import os
# Point BSF_DIR at your copy of the game; defaults to one unpacked beside this
# checkout. Reads the .bak so the runner is the stock one, unpatched.
G=os.environ.get('BSF_DIR') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)),'..','battleshipsforeverv090d')
CODE_OFF,CODE_SZ,CODE_VA=0x400,0x183290,0x401000
d=open(os.path.join(G,"BattleshipsForever.exe.bak"),'rb').read()
buf=d[CODE_OFF:CODE_OFF+CODE_SZ]
def va(o): return CODE_VA+o

# Delphi long strings anywhere in the image -> VA
strs={}
for m in re.finditer(rb'\xff\xff\xff\xff(....)', d, re.S):
    ln=struct.unpack('<I',m.group(1))[0]
    if not (2<=ln<=48): continue
    s=m.end(); body=d[s:s+ln]
    if d[s+ln:s+ln+1]!=b'\x00': continue
    if not re.fullmatch(rb'[a-z_0-9]+', body): continue
    strs[CODE_VA+(s-CODE_OFF)]=body.decode()

REG=0x0052D204
out={}
i=0
n=len(buf)
while i < n-24:
    # mov edx,imm32 ; mov ecx,imm32 ; mov eax,imm32 ; call rel32
    if buf[i]==0xBA and buf[i+5]==0xB9 and buf[i+10]==0xB8 and buf[i+15]==0xE8:
        impl=struct.unpack_from('<I',buf,i+1)[0]
        argc=struct.unpack_from('<I',buf,i+6)[0]
        nm  =struct.unpack_from('<I',buf,i+11)[0]
        rel =struct.unpack_from('<i',buf,i+16)[0]
        if va(i+15)+5+rel==REG and nm in strs:
            out[strs[nm]]=(argc, impl, va(i))
        i+=20; continue
    i+=1
if __name__=='__main__':
    print(f"resolved {len(out)} builtins", file=sys.stderr)
    want=sys.argv[1:] or ['place_meeting','place_free','instance_place','position_meeting',
        'collision_point','collision_line','collision_circle','collision_rectangle','collision_ellipse',
        'instance_nearest','instance_deactivate_region','instance_activate_region',
        'instance_deactivate_all','event_perform','event_inherited','instance_create',
        'instance_destroy','lengthdir_x','lengthdir_y','point_distance','point_direction',
        'ds_map_add','ds_map_clear','sprite_set_precise','instance_number','instance_exists']
    for w in want:
        if w in out:
            a,impl,site=out[w]
            print(f"  {w:28s} argc={a:<3d} thunk=0x{impl:08X}  (registered at 0x{site:08X})")
        else:
            print(f"  {w:28s} NOT REGISTERED")

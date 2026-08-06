#!/usr/bin/env python3
"""Resolve GM 7.0 builtin *variables* -> (getter VA, setter VA) from the runner.

Distinct from gmbuiltins.py, which does builtin FUNCTIONS. The variable registry is
also straight-line code:

    push <flag>            ; 0 = plain, 1 = ?
    mov  ecx, <setter>     ; 0 (xor ecx,ecx) when read-only
    mov  edx, <getter>
    mov  eax, <name string>
    call 0x00529B08        ; RegisterBuiltinVar(name:eax, setter:ecx, getter:edx, flag)

These are the ones that LOOK like variables in GML but are function calls in the runner.
"""
import struct, re, sys, os
# Point BSF_DIR at your copy of the game; defaults to one unpacked beside this
# checkout. Reads the .bak so the runner is the stock one, unpatched.
G=os.environ.get('BSF_DIR') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)),'..','battleshipsforeverv090d')
CODE_OFF,CODE_SZ,CODE_VA=0x400,0x183290,0x401000
d=open(os.path.join(G,"BattleshipsForever.exe.bak"),'rb').read()
buf=d[CODE_OFF:CODE_OFF+CODE_SZ]
def va(o): return CODE_VA+o
REG=0x00529B08

strs={}
for m in re.finditer(rb'\xff\xff\xff\xff(....)', d, re.S):
    ln=struct.unpack('<I',m.group(1))[0]
    if not (2<=ln<=48): continue
    s=m.end(); body=d[s:s+ln]
    if d[s+ln:s+ln+1]!=b'\x00': continue
    if not re.fullmatch(rb'[a-z_0-9]+', body): continue
    strs[CODE_VA+(s-CODE_OFF)]=body.decode()

out={}
i=0; n=len(buf)
while i<n-20:
    # variant 1: mov ecx,imm32 ; mov edx,imm32 ; mov eax,imm32 ; call
    if buf[i]==0xB9 and buf[i+5]==0xBA and buf[i+10]==0xB8 and buf[i+15]==0xE8:
        setter=struct.unpack_from('<I',buf,i+1)[0]
        getter=struct.unpack_from('<I',buf,i+6)[0]
        nm    =struct.unpack_from('<I',buf,i+11)[0]
        rel   =struct.unpack_from('<i',buf,i+16)[0]
        if va(i+15)+5+rel==REG and nm in strs:
            out[strs[nm]]=(getter,setter); i+=20; continue
    # variant 2: mov edx,imm32 ; xor ecx,ecx ; mov eax,imm32 ; call   (read-only)
    if buf[i]==0xBA and buf[i+5]==0x33 and buf[i+6]==0xC9 and buf[i+7]==0xB8 and buf[i+12]==0xE8:
        getter=struct.unpack_from('<I',buf,i+1)[0]
        nm    =struct.unpack_from('<I',buf,i+8)[0]
        rel   =struct.unpack_from('<i',buf,i+13)[0]
        if va(i+12)+5+rel==REG and nm in strs:
            out[strs[nm]]=(getter,0); i+=17; continue
    i+=1
if __name__=='__main__':
    print(f"builtin variables resolved: {len(out)}", file=sys.stderr)
    ro=sum(1 for g,s in out.values() if s==0)
    print(f"  read-only: {ro}, read/write: {len(out)-ro}", file=sys.stderr)
    for k in sorted(out):
        g,s=out[k]
        print(f"  {k:28s} getter=0x{g:08X} setter={'-' if s==0 else '0x%08X'%s}")

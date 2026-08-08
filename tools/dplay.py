#!/usr/bin/env python3
"""The DirectPlay-init skip: constants, guards, and apply/revert.

Shared by `patch_bsf.py` (shipping patcher) the same way `hwvp.py` is, and like
it deliberately dependency-free beyond that module (whose build fingerprint it
reuses, so the "is this the runner we disassembled" guard exists once).

------------------------------------------------------------------------ the edit
The GM 7.0 runner is Delphi, built against the JEDI DirectX headers. That
header's DPlayX unit has an `initialization` section — run at process start,
before any game code — that does LoadLibrary('DPlayX.dll') plus five
GetProcAddress calls to wire up the DirectPlay multiplayer pointers.

On Windows 10/11 DirectPlay is a removed legacy "Feature on Demand", and any
LoadLibrary of dplayx.dll is exactly what triggers the full-screen "Battleships
Forever on your PC needs the following Windows feature: DirectPlay" dialog —
on every launch until the user installs a component the game then never uses:
neither executable's scripts contain a single `mplay_*` call (GML's only route
to those pointers; verified over the decompiled resource tree).

The unit ships its own skip path. Disassembly at the site (both exes):

    5484d8: 83 2d b0 a8 5c 00 01   subl $1, ...           ; once-only guard
    5484df: 0f 83 99 00 00 00      jae  ret
    5484e5: e8 6e 0b f4 ff         call IsNTandDelphiRunning
    5484ea: 84 c0                  test %al,%al           <-- the two bytes
    5484ec: 0f 85 8c 00 00 00      jne  ret               ; skip the whole load
    5484f2: 68 80 85 54 00         push $"DPlayX.dll"
    5484f7: e8 e8 f2 eb ff         call LoadLibrary
    ...                            ; five GetProcAddress, then
    54857e: c3                     ret

`IsNTandDelphiRunning` is the JEDI headers' guard against loading DirectPlay
under the Delphi debugger on NT: when it fires, the unit skips the load
entirely and leaves every pointer nil — a path the unit was WRITTEN to survive
(the matching `finalization` checks the module handle for 0 before
FreeLibrary). The edit turns `test %al,%al` (84 c0) into `or $1,%al` (0c 01),
which forces that branch: same length, flags say "guard fired", the process
never mentions dplayx.dll, and Windows has nothing to prompt about.

⚠ NEVER pattern-match `84 c0` — it is everywhere. The site is a fixed file
offset plus a shape guard whose discriminator is the LOAD ITSELF: the guarded
`push imm32` must point at the literal 'DPlayX.dll' string in CODE.

The same GM 7.0 runner backs BattleshipsForever.exe and ShipMaker.exe -- their
CODE sections are byte-identical -- so the offset and the guard apply to both.
"""
import struct

import hwvp

# File offset of the `test %al,%al` immediately after the IsNTandDelphiRunning
# call in the DPlayX unit's initialization.
OFFSET = 0x001478EA
TEST = bytes((0x84, 0xC0))   # test %al,%al -- honour the guard's answer (stock)
SKIP = bytes((0x0C, 0x01))   # or $1,%al   -- guard "fired": never load DPlayX

# CODE section mapping (VA 0x401000 at file offset 0x400), for resolving the
# address the guarded `push imm32` carries back to a file offset.
CODE_VA, CODE_FILE = 0x401000, 0x400
DLL_NAME = b'DPlayX.dll\x00'


class ShapeError(hwvp.ShapeError):
    """The bytes at the target offset are not the DPlayX-init guard branch.

    Subclasses hwvp.ShapeError so a caller can catch that one type around
    apply(), which raises the parent from the shared build check and this from
    the site checks."""


def read_bytes(path):
    """The two guard bytes as they currently stand on disk."""
    with open(path, 'rb') as f:
        return f.read()[OFFSET:OFFSET + 2]


def verify_shape(d, path):
    """The offset must be the guard test of the DPlayX unit initialization.

    Checked structurally: call rel32 before it, `jne rel32` after it, and a
    `push imm32` whose immediate resolves to the literal 'DPlayX.dll' string.
    Raises ShapeError rather than exiting, so callers decide how to report.
    """
    if OFFSET + 13 > len(d):
        raise ShapeError(f'{path}: offset {OFFSET:#010x} is past end of file')
    if d[OFFSET - 5] != 0xE8:
        raise ShapeError(
            f'{path}: no `call rel32` before {OFFSET:#010x} '
            f'(byte {d[OFFSET - 5]:#04x}) -- not the guarded init site')
    if bytes(d[OFFSET + 2:OFFSET + 4]) != b'\x0f\x85':
        raise ShapeError(
            f'{path}: no `jne rel32` after {OFFSET:#010x} '
            f'(bytes {bytes(d[OFFSET + 2:OFFSET + 4]).hex(" ")}) -- the skip '
            'branch this patch forces is not here')
    if d[OFFSET + 8] != 0x68:
        raise ShapeError(
            f'{path}: no `push imm32` at {OFFSET + 8:#010x} -- nothing being '
            'loaded here')
    va = struct.unpack_from('<I', d, OFFSET + 9)[0]
    at = va - CODE_VA + CODE_FILE
    got = bytes(d[at:at + len(DLL_NAME)]) if 0 <= at <= len(d) - len(DLL_NAME) else b''
    if got != DLL_NAME:
        raise ShapeError(
            f'{path}: the push at {OFFSET + 8:#010x} does not carry the '
            f"'DPlayX.dll' string (VA {va:#010x} -> {got!r}) -- this is not "
            'the DirectPlay load site')


def apply(path, to=SKIP):
    """Write `to` over the guard test. Verifies build + shape first. Idempotent.

    Returns (changed: bool, before: bytes, after: bytes).
    """
    frm = TEST if to == SKIP else SKIP
    with open(path, 'rb') as f:
        d = bytearray(f.read())
    hwvp.verify_build(d, path)
    verify_shape(d, path)
    before = bytes(d[OFFSET:OFFSET + 2])
    if before == to:
        return False, before, before
    if before != frm:
        raise ShapeError(
            f'{path}: refusing -- expected {frm.hex(" ")} at {OFFSET:#010x}, '
            f'got {before.hex(" ")}. Restore from backup first.')
    d[OFFSET:OFFSET + 2] = to
    with open(path, 'wb') as f:
        f.write(d)
    # Re-read from disk rather than trusting the buffer: this is the check that
    # the write actually landed.
    after = read_bytes(path)
    if after != to:
        raise ShapeError(f'{path}: write did not take effect; check permissions')
    return True, before, after


def revert(path):
    """SKIP -> TEST, in place. No backup needed: it is the same two bytes."""
    return apply(path, to=TEST)

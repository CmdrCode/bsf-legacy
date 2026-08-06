#!/usr/bin/env python3
"""The SWVP -> HWVP device-flag patch: constants, guards, and apply/revert.

Shared by `patch_bsf.py` (shipping patcher) and the local measurement harness, so
the guard exists once. Deliberately dependency-free -- importing this must not
drag in the measurement harness.

------------------------------------------------------------------------ the edit
BSF creates its Direct3D 8 device with

    D3DCREATE_SOFTWARE_VERTEXPROCESSING | D3DCREATE_FPU_PRESERVE   (0x22)

and this flips it to

    D3DCREATE_HARDWARE_VERTEXPROCESSING | D3DCREATE_FPU_PRESERVE   (0x42)

Two bytes per executable. Verified by disassembly at both call sites:

    4a3ad5: 50              push %eax              ; ppReturnedDeviceInterface
    4a3ad6: 8d 45 b8        lea  -0x48(%ebp),%eax
    4a3ad9: 50              push %eax              ; pPresentationParameters
    4a3ada: 6a 22           push $0x22             ; BehaviorFlags   <-- the byte
    4a3adc: 56              push %esi              ; hFocusWindow
    4a3add: 6a 01           push $0x1              ; D3DDEVTYPE_HAL
    4a3adf: 6a 00           push $0x0              ; Adapter
    4a3ae1: a1 60 7a 58 00  mov  0x587a60,%eax     ; the IDirect3D8*
    4a3ae6: 50              push %eax
    4a3ae7: 8b 00           mov  (%eax),%eax
    4a3ae9: ff 50 3c        call *0x3c(%eax)       ; vtable slot 15 = CreateDevice

⚠ BOTH sites are patched, or neither. They are a try-then-retry pair: the second
runs only if the first CreateDevice fails. Patching just the first would let a
failed HWVP creation fall silently back to SWVP, so the game would keep working
while every measurement described the old path under a new name. With both
patched it either runs on HWVP or does not start -- loud, and revertible.

⚠ NEVER pattern-match `6a 22`. There are 116 such byte pairs in the image; only 3
are in the CODE section and the other 113 sit inside the compressed resource blob,
where a find-and-replace would corrupt game data outright. Of the three code
sites, the one at 0x000A2A4E is `SetRenderState(D3DRS_FOGCOLOR, ...)` -- rewriting
it would silently become D3DRS_MULTISAMPLEANTIALIAS and produce a baffling visual
bug much later. Hence: fixed offsets, plus a shape guard whose discriminator is the
VTABLE SLOT (CreateDevice is `call *0x3c(reg)`; SetRenderState is `*0xc8(reg)`).

The same GM 7.0 runner backs BattleshipsForever.exe and ShipMaker.exe -- their CODE
sections are byte-identical -- so the offsets and the guard apply unchanged to both.
"""
import struct

# Immediates of the two `push imm8` instructions, as FILE offsets.
OFFSETS = (0x000A2EDC, 0x000A2F0D)
SWVP, HWVP = 0x22, 0x42

# GM 7.0 runner fingerprint: the dword at VA 0x00500000. CODE is VA 0x00401000 at
# file offset 0x400, so VA 0x500000 -> file 0x400 + (0x500000 - 0x401000).
SIG_OFFSET = 0x000FF400
SIG_EXPECTED = 0x00589A24


class ShapeError(Exception):
    """The bytes at a target offset are not a CreateDevice BehaviorFlags push."""


def _flags(d):
    return [d[o] for o in OFFSETS]


def read_bytes(path):
    """The two flag bytes as they currently stand on disk."""
    with open(path, 'rb') as f:
        return _flags(f.read())


def verify_build(d, path):
    """Refuse an executable that is not the GM 7.0 runner we disassembled."""
    if len(d) < SIG_OFFSET + 4:
        raise ShapeError(f'{path}: too small to be the expected runner')
    got = struct.unpack_from('<I', d, SIG_OFFSET)[0]
    if got != SIG_EXPECTED:
        raise ShapeError(
            f'{path}: GM 7.0 signature mismatch at file {SIG_OFFSET:#x} '
            f'(VA 0x00500000): got {got:#010x}, expected {SIG_EXPECTED:#010x}. '
            'This is not the build these offsets were derived from; refusing.')


def verify_shape(d, path):
    """Each offset must be the immediate of a `push imm8` feeding CreateDevice.

    Raises ShapeError rather than exiting, so callers decide how to report.
    """
    for o in OFFSETS:
        if o >= len(d):
            raise ShapeError(f'{path}: offset {o:#010x} is past end of file')
        if d[o - 1] != 0x6A:
            raise ShapeError(
                f'{path}: {o:#010x} is not the immediate of a `push imm8` '
                f'(preceding byte {d[o - 1]:#04x})')
        window = bytes(d[o + 1:o + 25])
        if window.find(b'\xff\x50\x3c') < 0:
            raise ShapeError(
                f'{path}: no `call *0x3c(%eax)` (CreateDevice, vtable slot 15) '
                f'within 24 bytes of {o:#010x} -- this is not a CreateDevice site. '
                f'Bytes: {window.hex(" ")}')


def apply(path, to=HWVP):
    """Write `to` at both offsets. Verifies build + shape first. Idempotent.

    Returns (changed: bool, before: list[int], after: list[int]).
    """
    frm = SWVP if to == HWVP else HWVP
    with open(path, 'rb') as f:
        d = bytearray(f.read())
    verify_build(d, path)
    verify_shape(d, path)
    before = _flags(d)
    if all(v == to for v in before):
        return False, before, before
    if not all(v == frm for v in before):
        raise ShapeError(
            f'{path}: refusing -- expected both bytes to read {frm:#04x}, got '
            f'{[hex(v) for v in before]}. A half-applied patch is exactly the state '
            'this refuses to create or continue from; restore from backup first.')
    for o in OFFSETS:
        d[o] = to
    with open(path, 'wb') as f:
        f.write(d)
    # Re-read from disk rather than trusting the buffer: this is the check that
    # the write actually landed.
    after = read_bytes(path)
    if not all(v == to for v in after):
        raise ShapeError(f'{path}: write did not take effect; check permissions')
    return True, before, after


def revert(path):
    """HWVP -> SWVP, in place. No backup needed: it is the same two bytes."""
    return apply(path, to=SWVP)

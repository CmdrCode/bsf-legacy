#!/usr/bin/env python3
"""Game Maker 7.0 gamedata reader — decrypts the resource tree in a GM7 exe.

Ports the GM7 path of elipsitz/gm_reader (Rust, `src/decoder/decrypt.rs`) to
Python so the patcher has no toolchain dependency.

The scheme ("gmkrypt") is: zlib-inflate the block, then undo a byte swap driven by
a 256-entry table GENERATED FROM A SEED, combined with a position-dependent
subtraction:

    plain[i] = (table[cipher[i]] - (offset + i)) & 0xFF

Two things about that had us chasing ghosts for a whole session:

* It is **not** a pure substitution — the `- (offset + i)` term means one cipher
  byte decodes differently at different positions. Our earlier attempt to solve a
  fixed 256-byte table therefore found contradictions (`n` -> both `m` and `o`)
  and no consistent alignment. That was the position term, not bad data.
* The table is **generated**, not stored. The 256-byte permutation the earlier
  static pass found in the blob was a red herring; GM 8.x stores its table, GM 7.0
  derives it. `gmdecrypt.py` implemented the GM 8.x scheme — right family, wrong
  version, which is exactly why it failed.

The seed lives inside the "garbage" header: [s1][s2][skip 4*s1][SEED][skip 4*s2].
The earlier disassembly read that structure correctly but took the field after the
first skip to be a length rather than the seed.
"""
import struct
import sys
import zlib

# Where a GM 7.0 runner keeps its gamedata. Same constant gm_reader uses.
GM700_OFFSET = 1_980_000
MAGIC = 1234321
VERSION = 700


def u32(buf, pos):
    return struct.unpack_from('<I', buf, pos)[0]


def make_generic_swap_table(a, b):
    """GM's table generator: 10000 adjacent swaps driven by (a, b).

    Returns (forward, inverse). Decryption needs the inverse, encryption the
    forward table -- returning both keeps the encoder from inverting straight back
    to a permutation this function already had in hand.
    """
    fwd = list(range(256))
    for i in range(1, 10001):
        j = 1 + ((i * a + b) % 254)
        fwd[j], fwd[j + 1] = fwd[j + 1], fwd[j]
    inv = [0] * 256
    for i in range(1, 256):
        inv[fwd[i]] = i
    return fwd, inv


def make_gmkrypt_swap_table(seed):
    return make_generic_swap_table(6 + (seed % 250), seed // 250)


#: The swapped region always begins one byte after the seed header -- see the
#: pass-through byte in gmkrypt_decrypt. Returned so the encoder's index maths
#: reads against a name rather than a bare 1.
SWAP_START = 1


def gmkrypt_decrypt(data):
    """Undo the GM 6/7 'gmkrypt' pass. Returns (plaintext, seed, swap_start, swap_offset)
    — the latter three are what the encoder needs to put bytes back.

    The per-byte term `- (offset + i)` has period 256, so within each residue
    class of `i` the whole pass is a plain substitution. Decoding 256 strided
    slices with `bytes.translate` is ~25x a Python byte loop over a 7 MB tree.
    """
    s1 = u32(data, 0)
    s2 = u32(data, 4)
    pos = 8 + 4 * s1
    seed = u32(data, pos)
    pos += 4 + 4 * s2

    # Exactly one byte passes through untouched before the swapped region.
    head = data[pos:pos + 1]
    pos += 1
    swap_offset = pos                      # bytes consumed from the input so far

    _, table = make_gmkrypt_swap_table(seed)
    body = bytearray(data[pos:])
    for c in range(256):
        sub = (swap_offset + c) & 0xFF
        strided = bytes(body[c::256])
        body[c::256] = strided.translate(bytes((v - sub) & 0xFF for v in table))
    return bytes(head) + bytes(body), seed, SWAP_START, swap_offset


def encrypt_bytes(plain, seed, swap_offset, index, count):
    """Re-encrypt `count` plaintext bytes starting at `index` (index is relative to
    the start of the swapped region). Inverse of the loop above, so a patcher can
    write bytes back without re-encrypting the whole tree."""
    fwd, _ = make_gmkrypt_swap_table(seed)
    return bytes(fwd[(plain[i] + swap_offset + index + i) & 0xFF] for i in range(count))


ZLIB_HEADERS = (b'\x78\x9c', b'\x78\xda', b'\x78\x01')


def zlib_blocks(raw, start):
    """Candidate `[u32 len][zlib]` block positions at or after `start`, ascending.

    Found by searching for the zlib header and reading the length field back off
    its front, rather than testing a length field at every byte -- the exe is
    ~8 MB, so the difference is 6.5M struct unpacks against a handful of memchr
    passes.
    """
    out = []
    for magic in ZLIB_HEADERS:
        i = raw.find(magic, start + 4)
        while i >= 0:
            pos = i - 4
            if pos >= start:
                n = u32(raw, pos)
                if 1000 < n <= len(raw) - pos - 4:
                    out.append((pos, n))
            i = raw.find(magic, i + 1)
    out.sort()
    return out


def load(path):
    """Locate, inflate and decrypt a GM 7.0 gamedata tree."""
    raw = open(path, 'rb').read()
    magic = u32(raw, GM700_OFFSET)
    ver = u32(raw, GM700_OFFSET + 4)
    if magic != MAGIC or ver != VERSION:
        raise SystemExit(f'not a GM7.0 exe: magic={magic} version={ver}')

    # debug bool, then settings, then the d3dx8 name+content blobs, then the
    # encrypted tree. Rather than model settings, take the LAST [len][zlib] block,
    # which is the tree (it runs to EOF) -- so walk the candidates backwards and
    # stop at the first that actually inflates.
    for pos, n in reversed(zlib_blocks(raw, GM700_OFFSET + 8)):
        try:
            return raw, (pos, n, zlib.decompress(raw[pos + 4:pos + 4 + n]))
        except zlib.error:
            pass
    raise SystemExit('no zlib block found after the header')


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        'battleshipsforeverv090d/BattleshipsForever.exe'
    raw, (pos, clen, blob) = load(path)
    print(f'tree: compressed at {pos:#x} len={clen} -> inflated {len(blob)} B')

    plain, seed, swap_start, swap_offset = gmkrypt_decrypt(blob)
    print(f'seed={seed} swap_start={swap_start} swap_offset={swap_offset}')

    printable = sum(1 for b in plain[:200000] if 32 <= b < 127 or b in (9, 10, 13))
    print(f'printable in first 200KB: {printable / 2000:.1f}%')
    for probe in (b'initSections', b'external_define', b'l_maxhp', b'argument0',
                  b'spr_Section', b'GMZ_dll'):
        print(f'  {probe.decode():18s} x{plain.count(probe)}')

    out = 'dump/tree_plain.bin'
    open(out, 'wb').write(plain)
    print('wrote', out)


if __name__ == '__main__':
    main()

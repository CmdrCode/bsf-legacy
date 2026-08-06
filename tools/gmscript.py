#!/usr/bin/env python3
"""Parse GM 7.0 script records out of a decrypted tree.

Script record:  [u32 len][name][u32 version == 400][u32 zlen][zlib-compressed GML]

⚠ The script bodies are ZLIB-COMPRESSED (`78 9c`). That is why `dump/all_gml.txt` contains
script *call sites* but no script *bodies* -- the original dump never inflated this section.
Anything that prices GML by reading all_gml.txt is blind to every script in the game.
"""
import struct, re, sys, zlib, json

SCRIPT_VER = 400
NAME = re.compile(rb'^[A-Za-z_][A-Za-z0-9_]{0,63}$')

# ---------------------------------------------------------------------------
# Substitution table for the script-body obfuscation, solved 2026-08-02.
# Derived by: anchoring on the byte histogram (0x5B=space at 29.9%, 0x47/0x44 =
# CRLF at exactly equal counts), then a two-pass solver -- identifier matching
# against dump/all_gml.txt, and trigram context against the same corpus.
# Validated: 201/203 scripts brace-balanced; 86.9% of decoded identifiers appear
# verbatim in the independent RAM-scraped corpus; near-miss check against the
# 1084 GM builtin names from gmbuiltins.py leaves 15 mismatches in 19,647.
# Residual unmapped bytes: 0.34%, almost entirely inside comment banners.
# -------------------------------------------------------------------------
# CORRECTION 2026-08-04 -- five digit bytes were wrong, and it was not cosmetic.
#
# Ground truth is the angle-normalisation idiom, which appears in PLAINTEXT in the
# OBJECT section as ((a - b + 540) mod 360) - 180 and in wepTurningLimit as the
# same bytes -- a Rosetta stone for three digits, the other two following by
# elimination:
#
#     raw 6F 22 6B    read '?40' -> '540'    0x6F was UNMAPPED; it is '5'
#     raw 6E 71 6B    read '370' -> '360'    0x71 is '6', not '7'
#     raw 24 72 6B    read '150' -> '180'    0x72 is '8', not '5'
#     by elimination                         0x74 is '9' (was '8'), 0x21 is '7' (was '9')
#
# Independently confirmed against the plaintext object section: ctr_Turrets' Create
# sets l_maxtgsize = 99999 and wepCheckTgSize's guard is those same five bytes,
# which the old table read as 88888. Corrected digit frequencies over all 203
# scripts rank 0,1,2,3,5,4,8,6,9,7 -- a normal source distribution. Self-check: with
# the fix, wepTurningLimit decodes as textbook GML instead of garbage.
#
# What the error cost: under the old table tr_wep_tgal reads tr_fire(15) / tr_fire(18)
# where it is really 18 / 19. Channel 15 is ShipSection's rotation-limit trigger, so
# inlining that script's decoded text verbatim -- which an optimisation experiment was
# about to do -- would have rewired every turret's target-acquired trigger to a
# section event. A population-trace gate would very likely have absorbed it.
#
# The UPPERCASE letters are scrambled too: the same script's comment decodes as
# "ARQUIDE/LOST TADGET TDIGGED" for "ACQUIRED/LOST TARGET TRIGGER". Never trust a
# decoded script body carrying uppercase identifiers or numeric literals without
# cross-checking it against the plaintext OBJECT section (gmobj.walk_section()).
# -------------------------------------------------------------------------
SUBST = {
    0x01: 'w',
    0x02: 'z',
    0x03: 't',
    0x04: 'q',
    0x05: '}',
    0x06: 'n',
    0x07: 'k',
    0x09: 'h',
    0x0A: 'e',
    0x0C: 'b',
    0x0F: '[',
    0x10: 'X',
    0x12: 'U',
    0x13: 'D',
    0x15: 'O',
    0x16: 'L',
    0x18: 'I',
    0x19: 'F',
    0x1B: 'R',
    0x1E: '=',
    0x1F: ':',
    0x21: '7',
    0x22: '4',
    0x24: '1',
    0x25: '.',
    0x27: '*',
    0x28: '"',
    0x2A: '$',
    0x2B: '!',
    0x44: '\n',
    0x47: '\r',
    0x5B: ' ',
    0x5C: 'Y',
    0x5E: '%',
    0x61: '&',
    0x62: '(',
    0x64: ')',
    0x65: '+',
    0x66: ',',
    0x68: '-',
    0x69: '/',
    0x6B: '0',
    0x6C: '2',
    0x6E: '3',
    0x6F: '5',
    0x71: '6',
    0x72: '8',
    0x74: '9',
    0x75: ';',
    0x77: '<',
    0x78: '>',
    0x7B: 'A',
    0x7D: 'B',
    0x7E: '#',
    0x80: 'E',
    0x81: 'G',
    0x83: 'H',
    0x84: 'J',
    0x86: 'K',
    0x87: 'M',
    0x89: 'N',
    0x8A: 'P',
    0x8C: 'Q',
    0x8D: 'S',
    0x8F: 'T',
    0x90: 'V',
    0x92: 'W',
    0x93: 'C',
    0x95: 'Z',
    0x96: "'",
    0x98: ']',
    0x99: '_',
    0x9C: 'a',
    0x9D: 'c',
    0x9F: 'd',
    0xA0: 'f',
    0xA2: 'g',
    0xA3: 'i',
    0xA5: 'j',
    0xA6: 'l',
    0xA8: 'm',
    0xA9: 'o',
    0xAB: 'p',
    0xAC: 'r',
    0xAE: 's',
    0xAF: 'u',
    0xB1: 'v',
    0xB2: 'x',
    0xB4: 'y',
    0xB5: '{',
}


def decode(body: bytes) -> str:
    """Apply the script-body substitution. Unmapped bytes become U+FFFD."""
    return ''.join(SUBST.get(x, '\ufffd') for x in body)


def u32(b, p): return struct.unpack_from('<I', b, p)[0]

#: Where gm7.py writes the decrypted tree.
DEFAULT_TREE = 'dump/tree_plain.bin'


def candidates(b):
    """Ascending positions where a script record plausibly starts.

    A record is [u32 name_len][name][u32 SCRIPT_VER][u32 zlen][zlib], so the
    version dword is found first and the start backed out of it -- 64 checks per
    hit instead of a struct unpack at all ~7M byte positions of the tree.
    """
    tag = struct.pack('<I', SCRIPT_VER)
    out = []
    v = b.find(tag)
    while v >= 0:
        for pos in range(max(0, v - 4 - 64), v - 4):
            if u32(b, pos) == v - 4 - pos:
                out.append(pos)
        v = b.find(tag, v + 1)
    out.sort()
    return out


def parse_all(path=DEFAULT_TREE):
    b = open(path, 'rb').read()
    out = {}
    for pos in candidates(b):
        n = u32(b, pos)
        if pos + 4 + n + 8 > len(b):
            continue
        nm = b[pos + 4:pos + 4 + n]
        if not NAME.match(nm):
            continue
        zlen = u32(b, pos + 4 + n + 4)
        if not (2 <= zlen <= (1 << 22)):
            continue
        blob = b[pos + 4 + n + 8: pos + 4 + n + 8 + zlen]
        if blob[:1] != b'\x78':
            continue
        try:
            code = zlib.decompress(blob)
        except zlib.error:
            continue
        out[nm.decode()] = decode(code)
    return out

if __name__ == '__main__':
    s = parse_all()
    print(f"scripts: {len(s)}, total GML {sum(len(v) for v in s.values()):,} B", file=sys.stderr)
    json.dump(s, open('scripts.json', 'w'))
    for k in sys.argv[1:]:
        print(f"\n{'='*90}\n### {k}  ({len(s.get(k,''))} B)\n{s.get(k,'(missing)')}")

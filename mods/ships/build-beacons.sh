#!/bin/bash
#
# The Ratline beacons, built from nothing by the `ship` CLI.
#
# Both `.sb4` files here are tracked, so this script is not what produces the
# design -- the file is. It is what lets anyone change their mind about a
# colour or a spar and get the same hull back, which is not true of a design
# assembled by typing the commands once. Re-runnable: it starts by writing the
# bare header over whatever is there.
#
# EP9's Ratlines are marked by dead beacons -- "passive masses in expected
# places; the expected places are the secret" (campaign/ACT-II.md). So the
# design has to read as *switched off* while still being findable across a
# storm lane: cold steel structure, and a dead ember where the lamp would be.
#
#   bash mods/ships/build-beacons.sh
#
set -e
cd "$(dirname "$0")/../.."

S() { python3 tools/bsf/ship.py "$@" >/dev/null; }

F=mods/ships/beacon_ratline.sb4

# `accel` is deliberately non-zero: `export` writes a //battlestation tag when
# it is 0, and the game then grafts BattleStation's step event on, which spins
# the hull forever at l_turning. The mission holds these still with `hold:`.
# Core 5 is spr_Platform -- one of the two cores that carry no bridge bead,
# which is what keeps this from reading as a crewed ship.
cat > "$F" <<'EOF'
//sb4 ver2
//START



//SHIP & CORE

nShp,0.01,0,0.01,400,350,0,ratline_beacon,
nCor,5,0,58930,1,1,4210752,3000,3000,0



//SECTIONS

EOF

# --- structure ------------------------------------------------------------
# Depth is set explicitly: Game Maker draws larger depth first, so the lens
# sits in front of the housing and the housing in front of the spars it
# swallows. Everything overlaps by >= 10px (D10) -- the spars run 11 inside the
# housing edge, the caps 8 onto the spars.
#
# The east/west spars sit on y = 0, where a reflection would land on top of the
# original, so they are added singly; only the north spar takes --mirror.
S add 'Sections\Syn_sec02.png'         "$F" --at=0,0    --depth 6              # 1  housing
S add 'Stock Sections\BSF_Stock13.png' "$F" --at=0,0    --depth 1 --parent 1   # 2  lens
S add 'Sections\Ixr_sec04.png'         "$F" --at=47,0   --depth 7 --parent 1   # 3  spar E
S add 'Sections\Ixr_sec04.png'         "$F" --at=-47,0  --depth 8 --parent 1   # 4  spar W
S add 'Sections\Ixr_sec04.png'         "$F" --at=0,-47  --depth 9 --parent 1 --angle 90 --mirror
S add 'Kae_small\Kae_sec145.png'       "$F" --at=68,0   --depth 2 --parent 3   # 7  cap E
S add 'Kae_small\Kae_sec145.png'       "$F" --at=-68,0  --depth 3 --parent 4   # 8  cap W
S add 'Kae_small\Kae_sec145.png'       "$F" --at=0,-68  --depth 4 --parent 5 --mirror

# --- colour ---------------------------------------------------------------
# Every section is pinned with a fixed colour rather than a team shade, so a
# beacon looks the same whatever team it spawns into. That is the whole point:
# it belongs to nobody, and reading as ally-cyan would say the opposite.
#
# Section art is a two-tone mask -- fill 47/255, edge 255 -- so these values are
# what the *outline* comes out as and the body reads far darker. Hence colours
# that look too pale written down and correct on screen.
S colour all "$F" --to '#AFBECE'                       # cold steel structure
for i in 3 4 5 6;  do S colour $i "$F" --to '#8D9CAC' --no-mirror; done
for i in 7 8 9 10; do S colour $i "$F" --to '#6D7B8A' --no-mirror; done
S colour 2 "$F" --to '#6E5334'                         # the lamp, long out
S name "$F" 'Ratline Beacon'

# --- the hulk -------------------------------------------------------------
# Two of the five in EP9 are this one, so the run does not look stamped out.
# Damage is done by *removing* parts, never by rotating them: a rotated spar
# reads as a rotated sprite, and it opens a hole at the housing joint (D14).
# Removing section 3 takes cap 7 with it -- the cascade is the point.
H=mods/ships/beacon_ratline_hulk.sb4
cp "$F" "$H"
S remove 3  "$H" --no-mirror    # east arm sheared off flush with the housing
S remove 10 "$H" --no-mirror    # south cap gone, bare spar left
S colour all "$H" --to '#8E9AA6'
for i in 4 5 6; do S colour $i "$H" --to '#75818D' --no-mirror; done
for i in 8 9;   do S colour $i "$H" --to '#5D6874' --no-mirror; done
S colour 2 "$H" --to '#3A3630'  # this lamp is not merely off, it is gone
S name "$H" 'Ratline Beacon (hulk)'

# --- verify ---------------------------------------------------------------
# The .shp is what the game loads and it is tracked beside the .sb4, so
# exporting is part of building, not a step to remember later.
#
# The hulk has exactly one finding and it *is* the design: section 9's mirror
# partner was removed on purpose. `check --accept` would swallow it, but it
# would swallow the next one too -- and the baseline it writes lives in the
# gitignored cache, so a fresh clone would not have it anyway. Asserting the
# expected count instead keeps a real regression loud (D18).
# Counted off `check`'s own header line rather than off the finding lines: an
# accepted finding prints indented and an unaccepted one prints with a `!`, so
# a pattern written against either form silently counts the other as zero.
verify() {                      # <file> <expected finding count>
    local out n
    out=$(python3 tools/bsf/ship.py check "$1" --all) || true
    printf '%s\n' "$out"
    n=$(printf '%s\n' "$out" | sed -n '1s/.*: \([0-9][0-9]*\) finding.*/\1/p')
    if [ "${n:-0}" != "$2" ]; then
        echo "$1: expected $2 finding(s), got ${n:-0}" >&2
        exit 1
    fi
}

verify "$F" 0
verify "$H" 1
python3 tools/bsf/ship.py export "$F"
python3 tools/bsf/ship.py export "$H"

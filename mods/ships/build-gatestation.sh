#!/bin/bash
#
# Bolthole's gate battery -- the pair of gun platforms that challenge the player
# at the perimeter in EP9, before the yard itself is in frame.
#
# Design frame: **+x is forward**, toward the threat, because turret barrels
# point +x (D16) and building anything else means fighting the art. The mission
# turns the whole platform with `facing:`, so the two are mirror images of one
# situation rather than two designs.
#
# Sized off the game's own answer (D17): BattleStation is 4 sections and 1200
# hull with four Blasters, a PointMaser and a NanoMatrix; SmallStation is 6
# sections and 800. This sits between them and trades their light guns for one
# heavy mount, because the brief is menace rather than throughput.
#
#   bash mods/ships/build-gatestation.sh
#
set -e
cd "$(dirname "$0")/../.."

S() { python3 tools/bsf/ship.py "$@" >/dev/null; }

F=mods/ships/station_gatebattery.sb4

# l_colourtype 1 is the *allied* palette, and it is load-bearing rather than
# cosmetic: it makes `ship colour --team` resolve image_blend to the colour the
# game will actually draw, so the render and the running game agree. These are
# Bolthole's own guns and have to read as the same navy as the station behind
# them -- unlike the beacons, which belong to nobody and are pinned outright.
#
# accel non-zero so `export` does not tag it //battlestation and graft
# BattleStation's forever-rotating step event on; the mission holds it still.
# Core 5 is spr_Platform: no bridge bead, which is what a gun platform wants.
cat > "$F" <<'EOF'
//sb4 ver2
//START



//SHIP & CORE

nShp,0.01,0,0.01,900,350,0,gate_battery,
nCor,5,1,65535,1,1,4210752,3000,3000,0



//SECTIONS

EOF

# --- structure ------------------------------------------------------------
# A fortification, not a hull: roughly square in plan, so it reads as something
# emplaced rather than something that flew here. Every joint carries >= 6px of
# real overlap (D10), measured on the art rather than the origins (D12) --
# Old_CE30 63x53, Old_CE28 79x47, Old_CE41 54x34, Boba_sec04 63x53,
# Syn_sec06 54x34.
#
# The first pass hung the reactor off the back on a thin neck and let the
# cannon cover the whole prow, which read as a gun with a station attached. The
# armour now runs wider than the gun on every side.
S add 'Old Sections\Old_CE30.png'   "$F" --at=0,0     --depth 20            # 1 core block
S add 'Sections\Syn_sec01.png'      "$F" --at=40,0    --depth 12 --parent 1 --angle 90  # 2 armour face
S add 'Old Sections\Old_CE41.png'   "$F" --at=4,-36   --depth 30 --parent 1 --mirror  # 3,4 barbettes
S add 'Sections\Boba_sec04.png'     "$F" --at=-44,0   --depth 60 --parent 1 # 5 reactor block
S add 'Sections\Syn_sec06.png'      "$F" --at=-26,-34 --depth 45 --parent 1 --mirror  # 6,7 shoulders

# --- guns and shielding ---------------------------------------------------
# `arm` routes by object, so the Deflectors land in the *module* table where
# they belong -- a module in the weapon table costs the ship every weapon on it
# (D19c). Stats are written as the loader's -1 sentinel throughout, so each
# mount fights exactly like the object it names.
#
# The TacNukeCannon is seated back at +24 rather than out on the point: its
# origin sits 19.5 behind the muzzle and the sprite runs 30.5 in front of it
# (D16), so further forward puts the barrel out past the armour it is supposed
# to be firing from behind.
S arm TacNukeCannon "$F" --at=32,0    --parent 2            # the big one
S arm Railgun       "$F" --at=10,-36  --parent 3 --mirror   # barbette guns
S arm PointMaser    "$F" --at=-30,-22 --parent 1 --mirror   # point defence
S arm Deflector     "$F" --at=36,-30  --parent 2 --mirror   # forward shield emitters
S arm Deflector     "$F" --at=-4,-48  --parent 3 --mirror   # flank shield emitters
S arm NanoMatrix    "$F" --at=-44,0   --parent 5            # every stock station has one

# --- colour ---------------------------------------------------------------
# Hull on the allied palette so it matches the station it guards; the barbettes
# pinned to a hot amber, which is the only thing on the design that says
# *armed*. Three shades of the one palette give the armour depth the way a real
# hull gets it -- that is what the shade index is for.
S colour all "$F" --team 1
S colour 2   "$F" --team 0                        # armour face: the bright thing you meet
S colour 3   "$F" --to '#FFAE49'                  # barbettes: warning amber
S colour 6   "$F" --team 2                        # shoulders, paler plate
S name "$F" 'Bolthole Gate Battery'

python3 tools/bsf/ship.py check "$F"
python3 tools/bsf/ship.py export "$F"
python3 tools/bsf/ship.py tree "$F"

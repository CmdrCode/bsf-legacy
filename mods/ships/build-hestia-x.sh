#!/bin/bash
#
# Hestia X, prototype hull *Erebus* -- Bolthole's one cloaked destroyer, the
# ship Admiral Hong decloaks off the player's bow at the end of EP9.
#
# The brief in ACT-II.md is the design constraint, almost word for word:
# "Hestia's lines, but wrong in the particulars, the hull drinking the
# stormlight rather than returning it." So the bones are the stock Hestia,
# unmoved -- the same three sprites at the same six coordinates -- and the alien
# work is held *inside* their footprint. Nothing grafted on lengthens a wing or
# blunts a prong: read the silhouette and it is a Hestia, read the plating and
# none of it is Fleet.
#
#   bash mods/ships/build-hestia-x.sh
#
set -e
cd "$(dirname "$0")/../.."

S() { python3 tools/bsf/ship.py "$@" >/dev/null; }

F=mods/ships/hestia_x_erebus.sb4

# Stock Hestia numbers throughout (thrust 0.06, turn 0.75, speed 2.5, 300 hull,
# ai_range 350) -- a refit, not a new class, and the mission wants the player to
# recognise the drive signature.
#
# Core 1 is spr_Alien, and it is the thesis in one field: the reactor at the
# middle of a Fleet destroyer is salvage. It is also 36x36 against spr_Core's
# 56x24, so it fills the Hestia's narrow waist instead of hiding in it. The
# colour is a GM literal in BGR: 15752331 is #8B5CF0, the violet the whole graft
# is keyed to.
cat > "$F" <<'EOF'
//sb4 ver2
//START



//SHIP & CORE

nShp,0.06,0.75,2.5,300,350,0,hestia_x_erebus,
nCor,1,1,15752331,1,1,4210752,3000,3000,0



//SECTIONS

EOF

# --- the Hestia's bones ---------------------------------------------------
# Stock coordinates read straight off the shipped hull: strut (-22,-25), wing
# (-5,-45) hung off it, prong (38,-17), depths 5/6/4 as on the original.
#
# Measured footprints, which is what every graft below is placed against (D12
# -- the art, not the origin):
# Depths are spaced by four rather than packed. `--mirror` gives the partner
# depth+1, so packed values collide, and a collision is not cosmetic: ShipMaker
# drops a section that shares a depth on export, and `ship export` says so. The
# stacking order is the stock Hestia's -- prong over strut over wing -- with
# every graft strictly behind the Fleet plate it trims.
#   strut  BSF_Stock01  bar x[-40,-36] y[-46,-17], tail x[-40,-5] y[-17,-10]
#   wing   BSF_Stock02  wedge x[-38,+27] y[-56,-36], fat end at the left
#   prong  BSF_Stock03  wedge x[+3,+73] y[-28,-9], point at the right
#
# The prongs cover y[-28,-9] and y[+9,+28], so the Hestia has an open channel
# down the middle of its own delta -- y[-9,+9] from the core out to the points.
# That channel is where most of the alien work goes.
S add 'Stock Sections\BSF_Stock01.png' "$F" --at=-22,-25 --depth 8  --mirror             # 1,2 inner struts
S add 'Stock Sections\BSF_Stock02.png' "$F" --at=-5,-45  --depth 12 --parent 1 --mirror  # 3,4 rear wings
S add 'Stock Sections\BSF_Stock03.png' "$F" --at=38,-17  --depth 4  --mirror             # 5,6 forward prongs

# --- the graft ------------------------------------------------------------
# Kae_alien is the one section folder no stock hull touches -- 0 placements
# across the 111-ship corpus -- which is exactly why it is the right set here:
# nothing else in the game is built out of these plates.
#
# **The graft goes underneath.** An earlier pass laid the alien plates over the
# Fleet ones at low depth and lost the ship: the carapace covered every panel
# line that makes a Hestia look like a Hestia, and what came back was an alien
# hull with a Fleet outline. Buried plate is the BSF idiom anyway (D3), so these
# sit at depth 12+ and show only as fringe along an edge, or in the one place
# the Fleet plate leaves open.
#
# Both the wing and the prong slope 17 degrees down to the right (measured off
# BSF_Stock02 and BSF_Stock03: 17 rows over 56 columns), so every fringe plate
# is rotated -17 to lie along the edge it trims rather than crossing it. Mirror
# negates the angle, which is what the far side wants (D5).
S add 'Kae_alien\Kae_sec105.png' "$F" --at=-12,-51 --angle=17 --depth 24 --parent 3 --mirror  # 7,8   wing leading edge
S add 'Kae_alien\Kae_sec103.png' "$F" --at=34,-23  --angle=17 --depth 20 --parent 5 --mirror  # 9,10  prong leading edge

# Centreline, unmirrored -- these sit on y=0 and are their own reflection.
#
# 97 is the spine and it is the one that sells the ship. The prongs cover
# y[-28,-9] and y[+9,+28], so the Hestia has an open channel down the middle of
# its own delta; seated at +38 the spine runs x[3,72] and fills that channel end
# to end, surfacing at the points without extending them. Depth 7 keeps it
# behind the Fleet plate, so it shows exactly where the hull is open and nowhere
# else.
#
# 84 is the stern radiator, and it does structural work as well as visual: the
# strut tails end at x-40 either side of an open stern, and this spans between
# them.
#
# 88 is the only bilaterally symmetric plate in the set (symh 1.00), so it is
# the one thing allowed on top, at depth 0, wrapped around the bridge as a
# collar. It is not the cloak -- the cloak is a real module, mounted below.
S add 'Kae_alien\Kae_sec97.png'  "$F" --at=38,0   --depth 16   # 11 dorsal spine   x[3,72]  y[-7,6]
S add 'Kae_alien\Kae_sec80.png'  "$F" --at=-22,0  --depth 28   # 12 cloak plant    x[-49,5] y[-10,9]
S add 'Kae_alien\Kae_sec88.png'  "$F" --at=0,0    --depth 0    # 13 alien collar   x[-13,13] y[-10,10]

# --- guns -----------------------------------------------------------------
# The Hestia's own battery, mount for mount, because Hong refitted a destroyer
# rather than building one: Pulse on the wings, Blaster on the prongs,
# GatBlaster forward, ParticleGun aft. `arm` routes by object, so the shield
# modules land in the module table where they belong (D19c), and every stat
# stays at the loader's -1 sentinel so each mount fights as its object does.
#
# The one stat change the refit is allowed: the two Deflectors become
# AegisDeflectors, the closest thing the game has to the flux barrier the
# briefing describes.
S arm Pulse          "$F" --at=-5,-43  --parent 3  --mirror            # wing pulse
S arm Blaster        "$F" --at=40,-7   --parent 5  --mirror --arc 30   # prong blasters
S arm GatBlaster     "$F" --at=23,0    --parent 11 --arc 30            # forward gatling
S arm ParticleGun    "$F" --at=-25,0   --parent 12                     # aft particle gun
S arm AegisDeflector "$F" --at=-25,-56 --parent 3  --mirror            # flux emitters

# The Umbra Cloak. Not a stock part: `mods/umbracloak.gml` builds the object at
# load, parented to `ctr_Turrets` the way every stock module is, and puts the
# name in scope on `ctr_Ship` so a compiled hull can mount it. `ship arm` routes
# it as a module and writes every stat as -1, so the object's own Create is what
# the mount fights with.
#
# Seated at +56 on the dorsal spine: the delta's open channel is y[-9,9] and the
# 15x15 plate spans y[-7,7] there, so it sits in the one gap the Fleet hull
# leaves down its own centreline, ahead of the guns and behind the points.
S arm UmbraCloak     "$F" --at=56,0    --parent 11                    # the cloak itself

# --- colour ---------------------------------------------------------------
# Two families at roughly the same brightness, which is the whole trick: the
# hull does not read dark because it is nearly black -- that would just be
# invisible against space -- it reads dark because every colour on it is cold
# and unlit, and because the two materials plainly are not the same material.
#
# Pinned rather than team-shaded on purpose: a cloak that changed colour with
# the team it spawned into would be a paint job.
S colour all "$F" --to '#7C90B4'   # Fleet plate: cold steel, nothing shining on it
S colour 1   "$F" --to '#64769A'   # struts sit deeper
S colour 5   "$F" --to '#8698BC'   # prongs catch what little there is

S colour 7   "$F" --to '#6B45B8'   # wing leading edge
S colour 9   "$F" --to '#6B45B8'   # prong leading edge
S colour 11  "$F" --to '#A87BFF'   # dorsal spine, the length of the delta
S colour 12  "$F" --to '#5B379E'   # cloak plant
S colour 13  "$F" --to '#E6D8FF'   # cloak emitter -- the one bright thing on it

S name "$F" 'Hestia X'

python3 tools/bsf/ship.py check "$F" || true

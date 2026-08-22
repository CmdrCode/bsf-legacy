# BSF ships — reference

Field tables, grammar and mechanics for `tools/bsf/`. Everything marked
**(GML)** was read out of ShipMaker's own code; **(data)** was measured against
real ship files.

Run everything from `tools/bsf/`. Deps: Pillow, numpy. No wine, no game.

## Commands

```
ship tree       <file> [--json]        hierarchy; mounts listed under their host
ship render     <file> -o out.png [--scale N] [--no-bridge]
ship scene      <file>                 the flat draw list as JSON
ship serve      [FILE|DIR ...] [--root DIR] [--bind auto|IP] [--port N]
                                       live browser preview of every hull in
                                       the watched roots, on one port; prints
                                       the URL, tailnet one included
ship select     '<query>' <file> [--shot PNG] [--scale N] [--json]
ship check      <file> [--accept] [--all]
ship visibility <file> [--json]
ship move       <id> <file> (--by dx,dy | --to x,y) [--with-children] [--no-mirror]
ship rotate     <id> <file> --by DEG   [--with-children] [--no-mirror]
ship flip       <id> <file> --axis x|y [--with-children] [--no-mirror]
ship add        '<sprite>' <file> --at X,Y [--parent N] [--angle A]
                                     [--scale XS,YS] [--depth D] [--donor N] [--mirror]
ship mirror     <id> <file> [--with-children]
ship remove     <id> <file> [--orphan] [--no-mirror]
ship reparent   <id> <file> --to N [--no-mirror]
ship arm        '<object>' <file> --at X,Y [--parent N] [--angle A]
                                     [--arc R] [--mirror]
ship colour     <id|all> <file> (--to '#RRGGBB' | --team 0|1|2)
                                     [--with-children] [--no-mirror]
ship name       <file> [NEW]           show the display name, or set it
ship parts      list|sheet|near|build
ship log <file> / diff <file> <rev> / undo <file>
```

**Edit targets.** `move`, `rotate` and `remove` take a section id bare (`5`) or
a mount kind-prefixed (`weapon:0`, `module:1`, `doodad:2`). Mount ids are only
unique within a kind — a section 0 and a weapon 0 are both ordinary — which is
why the prefix exists. A *section* edit carries its mounts (D18); a *mount* edit
moves that one mount, which is what seating a turret needs.

The display name is `l_name`, token 6 of `nShp` (sb4) or `nShp2` (sh3) in both
generations. sh3 quotes it and sb4 does not; `ship name` handles that, and
refuses a name containing a comma because the loader has no escaping for one.

Small things that waste a minute each:

- **Negative coordinate pairs** work bare (`--at -60,0`) *and* with `=`. The CLI
  rejoins them before argparse sees them, because argparse otherwise reads a
  leading `-` as a flag and `-60,0` does not look like a negative number to it.
- **`ship diff` is `<file> <rev>`**, not the other way round.
- **Query bare-words reject regex anchors.** `name ~ ^BSF_Stock09$` will not
  tokenize; quote it — `name ~ "^BSF_Stock09$"`.
- **sh3 quotes `l_name` and sb4 does not.** `ship name` handles it; hand-editing
  does not.
- **Kill a preview with `fuser -k <port>/tcp`, never `pkill -f`** — `pkill`
  matches the calling shell's own command line and kills it.

Gates: `python3 roundtrip.py` (add `--strict` to also validate `gmstr()` against
every number on disk) and `python3 selftest.py`. Both must pass before an edit
is finished; `selftest` covers what byte-equality cannot see.

## Selector grammar

```
expr  := or
or    := and ('or' and)*
and   := not ('and' not)*        -- juxtaposition also means 'and'
not   := 'not' not | atom
atom  := '(' expr ')' | call | field OP value | word
call  := touching '(' secid ')' | near '(' secid ',' px ')'
OP    := = | == | != | < | <= | > | >= | ~
```

`~` is a case-insensitive regex search, so plain substrings work too.

| class | names | cost |
|---|---|---|
| fields | `id kind name sprite x y angle xscale yscale depth parent mirror hp defhp alpha colour` | free, reads the file |
| derived | `visible area occluded` | one render, shared by the whole query |
| words | `section weapon module doodad mirrored floating all` | `floating` renders |
| calls | `touching(secid)` `near(secid, px)` | render |

Output says which class you were in — `[file only]` or `[one render]`. Calls
take a **section** id on purpose: pointing a durable selector at a weapon id
builds on the one thing the format guarantees will change.

`ship parts list --where` uses the same grammar over a different field set:
`name folder w h bw bh px fill aspect cx cy symh symv flat_n flat_e flat_s
flat_w radius`. All continuous — `symh > 0.9`, not `symmetric`, because
hand-drawn masks are near-symmetric, not symmetric.

## Coordinates

Core-relative, **y down**. The file stores absolute canvas coordinates for
sections and mounts; the CLI converts on read and write. `.shp` (sh3) already
stores core-relative, which is how the convention was confirmed: Pendulum's
section 1 is `3590,3075` in `.sb4` against a core at `3620,3060`, and
`nSec2a,-30,15` in `.shp`. **(data)**

`secparent` is `0` for the core in `.sb4`, `-1` in `.shp`.

## Record fields

Field indices below **exclude** the record kind, so `nSecA[0]` is `secid`.

```
nCor    image_index, l_colourtype, l_colour, xscale, yscale, l_fadecol, x, y, l_formrank
nSecA   secid, x, y, lname, xscale, yscale, angle,
        l_hp, l_defhp, l_blend, image_alpha, image_blend, depth, secparent
nSecB   secid, rs_rotate, rs_limit, rs_rotcwframes, rs_rotccwframes, rs_cwdelay,
        rs_ccwdelay, rs_cwborder, rs_ccwborder, rs_startcounter, rs_startrotang,
        0, l_colourmod, l_colour, eff_noglow, eff_shimmer
nSecC   secid, effect, ef_alpha, 0, ef_hidelay, ef_lodelay, ef_hiborder, ef_loborder,
        ef_blend, ef_color, l_blurragemin, change, ef_offx, ef_offy, eff_xscale, eff_yscale
nSecD   secid, ef_fade, ef_fadeinframes, ef_fadeoutframes, ef_startcounter,
        ms_move, ms_dist, ms_dir, ms_aframes, ms_rframes, ms_adelay, ms_rdelay,
        ms_startcounter, ms_startdist
nSecTr  secid, tr_ontype1, tr_offtype1, tr_ontype2, tr_offtype2, tr_ondelay,
        tr_offdelay, tr_mode, tr_oneframes, tr_offeframes[, ]   <- ver2 trailing comma
nWepA   wepid, x, y, sprite, xscale, yscale, angle, image_speed,
        image_alpha, image_blend, 0, colour
nWepB   wepid, parent.secid, arcrange, ...
nModA   modid, x, y, sprite, xscale, yscale, angle, image_speed, 0, duplicate,
        l_hp, l_range, l_target.secid, l_eng, l_engregen, l_cost
nModB   modid, parent.secid, l_special1..l_special8, image_alpha, colour
nModC   modid, ts_depthed
nDooA   dooid, x, y, lname, xscale, yscale, angle, image_speed, depth,
        image_blend, l_colour, l_start, l_blend, image_alpha, parent.secid
nThrEx  modid, t_sprite, t_angrange, t_xscale, t_yscale, t_shake, t_aspeed, t_dspeed
nSecMir / nWepMir / nModMir / nDooMir    id, partner id   (-4 = no partner)
nTrigS  owner secid, on(1)/off(0), target kind 1=section 2=weapon, target id
nDriver wepid, driven secid
nLink   parent wepid, wepid
```
All **(GML)**, from the save routine.

**Tier 1** (parsed, editable, rendered, queryable): `nShp`, `nCor`, `nSecA`,
`nSecMir`, `nWepA/B/Mir`, `nModA/B/Mir`, `nDooA/Mir`.
**Tier 2** (round-tripped verbatim): everything else — `nSecB/C/D/Tr`,
`nWepC/D/Tr`, `nModC`, `nTrigS`, `nDriver`, `nLink`, `nTesla`, `nThrEx`.

The `.sb4` loader's `switch` has **no `default:`**, so unknown records are
silently ignored — useful (custom metadata can ride in the file) and dangerous
(ShipMaker drops it on resave). **(GML)**

## The mirror transform

Reflection about the core's horizontal centreline. **(GML)**, from the editor's
auto-mirror routine.

Everything: `y -> 2*core.y - y`, `image_angle -> -image_angle`.

| part | also |
|---|---|
| section | `yscale -> -yscale`; `nSecB` swaps `rotcw/ccwframes` and `cw/ccwdelay`, swaps **and negates** `cw/ccwborder`, negates `startrotang`, and sets the side marker `rs_startcounter`; `nSecC` negates `ef_offy` and `eff_yscale`; `nSecTr` swaps trigger types 5↔6 and 11↔12 |
| weapon | `yscale -> -yscale` **only** for `Sidewinder` |
| module | `l_target` retargets through the mirror; `Thruster`/`ThrusterEx` take `l_special6 -> 360 - l_special6` |
| doodad | nothing else — the editor does not flip a doodad's `yscale` |

Parent remap, for every kind:

```
if src.parent is the core || |src.parent.y - core.y| < 1:  copy.parent = src.parent
else:                                                      copy.parent = src.parent.mirror
```

**`yscale` is the trap.** Only a *section* negates it (plus `Sidewinder`, whose
sprite is not symmetric about its barrel). An ordinary weapon, a module and a
doodad all keep theirs — the editor only touches their angle. A checker that
expects a flip everywhere reports every correctly mirrored turret on every ship.

**When a pair needs different deltas, the drift *is* the defect.** If a mirror
pair has to move by different amounts to line up, do not try to express that
through `--mirror`; use `--no-mirror` and set each side explicitly, then verify
`check` reports no `mirror` findings for the pair.

**Side marker caveat (data).** ShipMaker writes `rs_startcounter = ±1` on the
copy and then calls `resetRotation`, so no file on disk contains `+1`: every
real pair carries `-1` on one side and `0` on the other. The CLI reproduces the
observed convention, not the pre-reset intermediate.

## Creating sections

New sections **clone a donor's** `nSecB/C/D/Tr`, rewriting only the id and the
handed fields. Donor preference: `--donor`, then a section with the same sprite,
then the new parent, then anything. With no donor at all, corpus defaults are
used and said out loud.

New ids are `max(secid) + 1` and **never reuse a gap**. `nTrigS` targets are
tier-2 and a delete can strand one; taking a fresh id keeps a stale trigger
visibly dangling instead of silently re-binding it to an unrelated new part.
`check` reports dangling references.

**`l_defhp` has no formula (data).** It is per-section state: on
`station_bolthole`, four sections share one sprite, one scale and full
visibility and still carry 197.12, 196.79, 243.28 and 242.27. It is inherited
from the donor; set it in ShipMaker when it matters.

## Rendering

`scene.py` compiles one flat, depth-sorted draw list and both renderers consume
it, so the PNG and the browser canvas cannot disagree. Game Maker draws **larger
depth first**, so the highest depth is furthest back; the core sits at 99999.

Doodads are not a layer — ShipMaker recomputes every doodad's depth as
`parent.depth - 0.0001` after a load, putting each immediately in front of the
section it is attached to. **(GML)** The same code re-depths a weapon or module
*if* its `ts_depthed` flag is set, which the fixed weapon/module layers do not
model; no ship on disk sets it, and settling layer order is a `ship verify` job.

Other things that will bite:

- **GM colours are BGR.** `8454016` = `0x80FF80` = rgb(128,255,128). `$FF2222`
  is blue — which is what makes deflectors and boosters read as glowing beads.
- **Sections are two-tone masks** multiplied by a team colour. Converting one
  naively to RGBA yields a black square. The fill tone is 47/255 and the edge
  255, so a section drawn in `#AFBECE` reads as a near-black body with a pale
  steel outline. Pick the colour you want the **outline** to be.
- **A mirror pair sits at adjacent depths.** 69 of 73 pairs on disk differ by
  exactly 1, and the four that do not carry hand-set values. **(data)**
  `ship mirror` inserts the twin immediately behind its partner and pushes
  everything deeper back one; it used to hand out `next_depth()`, which put the
  reflection at the very back of the stack and drew one of four identical spar
  caps behind the spar the other three sat in front of.

### The live preview page

`ship serve` watches **roots, not a file**: every hull in them is in one
dropdown on one port. Bare, the roots are this repo's `mods/ships` and the
game's `Custom Ships` (via `paths.py`); naming files or directories replaces
that set, and `--root DIR` adds one. A named *file* is also the hull shown
first — otherwise it is the most recently saved `.sb4`. Roots are rescanned
every tick, so a hull ShipMaker saves appears without a restart. The scan is one
level deep.

```
GET /                      the page
GET /index[?ship=KEY]      the list, plus the selected hull's content hash
GET /scene.json?ship=KEY   the draw list, sprites inlined, `rev` alongside
```

- **A KEY is `<root-index>/<filename>`, resolved only by lookup in the current
  scan.** It is never joined onto a directory, so `?ship=../../etc/passwd` is a
  miss rather than something traversal has to be defended against. This is not
  theoretical: `--bind` is the documented way to show work to someone.
- **Both generations are listed.** A `.shp` beside a same-stem `.sb4` is
  indented under it and marked **⚠ stale** when its mtime is older — D20 made
  visible, so "did I re-export?" is answered on the page. Unpaired `.shp` (the
  stock hulls in `Custom Ships`) are ordinary entries.
- **The selected hull is content-hashed; the rest are stamped.** `/index`
  returns sha256 for the one on show and `(mtime, size)` for every other, which
  drives a **●** on hulls that changed while you were looking elsewhere. The dot
  is therefore approximate — a same-second, same-size rewrite elsewhere can miss
  — while the repaint of the hull you are watching is exact.
- **`/scene.json` returns the `rev` it served**, so a switch costs one fetch
  rather than two. Without it the next poll sees a different hash and re-fetches
  a scene the canvas already holds.
- **Sprites hot-reload, not just ships.** A hull's `rev` is its own bytes *plus*
  `sprites.tree_rev()`, a digest of every file under `Custom sprites/` (and the
  exe cache) by path, mtime and size — 565 files, 1.5 ms warm, reused for
  `TREE_TTL` = 200 ms. A ship's bytes say nothing about the art it names, so
  without that half a sprite dropped in beside a hull waiting for it stayed
  `unresolved` until the ship file itself was touched — the state you are in
  while drawing the sprite. The digest covers the *whole tree* deliberately: the
  case worth catching is a file that does not exist yet, and there is nothing to
  watch until it appears. Any sprite touched moves every hull's rev, which costs
  a watching page one re-fetch.
- **Three caches had to learn it, and each was invisible to the others.**
  `sprites.load`/`load_rgba` are keyed by `(path, flags, stamp(path))` rather
  than by path, so changed art is simply a different key and the stale entry
  ages out of the LRU — nothing decides when to invalidate. `stamp` is
  `(st_mtime_ns, size)`, not a content hash, which would mean re-reading 1.1 MB
  per poll to answer "nothing changed"; the gap that leaves is a same-size
  rewrite inside the filesystem's mtime granularity, which is nanoseconds on
  ext4 but a second or two on FAT and some network mounts. The browser's caches
  fall out of the token below.
- **Nothing on the wire is a path — `spr` is a token for the pixels.**
  `for_web` replaces each op's `spr` with `sha256(data URI)[:16]` and drops the
  scene's `file`. Three things at once: the page's image, alpha and tint caches
  are keyed by `spr`, so changed art arrives under a key it has never seen and
  is decoded again *while unchanged art stays a hit*; `--bind auto` offers this
  page on the tailnet, and both fields were absolute paths naming the account
  the game sits under; and one sprite wanted by two ops with different `mask` or
  pivot flags stops colliding, which the path key silently got wrong. `build()`
  keeps real paths — `render` and `check` need them — so the rewrite copies the
  ops rather than mutating them. `selftest.py` pins the privacy half directly
  and the hot-reload half against a temporary sprite tree.
- **`/index` echoes the key it answered about as `req`.** A poll in flight when
  you switch hulls answers about the *previous* one; adopting that undoes the
  switch, which is exactly what two fast presses of `]` did until `req` existed.
- **Hover asks the art, not the sheet.** The pick inverts the blitter's own
  transform, lands on a sprite pixel and reads its alpha. Both halves of that
  matter and both were once wrong: a sprite is not centred on its origin
  (`ox,oy` is the rotation point — a Blaster's is the base of its barrel, 5.0px
  right of centre, a NanoMatrix's 4.5), and a sheet is mostly empty (a section
  is 80x80 holding a plate filling 4% of it for `BSF_Stock09`, 27% for
  `BSF_Stock17`). A box centred on the origin therefore claimed forty pixels of
  clear space in every direction, and — sections sorting by depth — the front
  plate's empty sheet shadowed everything behind it. Measured on the Bolthole
  against the renderer's id buffer, it named the right part on **39.9%** of
  painted pixels and claimed a part on **47.6%** of the background; the pixel
  test scores 100% on both. `selftest.py` pins it by running the page's own JS
  under node (`pickcheck.mjs`) against that id buffer — the renderer already
  knows, per pixel, which op it drew, so there is no second opinion to maintain.
- **Overlap is answered by the stack, not by the top of it.** A pick collects
  *every* part under the cursor, front-most first, and the HUD lists them with a
  depth count. `↑`/`↓` walk the list without moving the mouse, which is the only
  way to reach a plate that is wholly buried. **Click pins** the stack so the
  cursor can leave — pinned, the list itself is clickable; `esc`, or a click on
  clear space, frees it. The current part is marked by its own silhouette in
  green rather than by a box, since the box is exactly the thing that is not the
  part.
- **`peel` (the toggle, or `p`) hides whatever is drawn *in front of* the
  current part**, which is what actually hides it; parts behind stay at the
  usual dim, because those are context rather than obstruction. Unpeeled they
  ghost to 0.10 instead. This is the viewer's answer to D3 — buried plate is
  armour, so the tool shows it rather than inviting you to delete it.
- **The pick holds the op, not its id.** Ids are unique only within a kind: the
  Bolthole has 33 collisions across `section`/`weapon`/`module`, so an id-keyed
  highlight lit whichever op happened to match. `render.py` had already learned
  this for `highlight=`; the page had not.
- **Zoom, pan and the toggles survive a switch** — flipping between two hulls at
  one scale and screen position is a blink comparator. `0` or a double-click
  re-centres, which is what makes keeping the pan safe. `[` and `]` cycle.
- **A failure is one hull's.** A scene that will not build draws a card naming
  the file and the exception while the server stays green, retried once after
  200 ms so a half-written ShipMaker save heals itself. Note the model is
  *lenient* — junk content builds a bare core rather than raising — so this path
  is for I/O and for bugs, not for malformed files.
- Nothing on the wire carries an absolute path: roots travel as short labels,
  repo-relative inside the checkout and the bare directory name outside it.

**Where it listens.** `--bind auto` is the default and opens *two* sockets:
loopback, and the Tailscale address when `tailscale ip -4` reports one in
`100.64.0.0/10`. Two sockets rather than a wildcard bind is the point — the URL
works from another of your devices without the page being offered to whatever
network the machine is on. `--bind <addr>` forces a single socket, so
`--bind 127.0.0.1` is the opt-out and `--bind 0.0.0.0` the deliberate LAN
exposure. The IP is used rather than the MagicDNS name because the name is the
machine's hostname and a URL travels.

Startup prints one line per address, deep-linked to the hull that was named on
the command line (bare, no `?ship=` — the page picks the newest itself and a
link would be a guess). **Starting a second server on a port that already has
one is refused**: `run()` fetches `/index` first, and if a preview is there it
prints the URL for your hull and exits 0, or exits 4 saying the running one does
not watch that file. So re-running `ship serve <hull>` is how you recover a lost
URL.

`serve.resolve(route, query, index)` is split out of the request handler so all
of the above is testable without a socket; `selftest.py` drives it directly,
along with `addresses()`, `tailscale_ip()` and `_links()`.

### Mount stats, and the `-1` sentinel

`nWep2a` and `nMod2` both test each stat against `-1` before assigning it, so
`-1` means *keep whatever the object's own Create event set* — not "missing".
**(GML)** `ship arm` writes `-1` throughout, which is why a mount fights like
the object it names rather than like the donor it was cloned from.

| record | `-1`-guarded fields |
|---|---|
| `nWep2a` | firingrate, firingclip, firingreload, damage, turning, deviation, hp, range, bulletcol, bulletspeed, specials 1–5 (`l_name` uses `""`) |
| `nMod2` | cost, eng, engregen, hp, range, specials 1–8 (`l_name` uses `""`) |
| `nTur2` | **none** — `l_arcrange` and `l_arcoffset` are assigned flat |

Two consequences worth keeping:

- **A zero is not a `-1`.** `0 != -1`, so writing zeros *overrides*, and a
  NanoMatrix with range 0 repairs nothing while looking exactly like one that
  works. `sprites.MODULE_DEFAULTS` holds the values measured in a running game;
  anything absent from it is written in `-1`s and behaves stock, which is why
  an unmeasured module mounts fine.
- **`arcrange` has to be stated.** `ship arm` defaults to 180 (the full circle)
  and `--arc` narrows it. Nothing else on a mount needs a real number.

### Fixing a section's colour

A section does not normally own its colour: `l_colourmod` indexes the team's
three-shade palette and the game tints by whichever team the hull spawns into.
`-1` is the escape hatch — ShipMaker offers it as *"2. Custom Color"* — and then
`l_colour` beside it is the literal GM colour. `ship colour` is the supported
way to set it, because **the value lives in two places and needs both**:

| where | field | who reads it |
|---|---|---|
| `nSecA[11]` | `image_blend` | ShipMaker's canvas, `ship render`, `ship serve` |
| `nSecB[12]`/`[13]` | `l_colourmod`/`l_colour` | `ship export`, and so the game |

`export` appends `l_colour` as `nSec2a`'s optional **eleventh** field, but only
when `l_colourmod` is `-1`; the game's `nSec2a` closes with `if argument10 = 0
then l_colour = global.colour[…] else l_colour = argument10`. **(GML)** So
writing `image_blend` alone — the obvious edit, and the one `stockship` makes
for its wreck tint — gives a design that is the right colour in every picture
and the team's colour in the only place that counts.
- **Exe frames arrive already keyed.** Their alpha is resolved; re-running GM's
  bottom-left keying over them throws it away.
- **`destination-in` composites against the whole canvas**, not the sprite being
  drawn. Tint on an offscreen canvas or every masked op erases what came before.
- Sprite origins come from the resource tree, not a fitted heuristic —
  `exeart.py` reads `origin_x`/`origin_y` out of the decrypted exe.

## File encoding

A ship file is either plain text or shifted by +68 per byte. **Do not sniff for
a leading `//`**: of 168 files on disk only 20 begin with a comment, 141 are
plain Game Maker source starting with `event_inherited()` or `sprite_index=`,
and 7 are genuinely shifted. `model.decode` scores both readings and takes
whichever looks like text. A byte-exact round-trip cannot catch this mistake,
because `encode` undoes whatever `decode` did.

Four generations, all readable by the corpus miner:

| gen | sections written as |
|---|---|
| `sb4` | `nSecA,id,x,y,sprite,...` records, absolute coords |
| `sh3` | `nSec2a,x,y,"sprite",...` records, core-relative |
| `sh2` | `nSec(x,y,spr_SectionNN,...)` GML calls |
| `sh1` | raw GML: `instance_create(x,y,ShipSection)` then `sprite_index=spr_...` — also `EShipSection` on campaign opponents |

`.sb4` has two versions; ver2 adds a trailing comma to `nSecTr`. Token-preserving
storage handles it — do not special-case it.

### What the game does with the file

Every generation ends up as GML the game compiles. `importShip` reads the file,
`unkryptstring`s it if it is shifted, and hands the text to `object_event_add(
newobj, ev_create, 0, cod)` — a ship object is created at load time and the file
*is* its Create event. sh1 and sh2 go in as they are. sh3 goes through
`parseReadParams`, which rebuilds each record as a call — `nSec2a,1,2,…` becomes
`nSec2a(1,2,…)` — and concatenates them into the same string. **The CSV
generation is a compact source encoding, not a data format**; what it bought was
file size and load time, not safety.

So a string field is code, and the format has no escaping anywhere: a comma ends
the field, a newline ends the record, a quote closes the string, and whatever
follows is compiled. `model.FIELD_UNSAFE` names the three characters; `Ship.name`
refuses them and `export._qstr` / `export._ident` strip them, which is the only
thing between a hostile `.sb4` and a `.shp` that runs code on load.

**The game's own filter is not a backstop.** It is five substrings — `file_`,
`execute_`, `registry_`, `object_event_`, `script_` — checked only on the sh1/sh2
path, with the one legitimate `object_event_add(...draw_sprite_ext...)` line
swapped out for a sentinel first so it does not trip its own test. Two things
make it inert: the arguments are reversed, so `string_pos(words, "file_")` looks
for the whole ship inside the five-character literal and returns 0 for every
ship (the same script writes `string_pos("//sh2", words)` correctly nine lines
later), and `external_define` / `external_call` were never on the list anyway.
Treat any `.shp` from outside as executable — `ship tree` reads one by regex and
never evaluates it, which is the safe way to look.

**All four generations now build sections and mounts**, not just `.sb4`. Before
that, `ship tree` on any `.shp` reported 0 sections while round-tripping the file
byte-exact, which reads as "the ship is empty" rather than "this reader does not
model it". The mapping below was recovered by aligning `Custom Ships/Pendulum.sb4`
against its own export `Pendulum.shp` — the same eight sections in both
generations, and the only cross-generation pair that exists.

### sh3 (`nSec2a`) — what it drops, and where it hid it

    nSec2a,x,y,"sprite",image_xscale,image_yscale,image_angle,l_hp,blend,alpha,shade

* **No section id.** A section is its position in the file, and `nPar2` refers to
  sections that way. The model exposes 1-based ids so `0` still means the core.
* **No depth field — depth is record order**, strictly descending. Pendulum's
  eight `nSec2a` records carry the `.sb4`'s depths 8,7,6,5,4,3,2,1 in exactly
  that order, which is also why the two files list sections differently.
* **No resolved colour — the last token is the team shade index.** `.sb4` stores
  `image_blend` already resolved; sh3 stores 0/1/2 into the team's palette,
  because the colour is not the ship's to choose — the game tints by the team it
  spawns into, which is why `importShip` takes one. Across Pendulum's sections
  the indices 2,2,0,0,1,1,0,0 line up exactly with (128,255,128), (0,255,0) and
  (64,255,64), the player palette in order. Reading this token as "no colour"
  renders the whole hull **black** and looks entirely plausible in `ship tree`.
* **Parents live in `nPar2,<parent>,<child>`**, both 0-based record indices, and
  the argument order is the reverse of everything else in the format. Pendulum's
  four records (6,2) (7,3) (6,4) (7,5) reproduce the `.sb4`'s 5→3, 6→3, 7→4, 8→4.
* **Weapons and modules share one family**, `nTur2,x,y,sprite,angle,…,parent`.
  Pendulum's four records are its three weapons *and* its ThrusterEx. No scale is
  recorded; every mount in the twin is 1.

### sh2 — sh3's structure in call syntax

`nSec(x,y,sprite,xs,ys,ang,hp,shade)`, `nTur(...)`, and the same reversed
`nPar(parent,child)`. Lines end in a **bare CR**, so `re.M` anchored on `\n`
matches nothing — normalise before parsing. sh2 and sh1 name GM *resources*
(`spr_Section01`); only sh3 stores a file path, which is why a hull using
`Kae_detail/` art cannot be expressed as sh1 or sh2.

### sh3 tier-2 — solved from the source, not from the files

`nSec2b`, `nSec2c`, `nSec2M`, `nSecT` and `nSec2d` are **animation state**, and
`tools/bsf/export.py` writes all of them. `ship export foo.sb4` produces the
`.shp` the game loads.

| record | sets | notes |
|---|---|---|
| `nSec2b` | `rs_*` | rotation: frames, borders, delays, start angle |
| `nSec2c` | `ef_*` | glow/fade; the tail means `blurrage` when `effect == 5` and offsets/scales otherwise |
| `nSec2M` | `ms_*` | movement: distance, direction, frames, delays |
| `nSecT` | `tr_*` | triggers |
| `nSec2d` | `eff_noglow`, `eff_shimmer` | **and `j += 1`** — this is what commits the section |

**How, and why the earlier attempt failed.** Both are decompilable: the game
carries the readers (`nSec2a`…), ShipMaker carries the `.sb4` readers (`nSecA`…)
*and* `saveShipSHP`, its own writer. ShipMaker is a GM7 game, so `gm7.py`
decrypts its tree and `gmscript.py` parses its 233 scripts exactly as for the
game. **The source was available the whole time; the earlier pass inferred by
aligning example files and concluded the format was unrecoverable.** Reach for
the decompiled source before comparing artefacts.

Two traps only the source shows:

* **Order is depth, descending — and ties lose sections.** `saveShipSHP` builds
  the order with `ds_map_add(objs, deep, id)` and drains it by key, so sections
  sharing a depth collide and all but one vanish. `station_bolthole.sb4` has
  five at depth 200; ShipMaker would export 126 of its 130. `export.py` sorts
  stably and keeps all of them, warning that it diverged.
* **Frames must be non-zero even when the animation is off.** `nSec2M`'s reader
  computes `ms_dist/ms_aframes` unconditionally.

Seams do not line up between the generations: `ef_fade` is stored by `nSecD` and
read back by `nSec2c`, and the `.sb4` keeps fade as a *frame count* where the
`.shp` keeps a *speed* (`resetFade`: `(hiborder - loborder) / frames`). Map per
field, never per record.

**The gate** is `roundtrip.py --export`: re-export every `.sb4` in the game's
`Custom Ships/` that ships beside its own `.shp` and compare. Today that is
Pendulum alone. It deliberately does **not** scan `mods/ships/`, because
`ship export` writes the `.shp` next to the `.sb4` there — grading the writer
against its own output passes by construction. Pendulum matches on every line
except `//sh3 ver1` (it predates the `ver2` tag) and eight `nTrigS/nTrigW
…,9,0,0` lines, which are inert: they set `tr_toggle` on parts whose four
trigger types are all zero, and the game's `nSecT`/`nWepT` already do that for
exactly those parts.

**Trigger types ≥ 11 need a partner** named by an `nTrigS`/`nTrigW` record
(11–16 a weapon, 17–19 a section). Without one the trigger is dangling and
exports as 0 — Pendulum settles both directions in one file: its sections 6
and 8 store type 17 *with* records and keep it; its first weapon stores 17
without one and comes back 0.

## Weapons

`ship arm <object>` takes the game's own object name -- `PointMaser`,
`Blaster`, `ParticleGun`, `NanoMatrix` -- which is what `nWepA[3]` stores.

`nWepA` is understood field by field. **`nWepB` past `parent.secid`, and all of
`nWepC`/`nWepD`/`nWepTr`, were never recovered**, so a new weapon clones them
from a real one: a weapon already on the ship, else one off Pendulum. Same
argument as D16 -- a template of plausible zeros is how a turret ends up with no
firing arc.

How the game arms its own stations, which is the place to start rather than
guessing:

| ship | armament |
|---|---|
| `Flak_Platform` | 1 section, 1 `PointMaser` -- *this is the point-defence weapon* |
| `Defence_Platform` | 1 `Blaster` |
| `Battle_Station` | 4 `Blaster`, 1 `NanoMatrix`, 1 `PointMaser` |
| `Space_Station` | 2 `ParticleGun`, 2 `Blaster`, 1 `NanoMatrix` |
| `Fleet_HQ` | 2 `Laser`, 4 `Demeter`, 2 `ParticleGun`, 1 `ProjectorSol`, 1 `NanoMatrix` |

Every stock station carries exactly one `NanoMatrix` (repair).

**Turret geometry.** Sprites are small (`PointMaser` 12x9, `Blaster` 23x12,
`ParticleGun` 11x7) with **off-centre origins** and barrels pointing **+x**. Two
consequences: a turret on the −x flank must be rotated 180° or it aims into the
hull, and rotating moves the body several pixels relative to its origin, so it
has to be re-seated afterwards. Seat against the hull edge *measured at that
row* -- the same spine measured 22 wide at one row and 18 at another.

## Importing the game's own ships

`stockship.py` reads any of the 63 shipped ships out of its Game Maker source
and writes it into a `.sb4` -- used to size a station's berths against the hulls
meant to dock there. Four things it has to get right:

- **`l_child` declares attachment backwards.**
  `l_section[j].l_child[...] = l_section[j-1]` means *j owns j-1*, so the parent
  link is the inverse of the declaration.
- **The subscript nests.** `l_child[l_section[j].l_childnum]` contains its own
  `]`, so a pattern matching it must backtrack to the bracket that really closes
  it.
- **Weapons live in a second index space**, after a `j = 0` reset, and attach
  via `l_section[K].l_child[...] = l_weapon[j].id`.
- **Every ship needs a core.** BSF ships draw a hull that their plates bolt
  onto, and a `.sb4` has room for one `nCor` which the host already owns -- so
  an imported ship gets its core as an ordinary section wearing
  `Stock Misc\spr_Core.gif`. That doubles as the hull's single root, so
  `remove <root>` takes the whole ship, turrets included.

Damage a moored hull by removing sections **with cascade, never `--orphan`** --
orphaning leaves a wing floating where the hull used to be.

## The linter

`check` has an opinion about exactly six things, all mistakes rather than
choices: `duplicate` (same art, same place, same transform), `floating` (not
touching the hull), `hole` (background enclosed by **two or more** parts — a
pocket rimmed by one part is a window in that part's own art), `mirror` (a pair
that does not reflect, with the exact deviation), `dangling`, `missing`.

**A baseline, not a tolerance.** There is no natural cutoff. Measured on
`station_bolthole` *as originally authored*: every angle exactly right and every
positional offset exactly 1.00 or 2.00 px — deliberate whole-pixel nudges. A
tolerance of 0.5 flagged seven pairs, 1.0 flagged one, 2.01 flagged none.
(That drift has since been fixed in the ship, so the numbers are history, not a
current property of the file.) So every deviation is
reported with its magnitude and `--accept` records the current set; a finding
whose magnitude *changes* is new again.

`check` **exits 1 whenever it reports anything**. That is by design, not a
failure -- do not treat a non-zero exit as the tool breaking.

**What to baseline and what to fix.** A `hole` where a turret covers the mouth
of a decorative slot in the plate art is a baseline entry: nothing is wrong, the
art simply has a notch and something now caps it. A `floating` finding is never
a baseline entry -- accepting one hides a part that is genuinely not attached.

**Two failure modes it is very good at catching, and you will not see either in
a render:**

- *The 1px trap.* A hull whose two halves differ by 1px in `dy` had one spine
  column spaced 79 apart against a 77 reach -- so that column was **never
  vertically connected**, and the station held together only through the other
  column, which happened to be spaced 77.8. Nothing looked wrong until an
  extension inherited the spacing and floated.
- *Corner diamonds.* `BSF_Stock09` has cut corners, so a 2×N grid of them
  leaves a 24px enclosed pocket at every internal corner unless the rows
  overlap ~3px.

## Cache layout

`tools/bsf/.cache/` is gitignored and safe to delete:

| path | what |
|---|---|
| `exeart/` | sprite frames + `index.json` (origins, sizes, frame counts) from the decrypted exe |
| `catalogue/parts.json` | measured shape metrics, invalidated by the sprite tree's mtime |
| `catalogue/cooccurrence.json` | mined section adjacency, keyed to the same stamp |
| `history/` | shadow git repo: every ship version seen, plus `*.accepted.json` baselines |
| `research/` | ShipMaker GML memory dump, decrypted resource tree, dump script |

## Test data

Two `.sb4` files, and only one of them is a fixture:

- **`Custom Ships/Pendulum.sb4`** (ver1, 8 sections, 3 weapons, 1 module) — the
  stable reference, and the only stock ship with mounts. Treat it as read-only:
  copy to scratch before anything writes. It is also the donor `ship arm` clones
  the unmodelled `nWep*` fields from.
- **`mods/ships/station_bolthole.sb4`** (ver2) — **a live asset, not a fixture.**
  It was a 20-section hull with 10 drifted mirror pairs, which is what D20's
  tolerance calibration was measured on; it is now a 130-section armed shipyard
  with that drift fixed. Anything asserting facts about its geometry is asserting
  facts about someone's work in progress — which is exactly how a `selftest`
  case broke once already.

**No ship on disk has a doodad** — `selftest.py` builds a fixture, because
`nDooA` came from the save routine rather than from data.

The 63 ships that ship with the game, dumped as GML, are readable through
`stockship.py` — it resolves them via `paths.GML` (`$BSF_GML` overrides) — and
are the best source of "how does the game itself do this".

## Open threads

- **Does `secid` survive a deletion?** Sections are written from a
  `global.sections[]` array so ids are slots, but whether deletion compacts is
  unproven. One test settles it: load a ship in ShipMaker, delete a middle
  section, save, diff.
- **sh3 `.shp` export** — *reading* is done (see the generations table); writing
  is blocked on the tier-2 records, not on the format. See "Still not understood"
  above for the two approaches already tried and why each fails. This matters
  because it is what the game loads: a mission that spawns a design spawns the
  `.shp`, and `station_bolthole`'s is currently 20 sections against the `.sb4`'s
  130.
- **The decrypted tree stores each GML script as `[name][zlib body]`**, but only
  a handful inflated — the greedy slice swallowed streams. Fixing it would
  retire the memory dump and give authoritative GML with no wine.

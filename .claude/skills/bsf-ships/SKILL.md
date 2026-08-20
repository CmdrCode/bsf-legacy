---
name: bsf-ships
description: Read, edit, render, lint and live-preview Battleships Forever ship files (.sb4/.shp) offline with the tools/bsf CLI — geometry, mirroring, mounts, doodads, the parts catalogue and the occlusion linter, with no game or wine running. Use when asked to inspect, modify, build, check, compare or draw a BSF ship, section, turret or hull.
---

# BSF ships

How to work on a ship file with `tools/bsf/ship.py`. The mechanics here are
recovered from ShipMaker's own GML and measured against real ships — trust them
over first instincts about how a 2D editor "should" behave.

**Evolution rule — fold learnings back automatically.** When a session
establishes a new mechanic, corrects something here, or finds a rule that bit
you, update this file (workflow and rules) or [REFERENCE.md](REFERENCE.md)
(grammar and field tables) as part of the same session, without asking. This
follows `bsf-capture`'s posture rather than `bsf-storytelling`'s.

## Hard rules (each one has cost real work)

1. **y is down. `-15` is up.** It matches the file, the editor and Game Maker.
   Flipping it would put a sign error at every boundary.
2. **Overlap is normal** — it is how hulls are built, from deliberately stacked
   80×80 plates. Only `check` is allowed to have an opinion about geometry.
3. **Buried plate is armour, not waste.** Sections carry 196–375 HP each
   against a hull `maxhp` of 300. Never advise deleting something for being
   hidden; `visibility` reports occlusion as data and `check` never warns on it.
4. **Only `secid` is stable.** `wepid`, `modid` and `dooid` are renumbered from
   scratch on every ShipMaker save, in arbitrary instance order. Never hold one
   across a round-trip — describe parts with `select` instead.
5. **Mirroring is not a coordinate flip.** It reflects y, negates `yscale` and
   `angle`, *swaps* the clockwise and counter-clockwise rotator settings, flips
   handed trigger types, and remaps the parent through the partner. Always go
   through `ship mirror`; never hand-write the other half.
6. **Mounts store absolute coordinates plus a parent.** Moving or rotating a
   section without them strands its turrets in space — silently, until you
   render. The CLI handles this; anything hand-editing `nSecA` must too.
7. **Tier-2 fields are preserved, not understood.** Never hand-edit an `nSecB`,
   `nSecC`, `nSecD` or a trigger record. New sections *clone a donor* instead.
   The one documented exception is the colour pair `nSecB[12]/[13]`, which
   `ship colour` writes — every layer that reads it has been read, from
   ShipMaker's own menu to the game's `nSec2a`. See REFERENCE.
7a. **Check what the donor was carrying.** Cloning copies effects and stats
   too, and Pendulum — the ship on disk everything falls back to — is a bad
   first pick twice over: its section 1 has `effect = 5`, the Aegis blur that
   redraws its sprite dozens of times a frame additively, and its weapon 0 is a
   hand-tuned PlasmaBall. Building a hull from nothing once handed all ten
   sections that effect, on a design whose whole point was to look switched
   off. Both fallbacks now pick the *plainest* candidate rather than the first;
   on a hull with parts of its own, `--donor` is yours to aim.
8. **GM writes reals at exactly two decimals.** Re-serialising an untouched
   value is a spurious diff and looks like corruption in `ship diff`. The model
   keeps original text for untouched fields; keep it that way.
9. **Game art never enters the repo.** Sheets, masks and extracted frames live
   in the gitignored `tools/bsf/.cache/`.

### Placing parts — everything here was earned the hard way

10. **Never trust a hairline contact.** Give parts **≥3px of real overlap**,
    never a kissing edge. Every mask shifts a fraction of a pixel when the
    canvas grows, so two parts placed to just-touch come apart the moment
    something is added elsewhere — and `check` reports them as floating, far
    from where you were working.
11. **Section art is not a rectangle.** `BSF_Stock16` is ±11 wide at the
    shoulders and only ±7 at the waist, so spacing alone can neither close the
    waist gaps nor avoid overlapping the shoulders. Fill a gap from *behind*
    with a part at higher depth instead of squeezing the parts together.
12. **Measure pixels, not section centres.** `nSecA` and GML coordinates are
    origins; the art extends roughly 40 units past each one. A hull measured on
    centres came out 146 tall against a real 193 and fouled the berth built
    for it.
13. **Overlapping bounding boxes are not contact.** Two boxes can overlap while
    the art inside them never touches — always test the masks.
14. **A part bridging a joint encloses the gap at that joint.** Seat parts
    within a single segment; straddling two turns an open notch into a hole.
15. **Seat weapons against the hull edge measured at that row.** The edge moves:
    the same spine is 22 wide at one row and 18 at another. Placing to a nominal
    edge floated eight turrets in one pass.
16. **Turret sprites have off-centre origins, and their barrels point +x.** A
    turret on the −x flank aims into the hull unless rotated 180°, and rotating
    it swings the body several pixels off its mount — re-seat afterwards.

### Judgement

17. **Look for the game's own answer before inventing one.** `PointMaser` is
    the point-defence weapon because `Flak_Platform` *is* one section and one
    PointMaser; every stock station carries a `NanoMatrix`. `stockship.py` reads
    any of the 63 shipped ships, so checking is cheap — do that before choosing
    a part by eye. It reads them out of the game's own GML, which is game-derived
    and so lives outside this repo; `paths.py` resolves it from your install
    (`$BSF_GML` overrides).
18. **Never accept a baseline containing `floating`.** `--accept` is for known
    quirks, not for silencing a real defect. Fix, then accept.
19. **Don't pin tests to mutable assets.** A gate that asserts facts about a
    ship someone may legitimately improve will fail for the wrong reason.

### Loading a design in the actual game

19a. **`ship check` passing is not evidence the game can load it.** Everything
    above is offline: it reads geometry, not what the engine makes of it. The
    first in-game load of `station_bolthole.shp` produced **14 turrets with
    `rs_owner = noone`**, each dereferencing `rs_owner.image_angle` every step —
    a measured **203 KB/s** of `game_errors.log` from one hull, against 0 B/s
    for the same scene without it and 0 B/s for four stock hulls. Nothing
    offline had flagged it. When a design is first instantiated, spawn it alone
    in a running game and watch the error log grow; the ownerless-mount count is
    `with (ctr_ITurrets) if (rs_owner < 100000) …`, since instance ids start at
    100000 and `noone` is -4.

19e. **`-1` is the loader's "keep the object's own value", and it is the
    default a new mount wants.** `nWep2a` tests every stat against it before
    assigning — firing rate, clip, reload, damage, hp, range, deviation,
    turning, bullet colour and speed — and `nMod2` does the same for a module's
    cost, energy, regen, hp, range and all eight specials. **(GML)** So a mount
    written entirely in `-1`s fights exactly like the object it names.

    Both halves of that mattered. Cloning a donor's `nWepB` wholesale gave a
    new Railgun *Pendulum's PlasmaBall stats* — a bug no render can show, since
    a render only draws the sprite. And reading "nMod2 overrides the object's
    defaults" as "every module must be measured before it can be mounted" had
    locked out `Deflector` and `AegisDeflector`, the game's only two shield
    modules. The real rule is narrower: **never write a zero you did not mean.**
    A zero *does* override, which is how you get a NanoMatrix with range 0 that
    repairs nothing and looks exactly like one that works.

    `arcrange` is the exception with no sentinel — `nTur2` assigns it flat — so
    a new mount states one. `ship arm` uses 180, the full circle; `--arc`
    narrows it.

19c. **A module is not a weapon, and filing one as a weapon costs the whole
    ship.** The loader's `nWep2a` handler reads `l_weapon[wj].l_bullet`; a
    module has no such variable, the read throws, and because this runs inside
    the ship object's *Create* event the throw abandons the rest of it — every
    later mount, `l_weaponnum=wj-1`, `initWeapons` and `initOwners`. The hull
    arrives with `l_weaponnum = 0` and every turret still holding the default
    `rs_owner = -4`. That was the whole of the 203 KB/s above: **one** misfiled
    NanoMatrix among 33 mounts. Measured: `l_bullet` exists on Blaster,
    PointMaser, ParticleGun, PlasmaBall and Railgun, and not on NanoMatrix or
    ThrusterEx. `sprites.MODULES` is the list, `ship check` reports it as
    `unloadable`, `ship arm` routes by object, and `ship export` refuses — but
    the underlying rule is the one to remember, because a `.sb4` can be authored
    this way by anything.

19b. **`importShip` does not place a ship.** It parses the design into a fresh
    object parented to `ctr_Ship`, hands that object to a `ctr_Spawner`, and the
    spawner waits for a *mouse click* — the x/y arguments do not place it.
    Measured: after `importShip` returned, `instance_number` of the new object
    was 0. Anything scripted must take `ctr_Spawner.l_owner` and
    `instance_create` the hull itself. Read the object off the cursor rather
    than out of `global.l_fnames`, whose key is the path plus a per-team suffix
    (`"allied"`, `"player"`). And destroy any stranded cursor first: parse
    refuses outright while one exists (`if instance_exists(ctr_Spawner) then
    return -4`), so one crash inside the spawner silently blocks every later
    import in the room.

19d. **The loader caches every design by path, for the life of the process** —
    `global.l_fnames` holds `<path>` + a team suffix, `global.l_objects` the
    object it built. Two consequences, both of which cost a debugging session.
    *Editing a `.shp` and re-applying does not pick it up:* the second import
    returns the stale object, so a design change needs the game restarted, or
    the cache torn down the way the main menu does it —
    `for (i=0; i<ds_list_size(global.l_fnames); i+=1) object_delete(
    global.l_objects[i]); ds_list_clear(global.l_fnames)`. *And a cache hit
    arms no `ctr_Spawner`*, so scripted placement must use importShip's **return
    value** (the object index, or -4 on failure) rather than reading
    `ctr_Spawner.l_owner` — the cursor is there only on the first import of a
    file, which makes cursor-reading code work exactly once per session and
    silently drop the hull on every replay.

19f. **A `.shp` is compiled, not parsed — in every generation.** `importShip`
    reads the file and hands the text to `object_event_add(newobj, ev_create, 0,
    cod)`: the file *is* the new ship object's Create event. sh1 and sh2 go in
    as they are; sh3 goes through `parseReadParams`, which rebuilds each record
    as a call (`nSec2a,1,2,…` → `nSec2a(1,2,…)`) and concatenates it into the
    same string. The CSV generation is a compact *source* encoding — it bought
    file size and load time, not safety. So a **field** is code, and the format
    has no escaping: a comma ends the field, a newline ends the record, a quote
    closes the string, and what follows compiles. `model.FIELD_UNSAFE` names the
    three characters, `Ship.name` refuses them, and `export._qstr`/`_ident`
    strip them on the way out — that is the whole of what stands between a
    hostile `.sb4` and a `.shp` that runs. **The game's own filter is not a
    backstop** (see REFERENCE.md). Read an outside `.shp` with `ship tree`,
    which is regex and never evaluates; do not load one to find out what it is.

### The two things that are not in git

20. **The `.sb4` is source; the game loads the `.shp`.** Sections there are
    `nSec2a` records this model does not build, so *no* `.sb4` edit reaches the
    game without a ShipMaker re-export. Say so whenever handing work over.
21. **`mods/ships/` is the exception to the gitignore, and both halves are
    tracked.** `*.sb4` and `*.shp` are ignored everywhere else, then
    re-included by name for this one directory — the `.sb4` because it is the
    editable source, the `.shp` because it is what the game loads, and a
    `.shp` that has fallen behind its `.sb4` is a real bug you want to see in
    a diff. So **export before you commit**, and a campaign hull *is* ordinary
    tracked work. Everything outside that directory still has only the shadow
    repo in the cache for version control.

## Workflow

0. **Start the preview, and give the user the URL.** Do this first, every
   time, before any inspection or edit — not only when asked, and not only when
   someone is watching. The whole point of the tool is that the person you are
   working for can see the hull change under your hands and stop you early.

   ```bash
   ship serve mods/ships/<the hull>.sb4 &      # background it; it never returns
   ```

   Then **paste the printed URLs into your reply verbatim.** It prints one per
   address, already deep-linked to the hull you named:

   ```
   watching 8 hulls in mods/ships
     http://127.0.0.1:8771/?ship=0%2Fstation_bolthole.sb4
     http://100.96.200.11:8771/?ship=0%2Fstation_bolthole.sb4   tailnet — …
   ```

   The second line appears when Tailscale is up — that is the one to hand over,
   because it works from a phone or another machine. Never retype or shorten a
   URL; the `?ship=` key is percent-encoded and a hand-written one will miss.
   Do not go hunting for the address yourself: `--bind auto` is the default and
   already listens on loopback *and* the tailnet.

   **Never start a second server.** One covers every hull, and running
   `ship serve` again on a port that already has one just prints the URL for
   the hull you named instead of starting anything — so the command above is
   safe to repeat and is the right way to recover a URL you have lost. If it
   reports that the running preview does not watch your hull, that server was
   started against narrower roots; say so rather than starting a rival on
   another port.

1. **Look first.** `ship tree <file>` for the hierarchy (sections nested,
   mounts listed under their host), `ship render <file> -o out.png --scale 4`
   then read the PNG. The preview from step 0 is the interactive view — it
   watches the files and repaints whoever wrote them, CLI or ShipMaker. Bare,
   it watches `mods/ships` and the game's `Custom Ships` and puts them all in
   one dropdown; name a file to have it shown first, a directory to watch that
   instead. The URL carries the hull, `[`/`]` cycle, `0` re-centres, and zoom
   and pan survive a switch so flipping between two hulls compares them
   honestly.
2. **Name what you mean before you touch it.** Write a selector, check it with
   `ship select '<query>' <file> --shot sel.png`, and only then edit. Ids move;
   descriptions do not. Grammar in [REFERENCE.md](REFERENCE.md).
3. **Edit.** `move` / `rotate` / `flip` for geometry, `add` / `mirror` /
   `remove` / `reparent` for structure, `arm` for weapons, `colour` for a
   fixed tint. Edits follow the
   `nSecMir` partner by default; `--no-mirror` opts out. Subtrees need
   `--with-children`; mounts always come along. A section id is bare (`5`), a
   mount is kind-prefixed (`weapon:0`) — and a mount edit moves that mount
   alone, which is what seating a turret needs.
4. **Check after every structural step, not at the end.** `ship check <file>`
   is silent unless something is genuinely wrong, and it catches the things
   that are invisible in a render — a part left floating, a gap enclosed. Run
   it while you still remember what you just moved. Accept a ship's known
   quirks once with `--accept`; later runs show only what is new.
5. **Verify by eye.** Render again and read it. The linter cannot tell you
   whether a hull looks right — a human caught both a plate overlap and a wrong
   part choice that `check` was perfectly happy with.

The preview repaints on every write, so whoever holds the URL can redirect you
mid-build instead of after it. The URL names one hull (`?ship=<key>`) and the
server holds no selection, so they can browse the dropdown to a different one
without moving your view, and the link still means the same hull tomorrow. Keys
resolve only against the current scan, so nothing outside the watched roots is
reachable from that address.

The tailnet URL reaches your own devices, not the local network — `auto` opens
two sockets rather than binding the wildcard. For anything wider, or narrower,
say so: `--bind 0.0.0.0` for the LAN, `--bind 127.0.0.1` for loopback only.

### Starting a hull from nothing

There is no `ship new`. Write the six-line header yourself — `//sb4 ver2`, the
banners, one `nShp` and one `nCor` — and then `ship add` onto it; the first
section clones its tier-2 block from a ship on disk (see rule 7a). Keep the
whole build in a re-runnable shell script rather than typing the commands once:
the `.sb4` is the tracked artefact, but the script is what lets you change your
mind about a colour or a spar and get the same hull back.

`nShp` is `accel, turn, speed, maxhp, ai_range, ai_mode, name, desc` and `nCor`
is `image_index, colourtype, colour, xscale, yscale, fadecol, x, y, formrank`.
**(GML)** Two of those choose a code path rather than a number:

- **`accel = 0` makes it a battlestation.** `export` writes a `//battlestation`
  tag on line 2 and the game's parser then grafts `BattleStation`'s step event
  onto the hull — which pins `l_maxspeed` and *rotates it forever* at
  `l_turning` per step. Fine for a station; surprising for anything else. A
  small non-zero `accel` plus `hold: true` in the mission is the path this
  repo's own hulls take.
- **Core 3 and 5 (`spr_Civilian`, `spr_Platform`) carry no bridge bead**, which
  is what you want for anything that is not a crewed ship. `export` emits the
  `nCor2a` line they need to draw themselves at all.

Undo is always available: `ship log`, `ship diff <rev>`, `ship undo`. Every
version seen — including ones ShipMaker wrote — is committed to a shadow git
repo in the cache, so nothing is lost by trying something.

## Definition of done

An edit is finished when all of these hold:

- `python3 tools/bsf/roundtrip.py` still reports **every file byte-exact** —
  the total is whatever the install holds (181/181 as of 2026-08-16), so read
  the failure count, not the total. A count is not a verdict.
- `python3 tools/bsf/selftest.py` gains no failures. It is not at zero: the
  pre-existing `doodad sprite resolves -- ['ThrusterEx']` has been failing
  independently of any edit, so compare against a run on a clean tree rather
  than against zero.
  (Both read stock ships from the game install, so they need one — the corpus
  they walk is not in this repo.)
- `ship check` reports nothing new against the baseline — and in particular
  **no `floating`**, which is never acceptable and never baseline-able.
- The render has been *looked at*, not just produced.
- Mirror symmetry is no worse than it was: `check` should not gain `mirror`
  findings that were not there before.
- If a `.shp` exists beside the `.sb4`, the handover says plainly that the game
  still loads the old one until someone re-exports from ShipMaker.

## Choosing parts

`ship parts list --where '<query>'` filters ~550 sprites by measured shape —
bounding box, fill, symmetry scores, per-edge straightness. Narrow to a dozen,
then `ship parts sheet` and look. `ship parts near <sprite>` reports what real
ships place beside it, with its support count; **believe the count** — the
corpus is ~105 ships and ~1,030 placements, and it is essentially all Stock
Sections. A co-occurrence resting on four placements is anecdote.

## Design judgement

*Deliberately empty.* What makes a BSF hull look good is not encoded here, and
inventing it would be worse than nothing. Fill this from real review comments as
they accumulate; when there is enough of it, graduate it to its own
permission-gated skill alongside `bsf-storytelling`.

## Deeper knowledge

[REFERENCE.md](REFERENCE.md) — the full command list, selector grammar, record
field tables for every part family, the mirror transform field by field, what is
tier-1 versus tier-2, and the cache layout.

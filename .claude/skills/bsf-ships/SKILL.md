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
    a part by eye.
18. **Never accept a baseline containing `floating`.** `--accept` is for known
    quirks, not for silencing a real defect. Fix, then accept.
19. **Don't pin tests to mutable assets.** A gate that asserts facts about a
    ship someone may legitimately improve will fail for the wrong reason.

### The two things that are not in git

20. **The `.sb4` is source; the game loads the `.shp`.** Sections there are
    `nSec2a` records this model does not build, so *no* `.sb4` edit reaches the
    game without a ShipMaker re-export. Say so whenever handing work over.
21. **Ship assets are gitignored.** `*.sb4` is in `.gitignore` and
    `mods/ships/` is untracked, so the shadow repo in the cache is the only
    version control they have. Never report ship work as "committed".

## Workflow

1. **Look first.** `ship tree <file>` for the hierarchy (sections nested,
   mounts listed under their host), `ship render <file> -o out.png --scale 4`
   then read the PNG. For an interactive view, `ship serve <file>` and leave it
   running — it watches the file and repaints whoever wrote it, CLI or ShipMaker.
2. **Name what you mean before you touch it.** Write a selector, check it with
   `ship select '<query>' <file> --shot sel.png`, and only then edit. Ids move;
   descriptions do not. Grammar in [REFERENCE.md](REFERENCE.md).
3. **Edit.** `move` / `rotate` / `flip` for geometry, `add` / `mirror` /
   `remove` / `reparent` for structure, `arm` for weapons. Edits follow the
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

When the work is for someone watching, `ship serve --bind <an address they can
reach>` and
give them the URL: it repaints on every write, so they can redirect you mid-build
instead of after it.

Undo is always available: `ship log`, `ship diff <rev>`, `ship undo`. Every
version seen — including ones ShipMaker wrote — is committed to a shadow git
repo in the cache, so nothing is lost by trying something.

## Definition of done

An edit is finished when all of these hold:

- `python3 roundtrip.py` still reports **175/175** byte-exact.
- `python3 selftest.py` reports **0 failed**.
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

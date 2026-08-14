# PROTOTYPE — mission editor / beat editor

**Throwaway.** Delete this directory once the verdicts below are filled in and
the winning combination has been rewritten properly under `tools/editor/`.

## Run it

```
python3 prototype/mission-editor/run.py       # regen data, serve, open browser
```

`?variant=1|2|3`, or `[` / `]`, or the bar at the bottom. Works off `file://`
too — plain `<script src>`, no modules, no CDN, no fetch. `run.py` re-reads
`campaign/missions/ep9.yaml` into `mission_data.js` on each start (`--yaml PATH`
for another mission).

---

## Round one — what should it look like? *(settled)*

Four layout shapes: **A** workbench (map-first, drag geometry), **B** script
(screenplay column), **C** timeline (map over an NLE transport), **D** source
(YAML → compiled ladder → map).

**Winner: C.** The mission's hard part is *when things overlap* — a gate waiting
to be reached, the meteor window, music beds — and only the lane model shows it.
C is now the shared chrome in `timeline.js`; A, B and D stay reachable at
`?variant=A|B|D` for reference until round two is settled, then they go.

## Round two — how do you edit it? *(settled)*

**Winner: 1, the inspector.** Compact read-only track, docked field rail. Models
2 (direct manipulation) and 3 (command line) stay at `?variant=2|3` until the
real editor exists, then they go.

Same chrome, three editing models. Each supports the full set: edit fields,
create beats, insert them anywhere, reorder, delete, undo.

| | model | how you add a beat | how you edit a field | how you reorder |
|---|---|---|---|---|
| **1** | **Inspector** — compact read-only track, docked 346px field rail | `+` in any gap on the track → verb menu | typed into the rail, one card per verb, `✕` to remove a verb, `+ verb` to add | drag a block along the track, drop indicator in the gaps |
| **2** | **Direct** — tall blocks that *are* the editor, verb palette above the lanes | drag a verb from the palette into a **gap** | click the dialogue in the block and type; other verbs read out under it | drag a block by its `⠿` grip · drag chips **between** blocks to move an action, to the **bin** to delete |
| **3** | **Command** — one command line, modal keys, fuzzy palette | `o` / `O` → palette picks the verb | `enter` edits in the command line, `tab` cycles the beat's fields | `alt` + `←` / `→` |

All three share: the map, the lanes, the transport, lint, and a **`{ } yaml`
drawer** — whatever you do, the drawer shows the DSL that would be saved, with
the selected beat highlighted. If an edit can't round-trip to YAML it isn't real.

Things worth trying:

- **1**: select beat 11 (three spawns, a camera move and a say) — the rail is the
  only place that shows all of it at once. Then drag beat 14 two slots left.
- **2**: drag `camera` onto a beat, then drag the chip straight back out to the
  bin. Then drag a beacon on the *map* — same gesture, same undo stack.
- **3**: `o` → say → `enter` → type → `enter`. Then `alt+←` twice. Then `u`.
  Never touch the mouse.
- Any of them: try to put a `say` on a beat that already has an `objective` —
  it's refused, because the counter only advances once per rung.

## Game art — extracted live, held in memory, never written down

The preview draws the actual game's sprites. `run.py` decrypts
`BattleshipsForever.exe` into RAM at startup (~50 ms for the 6.9 MB tree),
indexes all **503 sprite records**, classifies them, and serves frames on demand:

    GET api/assets              manifest: w, h, origin, frame count, mask flag
    GET api/sprite/<name>?f=N   one frame, inflated + PNG-encoded on first ask
    GET api/ship/<Hull>         section geometry for a real hull, when dumped

**Nothing derived from the game is ever written to disk.** That is the rule for
the real editor too (below), and it is also what keeps the repo clean by
construction: there is no generated asset file to accidentally commit. If the
game is not found the editor says `no art` and falls back to vector shapes.

Three things the extractor had to get right, all of them traps from the design note:

- **Origins are data.** The sprite record carries them after the bbox and five
  flags; `spr_Rock` is (24,24) on a 48×48 but `spr_MesHQ` is (0,0). Everything
  blits at `-ox,-oy`.
- **158 of the 503 sprites are palette masks** — three shades of grey the engine
  multiplies by a colour. Not just hull sections: `spr_Nebula`,
  `spr_Spacestation`, `spr_Meteor` and `spr_Marker` are masks too. Blit one
  straight and you get a black box.
- **The tint is the object's, not ours.** `MoveToArea` sets
  `image_blend = c_green`, `SpaceStation` takes `global.colour[1,0]`,
  `obs_Meteor` is `c_white`, `ter_Nebula` runs at `image_alpha = 0.30 + …`.
  Those came out of the objects' own Create events, not out of taste.

So the map now shows the real Hestia hull (sections, team shade, doodad sprites),
real nebula clouds, the real green `MoveToArea` beacons, `ter_Planet`,
`SpaceStation`, and a procedural starfield — because the mission rooms are black
with all eight background slots unused. In the inspector, a `say`'s portrait is
the portrait, with its true size and origin, and clicking it opens a picker of
every `spr_Mes*` in the tree; a spawn shows the sprite that object will draw. A
name that is not in the tree renders **not in tree** in red — the same thing
`build.py`'s lint would reject, but visible while you type it.

Hulls are the one thing not from the exe: the built-in ship designs stay locked
in there, so section geometry comes from the render-model dump in the research
tree (`dump/ship_html/`) when it exists. Live hull truth is milestone 3's
`guidump.txt`.

## For the real editor (`tools/editor/`)

- Assets are **extracted from the player's own game at run time, in memory** —
  the dev server owns a `Library` over the decrypted tree and serves frames on
  demand. No asset files, no vendored art, no build step, nothing to redistribute.
- Ship the extractor (`assets.py`), never its output. Same rule for `rooms.json`
  and anything else derived: compute it per run.
- The object→sprite binding still leans on the runtime `objects_rt.txt` dump.
  Doing it from the exe alone needs an index-correct sprite section walk to pair
  with `gmobj.walk_section()` — that is the one piece of milestone 1 left.

## What's real and what's faked

Real: EP9's beats, gates, storm cells, room, player and fail text, parsed from
the actual `ep9.yaml`. Rung numbering follows `build.py`'s `number_beats()` and
matched the committed `mods/act2m1.gml` exactly before any edits. The lint is
`build.py`'s text rules. `Core.parseYaml` was diffed against PyYAML on
`ep9.yaml`; `Core.toYaml` round-trips the parsed model back to itself.

Faked: the beatlog stream in variant D and every "poke the game" affordance;
scenery *placement* (the game re-randomises `nebula: 16` every run, so the
seeded scatter is a prediction, not a layout); meteors, which only exist once the
spawner fires. **No edit is written to disk** — reload and they are gone.

Known gaps, deliberate: no editing of room / player / zones / gates-as-a-list
(that's the layout tier, and variant A already showed dragging works); no
`goto beat`, held in reserve per the design note; undo only, no redo.

## Verdicts

**Round one — layout: C, timeline.**
- Steal from the others:
- Answer to the handoff's open question (textarea first, yes/no):

**Round two — editing model: 1, the inspector.**
- Steal from the others:
- Still open: does the rail want the picker for *objects* too (628 of them), the
  way it now has one for sprites?

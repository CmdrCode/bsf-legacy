---
name: bsf-storytelling
description: Voice, color, and canon guide for writing Battleships Forever campaign scenarios in the shipped game's style (the chosen "V1" treatment) — briefings, beat ladders, comm dialogue, mission structure, Act II canon. Use when writing or editing campaign missions, briefings, dialogue, episode docs, or any BSF Legacy story content.
---

# BSF scenario voice

The production voice for BSF Legacy campaign writing, distilled from the shipped
game's eight episodes and the Act II decisions made with the user.

**Evolution rule — permission required.** This skill is meant to grow, but never
silently: when a writing session establishes a new voice rule, canon fact, or a
correction to something here, propose the exact edit to the user and update this
file only after they approve. Log approved changes in the Evolution log at the
bottom. (This differs from `bsf-capture`, which folds learnings back
automatically.)

## Sources of truth

- `campaign/ACT-II.md` — the Act II scenario, on `main`. Its Version 1 is the
  chosen treatment; Versions 2–3 were style explorations.
- **The eight shipped Act I episodes** — their briefings, comm lines and
  triggers are what everything below was distilled from. **No transcript of them
  is in this repo, and none can be**: the campaign text is the game's own, and
  nothing extracted from Battleships Forever is ever committed here. Read the
  episodes in the game to check a line against the original.

The rest of this file is the distillation, so it stands on its own. You need the
original only to verify a quotation, never to write to the voice.

## The form

A mission is a **briefing screen + a beat ladder**. In the engine, dialogue IS
the scheduler (`l_messagecount` + `GUI_Messager`): each message panel advances
the counter; anything that isn't dialogue jumps it directly (enter zone, kill
count reaching zero, timer expiring). Write scenarios in that shape:

- **Briefing:** 2–3 short paragraphs, second person, Fleet-HQ formal. Recap in
  the first paragraph, tasking in the second. New hulls are announced in the
  briefing. Ends with an objectives list — at most three, phrased as survivals
  and destructions ("X must survive", "Destroy all Y").
- **Beats:** numbered, with deliberate gaps between blocks (the game reserves
  empty numbers for branches — keep that habit; e.g. 1–14, then 100+, 200+ for
  phases). Each beat = trigger + lines + staging note.
- **Mission titles:** one gritty word or a curt two-word phrase. Shipped set:
  Milk Run, Rat Hole, Bunker, Titan, Siege, Slaughterhouse, Graveyard,
  Stronghold. Act II: Bolthole, Sacred Ground.
- **Mid-mission turns** arrive as a `New Objective` panel, not narration.
- **Autosave** at story beats (never on Hard). Music changes are beats too.
- **Failure messages** follow the pattern `<Thing> was destroyed!`
  (also: `... Escaped!`, `Your fleet was annihilated!`).
- Missions end with **Mission Accomplished** — and the game lets villains have
  the last word (EP8 ends on Nagaya's "Coward!"). Don't over-resolve.

## The voice

- The player is **never named** — addressed by rank only (Captain / Commodore /
  Admiral). No gender, no backstory on screen.
- Comm traffic is earnest, direct, exclamation-heavy under fire ("Captain!",
  "Hurry!", "Watch your back Captain!"). Briefings are formal and dry.
- Short declarative sentences. Military flavor without jargon density
  ("Standby Formation one three five mark niner zero").
- A little period clunk is authentic — don't polish it into modern slickness,
  and don't add typos on purpose (the game's own typos stay verbatim only when
  quoting it).
- British-ish spellings where they occur (manoeuvre).
- **[Hint]** is its own channel: dry, instructional second person, concentrated
  early, absent once the player is trusted.
- **The Nanz stay unexplained.** They spoke once in the entire campaign, in
  broken ellipsed speech ("There will be... no talk. ... You have... trespassed
  on sacred ground."). Keep them near-silent, no portrait, never explain
  "sacred ground".
- **Nagaya** is boastful in short taunts ("You may have evacuated your base,
  but I'll kill you yet!").
- Grief and horror land in one plain line, understated ("It's a slaughterhouse
  over here sir, looks like they were boarded."). One line, then move on.
- Big handovers can be wordless — EP8 recolors Fleet HQ to your team instead of
  saying it. Prefer staging over speeches.

## The colors (game literals)

| Channel | Color | Notes |
|---|---|---|
| Friendly comms (Fleet HQ, Hong, crew) | `$00FF00` green | portrait sprites |
| Hostile speakers + New Objective | `c_red` (GM BGR `$0000FF`) | |
| Nanz | `$FF00FF` magenta | **no portrait — text only** |
| Logs (Cherenkov's log) | `$FFFFFF` white | italic in doc renders |
| [Hint] | dim/grey | tutorial channel |

For HTML docs, use the campaign class system: `line hq / foe / alien / log /
hint / obj`, tags `save / music / fail`, plus briefing card, deployment strip,
and beat grid. Those names are the whole system — the Act II artifact follows
it.

## Act II canon (established with the user, 2026-08)

- Act titles: the shipped campaign is **Act I: Pirate Incursion**; the new
  campaign is **Act II: Legacy of the Fleet**.
- Act II opens **19 years** after Stronghold (BSF released 2007 → BSF Legacy
  2026). The Federation is gone; the war was lost slowly.
- **The enemy: the Compact** — the Nagaya–Nanz alliance, named by humans.
  Nagaya is alive. The Nanz remain unexplained.
- **Fleet Admiral T. Hong** commands what's left — the marine major of EP6–8,
  promoted by attrition ("the Fleet ran out of admirals before it ran out of
  war"). He kept the Conversion Bomb safe for 19 years and his engineers built
  the new tech from captured material.
- **Project Bolthole**: last free station + colony, hidden in **the Coalsack**
  dark nebula. No jump navigation inside; approach is days of realspace flying
  along **the Ratlines** — secret lanes marked by *dead beacons* (inert masses
  in expected places; the expected places are the secret). Approach Control
  authenticates or fires; it has fired on friends twice. Every captain is sworn
  to die before capture.
- **The player is a Captain again**, unnamed as always.
- **Hestia X, hull *Erebus***: one-off experimental destroyer. **Umbra Cloak**
  (reverse-engineered Nanz wreckage) + **Flux Shield** (the EP8 Fleet HQ
  barrier miniaturized — a true full-ship bubble, unlike section deflectors).
- **Episode 9 "Bolthole"** (`rm_Mission8`): storm-run home, no enemy ships,
  EP1's mirror with re-onboarding hints; written in `campaign/ACT-II.md`.
- **Episode 10 "Sacred Ground"** (`rm_Mission9`): infiltrate Nanz station
  VEGA-PRIME (the base from Cherenkov's log) and steal something. The embarked
  extraction team knows the objective; the captain is never told — doctrine
  RATLINE-9: *what a captain does not carry cannot be taken from them*. The
  stolen tech stays secret from the player too.
- Approved line-style example (Hong, EP9): "The Nanz operate a station in the
  Vega sector — the same base Cherenkov stumbled on nineteen years ago. We
  never had the strength to go back. Now we have something better than
  strength."

## Evolution log

- 2026-08-08 — Created from the Act II writing session. V1 (game voice) chosen
  as the production treatment; Cherenkov line reworded per user pick.
- 2026-08-08 — Act titles named by the user: Act I "Pirate Incursion",
  Act II "Legacy of the Fleet".

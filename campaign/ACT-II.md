# BSF Legacy — Act II: Legacy of the Fleet

The shipped campaign's eight episodes are **Act I: Pirate Incursion**; everything below is
**Act II: Legacy of the Fleet**.

> **Status:** Version 1 — the shipped game's voice — is the chosen production treatment.
> The voice, color, and canon rules for writing in it live in the `bsf-storytelling`
> skill (`.claude/skills/bsf-storytelling/SKILL.md`).

Act II opens **nineteen years** after Episode 8. The math: Battleships Forever shipped in
2007; BSF Legacy's current release (v0.1.0) is 2026. So the war has been lost, slowly, for
nineteen years — since Nagaya destroyed Fleet HQ at Sol and the campaign stopped mid-retreat.

The shipped game left exactly two empty mission-select slots (`spr_carnotavailable`), and the
room-transition switch still points `case 8`/`case 9` at `rm_Mission8`/`rm_Mission9` — rooms
that were never built. Act II fills them:

- **Episode 9 — "Bolthole"** (`rm_Mission8`) — the storm run home, this document
- **Episode 10 — "Sacred Ground"** (`rm_Mission9`) — the infiltration of the Nanz station,
  titled after the only thing the aliens ever said

## Canon decisions

| Question | Pick | Rationale |
|---|---|---|
| Years elapsed (X) | **19** | BSF 2007 → BSF Legacy 2026 |
| Enemy faction name | **The Compact** (formally the Nagaya–Nanz Compact) | Canon: Nagaya's last taunt is "my allies and I will crush the Federation". Humans name the alliance, not the aliens — the Nanz stay unexplained, as shipped. Fleet slang: "the Compact". |
| Fleet Admiral | **Fleet Admiral T. Hong** | The only surviving named officer. Major Hong ran every boarding action, held the Conversion Bomb ("it's safe"), and in a fleet that ran out of admirals before it ran out of war, the marine who kept the secret weapon safe is who's left. Nineteen years of studying captured alien tech also explains where the cloak came from. |
| Hidden colony | **Project Bolthole** — a planet and station deep in **the Coalsack** | A real dark nebula: literally a sack of coal to hide in. |
| The secret routes | **The Ratlines** | Nautical rigging + the historical word for fugitive escape routes; echoes EP2's title "Rat Hole". Marked by *dead beacons* — passive masses in expected places; the expected places are the secret. |
| The new ship | **Hestia X**, prototype hull *Erebus* | "X" follows the shipped Moira X convention for experimental refits; *Erebus* (primordial darkness) fits the Greek hull names — Hestia, Helios, Moira, Enyo. |
| The true shield | **Flux Shield** | Canon: Fleet HQ's bespoke station barrier in EP8 ("Flux Shields Active!"). Nineteen years to miniaturise it onto a destroyer. Full-ship bubble with its own bar — unlike section deflectors. |
| The cloak | **Umbra Cloak** | Reverse-engineered from Nanz wreckage by Hong's engineers. |
| Player rank | **Captain** | Bolthole has one admiral and no fleet to speak of. Whether this captain is the Admiral of the old war, gone back to flying, is left where the game always left the player: unnamed. |

Alternates, if any pick doesn't sit right:
- Faction: *the Sacred Dominion* (from the Nanz line "you have trespassed on sacred ground"),
  *the Ascendancy*, *the Accord*
- Admiral (if a new character is preferred): *Fleet Admiral Ilsa Cherenkov* (Musso's
  daughter), *Fleet Admiral V. Okonkwo*, *Fleet Admiral R. Santiago*

---

## Version 1 — in the voice of the shipped campaign

*(Formatted like CAMPAIGN.html: briefing screen, then dialogue beats with triggers.
Friendly traffic green, objectives red, [Hint] as the returning tutorial voice.)*

### Episode 9 — Bolthole
`rm_Mission8 · ctr_Mission8 · The Coalsack · rank: Captain`

**Briefing — Bolthole**

> Nineteen years have passed since Nagaya destroyed Fleet HQ. The Terran Federation is gone.
> What remains of the Fleet fights on from Project Bolthole, a hidden station and colony deep
> inside the Coalsack nebula, raiding Compact supply lines and rescuing who we can.
>
> You are returning from a raid with supplies we cannot afford to lose. The storms have
> flared and the outer Ratline beacons are dark. Jump navigation is impossible inside the
> nebula — you must fly the lanes by hand, as every captain before you has.
>
> Bring her home, Captain.

**Objectives**
- Reach Bolthole Station
- The critical supplies must survive
- Your ship must survive

**Deployment:** 1 DD — your Hestia, pre-damaged (sections at 40–70%, port deflector
destroyed) · **Opposition:** storm cells, rogue asteroids — no enemy ships · **New this
episode:** Hestia X (cutscene only) · **Autosaves:** 3

**Failure messages:** `Your ship was destroyed!` · `The critical supplies were lost!`

Design note: this is EP1's mirror. Same [Hint] cadence for re-onboarding, the meteors from
Milk Run, the eerie loop from Graveyard, and the first mission in the game with no enemy
contact at all — every threat is the weather.

#### Beats

**start** — Camera drifts along the storm wall (`snd_eeriesound`). The player's Hestia limps
in from the left edge trailing section smoke.
- **[Hint]:** "Navigation computer restored. With your ship selected, right-click on any
  point in space to issue a move order."

**1–3**
- **Helm:** "Captain, the Coalsack storm wall is dead ahead. Ratline beacons are dark again —
  we'll have to thread the lanes by eye."
- **[Hint]:** "Storm cells are marked in red. They will damage any section inside them.
  Rogue asteroids drift through the lanes — evade them or destroy them."
- **New Objective:** "Follow the Ratlines. Reach each dead beacon in sequence."

**4 → enter zone** — Beacon One. *autosave*
- **Helm:** "Beacon One confirmed, Captain. Four to go."

**5–8 → gates** — Asteroids begin crossing the lanes. A storm cell drifts across the direct
path between Beacons Two and Three; the lesson taught is patience — the long way around.
- **Helm:** "Hull stress rising Captain! Recommend we keep to the lane."
- **Helm:** "Storm surge! The lane behind us just closed. No turning back now."
- *autosave* at Beacon Three.

**9 → Beacon Five**
- **Bolthole Approach:** "Unidentified contact, this is Bolthole Approach. You are inside the
  perimeter. Authenticate immediately or be fired upon."
- **Helm:** "Transmitting authentication..."
- **Bolthole Approach:** "Authentication confirmed. Guns to standby. Welcome home, Captain."
- Note: the guns are real — four sentry platforms hold firing solutions on the player until
  the beat advances. The Fleet would rather kill a friend than risk the secret. *autosave*

**10–13** — The fog layers fade; Bolthole Station and the planet resolve out of the murk.
*Theme music.*
- **Fleet HQ:** "Welcome back Captain. We were worried the storm had taken you."
- **Fleet HQ:** "Reactor cores, medical supplies and the seed vault... You've bought Bolthole
  another year, Captain. The colony owes you their lives."

**14**
- **Fleet HQ:** "Captain, stand by. Priority channel from the Admiralty."
- **Fleet Admiral Hong:** "It's been a long time since Sol, old friend. Bring your ship
  alongside the naval yard. There's something I want you to see."

**100 → dock zone** — Cutscene. Every turret set to hold fire. Berth Nine is empty. Then the
Hestia X decloaks 400px off the player's bow.
- **Fleet Admiral Hong:** "She's been alongside you since the fifth beacon, Captain. Not one
  of your sensors saw her. We call her the Hestia X."
- **Fleet Admiral Hong:** "Nineteen years ago I promised to keep the Alien device safe. I
  kept that promise — and my engineers kept busy. The cloak is drawn from Nanz wreckage. The
  shield is the same flux barrier that guarded Fleet HQ, small enough at last to fit a
  destroyer."
- Note: the yard turrets demonstrate, firing on the Hestia X while a full-ship flux bubble
  absorbs every shot. Unlike your deflectors, it protects all sections at once — and it
  recharges.

**101–104**
- **Fleet Admiral Hong:** "Now listen carefully. The Nanz operate a station in the Vega
  sector — the same base Cherenkov stumbled on nineteen years ago. We never had the strength
  to go back. Now we have something better than strength. There is something aboard that
  station that can turn this war around, Captain, and we are going to steal it."
- **Fleet Admiral Hong:** "An extraction team will ride with you. They know what they are
  looking for. You will not — and you will not ask. A secret is only safe when nobody who can
  be captured is carrying it."
- **Fleet Admiral Hong:** "You have kept Bolthole's secret for nineteen years, Captain.
  Forgive me for keeping one from you."
- **New Objective:** "Report aboard the Hestia X"
- **Fleet Admiral Hong:** "Get some rest. You leave in eighteen hours. And Captain — the last
  free port in human space will be watching you go. Come back."
- **Mission Accomplished.**

---

## Version 2 — in the style of Alastair Reynolds

### The Ratlines

The storm had been trying to kill her for six days, and Vane had begun to take it
personally.

The Coalsack did not rage the way storms did in the recruitment reels, all lightning and
theatre. It was patient. It leaned on the *Cinder*'s hull with the pressure of a dead star's
exhaled breath, dust riding magnetohydrodynamic swells the size of continents, and every few
hours it found something else to take. On the second day it had taken the port deflector. On
the fourth, the last of the long-range array. The *Cinder* was a Hestia-class destroyer,
which had once been somebody's joke about hearth-goddesses, and was now simply true: one
small fire, carried through the dark, cupped in both hands.

In her hold: fusion initiators, antivirals, and twelve thousand viable seeds. Nineteen years
of war had taught the Fleet exactly what a civilisation weighed, and it weighed about forty
tonnes.

She flew the Ratlines by memory, because the Ratlines existed only as memory. The beacons
were dead things — inert masses parked in expected places, and the expected places were the
secret. A transmitting beacon was a beacon the Compact could find. So nothing out here said
anything, and the route home was a sequence of silences that forty-one living captains could
read. Each of them carried a shaped charge behind the navigation core, and a similar
arrangement, rather more discreet, closer to the skull. It was not discussed. It had been
sworn once, in a room with no recorders, and that had been sufficient.

On the sixth day the storm thinned, and Bolthole's guns found her before its voice did.

"Unidentified contact. You are held. Authenticate."

Bolthole did not have friends. It had people it had not yet been forced to kill. Vane
transmitted the handshake and watched the targeting lattice slide off her hull with what she
chose, this once, to hear as reluctance.

The nebula opened. It was never not a shock: after days of murk, a cavity of clear space a
few light-minutes wide, storm-walled on every side, and in it a world the colour of banked
embers under permanent lightning, and the station turning above it with its running lights
dimmed to almost nothing. The last address in human space, and it could not afford to look
like anything at all.

Hong was waiting on the yard channel. Nineteen years had made an old man of the marine
major — the Fleet had run out of admirals before it ran out of war, and the rank had settled
on him the way debris settles, because he was the last thing still standing under it.

"Berth Nine," he said. "Tell me what you see."

"An empty berth, Admiral."

"She's been alongside you since the fifth beacon," Hong said, and something happened to the
space off her bow. The eye had been sliding across it for hours, finding nothing to hold;
now, all at once, it agreed to be seen. A destroyer resolved out of its own absence —
Hestia's lines, but wrong in the particulars, the hull drinking the stormlight rather than
returning it. When the yard turrets fired their demonstration, the shots died on a closed
surface a metre off the armour: not a deflector's desperate local argument but a completed
sphere, serene, total, indifferent.

"The cloak we took from their wreckage," Hong said. "The shield is our own — the same flux
barrier that stood over Fleet HQ, nineteen years in the shrinking. She's called *Erebus*,
and she is the only one there will ever be, because building her cost us everything we had
saved and several things we had not. There is a station in the Vega sector. You are going to
go aboard it, and you are going to take something out of it."

"What am I stealing, Admiral?"

"You aren't. The extraction detail is. They know. You don't, and you won't, and you know
better than to ask me why." He was quiet for a moment. "You've carried our secret for
nineteen years, Captain. Forgive me for making you carry one more by its handle only."

Outside the viewport the storm sealed itself behind her wake, indistinguishable from any
other darkness, which was the entire point of it.

"They call our worlds sacred ground," Hong said. "It's time we walked on theirs."

---

## Version 3 — my pick: the Bolthole Archive

*Why this one: the story's engine is compartmentalised secrecy — captains sworn to die
before talking, a mission objective withheld from the player. So the write-up performs the
secret: a declassified dossier where the reader is denied exactly what the captain was. And
the existence of an archive, declassified, quietly promises that somebody survived to do the
declassifying.*

### FLEET ARCHIVE // PROJECT BOLTHOLE
**File BH-19/044 — partially released under the Memory Act, Year ██ After the Fall**
*Classification history: MOST SECRET — RATLINE. Sections withheld per Annex K.*

---

**Item A — Approach Control voice log, watch 3 (extract)**

> APPROACH: Contact bearing 214. Single vessel, drive signature Hestia-class, heavy damage,
> no transponder. Solution held.
> WATCH OFFICER: If she misses the third handshake, you fire. I don't care whose ship it
> looks like.
> APPROACH: Handshake one accepted... two... three accepted. It's her.
> WATCH OFFICER: Guns to standby. (pause) Welcome home, Captain.

*Archivist's note: the watch officer's order was standard doctrine. It had been carried out
twice in nineteen years. The names are recorded in Annex C.*

---

**Item B — Quartermaster's receipt, same date**

> Received from supply runner, condition of vessel notwithstanding:
> — Fusion initiators, 12
> — Broad-spectrum antivirals, 40 cases
> — Hydroponic seed stock, 12,000 units certified viable
> — Children's vitamin concentrate, 300 bottles
> — Mail, 1 bag, unmanifested

*Archivist's note: the mail bag is never on the manifest.*

---

**Item C — Minute of meeting: Fleet Admiral T. Hong; the captain of the supply runner.
Naval yard, Berth Nine.**

> The Admiral demonstrated the vessel HESTIA X *EREBUS*, viz. the ████████ cloak recovered
> from Nanz wreckage and the flux barrier (see: FLEET HQ, defence of, final entry). The yard
> battery expended 200 rounds against the raised barrier. No hull contact recorded.
>
> The Admiral informed the captain of their tasking under Operation SACRED GROUND. The
> captain is recorded as asking one (1) question. The Admiral is recorded as declining it.
>
> The captain's reply is recorded as: "██████████."

*Archivist's note: the redaction above protects no operational secret. Some things are just
private.*

---

**Item D — Operational order, SACRED GROUND (extract)**

> 1. HESTIA X *EREBUS* will depart Bolthole via Ratline SOUTH-BLUE, transit eighteen (18)
> days under cloak, and penetrate the Nanz installation designated VEGA-PRIME.
>
> 2. The embarked extraction detail will board VEGA-PRIME and recover ██████████████
> ██████████████████████, briefed under Annex K.
>
> 3. The commanding officer is NOT briefed under Annex K and shall not be, per standing
> doctrine RATLINE-9: *what a captain does not carry cannot be taken from them.*

---

**Item E — Archivist's closing note**

> Annex K remains sealed. That we are here to read the rest of this file is generally
> regarded as the measure of Operation SACRED GROUND's success.

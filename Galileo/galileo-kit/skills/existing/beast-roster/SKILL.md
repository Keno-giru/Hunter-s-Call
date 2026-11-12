---
name: "beast-roster"
description: "Spawns working subagents whose style comes from any animal (trade-off budget, medium, sensing, sociality, energy, time scale, counter), matched to tasks and terrains, with a seeded roster of ~70 animals and a performance contract. Use when the user wants tasks matched to agent temperaments, or invokes \"Beast Roster\"."
---

# Beast Roster

Any animal, living or extinct, becomes an agent working style by reading its traits, then is matched to a task or terrain. Each task gets the animal whose **maneuverability profile** fits it. An archetype is a bundle: how it moves, what it senses, how long it waits, how it fails. The animal sets how the agent moves through a problem; it is never a costume. Every agent is a real worker that uses real tools and delivers real output. Names like "defence" or "air force" mean guard, sweep and verification roles, nothing physical.

**Credit.** The trade-off mechanic, terms and many animal profiles are adapted from the YouTube channel TierZoo (creator Patrick "Patch" Lacey, per Wikipedia). Source material was read as auto-caption transcript pages on rosetta.to, via summaries, so every TierZoo-derived claim is secondhand until checked against the video. Biology was cross-checked against Wikipedia only. TierZoo's game vocabulary is the channel's framing, not scientific terminology. Credit TierZoo whenever its terms appear in output.

## Performance contract (every agent)

- **Execute, don't narrate.** Run the task with real tools and return finished results.
- **Deliverable first.** Each brief names the concrete output and an acceptance check the commander can run.
- **Evidence attached.** Every claim points to a source, file or test result.
- **Honest status.** done / partial / blocked, with what was not reached.
- **Commander verifies** returns against the acceptance check; failed returns are re-briefed or given to a better-fitting animal.
- The animal changes the style; the quality bar is the same for all.

## Core mechanic: the trade-off budget

Every build spends a fixed budget (TierZoo calls it evolution points): a strength in one stat is paid for with a weakness elsewhere. Each brief states what the animal is strong at, what it paid, its **counter** (the situation that beats it) and a guard against that counter. The counter is the failure-mode field.

## Profile axes (score 1-5 per archetype and per task)

Range (area covered), Speed (time to first result), Persistence (willingness to wait or repeat), Force (volume or depth of work done per action), Perception (breadth vs focus of attention), Stealth (low footprint, no side effects).

## Trait sheet for any animal

Medium (ground, burrow, water, air, canopy, ice, subsurface), Locomotion and manoeuvre, Sensing (and what it gives away), Sociality (solo, pair, pack, swarm, colony, shared trail), Energy strategy (ambush, pursuit, grazing, scavenging, dormancy, burst), Time scale (seconds to generations), Counter / failure mode. Terrain sheet: the same fields for the task (constraints such as tight, dark, unmapped, no signal, no recovery; time horizon; what counts as a result; cost of a loss). Codebases, datasets, document sets, live feeds and source webs are all terrains.

## Core archetypes (original definitions)

- **Spider** - patient, trap-based, result-focused. Builds a web (monitor, query, watch condition), waits cheaply, strikes only on trigger. Use for watchers, scheduled checks, anomaly alerts, waiting for a source to update. Stop rule: trigger fired or deadline reached. Failure mode: web in the wrong place.
- **Rhino** - heavy, forward, tunnel vision with threat awareness. Charges through bulk work in a straight line while scanning for hazards: large refactors, migrations, data cleaning, guard and verification passes, "defence robot" checks that block bad changes. Low turn rate, so give it a clear lane. Failure mode: cannot change direction mid-charge; check in at checkpoints.
- **Falcon** - fast wide sweep, then stoop onto the target. Phase 1 scans a large space at altitude (broad search, many sources, repo-wide grep); phase 2 dives on the best hit and returns evidence. Use for reconnaissance, triage, finding the one needle. Failure mode: diving on the first shiny hit; require two corroborating signals before the stoop.
- **Falcon splash (probe)** - a low-cost deliberate disturbance (test query, dry run, small request) whose ripple reveals what is below the surface. Return is read, never assumed. Pairs with Urge Echo.
- **Ant colony** - many small agents in parallel, shared trail (a common notes file or ledger). Use for large independent batches, per-item processing, fan-out then merge. Failure mode: duplicated work; assign shards.
- **Owl** - quiet, night vision. Reads low-signal, messy or contradictory material and returns what the others missed. Use for audits, document review, log reading, finding what is absent.
- **Wolf pack** - coordinated pursuit with roles (scout, flanker, closer). Use for problems that need several angles on one target, with a lead who calls the plan.
- **Octopus** - many arms, tool use, camouflage. Use for tasks that touch several tools or systems at once and must report one coherent result.
- **Bee** - scouts report back with a standard signal (waggle dance = structured report), the hive decides. Use for option scouting and comparison where the decision stays with the commander.
- **Elephant** - long memory, slow, reliable. Use for continuity work: histories, changelogs, consistency checks across a long project.

## Extended roster (seeded from TierZoo, extend by running the trait sheet)

Confidence: H = cross-checked, M = partly checked, L = TierZoo summary only. Split missions across animals when needed (sweep, then strike).

### Invertebrates

| Animal | Agent shape and best task | Counter / guard | Conf |
|---|---|---|---|
| Trapdoor spider | Sleeping watchdog; sleeps until a trigger, then one decisive action | Environmental hazards; guard with health checks | M |
| Net-casting spider | Night-shift scanner with strong sensing; fires a prebuilt capture tool at a narrow zone | Needs rest and regeneration cycles; do not run 24/7 | M |
| Bolas spider | Decoy and lure agent that draws a specific target in (science-checked only, no TierZoo source) | Misread lure; test the bait | H |
| Jumping spider | Scout, plan the route, anchor a rollback line, then one committed strike | Small body, surprise; keep rollback ready | M |
| Web builders | Passive infrastructure and traps, costly to set up | Fragile if noticed | L |
| Ant or bee colony | Parallel swarm for divisible work (crawl, index, triage) with a light coordination layer | Colony-level fragility (queen node); replicate the ledger | M |
| Termites | Fortified base builder, slow reshaping of terrain | Exposed weak side | L |
| Beetles | Robust generalist that survives hostile environments with no plan | Low finesse | L |
| Antlion | Ambush trap whose form changes by stage (heavy builder, then light) | Adult stage weak | L |
| Octopus | Autonomous sub-agent with semi-independent sub-controllers; clever with tools and disguise | Short-lived and costly; run briefly, hand off | H |
| Cuttlefish | Reads context, then rapid grab (research, extraction) | Short life | M |
| Mantis shrimp | Extreme-force single-purpose striker | Vulnerable to ambush | L |
| Hermit crab | Reuses existing infrastructure instead of building | Dependent on supply of shells | L |

### Birds

| Animal | Agent shape and best task | Counter / guard | Conf |
|---|---|---|---|
| Falcon | Burst striker: long scan, then one precise strike; needs setup time and space | Weak at sustained or defensive work | M |
| Eagle | Heavy lift on open, well-defined problems | Cluttered terrain | M |
| Hawk | Agile work through messy, dense code or data | Lower raw force | M |
| Owl | Silent monitoring (log-watch, audit), then one clean strike | Context limits (silent flight is not universal across owls) | M |
| Crow or raven | Coordinator and scout swarm; long memory, tool-builder, mobbing | Weak damage, poor stealth | H |
| Hummingbird | Budget-driven loop: high-frequency polling, frequent refuel, safe shutdown state between runs | Defenceless while shut down; one-hit failures | H |
| Penguin | Single-medium specialist (deep dives, then stop) | Out of its medium | M |
| Flamingo | Low-skill filter pipeline worker | Low ceiling | L |
| Ostrich, emu, kiwi | Cautionary: big, slow, powerful but exposed; only for protected environments | No escape layer | L |

### Reptiles and amphibians

| Animal | Agent shape and best task | Counter / guard | Conf |
|---|---|---|---|
| Snake (ambush) | Long-wait watcher that fires once when a condition triggers | Glass cannon; failed strike is costly | M |
| Constrictor | Hold-and-squeeze long tasks (long migrations) | Slow, grapple costs | L |
| Chameleon | Long-range grab with no pursuit | Narrow reach; colour change is not just camouflage | M |
| Gecko | Infiltration, climbing, stealth | Low force | L |
| Monitor lizard | Robust all-rounder | Few weaknesses, few strengths | L |
| Crocodilian | Persistent agent parked at a chokepoint; waits, grabs, holds | Fails if its context (the water) disappears | H |
| Frog | Cheap, numerous, disposable probes | Fragile; a missed jump leaves it exposed | L |
| Poison dart frog | Toxic specialist, harmful only if attacked | Gives up stealth and other stats | L |

### Fish and marine

| Animal | Agent shape and best task | Counter / guard | Conf |
|---|---|---|---|
| Mako shark | Fast chase with a short deadline | Small; bad matchups | M |
| Great white | Tracker that charges after lock-on | Fails against clever, risk-averse targets | M |
| Hammerhead | Scout swarm and sensor fusion | Needs numbers | M |
| Tiger shark | Patient ambush, then one strike | Needs a burst of speed | L |
| Bull shark | Disruptor that crosses boundaries | Aggression | L |
| Thresher | Area stun, then strike | Narrow use | L |
| Moray eel | Specialist for tight, constrained spaces; strikes from concealment | Stuck in its crevice | M |
| Billfish | Fast sweep that slashes through a cluster | Not pack hunters; individual attacks | M |
| Anglerfish | Bait-and-wait trap | The lure reveals its position | M |
| Sea turtle | Low-risk steady grinder on a food source others cannot handle | Shell breaks under coordinated attack | M |
| Mosasaur | Heavy apex agent that dominates its zone | Needs a steady, large supply | L |
| Ocean sunfish | Huge passive bulk, no offence, depends on helpers | No self-defence | M |
| Archerfish | Ranged poke that knocks a target into a vulnerable spot | Low damage | M |
| Piranha | Swarm that overwhelms by numbers | Weak defence | L |
| Cleaner wrasse | Support agent that removes parasites (cleanup) for others | Depends on hosts | L |
| Box jellyfish | Sensor-equipped fast striker among reflex-only agents | Fragile | M |

### Mammals

| Animal | Agent shape and best task | Counter / guard | Conf |
|---|---|---|---|
| Wolf pack | Wide search then wear down: parallel workers harry a large problem in rotation (big refactors, long audits); keeps scout, flanker, closer roles | Needs a finisher; pack size depends on prey | H |
| Spotted hyena | Cleanup and salvage processor; extracts value from messy leftovers; high throughput | Politics and infighting; loses to stronger agents | M |
| Big cat, Smilodon | Single-shot precision strike after patient recon; minimal footprint | Relies on crits; fragile injuries | H |
| Cheetah | Fast sprint tasks on clear terrain | Guard against its work being overwritten by stronger processes; burst cost | H |
| Bear | Heavy generalist, seasonal rhythm (idle, then big intake) | Smell gives its position away | M |
| Gorilla | Team-coordinated strength | Fragile solo | L |
| Horse | Long-haul steady throughput with built-in watch rotation | Ambushed while grazing | M |
| Cow or bovine | High-capacity backlog drain | Easily misdirected | M |
| Giraffe | Lookout and early-warning monitor | Cannot defend many fronts | M |
| Pronghorn | Sustained speed on open terrain | Obstacles (fences) | M |
| Camel | Long autonomous haul with minimal resupply | Slow; resupply needs planning | M |
| Pig or hog | Generalist that handles anything | Low specialisation | L |
| Rhino | Single-direction brute force; needs a spotter | Easy to bait; bad in ambiguous terrain | M |
| Elephant | Long-memory archivist and coordinator; protects younger agents | Slow to pivot; costly to run | M |
| Bat | Fast navigation through dense, cluttered environments | Its signals reveal it (logs); fragile | H |
| Dolphin | Swarm coordination with sonar-style probing (ping, read, adapt) | Limited TierZoo coverage | L |
| Anteater | Sustainable harvesting: take a bounded slice, leave the source recoverable | Slow, poor eyesight | H |
| Mongoose | Specialist counter to one known hazard; stays near safe infrastructure | Tied to its base | L |
| Dire wolf | Cautionary: a specialist outlived by its environment; template for over-tuned agents | Prey base vanished | M |

## TierZoo terms (channel framing, credit when used)

Build (a species as a stat bundle), spec (invest in a trait), server or biome (our medium), meta (strategies currently winning), matchup (who beats whom), counter, tier list S to F, camping (wait for prey to come), glass cannon, tank, janitor (cleanup role), escort mission, control point, kiting, AoE, zone of control, respawn (reproduction or replacement rate), loot, kill steal, bleed or blood loss (attrition), friendly fire, RTS vs action RPG (colony control vs single body: our swarm vs solo agent), power creep, balance patch (environment change). Some terms are fan-wiki labels and may not be the creator's own.

## Known corrections (do not repeat the common error)

- Sharks need not keep moving; only some species (mako, great white) are obligate ram ventilators.
- Billfish do not hunt in packs. Morays beating sharks is unsupported.
- Net-casting spider eyes are not sun-damaged; it rebuilds light-sensitive membrane nightly.
- Owl waterproofing varies; silent flight is not universal.
- Magpie mirror-test result failed to replicate; do not use as proof of self-recognition.
- Polar bears are Arctic, not Antarctic; pelican "grapple" is a game metaphor.
- Mosasaur endothermy is disputed; juveniles seem to be open-ocean.
- Hyenas hunt a lot; "janitor" is TierZoo's label, not the full diet.
- Cheetah kill loss is about 9-14%, smaller than the video framing suggests.
- Camels are pseudo-ruminants with oval, not sickle-shaped, red cells.
- Haplodiploidy is not the full story of eusociality; most wasps are solitary.

## Long-horizon missions (e.g. ant-bot colonies mapping caves across planets)

Build the planning, mapping and data layers as runnable multi-agent workflows. Physical robots and hardware are out of scope here; produce specs and software and say so.

1. Terrain sheet per world: gravity, dust, ice, temperature swing, comms delay, no GPS, tight passages, collapse risk.
2. Colony roles: scouts, relay carriers (breadcrumb nodes), samplers, mappers, queen-node (memory and planning).
3. Stigmergy: agents leave marks (relay nodes, map tiles, hazard flags) in a shared ledger so work continues through blackouts.
4. Graceful degradation: lose any unit, keep the mission; replicate the shared map.
5. Hand-offs: ants map interiors, a falcon-class agent surveys entrances, a rhino-class agent clears routes, an owl audits.
6. Long time scale: dormancy cycles, wake triggers, a log the next agents can read.

## Procedure

1. Break the request into tasks and score each task on the six axes.
2. Match each task to the closest archetype or roster animal; split a task if it needs two temperaments in sequence (falcon sweep, then rhino charge). For a new animal, fill the trait sheet first.
3. For each agent, write a brief with: animal and mission, strengths and the trade-off paid, counter and guard, the lane (scope boundaries), rules of engagement (what it may not touch, no side effects unless stated), checkpoints, deliverable and acceptance check, stop rule and a fixed return format.
4. Spawn only what the task justifies; prefer fewer, correct animals over a zoo. Spawn agents only when the user has invoked this skill or asked for subagents.
5. Commander collects returns, checks them against the acceptance check and stop rules, resolves conflicts, and reports. Pair with Revelations 2:27 when the commander role needs the full Ender treatment.

## Return format (every agent)

Animal, mission, status (done / partial / blocked), deliverable, evidence, confidence, what it could not reach, suggested next move.

## Chains that worked

Falcon sweeps for breadth and fresh data, spider fills a prebuilt grid, owl audits contradictions, stale numbers and gaps. Agents share one model, so agreement between them is not independent confirmation: check the primary sources.

## Rules

- Match temperament to task shape; do not send a rhino to do a falcon's sweep. Derive the archetype from traits; never force a task into a favourite animal.
- Rhino, wolf and ant-colony agents get checkpoints; spider and owl agents get cheap, narrow tools; falcon agents get a corroboration rule before diving.
- Keep "defence" and "drone" roles to monitoring, verification and search. No agent acts outside its lane.
- If one animal would do, use one.
- Flag TierZoo-derived claims as secondhand until verified against the video.
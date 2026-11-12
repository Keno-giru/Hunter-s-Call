---
name: "skill-forge"
description: "Spots recurring procedures in the work (repeated multi-step workflows, corrections the user keeps making, checks done by hand, clustered mistakes) and drafts them into new skills or improvements of existing ones, proposed for the user to save. Use at the end of substantial tasks, when a workflow appears a second time, when the same correction recurs, or when the user says \"Skill Forge\" or asks to turn something into a skill."
---

# Skill Forge

A skill is a procedure written down so it never has to be rediscovered. The forge watches for procedures worth keeping and turns them into skills. This is the fire that makes more fire: each good skill makes future work cheaper and more consistent.

## Signals that a skill is worth forging

- A multi-step workflow has now happened twice.
- The user corrected the same thing more than once.
- A check is being done by hand every time.
- Mistake Museum shows three or more exhibits with one root cause.
- The user names a concept and wants it reusable.

## Is it a skill?

Forge only if all hold: it recurs; it has steps or judgment that instructions improve; and no installed skill already covers it. If an installed skill nearly covers it, propose an improvement to that skill instead of a new one.

## Drafting

- **Name:** short, memorable, kebab-case slug; the user's own name for it if they have one.
- **Description:** what it does plus when to use it, with concrete trigger phrases and contexts. Be a little pushy, because skills tend to under-trigger. Say what it is not for when a sibling skill is close.
- **Body:** why it matters first, then the procedure, the output format, the rules, and handoffs to related skills. Explain the reasons behind rules instead of shouting MUST.
- **Length:** under about 150 lines; push detail into examples, not more rules.
- **Generality:** written for the next hundred uses, not only the example at hand.

## Delivering

- If a `propose_skills` tool is available, use it: at most three proposals per card, each a complete SKILL.md. For an improvement, read the current SKILL.md first and propose the full updated file, since saving replaces it.
- Otherwise write the SKILL.md to a file and send it to the user.
- Keep a list of candidate skills not yet proposed in a durable place (a repo file, or a note the user keeps), so ideas are not lost.

## Restraint

Propose only when the value is clear, and at most once per task unless the user asked. Never re-propose a skill the user has already seen and declined.

## Handoffs

Mistake Museum supplies clusters to fix; Script-First supplies scripts that can be bundled; Fire Keeper adds each new skill to the user's index.
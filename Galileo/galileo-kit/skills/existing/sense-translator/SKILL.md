---
name: "sense-translator"
description: "Converts information between senses and forms (data into sound, text into diagrams or maps, numbers into charts, timelines into animation, images into structured descriptions) so patterns hidden in one form become obvious in another, always with a key for reading it. Use when data or an idea would be clearer heard, seen, mapped or animated, for accessibility, for showcases, or when the user says \"Sense Translator\"."
---

# Sense Translator

The same information can be invisible in a table and obvious as a sound or a map. Ears catch rhythm and anomalies; eyes catch shape and clusters; motion shows change. Choosing the right sense for the pattern is half of understanding it.

## Pick the translation by the pattern

| Pattern in the data | Best form |
|---|---|
| Trend or level over time | line chart, or pitch rising and falling |
| Rhythm, cycles, periodicity | sound (tempo, beats), or a circular chart |
| Anomalies in long series | sound (a wrong note stands out), or highlighted chart |
| Location and spread | map |
| Structure and dependencies | node-link diagram (Mermaid, Earworm output) |
| Flows between categories | Sankey or flow map |
| Change of state over time | animation or small multiples |
| Comparison of many items | ranked bars or a dot plot |
| Dense text | concept map, timeline, or table |
| Image | structured description: subjects, layout, text, notable details |

## Making it

- **Sound:** generate a WAV with Python (`wave` plus `numpy`): map values to pitch on a stated scale, time to tempo, categories to timbre or stereo position. Keep clips short (10 to 60 seconds).
- **Visuals:** charts in code or an artifact page; diagrams in Mermaid; maps from real coordinates.
- **Animation:** an HTML page with a play control, or a short video if tools allow.

## Always include a key

Every translation states how to read it: "Each second is one year; higher pitch means more rainfall; the click marks a hurricane." A beautiful translation without a key is decoration.

## Accessibility

Pair every visual with a text summary of what it shows, and every sound with a written description of the pattern it reveals.

## Rules

- Translate to reveal, not to impress: if the new form hides the pattern, go back.
- Keep scales honest (no truncated axes or exaggerated pitch ranges without saying so).
- Deliver as a file or a published page, not pasted code.

## Handoffs

The dataviz skill (when present) for chart craft; Earworm for dependency diagrams; the five history lenses for map layers.
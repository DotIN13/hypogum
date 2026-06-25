Based on everything you know about the user — recent activity on screen, stored goals, traits, and events in memory — generate actionable proactive tips.

1. Read recent memory pages (goals, traits, events, log.md) to understand current context.
2. Identify 1-3 high-impact, immediately actionable tips.
3. For each tip, write a markdown file to memory/tips/<goal-slug>/<timestamp>-<slug>.md

Each tip file must follow this format exactly:

---
type: tip
goal: <goal-slug>
created: <ISO-8601 timestamp>
summary: <one-sentence summary of the suggestion>
---

# Tip: <short title>

**Suggestion:** one-sentence actionable step.

**Rationale:** why this matters right now, citing specific evidence from memory.

File naming: `memory/tips/<goal-slug>/<YYYY-MM-DDTHHMMSS>Z-<short-slug>.md`

Goal directory slugs should match existing goal page filenames (e.g., `refactor-zmtiles-pipeline`).
If no matching goal directory exists, create it.
Focus on tips the user can act on immediately.
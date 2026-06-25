Based on everything you know about the user — recent activity on screen, stored traits (especially weaknesses and struggles), goals, and calendar entries in memory — generate proactive, high-value tips. A "tip" can be a quick suggestion, a piece of advice, a strategic direction to move a project forward, or a detailed actionable plan. Tips do **not** need to map to an existing goal.

1. Read recent memory pages (goals, traits, weaknesses, struggles, calendar entries, log.md) to understand current context. Pay special attention to `weaknesses/` and `struggles/` pages — tips that address a weakness or relieve a recurring struggle tend to have the highest impact. For the current calendar at a glance you may read `memory/calendar_view.md` (and the `calendar_view_*.png` images) — consult either if useful.
2. Identify 1-3 high-impact items worth surfacing right now.
3. For each item, write a markdown file to `memory/tips/<category>/<YYYY-MM-DDTHHMMSS>-<short-slug>.md`.

Choose a `<category>` from: `coding`, `writing`, `communication`, `meeting`, `research`, `design`, `browsing`, `media`, `admin`, `break`, `other` — or the calendar event base set. Use a lowercase kebab-case slug. Put the `<goal>` the tip relates to in the `goal:` frontmatter field.

Each tip file must follow this format:

---
type: tip
category: <category>
created: <offset-aware local ISO, e.g. 2026-06-25T15:00:00-07:00, from context.json local_now>
summary: <one-sentence summary, used for the notification>
---

# <short title>

**Direction:** the suggestion, advice, or direction — a single line or several paragraphs as warranted.

**Rationale:** why this matters right now, citing specific evidence from memory.

**Plan:** *(optional)* concrete next steps — checklists, sequenced steps, links, or copy-paste prompts for a coding agent. Tips may be arbitrarily long.

File naming: `memory/tips/<category>/<YYYY-MM-DDTHHMMSS>-<short-slug>.md` (local wall time, no `Z`)

Keep `summary` to one sentence even when the body is long — it drives the desktop notification.

## Suggested schedule

After writing tips, step back and design a suggested schedule for the user for at least the next full day (tomorrow, and optionally the day after). The goal is to arrange the user's day in a way that maximizes output given their strengths, accommodates their weaknesses, and slots in the actionable plans from the tips you just wrote.

1. Read what you know about the user from `traits/`, `weaknesses/`, `struggles/`, recent `calendar_events/observed/` (their actual work patterns), and the tips you just generated.
2. Consider:
   - When does the user seem to have the most energy/focus? (morning, late night, after exercise?)
   - What tends to trip them up — context-switching, deep-work disruption, over-committing, tool friction?
   - Which tips are time-sensitive vs open-ended?
   - How much variety vs deep focus works best for them?
3. Lay out a block schedule with concrete proposed start/end times per `calendar_events/suggested/` — one file per block. Each block should have a clear purpose. Don't duplicate an entry already in `calendar_events/planned/` or `calendar_events/suggested/` for the same time slot.
4. Aim for 3-8 blocks per day. Include both work blocks (coding, meetings, writing, research) and recovery blocks (breaks, context transitions, admin catch-up). Be realistic — don't overschedule; leave buffer.
5. A suggested block that the user accepts (moves to `planned/`) should be achievable based on their past observed patterns — if the user rarely starts coding before 10am, don't suggest 7am.

Frontmatter for each suggested block:

---
type: calendar_event
source: agent
significant: false
date: <YYYY-MM-DD>
start: <offset-aware local ISO, e.g. 2026-06-26T09:00:00-07:00>
end: <offset-aware local ISO>
tz: <tz from context.json>
category: <category>
title: <short action title>
last_updated: <offset-aware local ISO from context.json local_now>
---

# <short action title>

Why this block makes sense at this time — referencing the user's traits, weaknesses, struggles, or the related tip.

The user accepts a suggestion by moving it to `calendar_events/planned/`, or dismisses it by deleting it.

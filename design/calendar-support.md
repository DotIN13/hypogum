# Calendar support

Status: **accepted** — implemented as a single pass.
Decision date: 2026-06-25
Owner: hypogum

## Goal

Give the user a browsable record of **what they did** and **what they plan**, as
markdown files the **ingest (memory) agent** creates and edits each cycle from
(a) **observer products** (screen/camera) and (b) **user-input notes** (dropped by
the user, an MCP tool, or a backend call). Frontmatter is the structured source of
truth; a derived `.ics` makes it subscribable in a real calendar. Recurring events
are supported.

This **replaces** two earlier concepts:

- `memory/events/` markdown pages — folded into `calendar_events/` via a
  `significant: true` tier (see below).
- the `user_events` SQL table — removed; `get_insights` now reads the calendar.

`observations` (the raw observer table) and the file-based tips
(`memory/tips/`, MCP `get_tips`) are unchanged.

## Storage

One file per event under `data/memory/calendar_events/`, organised into three
**lifecycle folders** — the folder is the source of truth for lifecycle, so there is
**no `status` field**:

```
calendar_events/
├── suggested/   agent proposals (from the tips step); accept → move to planned/, dismiss → delete
├── planned/     committed future: user plans, imported, recurring series, accepted suggestions
└── observed/    confirmed happened (system + user-reported); holds the open "now" block; terminal
```

Filename within a bucket: `YYYY-MM-DDTHHMM_<category>_<slug>.md`.

### Frontmatter schema

```yaml
---
type: calendar_event        # singular, matches type: entity/event/goal
source: observed            # observed | user | imported | agent
significant: false          # true → indexed/cross-linked/lint/search (replaces events/)
date: 2026-06-25            # local day bucket (YYYY-MM-DD)
start: 2026-06-25T09:00:00  # local ISO
end: 2026-06-25T10:30:00    # local ISO; empty only while an OBSERVED block is in progress
tz: America/Los_Angeles     # resolved by Python (HYPOGUM_TIMEZONE or OS-local)
category: coding            # base set suggested; free-form allowed
title: Worked on the calendar feature
all_day: false
missed: false               # planned occurrence whose time passed unfulfilled
cancelled: false            # cancelled instance/event
recurrence:                 # RRULE on a planned series
recurrence_id:              # override of one instance
series:                     # [[planned/master]] (overrides/observed)
fulfills:                   # [[planned occurrence]] this observed event satisfies
fulfilled_by:               # [[observed event]] (on the planned)
occurrence:                 # instance date this observed/override maps to
last_updated: 2026-06-25T10:30:05Z
# when significant: true, also: confidence, lifespan, tags, related, evidence_count
---
Arbitrarily long body with [[wikilinks]].
```

No `source_event_ids` — provenance goes to `log.md` / the body.

### Base category vocabulary (suggested, not enforced)

`coding, writing, communication, meeting, research, design, browsing, media,
admin, break, other` — the agent may coin new ones.

## Conventions

- **Folder = lifecycle:** `suggested/` (agent proposals), `planned/` (committed
  future + recurring series), `observed/` (confirmed happened; holds the open
  block). Accepting a suggestion moves the file `suggested/ → planned/`.
- **Single writer (ingest):** the ingest agent mutates only the one open observed
  block; every other file, and anything `source: user` / `locked: true`, is
  read-only to it. It never writes `suggested/` (the tips step does).
- **Two flavors:**
  - `significant: false` (default) — calendar fields only; **excluded** from
    `index.md`, cross-linking, lint, and search. Pure timeline.
  - `significant: true` — also carries `confidence`/`lifespan`/`evidence`/`history`
    /`tags`/`related`; **indexed**, cross-linked, lint-checked, searchable, feeds
    tips. Replaces the old `events/` pages.
- Calendar files are **exempt** from `MEMORY.md`'s reciprocal back-link rule (they
  may link out to entities; no back-link into the target's `related` is required).

## Flow

```
ScreenObserver/CameraObserver → products (observations/<date>/products/screen_*.md)
UserInputObserver: polls memory/.tasks/user-input/*.md → user_input obs → products/user_*.md
   │ products → .tasks/ingest-input/products.txt ; context.json = {local_date, local_time, tz}
   ▼ ingest agent (single writer):
     memory pages + significant calendar entries
     observed products → create/extend the open block in calendar_events/observed/
     user_* products  → calendar_events/planned/ (future) or observed/ (past); recurring → planned/ series
     reconcile planned ↔ observed (fulfills/fulfilled_by, missed)
   ▼ tips step → calendar_events/suggested/ (agent proposals)
   ▼ hypogum calendar export → data/calendar.ics  (RRULE/RECURRENCE-ID aware)
```

User input is just another observer: notes land in
`memory/.tasks/user-input/` (by hand, MCP, or backend), the `UserInputObserver`
turns each into a `user_*` product, and the ingest agent — the single writer —
interprets them. The observation `processed` flag makes ingest idempotent.

## Recurring events

A recurring planned event is **one "series" master file** (in `planned/`) with
`recurrence:<RRULE>` (e.g. `FREQ=WEEKLY;BYDAY=MO,WE,FR`). Occurrences are not
stored. A single deviating instance is an **override** file (`recurrence_id` +
`series` + new times or `cancelled: true`). An observed event that satisfies an
occurrence links via `fulfills` + `occurrence`.

ICS: master → `VEVENT` with `RRULE`; override → `VEVENT` sharing the master `UID`
plus `RECURRENCE-ID`; cancellation → `EXDATE` / `STATUS:CANCELLED`; actuals → their
own `VEVENT`s. Miss-detection is LLM-guided in the ingest prompt (no `dateutil` dep).

## Lifecycle rules

The open observed block closes on activity/category change, a gap > ~20 min
(idle/lock), or day rollover. The next cycle self-heals a stale-open block (closes
it at the last observed time if `last_updated` is older than ~2× `process_interval`).
Target ~5–15 readable blocks/day, ~10 min minimum, merging same-category switches
under ~15–20 min.

## ICS export

`hypogum/calendar/parse.py` reads each file's frontmatter → entries (dep-free
scalar parser; the bucket is taken from the folder). `hypogum/calendar/ics.py`
renders a single rolling `data/calendar.ics` (hand-rolled `VCALENDAR`/`VEVENT`,
`TZID` times, `UID` from filename, `SUMMARY="<category>: <title>"`, `CATEGORIES`,
RRULE/`RECURRENCE-ID` pass-through). All three buckets are exported, with a
`STATUS` reflecting the folder: `observed`/`planned` → `CONFIRMED`, `suggested` →
`TENTATIVE`, `cancelled: true` → `CANCELLED`; still-open and `missed` blocks are
skipped.

CLI: `hypogum calendar export [--out data/calendar.ics] [--days 90]` and
`hypogum calendar show [--date YYYY-MM-DD] [--bucket suggested|planned|observed]`.
Optional auto-export after ingest behind `HYPOGUM_CALENDAR_ICS`.

## Configuration

- `HYPOGUM_TIMEZONE` — IANA name (e.g. `America/Los_Angeles`); default = OS-local.
  Adds `tzdata` so the override works on Windows.
- `HYPOGUM_OBSERVE_USER_INPUT_ENABLED` (default true), `HYPOGUM_USER_INPUT_INTERVAL`.
- `HYPOGUM_CALENDAR_ICS` (default false) — auto-export `.ics` after each ingest.

## Removed

- `user_events` table + `save_event`/`get_events`/`get_event`/`update_event_tip`/
  `get_tips` across `DBStore`/`SQLAlchemyDBStore`/`RemoteDBStore`.
- `POST/GET /api/v1/events`, `GET /api/v1/events/{id}`,
  `PATCH /api/v1/events/{id}/tip`, `GET /api/v1/tips`.
- The `save_event` call + `event_id` in the processing pipeline.

## Out of scope

Calendar UI; real external-calendar sync/import (the `imported` source is
reserved); vector-indexing of mundane calendar entries; migrating pre-existing
`memory/events/` pages (left in place).

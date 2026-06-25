# Memory Conventions

This document defines the structure and conventions for the hypogum personal
memory — an LLM-maintained markdown wiki of the user. The memory agent reads
this file at the start of every ingest or lint task to understand the page
format, cross-referencing rules, and maintenance workflows.

## Directory structure

- `entities/`  — people, organizations, projects, tools, services
- `traits/`    — personality, skill, interest, preference, ownership, weakness
- `events/`    — significant occurrences (compound, not per-cycle observations)
- `goals/`     — current and past objectives
- `index.md`   — category-organized catalog of every page (LLM-maintained)
- `log.md`     — append-only audit trail (LLM-appends, newest first)

## Page format

Every page is a markdown file with YAML frontmatter and a structured body.

### Frontmatter (required fields)

```yaml
---
type: entity          # entity | trait | event | goal
confidence: 5         # 1-10, higher = more certain
lifespan: 5           # 1-10, higher = longer persistence
last_updated: 2026-06-24T10:00:00Z  # ISO 8601
evidence_count: 1
tags: []
related: []           # [[wikilinks]]
---
```

Trait pages also require:
```yaml
subtype: skill        # personality|skill|interest|preference|ownership|relationship|weakness
```

### Body structure

```markdown
# Title (human-readable name)

One-paragraph synthesis of what is known — the current best understanding,
combining all evidence so far.

## Evidence
- [YYYY-MM-DD] Specific observation with source detail

## History
- YYYY-MM-DD: what changed and why

## Tensions *(optional)*
- Unresolved contradiction or open question
```

### Frontmatter field semantics

- **confidence** — how certain the agent is about this page's claims.
  A single weak observation starts at confidence 3-5. Repeated, consistent
  evidence from multiple cycles raises confidence. Contradicting evidence
  lowers it. Hard cap: confidence cannot exceed `evidence_count + 2`.

- **lifespan** — how long this insight is expected to persist.
  1-3: transient (specific events, daily patterns). Stale after ~7 days.
  4-6: medium-term (projects, active interests). Stale after ~30 days.
  7-10: durable (personality, deep skills, relationships). Stale after ~90 days.

- **evidence_count** — number of distinct evidence entries. Incremented on
  every ingest that adds new supporting evidence.

- **tags** — lowercase keywords for topic grouping and search.

- **related** — `[[wikilinks]]` to other memory pages. Update the `related`
  frontmatter of both pages when adding a new cross-reference.

## Cross-referencing rules

1. Use `[[path.md]]` wikilinks for any entity, trait, event, or goal
   mentioned in a page body.
2. When adding a new link from page A to page B, also add A to B's
   `related` frontmatter list.
3. Every entity page (person, project, tool) should be linked from any
   trait page that references it. E.g., if `traits/Python.md` mentions
   "Apollo project," it must have `[[entities/Apollo.md]]` in `related`.

## Evidence rules

1. Every claim on a page needs at least one dated evidence entry.
2. Each evidence entry cites a specific observation (source, date, what was seen).
3. Multiple observations from different sources reinforce confidence.
4. Contradicting evidence between pages is **never silently merged**.
   Instead, add a `## Tensions` section to both pages and update
   `entities/tensions.md`.
5. Evidence is preserved, not overwritten — the `## History` section
   tracks how understanding has evolved.

## Index maintenance

`index.md` is the canonical catalog. It is organized by category headings:

```markdown
## entities
- [[entities/Alice.md]] — Colleague, frontend engineer on team Apollo

## traits
- [[traits/Python.md]] — Proficient backend/scripting language (confidence 7)

## events
- [[events/2026-06-20_onboarding.md]] — Started new onboarding project

## goals
- [[goals/learn_rust.md]] — Learning Rust for systems programming
```

Each entry has the `[[wikilink]]`, an em-dash, and a one-line summary
including current confidence. Pages are listed alphabetically within
each category.

**Updated on every ingest.** The agent adds new entries, updates summaries
of changed pages, and removes entries for merged/deleted pages.

**Verified on every lint.** The agent checks that every page has an index
entry and every index entry points to an existing page.

## Log format

`log.md` is append-only with newest entries first:

```markdown
# Memory Log

## [2026-06-24 10:30:00] ingest | 3 observations
- entities/Apollo.md: added @alice as reviewer, confidence 6→7
- traits/Python.md: new evidence, confidence unchanged
- entities/Cursor.md: NEW — switched from VSCode

## [2026-06-25 02:00:00] lint | daily health check
- 3 auto-fixes, 2 contradictions flagged, 5 pages marked stale
```

Each log entry starts with `## [YYYY-MM-DD HH:MM:SS] <operation> | <summary>`.
Operations: `ingest`, `lint`, `query`, `manual-edit`.

## Ingest workflow (agent instructions)

When processing observer product files:

1. Read all product files (rich markdown from observers).
2. Read `index.md` to find matching existing pages.
3. Read `log.md` (last ~20 entries) for recent context.
4. For each observation in the products:
   a. Identify entities (people, projects, tools) — create or update entity pages.
   b. Identify traits (skills, preferences, habits, weaknesses) — create or update trait pages.
   c. Identify significant events — create event pages or append to entity pages.
   d. Identify goals — create or update goal pages.
5. Cross-reference across products: a calendar mention of @alice connects to a screen observation showing @alice in Slack.
6. Write all updated/new pages (batch writes — one write per page).
7. Update `index.md`.
8. Append entry to `log.md`.
9. Write `data/memory/.tasks/ingest-result.json` with summary.

## Lint workflow (agent instructions)

When performing a health check:

1. Read `index.md` for full page catalog.
2. Read `log.md` (last ~50 entries) for recent activity.
3. Scan every page for:
   a. **Staleness** — `last_updated` older than `lifespan` days. Add `stale: true` frontmatter and a warning banner.
   b. **Contradictions** — conflicting claims between pages. Add `## Tensions` sections, update `entities/tensions.md`. Never auto-resolve.
   c. **Orphans** — pages with no inbound links. Add `orphan: true` frontmatter.
   d. **Missing cross-references** — mentioned entities without wikilinks. Add missing `[[...]]` links (auto-fix).
   e. **Near-duplicates** — similar page titles/topics. Flag for review, do not merge.
   f. **Frontmatter integrity** — fix missing/broken required fields (auto-fix).
   g. **Broken wikilinks** — links to nonexistent pages. Remove or flag (auto-fix if obviously stale).
   h. **Confidence decay** — high-confidence pages with no recent evidence. Propose downgrade.
4. Auto-fix safe issues (cross-refs, frontmatter, broken links).
5. Flag ambiguous issues in result (contradictions, duplicates, decay proposals).
6. Append entry to `log.md`.
7. Write `data/memory/.tasks/lint-result.json` with findings.

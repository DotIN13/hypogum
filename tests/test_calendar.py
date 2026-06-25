import datetime
from pathlib import Path

import pytest

from hypogum.agent.processor.describe import _frontmatter
from hypogum.calendar.ics import to_ics
from hypogum.calendar.parse import (
    CalendarEntry,
    load_entries,
    parse_frontmatter,
    recent_observed_entries,
)
from hypogum.calendar.view import export_view, render_markdown
from hypogum.config import to_local_iso

OBSERVED_CODING = """---
type: calendar_event
source: observed
significant: false
date: 2026-06-25
start: 2026-06-25T09:00:00
end: 2026-06-25T10:30:00
tz: America/Los_Angeles
category: coding
title: Worked on the calendar feature
---
Body.
"""

OBSERVED_EMAIL = """---
type: calendar_event
source: observed
date: 2026-06-25
start: 2026-06-25T08:00:00
end: 2026-06-25T08:30:00
tz: America/Los_Angeles
category: communication
title: Morning email
---
"""

OBSERVED_OPEN = """---
type: calendar_event
source: observed
date: 2026-06-25
start: 2026-06-25T11:00:00
end:
tz: America/Los_Angeles
category: research
title: Reading docs
---
"""

PLANNED_STANDUP = """---
type: calendar_event
source: user
date: 2026-06-26
start: 2026-06-26T09:00:00
end: 2026-06-26T09:15:00
tz: America/Los_Angeles
category: meeting
title: Daily standup
recurrence: FREQ=WEEKLY;BYDAY=MO,WE,FR
---
"""

PLANNED_MISSED = """---
type: calendar_event
source: user
date: 2026-06-24
start: 2026-06-24T09:00:00
end: 2026-06-24T09:15:00
tz: America/Los_Angeles
category: meeting
title: Skipped standup
missed: true
---
"""

SUGGESTED_BREAK = """---
type: calendar_event
source: agent
date: 2026-06-25
start: 2026-06-25T15:00:00
end: 2026-06-25T15:15:00
tz: America/Los_Angeles
category: break
title: Take a short break
---
"""

LAYOUT = {
    "observed/2026-06-25T0900_coding_calendar.md": OBSERVED_CODING,
    "observed/2026-06-25T0800_communication_email.md": OBSERVED_EMAIL,
    "observed/2026-06-25T1100_research_docs.md": OBSERVED_OPEN,
    "planned/2026-06-26T0900_meeting_standup.md": PLANNED_STANDUP,
    "planned/2026-06-24T0900_meeting_skipped.md": PLANNED_MISSED,
    "suggested/2026-06-25T1500_break_take-break.md": SUGGESTED_BREAK,
}


def _make_memory(tmp_path: Path) -> Path:
    cal = tmp_path / "calendar_events"
    for rel, content in LAYOUT.items():
        f = cal / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
    return tmp_path


def test_load_entries_parses_buckets(tmp_path):
    root = _make_memory(tmp_path)
    entries = load_entries(root)
    assert len(entries) == 6
    by_title = {e.title: e for e in entries}
    standup = by_title["Daily standup"]
    assert standup.bucket == "planned"
    assert standup.recurrence == "FREQ=WEEKLY;BYDAY=MO,WE,FR"
    assert by_title["Take a short break"].bucket == "suggested"
    assert by_title["Reading docs"].bucket == "observed"
    assert by_title["Reading docs"].end == ""
    assert by_title["Skipped standup"].missed is True


def test_recent_observed_entries_only_observed_newest_first(tmp_path):
    root = _make_memory(tmp_path)
    observed = recent_observed_entries(root, limit=10)
    titles = [e["title"] for e in observed]
    assert "Daily standup" not in titles      # planned excluded
    assert "Take a short break" not in titles  # suggested excluded
    assert "Skipped standup" not in titles     # planned/missed excluded
    assert titles[0] == "Reading docs"         # newest start first
    assert (
        titles.index("Worked on the calendar feature")
        < titles.index("Morning email")
    )


def test_ics_includes_suggested_skips_open_and_missed(tmp_path):
    root = _make_memory(tmp_path)
    text = to_ics(load_entries(root))
    # 2 observed + 1 recurring planned + 1 suggested = 4; open + missed skipped
    assert text.count("BEGIN:VEVENT") == 4
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR" in text
    assert "STATUS:TENTATIVE" in text          # suggested
    assert "STATUS:CONFIRMED" in text          # observed/planned
    assert "TZID=America/Los_Angeles:20260625T090000" in text
    assert "SUMMARY:coding: Worked on the calendar feature" in text
    assert "Reading docs" not in text          # open block excluded
    assert "Skipped standup" not in text       # missed excluded
    assert text.startswith("BEGIN:VCALENDAR")


def test_render_markdown_has_three_sections(tmp_path):
    root = _make_memory(tmp_path)
    md = render_markdown(load_entries(root), today=datetime.date(2026, 6, 25))
    assert "## Today (2026-06-25)" in md
    assert "## This week" in md
    assert "## This month (June 2026)" in md
    assert "Worked on the calendar feature" in md   # today's observed
    assert "Take a short break" in md               # today's suggested
    assert "Tracked" in md                          # per-category summary line


def test_export_view_writes_markdown_and_png(tmp_path):
    pytest.importorskip("matplotlib")
    root = _make_memory(tmp_path)
    out = tmp_path / "out"
    res = export_view(root, out, today=datetime.date(2026, 6, 25), png=True)
    assert res["png"] is True
    assert (out / "calendar_view.md").exists()
    names = (
        "calendar_view_day.png",
        "calendar_view_week.png",
        "calendar_view_month.png",
    )
    for name in names:
        p = out / name
        assert p.exists()
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_to_local_iso_converts_utc():
    assert (
        to_local_iso("2026-06-25T07:12:02Z", "America/Los_Angeles")
        == "2026-06-25T00:12:02-07:00"
    )
    # naive input is assumed UTC
    assert (
        to_local_iso("2026-06-25T07:12:02", "America/Los_Angeles")
        == "2026-06-25T00:12:02-07:00"
    )
    # unparseable input is returned unchanged
    assert to_local_iso("not-a-date", "America/Los_Angeles") == "not-a-date"


def test_frontmatter_round_trips():
    meta = {
        "type": "screen",
        "created": "2026-06-25T00:12:02-07:00",
        "observation_count": 3,
        "observation_ids": [1, 2, 3],
        "active_window": "VS Code editor",
        "windows": ["VS Code", "Slack: general"],
        "empty": None,
    }
    text = _frontmatter(meta)
    fm = parse_frontmatter(text)
    assert fm["type"] == "screen"
    assert fm["created"] == "2026-06-25T00:12:02-07:00"
    assert fm["observation_count"] == "3"
    assert fm["active_window"] == "VS Code editor"
    assert "empty" not in fm                 # None values are skipped
    assert '"Slack: general"' in text        # colon-space value is quoted


def test_ics_offset_aware_start_uses_tzid_wall_time():
    e = CalendarEntry.from_frontmatter(
        "calendar_events/observed/2026-06-25T0900_coding_x.md",
        {
            "source": "observed",
            "start": "2026-06-25T09:00:00-07:00",
            "end": "2026-06-25T10:30:00-07:00",
            "tz": "America/Los_Angeles",
            "category": "coding",
            "title": "X",
        },
    )
    text = to_ics([e])
    assert "DTSTART;TZID=America/Los_Angeles:20260625T090000" in text
    assert any(
        ln.startswith("DTSTAMP:") and ln.rstrip().endswith("Z")
        for ln in text.splitlines()
    )

"""Render calendar entries to a subscribable iCalendar (.ics) file.

Hand-rolled (no external dependency). Times are emitted with ``TZID`` (resolved by
the calendar client's tz database) so recurrence stays DST-correct; entries with no
timezone fall back to floating local time. Recurring series emit ``RRULE``; single
overrides share the master ``UID`` plus ``RECURRENCE-ID``.
"""

import datetime
import hashlib
import re
from pathlib import Path

from hypogum.calendar.parse import CalendarEntry, load_entries

_PRODID = "-//hypogum//calendar//EN"
_BUCKET_STATUS = {
    "observed": "CONFIRMED",
    "planned": "CONFIRMED",
    "suggested": "TENTATIVE",
}
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _parse_iso(value: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _fmt_local(value: str) -> str | None:
    dt = _parse_iso(value)
    return dt.strftime("%Y%m%dT%H%M%S") if dt else None


def _fmt_date(value: str) -> str | None:
    dt = _parse_iso(value)
    if dt:
        return dt.strftime("%Y%m%d")
    if value and len(value) >= 10:
        return value[:10].replace("-", "")
    return None


def _dt_property(name: str, value: str, tz: str, all_day: bool) -> str | None:
    if all_day:
        d = _fmt_date(value)
        return f"{name};VALUE=DATE:{d}" if d else None
    local = _fmt_local(value)
    if not local:
        return None
    if tz:
        return f"{name};TZID={tz}:{local}"
    return f"{name}:{local}"


def _stem_from_wikilink(value: str) -> str | None:
    m = _WIKILINK_RE.search(value or "")
    target = m.group(1) if m else value
    return Path(target).stem if target else None


def _uid(stem: str) -> str:
    return hashlib.sha1(stem.encode("utf-8")).hexdigest()[:24] + "@hypogum"


def entry_to_vevent(entry: CalendarEntry, dtstamp: str) -> list[str] | None:
    """Build VEVENT lines for one entry, or None if it should not be exported."""
    if entry.missed or not entry.start:
        return None
    # Skip still-open observed blocks (no end, not all-day, not a recurring series).
    if not entry.end and not entry.all_day and not entry.recurrence:
        return None

    own_stem = Path(entry.path).stem
    if entry.recurrence_id and entry.series:
        master = _stem_from_wikilink(entry.series) or own_stem
        uid = _uid(master)
    else:
        uid = _uid(own_stem)

    lines = ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{dtstamp}"]

    dtstart = _dt_property("DTSTART", entry.start, entry.tz, entry.all_day)
    if not dtstart:
        return None
    lines.append(dtstart)
    if entry.end:
        dtend = _dt_property("DTEND", entry.end, entry.tz, entry.all_day)
        if dtend:
            lines.append(dtend)

    if entry.recurrence:
        lines.append(f"RRULE:{entry.recurrence}")
    if entry.recurrence_id:
        rid = _dt_property(
            "RECURRENCE-ID", entry.recurrence_id, entry.tz, entry.all_day,
        )
        if rid:
            lines.append(rid)

    summary = f"{entry.category}: {entry.title}" if entry.category else entry.title
    lines.append(f"SUMMARY:{_escape(summary)}")
    if entry.category:
        lines.append(f"CATEGORIES:{_escape(entry.category)}")
    status = "CANCELLED" if entry.cancelled else _BUCKET_STATUS.get(entry.bucket)
    if status:
        lines.append(f"STATUS:{status}")
    lines.append("END:VEVENT")
    return lines


def to_ics(entries: list[CalendarEntry]) -> str:
    dtstamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{_PRODID}", "CALSCALE:GREGORIAN"]
    for entry in entries:
        vevent = entry_to_vevent(entry, dtstamp)
        if vevent:
            out.extend(vevent)
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def export_ics(memory_root: Path, out_path: Path, days: int | None = None) -> int:
    """Write a rolling .ics for entries under <memory_root>/calendar_events/.

    Returns the number of events exported. ``days`` (if set) limits to entries whose
    date falls within the last N days.
    """
    entries = load_entries(memory_root)
    if days is not None:
        cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        entries = [e for e in entries if (e.date or "") >= cutoff or e.recurrence]
    text = to_ics(entries)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return text.count("BEGIN:VEVENT")

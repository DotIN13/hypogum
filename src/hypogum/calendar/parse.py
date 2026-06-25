"""Parse calendar_events/ markdown files into structured entries."""

import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)

CALENDAR_DIR = "calendar_events"
BUCKETS = ("suggested", "planned", "observed")


def parse_frontmatter(text: str) -> dict:
    """Extract scalar YAML frontmatter as a key→string dict.

    Deliberately simple (no external YAML dep): one ``key: value`` per line,
    blank values allowed. List/nested syntax is returned as its raw string.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    result: dict[str, str] = {}
    for line in m.group(1).split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        result[key.strip()] = val.strip()
    return result


def body_after_frontmatter(text: str) -> str:
    m = _FRONTMATTER_RE.match(text)
    return text[m.end():].lstrip("\n") if m else text


def _as_bool(val: str) -> bool:
    return val.strip().lower() in ("true", "1", "yes")


def _bucket_from_path(path: str) -> str:
    """The lifecycle folder (suggested/planned/observed) a calendar file lives in."""
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] == CALENDAR_DIR:
        return parts[1]
    return ""


@dataclass(slots=True)
class CalendarEntry:
    path: str
    bucket: str = ""           # suggested | planned | observed (from the folder)
    source: str = "observed"
    significant: bool = False
    date: str = ""
    start: str = ""
    end: str = ""
    tz: str = ""
    category: str = "other"
    title: str = ""
    all_day: bool = False
    missed: bool = False
    cancelled: bool = False
    recurrence: str = ""
    recurrence_id: str = ""
    series: str = ""
    fulfills: str = ""
    occurrence: str = ""
    last_updated: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_frontmatter(cls, path: str, fm: dict) -> "CalendarEntry":
        known = {
            "source", "date", "start", "end", "tz", "category",
            "title", "recurrence", "recurrence_id", "series", "fulfills",
            "occurrence", "last_updated",
        }
        flags = ("significant", "all_day", "missed", "cancelled", "type")
        return cls(
            path=path,
            bucket=_bucket_from_path(path),
            source=fm.get("source", "observed"),
            significant=_as_bool(fm.get("significant", "false")),
            date=fm.get("date", ""),
            start=fm.get("start", ""),
            end=fm.get("end", ""),
            tz=fm.get("tz", ""),
            category=fm.get("category", "other"),
            title=fm.get("title", ""),
            all_day=_as_bool(fm.get("all_day", "false")),
            missed=_as_bool(fm.get("missed", "false")),
            cancelled=_as_bool(fm.get("cancelled", "false")),
            recurrence=fm.get("recurrence", ""),
            recurrence_id=fm.get("recurrence_id", ""),
            series=fm.get("series", ""),
            fulfills=fm.get("fulfills", ""),
            occurrence=fm.get("occurrence", ""),
            last_updated=fm.get("last_updated", ""),
            extra={k: v for k, v in fm.items() if k not in known and k not in flags},
        )

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "bucket": self.bucket,
            "source": self.source,
            "significant": self.significant,
            "date": self.date,
            "start": self.start,
            "end": self.end,
            "category": self.category,
            "title": self.title,
        }


def calendar_dir(memory_root: Path) -> Path:
    return Path(memory_root) / CALENDAR_DIR


def load_entries(memory_root: Path) -> list[CalendarEntry]:
    """Load calendar entries from the suggested/planned/observed buckets only.

    Restricting to the known bucket folders keeps non-event files (e.g. the
    rendered ``calendar_view.*``) from being parsed as entries.
    """
    base = calendar_dir(memory_root)
    entries: list[CalendarEntry] = []
    for bucket in BUCKETS:
        bdir = base / bucket
        if not bdir.exists():
            continue
        for f in sorted(bdir.rglob("*.md")):
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            fm = parse_frontmatter(text)
            if not fm:
                continue
            rel = f.relative_to(memory_root).as_posix()
            entries.append(CalendarEntry.from_frontmatter(rel, fm))
    return entries


def _start_instant(e: CalendarEntry) -> datetime.datetime:
    """Sortable absolute instant from start (offset-aware) or date, for ordering."""
    for v in (e.start, e.date):
        if not v:
            continue
        try:
            dt = datetime.datetime.fromisoformat(v)
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.replace(tzinfo=datetime.UTC)
    return datetime.datetime.min.replace(tzinfo=datetime.UTC)


def recent_observed_entries(
    memory_root: Path, limit: int = 10, offset: int = 0,
) -> list[dict]:
    """Recent entries from the observed/ bucket, newest first — used by get_insights."""
    observed = [e for e in load_entries(memory_root) if e.bucket == "observed"]
    observed.sort(key=_start_instant, reverse=True)
    return [e.to_dict() for e in observed[offset:offset + limit]]

"""Calendar event file parsing and ICS export.

The ingest agent maintains markdown files under ``<memory>/calendar_events/`` whose
YAML frontmatter is the structured source of truth. This package reads that
frontmatter (``parse``) and renders a subscribable ``.ics`` (``ics``).
"""

from hypogum.calendar.parse import (
    CalendarEntry,
    load_entries,
    recent_observed_entries,
)

__all__ = ["CalendarEntry", "load_entries", "recent_observed_entries"]

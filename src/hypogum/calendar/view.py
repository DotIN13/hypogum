"""Render the calendar into human/agent-readable views: markdown + PNGs.

Deterministic projection of the ``calendar_events/`` files (no LLM). The markdown
view (``calendar_view.md``) covers today, this week, and this month; the PNGs
(``calendar_view_{day,week,month}.png``, matplotlib) visualise the same. PNGs are
skipped gracefully when matplotlib is not installed.
"""

import calendar as _calendar
import datetime
from pathlib import Path

from loguru import logger

from hypogum.calendar.parse import CalendarEntry, load_entries

_BUCKET_COLOR = {
    "observed": "#4C9A2A",
    "planned": "#2A6FDB",
    "suggested": "#E1A100",
}
_LANES = ("observed", "planned", "suggested")


# ── helpers ───────────────────────────────────

def _parse_dt(value: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _entry_date(e: CalendarEntry) -> datetime.date | None:
    if e.date:
        try:
            return datetime.date.fromisoformat(e.date)
        except ValueError:
            pass
    dt = _parse_dt(e.start)
    return dt.date() if dt else None


def _hhmm(value: str) -> str:
    dt = _parse_dt(value)
    if dt:
        return dt.strftime("%H:%M")
    return value[11:16] if len(value) >= 16 else value


def _duration_min(e: CalendarEntry) -> float:
    a, b = _parse_dt(e.start), _parse_dt(e.end)
    if a and b and b > a:
        return (b - a).total_seconds() / 60.0
    return 0.0


def _event_hours(e: CalendarEntry) -> tuple[float, float] | None:
    a = _parse_dt(e.start)
    if not a:
        return None
    start_h = a.hour + a.minute / 60.0
    b = _parse_dt(e.end)
    end_h = (b.hour + b.minute / 60.0) if (b and b > a) else start_h + 0.25
    end_h = min(max(end_h, start_h + 0.15), 24.0)
    return start_h, end_h


def _group_by_day(
    entries: list[CalendarEntry],
) -> dict[datetime.date, list[CalendarEntry]]:
    by_day: dict[datetime.date, list[CalendarEntry]] = {}
    for e in entries:
        d = _entry_date(e)
        if d:
            by_day.setdefault(d, []).append(e)
    return by_day


def _cat_breakdown(observed: list[CalendarEntry], top: int | None = None) -> str:
    cat_min: dict[str, float] = {}
    for e in observed:
        cat_min[e.category] = cat_min.get(e.category, 0.0) + _duration_min(e)
    items = sorted(cat_min.items(), key=lambda kv: -kv[1])
    if top:
        items = items[:top]
    return ", ".join(f"{c} {m / 60:.1f}h" for c, m in items if m > 0)


# ── markdown ──────────────────────────────────

def _md_today(day_entries: list[CalendarEntry], today: datetime.date) -> list[str]:
    out = [f"## Today ({today.isoformat()})", ""]
    if not day_entries:
        out += ["_No calendar entries today._", ""]
        return out

    for bucket in _LANES:
        items = sorted(
            (e for e in day_entries if e.bucket == bucket),
            key=lambda e: e.start,
        )
        if not items:
            continue
        out.append(f"**{bucket.capitalize()}**")
        for e in items:
            end = _hhmm(e.end) if e.end else "now"
            flag = " (missed)" if e.missed else (" (cancelled)" if e.cancelled else "")
            out.append(f"- {_hhmm(e.start)}–{end} · {e.category} · {e.title}{flag}")
        out.append("")

    observed = [e for e in day_entries if e.bucket == "observed"]
    total = sum(_duration_min(e) for e in observed)
    if total > 0:
        out.append(f"_Tracked {total / 60:.1f}h today — {_cat_breakdown(observed)}_")
        out.append("")
    return out


def _md_week(by_day, week_start: datetime.date) -> list[str]:
    week_end = week_start + datetime.timedelta(days=6)
    out = [f"## This week ({week_start.isoformat()} – {week_end.isoformat()})", ""]
    for i in range(7):
        d = week_start + datetime.timedelta(days=i)
        es = by_day.get(d, [])
        label = d.strftime("%a %m-%d")
        if not es:
            out.append(f"- {label} — —")
            continue
        obs = [e for e in es if e.bucket == "observed"]
        pl = [e for e in es if e.bucket == "planned"]
        sg = [e for e in es if e.bucket == "suggested"]
        bits = []
        if obs:
            cats = _cat_breakdown(obs, top=3)
            bits.append(f"{len(obs)} observed" + (f" ({cats})" if cats else ""))
        if pl:
            bits.append(f"{len(pl)} planned")
        if sg:
            bits.append(f"{len(sg)} suggested")
        out.append(f"- {label} — " + "; ".join(bits))
    out.append("")
    return out


def _md_month(by_day, today: datetime.date) -> list[str]:
    out = [f"## This month ({today.strftime('%B %Y')})", ""]
    out.append("| Mon | Tue | Wed | Thu | Fri | Sat | Sun |")
    out.append("|-----|-----|-----|-----|-----|-----|-----|")
    for week in _calendar.monthcalendar(today.year, today.month):
        cells = []
        for day in week:
            if day == 0:
                cells.append("")
                continue
            d = datetime.date(today.year, today.month, day)
            n = len(by_day.get(d, []))
            mark = f" ·{n}" if n else ""
            star = "**" if d == today else ""
            cells.append(f"{star}{day}{star}{mark}")
        out.append("| " + " | ".join(cells) + " |")
    out += ["", "_·N = number of calendar entries that day._", ""]
    return out


def render_markdown(
    entries: list[CalendarEntry], *, today: datetime.date, tz_label: str = "",
) -> str:
    by_day = _group_by_day(entries)
    week_start = today - datetime.timedelta(days=today.weekday())
    gen = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    tzs = f" ({tz_label})" if tz_label else ""

    lines = [
        "# Calendar view",
        "",
        f"_generated {gen}{tzs} — local day {today.isoformat()}_",
        "",
    ]
    lines += _md_today(by_day.get(today, []), today)
    lines += _md_week(by_day, week_start)
    lines += _md_month(by_day, today)
    return "\n".join(lines) + "\n"


# ── PNGs (matplotlib, optional) ───────────────

def _matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except Exception:  # pragma: no cover - optional dependency
        return None


def _render_day_png(plt, day_entries, out_path: Path, today: datetime.date) -> None:
    fig, ax = plt.subplots(figsize=(11, 3.4))
    for li, bucket in enumerate(_LANES):
        for e in (x for x in day_entries if x.bucket == bucket):
            hours = _event_hours(e)
            if not hours:
                continue
            start_h, end_h = hours
            ax.barh(li, end_h - start_h, left=start_h, height=0.6,
                    color=_BUCKET_COLOR[bucket], edgecolor="white", alpha=0.9)
            ax.text(start_h + 0.05, li, f"{e.category}: {e.title}"[:40],
                    va="center", fontsize=7)
    ax.set_yticks(range(len(_LANES)))
    ax.set_yticklabels(_LANES)
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 2))
    ax.set_xlabel("hour")
    ax.set_title(f"Day — {today.isoformat()}")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def _render_week_png(plt, by_day, week_start: datetime.date, out_path: Path) -> None:
    from matplotlib.patches import Rectangle

    fig, ax = plt.subplots(figsize=(11, 6))
    for i in range(7):
        d = week_start + datetime.timedelta(days=i)
        for e in by_day.get(d, []):
            hours = _event_hours(e)
            if not hours:
                continue
            start_h, end_h = hours
            ax.add_patch(Rectangle((i + 0.05, start_h), 0.9, end_h - start_h,
                         color=_BUCKET_COLOR.get(e.bucket, "#888888"), alpha=0.85))
            ax.text(i + 0.08, start_h + 0.1, e.title[:14], fontsize=6, va="top")
    ax.set_xlim(0, 7)
    ax.set_ylim(24, 0)
    ax.set_xticks([i + 0.5 for i in range(7)])
    labels = [
        (week_start + datetime.timedelta(days=i)).strftime("%a %m-%d")
        for i in range(7)
    ]
    ax.set_xticklabels(labels)
    ax.set_yticks(range(0, 25, 2))
    ax.set_ylabel("hour")
    ax.set_title(f"Week of {week_start.isoformat()}")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def _render_month_png(plt, by_day, today: datetime.date, out_path: Path) -> None:
    from matplotlib.patches import Rectangle

    weeks = _calendar.monthcalendar(today.year, today.month)
    fig, ax = plt.subplots(figsize=(9, 1.3 * len(weeks) + 1))
    ax.set_xlim(0, 7)
    ax.set_ylim(0, len(weeks))
    ax.invert_yaxis()
    for r, week in enumerate(weeks):
        for c, day in enumerate(week):
            if day == 0:
                continue
            d = datetime.date(today.year, today.month, day)
            n = len(by_day.get(d, []))
            ax.add_patch(Rectangle((c, r), 1, 1, fill=True,
                         facecolor="#cfe8c0" if n else "white", edgecolor="#cccccc"))
            label = f"{day} ●" if d == today else f"{day}"
            ax.text(c + 0.06, r + 0.28, label, fontsize=9,
                    fontweight="bold", va="center")
            if n:
                ax.text(c + 0.06, r + 0.7, f"{n} event(s)", fontsize=7, va="center")
    ax.set_xticks([c + 0.5 for c in range(7)])
    ax.set_xticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    ax.set_yticks([])
    ax.set_title(today.strftime("%B %Y"))
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


# ── orchestration ─────────────────────────────

def export_view(
    memory_root: Path, out_dir: Path, *,
    today: datetime.date, tz_label: str = "", png: bool = True,
) -> dict:
    """Render calendar_view.md (+ optional PNGs) into ``out_dir``.

    Returns a small summary dict. PNGs are skipped if matplotlib is unavailable.
    """
    entries = load_entries(memory_root)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    md = render_markdown(entries, today=today, tz_label=tz_label)
    (out_dir / "calendar_view.md").write_text(md, encoding="utf-8")
    result = {"entries": len(entries), "png": False}

    if not png:
        return result

    plt = _matplotlib()
    if plt is None:
        logger.info("[calendar-view] matplotlib not installed; wrote markdown only")
        return result

    try:
        by_day = _group_by_day(entries)
        week_start = today - datetime.timedelta(days=today.weekday())
        _render_day_png(
            plt, by_day.get(today, []), out_dir / "calendar_view_day.png", today,
        )
        _render_week_png(plt, by_day, week_start, out_dir / "calendar_view_week.png")
        _render_month_png(plt, by_day, today, out_dir / "calendar_view_month.png")
        result["png"] = True
    except Exception as e:  # pragma: no cover - rendering is best-effort
        logger.warning("[calendar-view] PNG render failed: {}", e)
    return result

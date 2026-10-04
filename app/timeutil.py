"""Local-time helpers: the app stores UTC and plans in the configured timezone."""

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def parse_hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def local_dt(day: date, hhmm: str | time, tz: ZoneInfo) -> datetime:
    """Aware UTC datetime for a local wall-clock time on a given day."""
    t = parse_hhmm(hhmm) if isinstance(hhmm, str) else hhmm
    return datetime.combine(day, t, tzinfo=tz).astimezone(timezone.utc)


def in_window(t: time, start: time, end: time) -> bool:
    """Is t within [start, end)? Windows may wrap midnight (e.g. 21:00-06:00)."""
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def in_quiet_hours(now: datetime, quiet: dict, tz: ZoneInfo) -> bool:
    local = now.astimezone(tz).time()
    return in_window(local, parse_hhmm(quiet["start"]), parse_hhmm(quiet["end"]))


def week_start(day: date) -> date:
    """Monday of the week containing day."""
    return day - timedelta(days=day.weekday())


def local_day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC [start, end) of a local calendar day (correct across DST changes)."""
    return local_dt(day, time(0), tz), local_dt(day + timedelta(days=1), time(0), tz)


_DURATION = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m(?:in)?)?$", re.IGNORECASE)


def parse_duration(text: str) -> timedelta | None:
    """Parse '30m', '1h', '1h30m', '2d', '45min'. Returns None if not a duration."""
    m = _DURATION.match(text.strip())
    if not m or not any(m.groups()):
        return None
    d, h, mins = (int(g) if g else 0 for g in m.groups())
    return timedelta(days=d, hours=h, minutes=mins)

"""Choosing what to suggest: routines, micro-moves, learning paths, hobbies.

Hobbies and learning paths are ranked by a score built from their schedule rule
(spec: "Scheduling rules"). Without a rule an item behaves as round-robin, weight 1.

- round_robin: score = days since last done (ties broken by weight)
- neglect: score = days since last done x weight
- weekday_slots: only eligible on its weekdays, then ranks above everything else
- sessions_per_week: behind-schedule items get a boost; items that met their
  target sink to the bottom but stay available as a fallback
- start/end dates: the rule applies only inside its window; outside it the item
  returns to the default (round-robin)
"""

import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Area,
    Hobby,
    HobbyElement,
    LearningPath,
    LogEntry,
    MicroMove,
    Outcome,
    PathCategory,
    PathStep,
    PickMethod,
    Routine,
    ScheduleRule,
)
from app.timeutil import local_dt, week_start

DONE = (Outcome.DONE, Outcome.PARTIAL)
NEVER_DONE_DAYS = 30
NEVER = datetime.min.replace(tzinfo=timezone.utc)  # sorts never-done items first


# --- rules and scoring --------------------------------------------------------


def active_rule(rules: list[ScheduleRule], today: date) -> ScheduleRule | None:
    """The rule in force today: a dated rule whose window covers today beats an undated one."""
    dated, undated = None, None
    for r in rules:
        if r.start_date is None and r.end_date is None:
            undated = undated or r
        elif (r.start_date is None or r.start_date <= today) and (
            r.end_date is None or today <= r.end_date
        ):
            dated = dated or r
    return dated or undated


def score(rule: ScheduleRule | None, days_since: int, done_this_week: int, today: date) -> float | None:
    """Higher is more urgent. None means not eligible today."""
    method = rule.method if rule else PickMethod.ROUND_ROBIN
    weight = rule.weight if rule else 1.0

    if method == PickMethod.WEEKDAY_SLOTS:
        if not rule.weekdays or today.weekday() not in rule.weekdays:
            return None
        s = 100.0 + weight
    elif method == PickMethod.NEGLECT:
        s = days_since * weight
    else:
        s = days_since + weight / 100

    spw = rule.sessions_per_week if rule else None
    if spw:
        if done_this_week >= spw:
            s -= 1000
        else:
            expected = spw * (today.weekday() + 1) / 7
            s += max(0.0, expected - done_this_week) * 10
    return s


def _last_done(s: Session, column, tz: ZoneInfo) -> dict[int, date]:
    rows = s.execute(
        select(column, func.max(LogEntry.created_at))
        .where(column.is_not(None), LogEntry.outcome.in_(DONE))
        .group_by(column)
    )
    return {item_id: ts.astimezone(tz).date() for item_id, ts in rows}


def _week_counts(s: Session, column, today: date, tz: ZoneInfo) -> dict[int, int]:
    since = local_dt(week_start(today), "00:00", tz)
    rows = s.execute(
        select(column, func.count())
        .where(column.is_not(None), LogEntry.outcome.in_(DONE), LogEntry.created_at >= since)
        .group_by(column)
    )
    return dict(rows.all())


def _rank(items, column, rule_attr: str, s: Session, today: date, tz: ZoneInfo):
    if not items:
        return []
    rules: dict[int, list[ScheduleRule]] = defaultdict(list)
    ids = [i.id for i in items]
    for r in s.scalars(select(ScheduleRule).where(getattr(ScheduleRule, rule_attr).in_(ids))):
        rules[getattr(r, rule_attr)].append(r)

    last = _last_done(s, column, tz)
    week = _week_counts(s, column, today, tz)

    scored = []
    for item in items:
        days_since = (today - last[item.id]).days if item.id in last else NEVER_DONE_DAYS
        sc = score(active_rule(rules[item.id], today), days_since, week.get(item.id, 0), today)
        if sc is not None:
            scored.append((sc, item))
    scored.sort(key=lambda x: (-x[0], x[1].id))
    return [item for _, item in scored]


# --- learning paths -----------------------------------------------------------


def rank_learning(s: Session, today: date, tz: ZoneInfo, ratio: dict) -> list[LearningPath]:
    """Ranked paths for today's learning session.

    The category (professional/hobby) furthest behind its weekly target share goes first;
    the other category follows as a fallback for the "Another" button.
    """
    paths = list(
        s.scalars(
            select(LearningPath).where(LearningPath.active, LearningPath.completed_at.is_(None))
        )
    )
    ranked = _rank(paths, LogEntry.path_id, "path_id", s, today, tz)

    since = local_dt(week_start(today), "00:00", tz)
    counts = dict(
        s.execute(
            select(LearningPath.category, func.count())
            .join(LogEntry, LogEntry.path_id == LearningPath.id)
            .where(LogEntry.outcome.in_(DONE), LogEntry.created_at >= since)
            .group_by(LearningPath.category)
        ).all()
    )
    total = sum(counts.values()) + 1

    def deficit(cat: PathCategory) -> float:
        return ratio.get(cat.value, 0) * total - counts.get(cat, 0)

    first = max(PathCategory, key=deficit)
    return [p for p in ranked if p.category == first] + [p for p in ranked if p.category != first]


def next_step(path: LearningPath) -> PathStep | None:
    return next((st for st in path.steps if st.done_at is None), None)


# --- hobbies ------------------------------------------------------------------


def rank_hobbies(s: Session, today: date, tz: ZoneInfo) -> list[Hobby]:
    hobbies = list(s.scalars(select(Hobby).where(Hobby.active)))
    return _rank(hobbies, LogEntry.hobby_id, "hobby_id", s, today, tz)


def pick_element(s: Session, hobby: Hobby) -> HobbyElement | None:
    """The unlocked element done least recently (never-done first), or None if it has none."""
    unlocked = [e for e in hobby.elements if e.unlocked]
    if not unlocked:
        return None
    last = dict(
        s.execute(
            select(LogEntry.hobby_element_id, func.max(LogEntry.created_at))
            .where(LogEntry.hobby_element_id.in_([e.id for e in unlocked]), LogEntry.outcome.in_(DONE))
            .group_by(LogEntry.hobby_element_id)
        ).all()
    )
    return min(unlocked, key=lambda e: (last.get(e.id, NEVER), e.id))


# --- movement -----------------------------------------------------------------


def pick_routine(s: Session) -> Routine | None:
    """Round-robin over active routines: the one done least recently."""
    routines = list(s.scalars(select(Routine).where(Routine.active).order_by(Routine.id)))
    if not routines:
        return None
    last = dict(
        s.execute(
            select(LogEntry.routine_id, func.max(LogEntry.created_at))
            .where(LogEntry.routine_id.is_not(None), LogEntry.outcome.in_(DONE))
            .group_by(LogEntry.routine_id)
        ).all()
    )
    return min(routines, key=lambda r: (last.get(r.id, NEVER), r.id))


def pick_micro_move(s: Session, exclude_id: int | None = None, rng=random) -> MicroMove | None:
    moves = list(s.scalars(select(MicroMove).where(MicroMove.active)))
    if len(moves) > 1:
        moves = [m for m in moves if m.id != exclude_id]
    return rng.choice(moves) if moves else None


# --- streaks ------------------------------------------------------------------


def streak(s: Session, area: Area, today: date, tz: ZoneInfo) -> int:
    """Consecutive days (ending today, or yesterday if nothing yet today) with a done/partial log."""
    since = local_dt(today - timedelta(days=366), "00:00", tz)
    days = {
        ts.astimezone(tz).date()
        for ts in s.scalars(
            select(LogEntry.created_at).where(
                LogEntry.area == area, LogEntry.outcome.in_(DONE), LogEntry.created_at >= since
            )
        )
    }
    day = today if today in days else today - timedelta(days=1)
    n = 0
    while day in days:
        n += 1
        day -= timedelta(days=1)
    return n

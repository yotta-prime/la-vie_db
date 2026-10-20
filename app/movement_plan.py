"""The Movement plan: which movement slots (morning, evening, night) get a prompt on which
dates, and how each planned slot went. Edited on the admin Movement plan page."""

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import MOVEMENT_SLOTS
from app.models import LogEntry, MovementPlan, Outcome, Prompt, PromptStatus
from app.timeutil import local_day_bounds, local_dt

# Cell states. done/partial/skipped come from your reply; missed = sent (or due) with no reply.
DONE, PARTIAL, SKIPPED, MISSED, AWAITING, PLANNED, OFF = (
    "done", "partial", "skipped", "missed", "awaiting", "planned", "off")


@dataclass
class Cell:
    ticked: bool
    editable: bool
    state: str


@dataclass
class Day:
    day: date
    cells: dict[str, Cell] = field(default_factory=dict)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def editable(day: date, slot: str, slots: dict, now: datetime, tz: ZoneInfo) -> bool:
    """A slot can be ticked or unticked until its time today; past slots are history."""
    return local_dt(day, slots[slot]["time"], tz) > now


def month(s: Session, year: int, month_: int, slots: dict, now: datetime, tz: ZoneInfo) -> list[Day]:
    first, last = month_bounds(year, month_)
    ticked = {(p.day, p.slot) for p in s.scalars(
        select(MovementPlan).where(MovementPlan.day >= first, MovementPlan.day <= last))}

    start, _ = local_day_bounds(first, tz)
    _, end = local_day_bounds(last, tz)
    prompts = s.scalars(select(Prompt).where(
        Prompt.kind == "routine", Prompt.scheduled_for >= start, Prompt.scheduled_for < end)).all()
    outcomes = dict(s.execute(select(LogEntry.prompt_id, LogEntry.outcome).where(
        LogEntry.prompt_id.in_([p.id for p in prompts]))).all()) if prompts else {}
    sent: dict[tuple[date, str], str] = {}
    for p in prompts:
        key = (p.scheduled_for.astimezone(tz).date(), (p.payload or {}).get("slot", "morning"))
        outcome = outcomes.get(p.id)
        if outcome == Outcome.DONE:
            state = DONE
        elif outcome == Outcome.PARTIAL:
            state = PARTIAL
        elif outcome == Outcome.SKIP:
            state = SKIPPED
        elif p.status == PromptStatus.SCHEDULED:
            state = PLANNED
        elif p.status == PromptStatus.SENT and key[0] == now.astimezone(tz).date():
            state = AWAITING
        else:
            state = MISSED
        sent[key] = state

    days = []
    d = first
    while d <= last:
        row = Day(d)
        for slot in MOVEMENT_SLOTS:
            is_ticked = (d, slot) in ticked
            can_edit = slot in slots and editable(d, slot, slots, now, tz)
            state = sent.get((d, slot))
            if state is None or (state == PLANNED and can_edit):
                if can_edit:
                    state = PLANNED if is_ticked else OFF
                else:  # past: ticked but never sent (e.g. paused, quiet hours) counts as missed
                    state = MISSED if is_ticked else OFF
            row.cells[slot] = Cell(is_ticked, can_edit, state)
        days.append(row)
        d += timedelta(days=1)
    return days


def save(s: Session, year: int, month_: int, ticks: set[tuple[date, str]], slots: dict,
         now: datetime, tz: ZoneInfo) -> int:
    """Apply the ticks for the month's still-editable slots. Returns how many changed."""
    first, last = month_bounds(year, month_)
    existing = {(p.day, p.slot): p for p in s.scalars(
        select(MovementPlan).where(MovementPlan.day >= first, MovementPlan.day <= last))}
    changed = 0
    d = first
    while d <= last:
        for slot in MOVEMENT_SLOTS:
            if slot not in slots or not editable(d, slot, slots, now, tz):
                continue
            want, have = (d, slot) in ticks, existing.get((d, slot))
            if want and have is None:
                s.add(MovementPlan(day=d, slot=slot))
                changed += 1
            elif not want and have is not None:
                s.delete(have)
                changed += 1
        d += timedelta(days=1)
    return changed

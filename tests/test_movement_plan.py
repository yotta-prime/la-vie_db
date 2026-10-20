"""Movement plan: ticked slots (morning, evening, night) per date drive the movement prompts."""

import random
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app import movement_plan as mp
from app.db import Database
from app.defaults import seed_movement_plan, seed_settings
from app.engine import Engine
from app.models import Area, LogEntry, MovementPlan, Outcome, Prompt, PromptStatus, Routine, Setting

TZ = ZoneInfo("Europe/London")
DAY = date(2026, 10, 21)  # a Wednesday


def at(day: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(day, time(h, m), tzinfo=TZ).astimezone(timezone.utc)


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_all()
    seed_settings(d)
    with d.session() as s:
        s.add(Routine(name="My stretch"))
        s.add(Routine(name="Hips 1", series="Hip Course", position=0))
        s.add(Routine(name="Hips 2", series="Hip Course", position=1))
    yield d
    d.engine.dispose()


@pytest.fixture
def engine(db):
    return Engine(db, TZ, random.Random(1))


def tick(db, *cells):
    with db.session() as s:
        s.add_all(MovementPlan(day=d, slot=slot) for d, slot in cells)


def routine_prompts(db):
    with db.session() as s:
        return [(p.scheduled_for, (p.payload or {}).get("slot"))
                for p in s.scalars(select(Prompt).where(Prompt.kind == "routine").order_by(Prompt.scheduled_for))]


def test_only_ticked_slots_get_prompts_at_slot_times(engine, db):
    tick(db, (DAY, "morning"), (DAY, "night"))
    engine.plan_day(DAY)
    assert routine_prompts(db) == [(at(DAY, "06:30"), "morning"), (at(DAY, "20:30"), "night")]
    engine.plan_day(date(2026, 10, 22))  # nothing ticked
    assert len(routine_prompts(db)) == 2


def test_slot_offers_its_course_and_names_the_slot(engine, db):
    with db.session() as s:
        slots = dict(s.get(Setting, "movement_slots").value)
        slots["evening"] = {"time": "18:00", "source": "series:Hip Course"}
        s.get(Setting, "movement_slots").value = slots
    tick(db, (DAY, "evening"))
    engine.plan_day(DAY)
    (pid, msg), = engine.due(at(DAY, "18:00"))
    assert msg.text.startswith("<b>Movement (evening): Hips 1</b>")


def test_replan_adds_a_newly_ticked_slot_but_keeps_the_sent_one(engine, db):
    tick(db, (DAY, "morning"))
    engine.plan_day(DAY)
    (pid, _), = engine.due(at(DAY, "06:30"))
    engine.mark_sent(pid, 1, at(DAY, "06:30"))
    tick(db, (DAY, "evening"))
    engine.plan_day(DAY, replan_after=at(DAY, "12:00"))
    assert [slot for _, slot in routine_prompts(db)] == ["morning", "evening"]


def test_month_shows_history_and_only_future_slots_are_editable(engine, db):
    tick(db, (date(2026, 10, 19), "morning"), (date(2026, 10, 19), "evening"), (DAY, "morning"))
    engine.plan_day(date(2026, 10, 19))
    with db.session() as s:
        morning = s.scalar(select(Prompt).where(Prompt.kind == "routine").order_by(Prompt.scheduled_for))
        morning.status = PromptStatus.ANSWERED
        s.add(LogEntry(area=Area.MOVEMENT, prompt_id=morning.id, outcome=Outcome.DONE))
        for p in s.scalars(select(Prompt).where(Prompt.kind == "routine", Prompt.id != morning.id)):
            p.status = PromptStatus.EXPIRED
    now = at(DAY, "12:00")
    with db.session() as s:
        slots = s.get(Setting, "movement_slots").value
        days = {d.day: d.cells for d in mp.month(s, 2026, 10, slots, now, TZ)}
    assert len(days) == 31
    assert days[date(2026, 10, 19)]["morning"].state == mp.DONE
    assert days[date(2026, 10, 19)]["evening"].state == mp.MISSED
    assert days[date(2026, 10, 19)]["night"].state == mp.OFF
    assert not days[DAY]["morning"].editable and days[DAY]["morning"].state == mp.MISSED  # 06:30 passed, never sent
    assert days[DAY]["evening"].editable and days[DAY]["evening"].state == mp.OFF
    assert days[date(2026, 10, 31)]["night"].editable


def test_save_changes_only_editable_slots(db):
    tick(db, (date(2026, 10, 1), "morning"), (DAY, "morning"))
    now = at(DAY, "12:00")
    with db.session() as s:
        slots = s.get(Setting, "movement_slots").value
        changed = mp.save(s, 2026, 10, {(DAY, "evening"), (date(2026, 10, 30), "night")}, slots, now, TZ)
    assert changed == 2
    with db.session() as s:
        cells = {(p.day, p.slot) for p in s.scalars(select(MovementPlan))}
    # Past ticks (1 Oct, this morning) are history and stay as they were.
    assert cells == {(date(2026, 10, 1), "morning"), (DAY, "morning"), (DAY, "evening"), (date(2026, 10, 30), "night")}


def test_first_start_ticks_mornings_to_month_end_once_at_the_old_time(db):
    with db.session() as s:
        s.get(Setting, "prompt_times").value = dict(s.get(Setting, "prompt_times").value, movement_routine="07:15")
    seed_movement_plan(db, DAY)
    with db.session() as s:
        days = sorted(p.day for p in s.scalars(select(MovementPlan)))
        assert days[0] == DAY and days[-1] == date(2026, 10, 31) and len(days) == 11
        assert s.get(Setting, "movement_slots").value["morning"]["time"] == "07:15"
        s.execute(MovementPlan.__table__.delete())
    seed_movement_plan(db, DAY)  # already done: an empty plan stays empty
    with db.session() as s:
        assert s.scalars(select(MovementPlan)).first() is None

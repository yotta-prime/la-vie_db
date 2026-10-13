"""Answers and weekly trends (admin pages), from stored prompts and log entries."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app import progress
from app.db import Database
from app.models import (
    Area,
    Category,
    Course,
    CourseStep,
    LogEntry,
    MicroMove,
    Outcome,
    Prompt,
    PromptStatus,
    Routine,
)

TZ = ZoneInfo("Europe/London")
MON = date(2026, 10, 5)  # a Monday


def at(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(hhmm), tzinfo=TZ).astimezone(timezone.utc)


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_all()
    yield d
    d.engine.dispose()


def prompt(s, kind, area, when, status=PromptStatus.ANSWERED, **payload):
    p = Prompt(kind=kind, area=area, scheduled_for=when, sent_at=when, status=status, payload=payload or None)
    s.add(p)
    s.flush()
    return p


@pytest.fixture
def data(db):
    """Week 1 (5-11 Oct) and part of week 2 (12-13 Oct)."""
    with db.session() as s:
        yoga = Routine(name="Yoga flow")
        mm = MicroMove(text="Shoulder rolls")
        course = Course(name="Agents", category=Category.PROFESSIONAL)
        s.add_all([yoga, mm, course])
        s.flush()
        lesson = CourseStep(course_id=course.id, position=0, title="Memory", done_at=at(MON, "19:00"))
        s.add(lesson)
        s.flush()

        for i, day in enumerate([MON, MON + timedelta(1), MON + timedelta(2)]):
            p = prompt(s, "routine", Area.MOVEMENT, at(day, "07:00"), routine_id=yoga.id)
            s.add(LogEntry(area=Area.MOVEMENT, prompt_id=p.id, routine_id=yoga.id, outcome=Outcome.DONE,
                           created_at=at(day, "07:20")))
        p = prompt(s, "intention", Area.FOCUS, at(MON, "08:30"))
        s.add(LogEntry(area=Area.FOCUS, prompt_id=p.id, note="Finish the deploy gate", created_at=at(MON, "08:40")))
        p = prompt(s, "reflection", Area.FOCUS, at(MON, "20:45"))
        s.add(LogEntry(area=Area.FOCUS, prompt_id=p.id, rating=4, created_at=at(MON, "20:50")))
        p = prompt(s, "learning", Area.LEARNING, at(MON, "18:00"), candidates=[course.id], idx=0, step_id=lesson.id)
        s.add(LogEntry(area=Area.LEARNING, prompt_id=p.id, course_id=course.id, course_step_id=lesson.id,
                       outcome=Outcome.DONE, created_at=at(MON, "19:00")))
        prompt(s, "micro_move", Area.MOVEMENT, at(MON, "11:00"), status=PromptStatus.EXPIRED, micro_move_id=mm.id)
        s.add(LogEntry(area=Area.MOVEMENT, outcome=Outcome.DONE, label="Walk", duration_min=30, created_at=at(MON, "12:30")))

        # Week 2 so far: one routine, one desk break.
        p = prompt(s, "routine", Area.MOVEMENT, at(MON + timedelta(7), "07:00"), routine_id=yoga.id)
        s.add(LogEntry(area=Area.MOVEMENT, prompt_id=p.id, routine_id=yoga.id, outcome=Outcome.PARTIAL,
                       created_at=at(MON + timedelta(7), "07:15")))
        p = prompt(s, "micro_move", Area.MOVEMENT, at(MON + timedelta(7), "10:00"), micro_move_id=mm.id)
        s.add(LogEntry(area=Area.MOVEMENT, prompt_id=p.id, label="Shoulder rolls", outcome=Outcome.DONE,
                       created_at=at(MON + timedelta(7), "10:01")))
    return db


def test_answers_show_question_item_reply_and_notes(data):
    with data.session() as s:
        items = progress.answers(s, at(MON, "00:00"), at(MON + timedelta(1), "00:00"), TZ)
    by_q = {a.question: a for a in items}
    assert by_q["What's your one most important thing today?"].note == "Finish the deploy gate"
    assert by_q["How was your focus today?"].answer == ["Focus 4/5"]
    assert by_q["Learning session"].item == "Agents · Memory" and by_q["Learning session"].answer == ["✓ Done"]
    assert by_q["Movement routine"].item == "Yoga flow"
    desk = by_q["Desk break"]
    assert not desk.replied and desk.item == "Shoulder rolls"
    walk = by_q["Logged with /log"]
    assert walk.via_log and walk.item == "Walk" and walk.answer == ["✓ Done", "30 min"]
    assert [a.when for a in items] == sorted((a.when for a in items), reverse=True)


def test_answers_filter_by_area(data):
    with data.session() as s:
        items = progress.answers(s, at(MON, "00:00"), at(MON + timedelta(14), "00:00"), TZ, Area.FOCUS)
    assert {a.area for a in items} == {"focus"} and len(items) == 2


def test_weekly_metrics(data):
    now = at(MON + timedelta(8), "12:00")  # Tuesday of week 2
    with data.session() as s:
        weeks = progress.weekly(s, now, TZ)
    assert [w.start for w in weeks] == [MON, MON + timedelta(7)] and weeks[-1].partial
    w1, w2 = weeks[0].values, weeks[1].values
    assert w1["routine_days"] == 3 and w1["desk_breaks"] == 0 and w1["activity_min"] == 30
    assert w1["intentions"] == 1 and w1["focus_avg"] == 4.0
    assert w1["learning_sessions"] == 1 and w1["lessons"] == 1 and w1["professional_pct"] == 100
    assert w1["answer_rate"] == round(6 / 7 * 100)  # the desk break expired unanswered
    assert w2["routine_days"] == 1 and w2["desk_breaks"] == 1 and w2["focus_avg"] is None
    assert w2["answer_rate"] == 100


def test_weekly_with_no_data_is_just_this_week(db):
    with db.session() as s:
        weeks = progress.weekly(s, at(MON, "12:00"), TZ)
    assert len(weeks) == 1 and weeks[0].values["answer_rate"] is None

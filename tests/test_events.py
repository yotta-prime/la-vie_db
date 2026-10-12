"""Live-event lessons: attendance questions, recording notices, watched, and lesson choice."""

import random
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app import selection as sel
from app.content import CONTENT_DIR, import_file
from app.db import Database
from app.defaults import seed_settings
from app.engine import Engine
from app.models import Attendance, Course, CourseStep, LogEntry, Prompt, PromptStatus

TZ = ZoneInfo("Europe/London")
MONDAY = date(2026, 10, 12)


def at(day: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(day, time(h, m), tzinfo=TZ).astimezone(timezone.utc)


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_all()
    seed_settings(d)
    import_file(d, CONTENT_DIR / "oreilly.yaml")
    yield d
    d.engine.dispose()


@pytest.fixture
def engine(db):
    return Engine(db, TZ, random.Random(1))


def step(db, key):
    with db.session() as s:
        return s.scalar(select(CourseStep).where(CourseStep.source_key == key))


def send(engine, now):
    out = engine.due(now)
    for pid, _ in out:
        engine.mark_sent(pid, 5000 + pid, now)
    return out


def test_import_sets_event_fields_and_no_noise(engine, db):
    tdd = step(db, "oreilly-2026-09-30-ai-assisted-tdd")
    assert tdd.event_date == date(2026, 9, 30) and tdd.presenters == "Venkat Subramaniam"
    assert tdd.attendance == Attendance.ATTENDED and tdd.event_state == "attended"
    assert step(db, "oreilly-2026-10-13-agent-memory").event_state == "pending"
    assert step(db, "oreilly-2026-10-06-linux-admin").event_state == "awaiting"

    # Links shipped with the file are known: only the past, unanswered registration is asked about.
    out = send(engine, at(MONDAY, "10:00"))
    assert len(out) == 1
    pid, msg = out[0]
    assert "Did you attend?" in msg.text and "Claude Certified Associate Exam Prep" in msg.text
    assert [b.data for b in msg.buttons[0]] == [f"p:{pid}:attended", f"p:{pid}:missed"]
    assert send(engine, at(MONDAY, "10:01")) == []  # asked once only


def test_upcoming_event_asked_the_day_after(engine, db):
    send(engine, at(MONDAY, "10:00"))
    assert not [m for _, m in send(engine, at(date(2026, 10, 13), "20:00")) if "Agent Memory" in m.text]
    asked = [m for _, m in send(engine, at(date(2026, 10, 14), "07:00")) if "Agent Memory" in m.text]
    assert len(asked) == 1


def test_missed_then_recording_then_watched(engine, db):
    (pid, _), = send(engine, at(MONDAY, "10:00"))
    res = engine.handle_action(pid, "missed", at(MONDAY, "10:05"))
    assert "Missed" in res.edit.text and res.edit.buttons == []  # no recording yet
    assert step(db, "oreilly-2026-10-08-claude-exam-prep").event_state == "awaiting"

    with db.session() as s:  # recording arrives (file update, email or admin)
        s.scalar(select(CourseStep).where(CourseStep.source_key == "oreilly-2026-10-08-claude-exam-prep")).url = \
            "https://example.org/recording"
    (pid2, msg), = send(engine, at(MONDAY, "12:00"))
    assert "Recording ready" in msg.text and "missed this one live" in msg.text
    assert msg.buttons[0][0].url == "https://example.org/recording"
    assert msg.buttons[0][1].data == f"p:{pid2}:watched"

    res = engine.handle_action(pid2, "watched", at(MONDAY, "13:00"))
    assert "Watched" in res.edit.text
    st = step(db, "oreilly-2026-10-08-claude-exam-prep")
    assert st.done_at is not None and st.event_state == "watched"
    with db.session() as s:
        assert s.scalar(select(LogEntry).where(LogEntry.course_step_id == st.id)).course_id == st.course_id
    assert engine.handle_action(pid2, "watched", at(MONDAY, "13:01")).toast == "Already marked watched."


def test_attended_with_recording_offers_it_straight_away(engine, db):
    with db.session() as s:
        s.scalar(select(CourseStep).where(CourseStep.source_key == "oreilly-2026-10-08-claude-exam-prep")).url = \
            "https://example.org/rec"
    (pid, _), = send(engine, at(MONDAY, "10:00"))  # attendance question only, not a second message
    res = engine.handle_action(pid, "attended", at(MONDAY, "10:05"))
    assert "Attended" in res.edit.text and res.edit.buttons[0][0].url == "https://example.org/rec"
    assert send(engine, at(MONDAY, "10:06")) == []


def test_questions_wait_out_quiet_hours(engine, db):
    assert send(engine, at(MONDAY, "23:00")) == []  # quiet: queued, not sent, not dropped
    with db.session() as s:
        p = s.scalar(select(Prompt).where(Prompt.kind == "event_attendance"))
        assert p.status == PromptStatus.SCHEDULED
    out = send(engine, at(date(2026, 10, 13), "06:00"))
    assert len(out) == 1 and "Did you attend?" in out[0][1].text


def test_missed_recordings_first_and_waiting_events_never_offered(db):
    with db.session() as s:
        course = s.scalar(select(Course).where(Course.source_key == "oreilly-llm-foundations"))
        assert sel.next_step(course).title.startswith("Cracking LLMs Open")  # newest attended, for review
        exam = next(st for st in course.steps if st.source_key == "oreilly-2026-10-08-claude-exam-prep")
        exam.attendance, exam.url = Attendance.MISSED, "https://example.org/rec"
        assert sel.next_step(course) is exam  # missed + recording jumps the queue

        linux = s.scalar(select(Course).where(Course.source_key == "oreilly-linux"))
        assert sel.only_waiting(linux)  # only lesson is awaiting its recording
        agents = s.scalar(select(Course).where(Course.source_key == "oreilly-building-agents"))
        assert all(st.title != "Expert Showcase: Agent Memory" for st in [sel.next_step(agents)])
        eligible = {c.source_key for c in sel.eligible_courses(s)}
        assert "oreilly-linux" not in eligible and "oreilly-llm-foundations" in eligible


def test_learning_prompt_explains_missed_vs_review(engine, db):
    with db.session() as s:
        for c in s.scalars(select(Course)):
            c.active = c.source_key == "oreilly-llm-foundations"
    engine.plan_day(MONDAY)
    msg = next(m for _, m in send(engine, at(MONDAY, "17:30")) if "Learning" in m.text)
    assert "Review: you attended on 09 Sep" in msg.text and ">recording</a>" in msg.text

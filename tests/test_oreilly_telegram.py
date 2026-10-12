"""/oreilly browsing in Telegram (views and changes, without Telegram itself)."""

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.bot import Bot
from app.config import Settings
from app.content import CONTENT_DIR, import_file
from app.db import Database
from app.engine import Engine
from app.models import Attendance, CourseStep, LogEntry

TZ = ZoneInfo("Europe/London")
NOW = datetime.combine(date(2026, 10, 12), time(12), tzinfo=TZ).astimezone(timezone.utc)


@pytest.fixture
def engine(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_all()
    import_file(db, CONTENT_DIR / "oreilly.yaml")
    yield Engine(db, TZ)
    db.engine.dispose()


def labels(msg):
    return [b.label for row in msg.buttons for b in row]


def data(msg):
    return [b.data for row in msg.buttons for b in row if b.data]


def test_home_counts_and_navigation(engine):
    _, msg = engine.oreilly("o:home", NOW)
    assert "🔁 To review (attended): 43" in msg.text
    assert "📅 Upcoming: 4" in msg.text and "⏳ Awaiting recordings: 5" in msg.text
    assert "🎬 To watch (missed live): 0" in msg.text
    assert {"o:watch", "o:review", "o:upcoming", "o:awaiting", "o:paths"} <= set(data(msg))

    _, up = engine.oreilly("o:upcoming", NOW)
    assert labels(up)[0].startswith("📅 8 Oct 2026 · Claude Certified")
    assert labels(up)[-2].startswith("📅 TBC · Architectural Katas 2026")

    _, review = engine.oreilly("o:review", NOW)
    assert "Showing the 12" in review.text and len(review.buttons) == 13  # 12 + back


def test_paths_course_and_lesson(engine):
    _, paths = engine.oreilly("o:paths", NOW)
    assert "📚 Agentic AI engineering" in labels(paths) and "📘 Individual courses" in labels(paths)
    course_cb = next(d for d in data(paths) if d.startswith("o:course:"))
    _, course = engine.oreilly(course_cb, NOW)
    assert "Agentic coding practice" in course.text and "Watched 0/9" in course.text

    step_cb = next(d for d in data(course) if d.startswith("o:step:"))
    _, lesson = engine.oreilly(step_cb, NOW)
    assert "AI-Assisted Test-Driven Development" in lesson.text and "Attended: queued for review" in lesson.text
    assert lesson.buttons[0][0].url.startswith("https://click.et.oreilly.com/")
    assert "Actually missed it" in labels(lesson)


def test_mark_missed_then_watched_from_telegram(engine):
    sid = _sid(engine, "oreilly-2026-09-30-ai-assisted-tdd")
    toast, lesson = engine.oreilly(f"o:set:{sid}:missed", NOW)
    assert "watch list" in toast and "Missed live" in lesson.text
    _, home = engine.oreilly("o:home", NOW)
    assert "🎬 To watch (missed live): 1" in home.text

    toast, lesson = engine.oreilly(f"o:set:{sid}:watched", NOW)
    assert toast == "Marked watched." and "Watched ✓" in lesson.text and "↺ Not watched" in labels(lesson)
    with engine.db.session() as s:
        st = s.get(CourseStep, sid)
        assert st.done_at is not None and st.attendance == Attendance.MISSED
        assert s.scalar(select(LogEntry).where(LogEntry.course_step_id == sid)) is not None


def test_answering_pending_in_telegram_stops_the_question(engine):
    sid = _sid(engine, "oreilly-2026-10-08-claude-exam-prep")
    engine.oreilly(f"o:set:{sid}:attended", NOW)
    assert not [m for _, m in engine.due(NOW) if "Did you attend" in m.text]


def test_course_completes_when_last_lesson_watched(engine):
    sid = _sid(engine, "oreilly-2026-10-06-linux-admin")
    with engine.db.session() as s:
        s.get(CourseStep, sid).url = "https://example.org/linux"
    toast, _ = engine.oreilly(f"o:set:{sid}:watched", NOW)
    assert "Course complete: Linux administration" in toast


def test_bot_registers_oreilly_and_link_buttons():
    bot = Bot(Settings(_env_file=None, telegram_bot_token="123456:ABC", telegram_owner_chat_id=42), engine=object())
    app = bot.build()
    names = {c for h in app.handlers[0] for c in getattr(h, "commands", [])}
    assert "oreilly" in names


def _sid(engine, key):
    with engine.db.session() as s:
        return s.scalar(select(CourseStep.id).where(CourseStep.source_key == key))

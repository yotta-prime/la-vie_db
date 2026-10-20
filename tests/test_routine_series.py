"""Movement lessons from an outside course (routines with a series), loaded from a private file."""

import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import yaml
from sqlalchemy import select

from app import selection as sel
from app.content import import_content, import_file
from app.db import Database
from app.engine import ROUTINE_TEXT_MAX, Engine
from app.models import Area, LogEntry, Outcome, Routine

TZ = ZoneInfo("Europe/London")
T0 = datetime(2026, 10, 1, 6, tzinfo=timezone.utc)

COURSE = {
    "routines": [
        {
            "key": "c1",
            "name": "Hip Course",
            "url": "https://courses.example/c1",
            "lessons": [
                {"key": "c1-l1", "title": "Find your hips", "section": "Lesson 1", "url": "https://courses.example/c1/1",
                 "section_url": "https://courses.example/c1/1", "intro": "Warm up first.", "outro": "Homework: walk.",
                 "moves": ["Lunge", "Bridge"]},
                {"key": "c1-l2", "title": "Posture", "url": "https://courses.example/c1/2"},
            ],
        },
        {
            "key": "c2",
            "name": "Fascia Course",
            "lessons": [{"key": "c2-l1", "title": "Floss", "intro": "x " * 4000}],
        },
    ]
}


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_all()
    yield d
    d.engine.dispose()


@pytest.fixture
def private_dir(tmp_path):
    p = tmp_path / "private"
    p.mkdir()
    (p / "dailyom.yaml").write_text(yaml.safe_dump(COURSE), encoding="utf-8")
    return p


def done(s, r: Routine, when: datetime) -> None:
    s.add(LogEntry(area=Area.MOVEMENT, routine_id=r.id, outcome=Outcome.DONE, created_at=when))


def test_import_is_add_only_and_keeps_order(db, private_dir):
    assert import_file(db, private_dir / "dailyom.yaml")["routines"] == 3
    assert import_file(db, private_dir / "dailyom.yaml")["routines"] == 0
    with db.session() as s:
        r = s.scalar(select(Routine).where(Routine.source_key == "c1-l1"))
        assert (r.series, r.position, r.section, r.intro, r.outro) == (
            "Hip Course", 0, "Lesson 1", "Warm up first.", "Homework: walk.")
        assert [st.text for st in r.steps] == ["Lunge", "Bridge"]
        assert s.scalar(select(Routine).where(Routine.source_key == "c1-l2")).position == 1


def test_reimport_refreshes_lesson_text_but_keeps_admin_edits(db, private_dir):
    import_file(db, private_dir / "dailyom.yaml")
    with db.session() as s:
        r = s.scalar(select(Routine).where(Routine.source_key == "c1-l1"))
        r.name, r.url = "My hips", "https://mine.example"  # edited in the admin page
    better = yaml.safe_load(yaml.safe_dump(COURSE))
    better["routines"][0]["lessons"][0]["outro"] = "After video 1:\nMore text.\nAfter video 2:\nHomework: walk."
    (private_dir / "dailyom.yaml").write_text(yaml.safe_dump(better), encoding="utf-8")
    assert import_file(db, private_dir / "dailyom.yaml")["texts"] == 1
    assert import_file(db, private_dir / "dailyom.yaml")["texts"] == 0
    with db.session() as s:
        r = s.scalar(select(Routine).where(Routine.source_key == "c1-l1"))
        assert r.outro.startswith("After video 1:") and r.intro == "Warm up first."
        assert (r.name, r.url, [st.text for st in r.steps]) == ("My hips", "https://mine.example", ["Lunge", "Bridge"])


def test_private_folder_is_imported_alongside_content(db, private_dir, tmp_path):
    import_content(db, tmp_path / "missing", private_dir)
    with db.session() as s:
        assert len(s.scalars(select(Routine)).all()) == 3


def test_own_routines_and_lessons_take_turns_lessons_in_order(db, private_dir):
    import_file(db, private_dir / "dailyom.yaml")
    with db.session() as s:
        s.add(Routine(name="My stretch"))
    picks = []
    with db.session() as s:
        for day in range(5):
            r = sel.pick_routine(s)
            picks.append(r.name)
            done(s, r, T0 + timedelta(days=day))
            s.flush()
    # Own routine wins the first tie; the course in progress is finished before the next starts.
    assert picks == ["My stretch", "Find your hips", "My stretch", "Posture", "My stretch"]
    with db.session() as s:
        assert sel.pick_routine(s).name == "Floss"


def test_lesson_message_has_links_moves_and_collapsed_text(db, private_dir):
    import_file(db, private_dir / "dailyom.yaml")
    engine = Engine(db, TZ, random.Random(1))
    with db.session() as s:
        r1 = s.scalar(select(Routine).where(Routine.source_key == "c1-l1"))
        text = engine._routine_text(r1)
        assert 'href="https://courses.example/c1/1">video</a>' in text
        assert 'href="https://courses.example/c1">course</a>' in text
        assert ">section</a>" in text
        assert "1. Lunge\n2. Bridge" in text
        assert "<blockquote expandable><b>Before the video</b>\nWarm up first.</blockquote>" in text
        assert "<b>After the video</b>\nHomework: walk." in text

        long = engine._routine_text(s.scalar(select(Routine).where(Routine.source_key == "c2-l1")))
        assert len(long) <= ROUTINE_TEXT_MAX
        assert "(more in the lesson)" in long

        # A short after-video block is kept whole; the long before-video block gets the rest of the room.
        r = Routine(name="Mixed", series="Hip Course", intro="word " * 900, outro="Homework: short.")
        text = engine._routine_text(r)
        assert "Homework: short.</blockquote>" in text
        assert ROUTINE_TEXT_MAX - 300 < len(text) <= ROUTINE_TEXT_MAX

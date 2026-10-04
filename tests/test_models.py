import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import Database
from app.defaults import DEFAULT_SETTINGS, seed_settings
from app.migrations import LATEST
from app.models import (
    Category,
    Course,
    CourseKind,
    Hobby,
    HobbyProject,
    LearningPath,
    LogEntry,
    Routine,
    ScheduleRule,
    Setting,
    utcnow,
)

V0_SCHEMA = Path(__file__).parent / "fixtures" / "schema_v0.sql"


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_all()
    yield d
    d.engine.dispose()


def test_seed_settings_is_idempotent(db):
    seed_settings(db)
    with db.session() as s:
        s.get(Setting, "quiet_hours").value = {"start": "22:00", "end": "07:00"}
    seed_settings(db)
    with db.session() as s:
        assert s.query(Setting).count() == len(DEFAULT_SETTINGS)
        assert s.get(Setting, "quiet_hours").value["start"] == "22:00"


def test_project_unlocks_after_course_and_path(db):
    with db.session() as s:
        theory = Course(name="Day Skipper theory", category=Category.HOBBY)
        a = Course(name="Part A", category=Category.HOBBY, position=0)
        b = Course(name="Part B", category=Category.HOBBY, position=1)
        path = LearningPath(name="Yachtmaster", category=Category.HOBBY, courses=[a, b])
        sailing = Hobby(name="Sailing")
        solo = HobbyProject(name="Solo outing", hobby=sailing, requires_course=theory)
        offshore = HobbyProject(name="Offshore passage", hobby=sailing, requires_path=path)
        free = HobbyProject(name="Crewing", hobby=sailing)
        s.add_all([theory, path, sailing, solo, offshore, free])
        s.flush()
        assert not solo.unlocked and not offshore.unlocked and free.unlocked

        theory.completed_at = utcnow()
        a.completed_at = utcnow()
        assert solo.unlocked and not offshore.unlocked
        b.completed_at = utcnow()
        assert offshore.unlocked


def test_schedule_rule_must_target_exactly_one_item(db):
    with pytest.raises(IntegrityError):
        with db.session() as s:
            s.add(ScheduleRule())

    with pytest.raises(IntegrityError):
        with db.session() as s:
            h = Hobby(name="Chess")
            c = Course(name="Openings", category=Category.HOBBY, kind=CourseKind.SRS)
            s.add_all([h, c])
            s.flush()
            s.add(ScheduleRule(hobby_id=h.id, course_id=c.id))


def test_fresh_db_is_stamped_latest(tmp_path, db):
    path = db.engine.url.database
    (version,) = sqlite3.connect(path).execute("SELECT version FROM schema_version").fetchone()
    assert version == LATEST


def test_migrates_v0_database_keeping_logs(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(V0_SCHEMA.read_text())
    con.execute("INSERT INTO routine (id, name, duration_min, active) VALUES (1, 'Morning mobility', 10, 1)")
    con.execute(
        "INSERT INTO log_entry (id, created_at, area, routine_id, outcome, duration_min) "
        "VALUES (7, '2026-10-05 05:45:00', 'movement', 1, 'done', 10)"
    )
    con.commit()
    con.close()

    d = Database(f"sqlite:///{path}")
    d.create_all()
    with d.session() as s:
        entry = s.get(LogEntry, 7)
        assert entry.routine_id == 1 and entry.duration_min == 10 and entry.course_id is None
        r = s.get(Routine, 1)
        r.url = "https://www.youtube.com/watch?v=example"
        s.add(Course(name="New", category=Category.PROFESSIONAL))
    d.engine.dispose()

    assert (tmp_path / "old.db.pre-v1.bak").exists()
    (version,) = sqlite3.connect(path).execute("SELECT version FROM schema_version").fetchone()
    assert version == LATEST

    # Running again is a no-op.
    d = Database(f"sqlite:///{path}")
    d.create_all()
    d.engine.dispose()

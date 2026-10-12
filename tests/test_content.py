import sqlite3

import pytest
import yaml
from sqlalchemy import select

from app.content import CONTENT_DIR, import_file
from app.db import Database
from app.migrations import LATEST
from app.models import Course, CourseStep, LearningPath, utcnow

OREILLY = CONTENT_DIR / "oreilly.yaml"


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_all()
    yield d
    d.engine.dispose()


def test_oreilly_file_matches_approved_allocation(db):
    assert import_file(db, OREILLY) == {"paths": 3, "courses": 10, "lessons": 52, "links": 0}
    with db.session() as s:
        paths = {p.name: [c.name for c in p.courses] for p in s.scalars(select(LearningPath))}
        assert paths == {
            "Agentic AI engineering": ["Agentic coding practice", "Building & orchestrating agents",
                                       "LLM & prompting foundations"],
            "Software architecture": ["Architecture in the AI era"],
            "Engineering leadership & organisation": ["Engineering leadership", "AI & the organisation",
                                                      "Project delivery tools"],
        }
        standalone = s.scalars(select(Course.name).where(Course.path_id.is_(None))).all()
        assert sorted(standalone) == ["AI & cybersecurity", "Data", "Linux administration"]
        assert all(not p.sequential for p in s.scalars(select(LearningPath)))
        assert all(c.category.value == "professional" for c in s.scalars(select(Course)))
        assert s.scalar(select(CourseStep).where(CourseStep.done_at.is_not(None))) is None  # queued for review

        agents = s.scalar(select(Course).where(Course.name == "Building & orchestrating agents"))
        assert agents.steps[0].title.startswith("Give Your Agents Superpowers")  # newest first
        assert agents.steps[-1].title == "Expert Showcase: Agent Memory"  # upcoming last


def test_recording_links(db):
    import_file(db, OREILLY)
    with db.session() as s:
        steps = s.scalars(select(CourseStep)).all()
        linked = [st for st in steps if st.url]
        assert len(linked) == 43  # every attended event with a recording; pending/upcoming have none
        assert all(st.url.startswith(("https://click.et.oreilly.com/", "https://learning.oreilly.com/"))
                   for st in linked)
        unlinked = {st.title for st in steps if not st.url}
        assert "Expert Showcase: Agent Memory" in unlinked and "Linux Administration" in unlinked
        tdd = s.scalar(select(CourseStep).where(CourseStep.source_key == "oreilly-2026-09-30-ai-assisted-tdd"))
        assert tdd.url.startswith("https://click.et.oreilly.com/?qs=ABB7InYiOjEsImQiOjUwMTZ9")


def test_links_filled_into_existing_lessons_but_never_overwritten(db, tmp_path):
    """The NAS imported the file before links were added: re-import must fill them in."""
    import_file(db, OREILLY)
    with db.session() as s:
        for st in s.scalars(select(CourseStep)):
            st.url = None
        s.scalar(select(CourseStep).where(CourseStep.source_key == "oreilly-2026-09-17-vibe-vs-spec")).url = \
            "https://example.org/mine"

    counts = import_file(db, OREILLY)
    assert counts == {"paths": 0, "courses": 0, "lessons": 0, "links": 42}
    with db.session() as s:
        mine = s.scalar(select(CourseStep).where(CourseStep.source_key == "oreilly-2026-09-17-vibe-vs-spec"))
        assert mine.url == "https://example.org/mine"
        assert len([st for st in s.scalars(select(CourseStep)) if st.url]) == 43


def test_keys_are_unique():
    data = yaml.safe_load(OREILLY.read_text(encoding="utf-8"))
    courses = [c for p in data["paths"] for c in p["courses"]] + data["courses"]
    keys = [p["key"] for p in data["paths"]] + [c["key"] for c in courses]
    keys += [lesson["key"] for c in courses for lesson in c["lessons"]]
    assert len(keys) == len(set(keys))


def test_reimport_adds_only_new_and_keeps_admin_edits(db, tmp_path):
    import_file(db, OREILLY)
    with db.session() as s:
        c = s.scalar(select(Course).where(Course.source_key == "oreilly-data"))
        c.name = "Data (renamed in admin)"
        c.steps[0].done_at = utcnow()

    assert import_file(db, OREILLY) == {"paths": 0, "courses": 0, "lessons": 0, "links": 0}

    extra = tmp_path / "extra.yaml"
    extra.write_text(yaml.safe_dump({"courses": [{
        "key": "oreilly-data", "name": "Data", "category": "professional",
        "lessons": [{"key": "oreilly-2026-10-27-data", "title": "What's Happening in Data (27 Oct)"}],
    }]}), encoding="utf-8")
    assert import_file(db, extra) == {"paths": 0, "courses": 0, "lessons": 1, "links": 0}

    with db.session() as s:
        c = s.scalar(select(Course).where(Course.source_key == "oreilly-data"))
        assert c.name == "Data (renamed in admin)" and c.steps[0].done_at is not None
        assert c.steps[-1].title == "What's Happening in Data (27 Oct)" and c.steps[-1].position == 3


def test_migrates_v1_database_to_latest(tmp_path):
    """The NAS is on schema v1: no source_key columns yet."""
    path = tmp_path / "v1.db"
    d = Database(f"sqlite:///{path}")
    d.create_all()
    d.engine.dispose()
    con = sqlite3.connect(path)
    for table in ("learning_path", "course", "course_step"):
        con.execute(f"DROP INDEX ix_{table}_source_key")
        con.execute(f"ALTER TABLE {table} DROP COLUMN source_key")
    for col in ("event_date", "presenters", "attendance", "attendance_asked_at", "recording_notified_at"):
        con.execute(f"ALTER TABLE course_step DROP COLUMN {col}")
    con.execute("UPDATE schema_version SET version = 1")
    con.execute("INSERT INTO course (id, position, name, category, kind, active) "
                "VALUES (1, 0, 'Mine', 'hobby', 'steps', 1)")
    con.commit()
    con.close()

    d = Database(f"sqlite:///{path}")
    d.create_all()
    assert import_file(d, OREILLY)["lessons"] == 52
    with d.session() as s:
        assert s.get(Course, 1).name == "Mine" and s.get(Course, 1).source_key is None
    d.engine.dispose()
    (version,) = sqlite3.connect(path).execute("SELECT version FROM schema_version").fetchone()
    assert version == LATEST == 3
    assert (tmp_path / "v1.db.pre-v3.bak").exists()

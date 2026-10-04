import pytest
from sqlalchemy.exc import IntegrityError

from app.db import Database
from app.defaults import DEFAULT_SETTINGS, seed_settings
from app.models import (
    Hobby,
    HobbyElement,
    LearningPath,
    PathCategory,
    PathKind,
    ScheduleRule,
    Setting,
    utcnow,
)


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


def test_hobby_element_unlocks_when_path_completed(db):
    with db.session() as s:
        theory = LearningPath(name="Day Skipper theory", category=PathCategory.HOBBY, kind=PathKind.STEPS)
        sailing = Hobby(name="Sailing")
        solo = HobbyElement(name="Solo outing", hobby=sailing, requires_path=theory)
        free = HobbyElement(name="Crewing", hobby=sailing)
        s.add_all([theory, sailing, solo, free])
        s.flush()
        assert not solo.unlocked
        assert free.unlocked

        theory.completed_at = utcnow()
        assert solo.unlocked


def test_schedule_rule_must_target_exactly_one_item(db):
    with pytest.raises(IntegrityError):
        with db.session() as s:
            s.add(ScheduleRule())

    with pytest.raises(IntegrityError):
        with db.session() as s:
            h = Hobby(name="Chess")
            p = LearningPath(name="Openings", category=PathCategory.HOBBY, kind=PathKind.SRS)
            s.add_all([h, p])
            s.flush()
            s.add(ScheduleRule(hobby_id=h.id, path_id=p.id))

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.admin import routes
from app.config import get_settings
from app.models import (
    Course,
    CourseStep,
    Hobby,
    HobbyProject,
    LearningPath,
    MicroMove,
    PickMethod,
    Routine,
    ScheduleRule,
    Setting,
)

PASSWORD = "correct horse battery staple"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)
    monkeypatch.chdir(tmp_path)  # ignore any local .env

    async def no_sleep(_):
        return None

    monkeypatch.setattr(routes.asyncio, "sleep", no_sleep)
    get_settings.cache_clear()

    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def login(client):
    r = client.post("/admin/login", data={"password": PASSWORD})
    assert r.status_code == 200 and "Today" in r.text
    return client


def db(client):
    return client.app.state.db


def id_from(url: str) -> int:
    return int(re.search(r"/(\d+)", str(url)).group(1))


def test_requires_login(client):
    r = client.get("/admin/learning")
    assert r.url.path == "/admin/login"
    r = client.post("/admin/login", data={"password": "nope"})
    assert "Wrong password" in r.text
    assert client.get("/admin").url.path == "/admin/login"


def test_locked_without_password(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    get_settings.cache_clear()
    assert "locked" in client.get("/admin/login").text
    client.post("/admin/login", data={"password": ""})
    assert client.cookies.get(routes.COOKIE) is None
    assert client.get("/admin").url.path == "/admin/login"


def test_all_pages_render(client):
    login(client)
    for page in ["/admin", "/admin/movement", "/admin/learning", "/admin/hobbies", "/admin/settings", "/"]:
        r = client.get(page)
        assert r.status_code == 200, page


def test_learning_paths_courses_lessons(client):
    login(client)
    r = client.post("/admin/paths", data={"name": "Cloud architect", "category": "professional"})
    pid = id_from(r.url)
    r = client.post("/admin/courses", data={"name": "Networking", "kind": "steps", "path_id": pid})
    cid = id_from(r.url)
    client.post("/admin/courses", data={"name": "Security", "kind": "time", "path_id": pid})
    client.post(f"/admin/courses/{cid}/steps", data={"title": "Subnets\nRouting\n\nDNS"})
    client.post("/admin/courses", data={"name": "Spanish", "category": "hobby", "kind": "srs"})

    with db(client).session() as s:
        path = s.get(LearningPath, pid)
        assert [c.name for c in path.courses] == ["Networking", "Security"]
        assert [st.title for st in path.courses[0].steps] == ["Subnets", "Routing", "DNS"]
        spanish = s.scalar(select(Course).where(Course.name == "Spanish"))
        assert spanish.path_id is None and spanish.category.value == "hobby"
        step_id = path.courses[0].steps[2].id
        security_id = path.courses[1].id

    client.post(f"/admin/course-steps/{step_id}", data={"action": "up"})
    client.post(f"/admin/courses/{security_id}/action", data={"action": "up"})
    client.post(f"/admin/courses/{cid}", data={
        "name": "Networking basics", "category": "professional", "kind": "steps",
        "url": "https://example.org/net", "path_id": str(pid), "active": "on",
    })
    with db(client).session() as s:
        path = s.get(LearningPath, pid)
        assert [c.name for c in path.courses] == ["Security", "Networking basics"]
        assert [st.title for st in path.courses[1].steps] == ["Subnets", "DNS", "Routing"]
        assert path.courses[1].url == "https://example.org/net"

    page = client.get("/admin/learning").text
    assert "Cloud architect" in page and "Individual courses" in page and "Spanish" in page

    r = client.post(f"/admin/courses/{cid}/action", data={"action": "complete"})
    assert "Course complete" in r.text


def test_hobby_projects_dependencies_and_schedule(client):
    login(client)
    pid = id_from(client.post("/admin/paths", data={"name": "Yachtmaster", "category": "hobby"}).url)
    cid = id_from(client.post("/admin/courses", data={"name": "Theory", "kind": "steps", "path_id": pid}).url)
    hid = id_from(client.post("/admin/hobbies", data={"name": "Sailing"}).url)

    client.post(f"/admin/hobbies/{hid}/projects", data={"name": "Solo outing", "requires": f"course:{cid}"})
    client.post(f"/admin/hobbies/{hid}/projects", data={"name": "Offshore", "requires": f"path:{pid}", "url": "https://example.org"})
    client.post(f"/admin/hobbies/{hid}/projects", data={"name": "Crewing"})
    client.post(f"/admin/rules/hobby/{hid}", data={
        "method": "weekday_slots", "weekdays": ["5", "6"], "sessions_per_week": "2",
        "start_date": "2026-10-01", "end_date": "2026-12-31", "weight": "2",
    })

    page = client.get(f"/admin/hobbies/{hid}").text
    assert page.count(">locked<") == 2

    with db(client).session() as s:
        h = s.get(Hobby, hid)
        solo, offshore, crewing = h.projects
        assert solo.requires_course_id == cid and offshore.requires_path_id == pid
        assert crewing.unlocked and not solo.unlocked
        rule = s.scalar(select(ScheduleRule).where(ScheduleRule.hobby_id == hid))
        assert rule.method == PickMethod.WEEKDAY_SLOTS and rule.weekdays == [5, 6] and rule.weight == 2
        crewing_id = crewing.id

    client.post(f"/admin/projects/{crewing_id}", data={"action": "toggle"})
    r = client.post(f"/admin/rules/hobby/{hid}", data={"action": "reset"})
    assert "reset" in r.text
    with db(client).session() as s:
        assert s.get(HobbyProject, crewing_id).done_at is not None
        assert s.scalar(select(ScheduleRule).where(ScheduleRule.hobby_id == hid)) is None


def test_routines_with_links_and_micro_moves(client):
    login(client)
    rid = id_from(client.post("/admin/routines", data={"name": "Yoga"}).url)
    client.post(f"/admin/routines/{rid}", data={
        "name": "Yoga flow", "duration_min": "20", "url": "https://www.dailyom.com/x", "active": "on",
    })
    client.post(f"/admin/routines/{rid}/steps", data={"text": "Sun salutation", "url": "https://youtu.be/abc"})
    client.post("/admin/micro-moves", data={"text": "Shoulder rolls"})
    with db(client).session() as s:
        r = s.get(Routine, rid)
        assert r.name == "Yoga flow" and r.url == "https://www.dailyom.com/x"
        assert r.steps[0].url == "https://youtu.be/abc"
        assert s.scalar(select(MicroMove).where(MicroMove.text == "Shoulder rolls"))
    assert "youtu.be/abc" in client.get(f"/admin/routines/{rid}").text


def test_settings_save_and_replan(client):
    login(client)
    form = {
        "movement_routine": "07:00", "focus_intention": "08:30", "learning_session": "18:00",
        "hobby_session": "19:30", "focus_reflection": "20:45", "work_days": ["0", "1", "2", "3"],
        "work_start": "09:30", "work_end": "17:30", "quiet_start": "22:00", "quiet_end": "06:30",
        "micro_move_interval_min": "90", "distraction_checks_per_day": "1",
        "focus_block_default_min": "50", "professional_pct": "75", "backup_time": "03:30", "replan": "on",
    }
    r = client.post("/admin/settings", data=form)
    assert "re-planned" in r.text
    with db(client).session() as s:
        assert s.get(Setting, "prompt_times").value["movement_routine"] == "07:00"
        assert s.get(Setting, "work_days").value == [0, 1, 2, 3]
        assert s.get(Setting, "learning_ratio").value == {"professional": 0.75, "hobby": 0.25}

    bad = dict(form, work_start="9am")
    assert "HH:MM" in client.post("/admin/settings", data=bad).text

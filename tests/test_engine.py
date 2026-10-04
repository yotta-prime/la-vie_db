import random
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.db import Database
from app.defaults import seed_content, seed_settings
from app.engine import Engine
from app.models import (
    Area,
    Category,
    Course,
    CourseKind,
    CourseStep,
    Hobby,
    HobbyProject,
    LearningPath,
    LogEntry,
    PickMethod,
    Prompt,
    PromptStatus,
    Routine,
    RoutineStep,
    ScheduleRule,
    Setting,
)
from app.timeutil import in_window, parse_duration

TZ = ZoneInfo("Europe/London")
MONDAY = date(2026, 10, 5)
SATURDAY = date(2026, 10, 10)


def at(day: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(day, time(h, m), tzinfo=TZ).astimezone(timezone.utc)


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_all()
    seed_settings(d)
    yield d
    d.engine.dispose()


@pytest.fixture
def engine(db):
    return Engine(db, TZ, random.Random(1))


def prompts(db, kind=None):
    with db.session() as s:
        q = select(Prompt).order_by(Prompt.scheduled_for)
        if kind:
            q = q.where(Prompt.kind == kind)
        return s.scalars(q).all()


def send_due(engine, now):
    """Simulate the bot: render due prompts and mark them sent with fake message ids."""
    out = engine.due(now)
    for i, (pid, _) in enumerate(out):
        engine.mark_sent(pid, 1000 + pid, now)
    return out


# --- helpers ------------------------------------------------------------------


def test_time_helpers():
    assert parse_duration("1h30m") == timedelta(hours=1, minutes=30)
    assert parse_duration("2d") == timedelta(days=2)
    assert parse_duration("45min") == timedelta(minutes=45)
    assert parse_duration("guitar") is None
    assert in_window(time(23), time(21), time(6))
    assert in_window(time(5, 59), time(21), time(6))
    assert not in_window(time(6), time(21), time(6))


# --- planning -----------------------------------------------------------------


def test_plan_weekday(engine, db):
    assert engine.plan_day(MONDAY) == 14
    assert engine.plan_day(MONDAY) == 0  # idempotent

    kinds = [p.kind for p in prompts(db)]
    assert kinds.count("micro_move") == 7  # 10:00..16:00
    assert kinds.count("distraction") == 2
    routine = prompts(db, "routine")[0]
    assert routine.scheduled_for == at(MONDAY, "06:30")  # 05:30 UTC in BST


def test_plan_weekend_has_no_work_prompts(engine, db):
    assert engine.plan_day(SATURDAY) == 3
    assert {p.kind for p in prompts(db)} == {"routine", "learning", "hobby"}


def test_plan_skips_quiet_hours(engine, db):
    with db.session() as s:
        times = dict(s.get(Setting, "prompt_times").value)
        times["focus_reflection"] = "21:30"
        s.get(Setting, "prompt_times").value = times
    engine.plan_day(MONDAY)
    assert prompts(db, "reflection") == []


def test_plan_across_dst_change(engine, db):
    # Clocks go back on Sunday 25 Oct 2026; 06:30 local is then 06:30 UTC.
    engine.plan_day(date(2026, 10, 26))
    assert prompts(db, "routine")[0].scheduled_for == datetime(2026, 10, 26, 6, 30, tzinfo=timezone.utc)


# --- movement -----------------------------------------------------------------


def test_routine_prompt_done_logs_and_streaks(engine, db):
    seed_content(db)
    engine.plan_day(MONDAY)
    out = send_due(engine, at(MONDAY, "06:31"))
    assert len(out) == 1
    pid, msg = out[0]
    assert "Morning mobility" in msg.text and "1. Cat-cow" in msg.text

    res = engine.handle_action(pid, "done", at(MONDAY, "06:45"))
    assert "Done" in res.edit.text and "streak 1 day" in res.edit.text
    assert engine.handle_action(pid, "done", at(MONDAY, "06:46")).toast == "Already logged."

    with db.session() as s:
        entry = s.scalar(select(LogEntry))
        assert entry.routine_id is not None and entry.area == Area.MOVEMENT


def test_missed_prompts_expire(engine, db):
    seed_content(db)
    engine.plan_day(MONDAY)
    assert engine.due(at(MONDAY, "07:10")) == []
    assert prompts(db, "routine")[0].status == PromptStatus.EXPIRED


def test_pause_and_resume(engine, db):
    seed_content(db)
    engine.plan_day(MONDAY)
    assert "Paused movement" in engine.pause(["movement", "2d"], at(MONDAY, "06:00"))
    assert engine.due(at(MONDAY, "06:31")) == []
    assert prompts(db, "routine")[0].status == PromptStatus.SKIPPED
    assert engine.resume(["movement"], at(MONDAY, "06:40")) == "Resumed movement."


# --- focus --------------------------------------------------------------------


def test_intention_reply_feeds_reflection(engine, db):
    engine.plan_day(MONDAY)
    (pid, msg), = send_due(engine, at(MONDAY, "08:00"))
    assert msg.force_reply
    assert engine.handle_text("Finish the report", 1000 + pid, at(MONDAY, "08:05")) == "Noted."

    _, reflection = next(
        (p, m) for p, m in engine.due(at(MONDAY, "20:30")) if "End of day" in m.text
    )
    assert "Finish the report" in reflection.text


def test_unaddressed_text_attaches_to_recent_question(engine, db):
    engine.plan_day(MONDAY)
    send_due(engine, at(MONDAY, "08:00"))
    assert engine.handle_text("Emails", None, at(MONDAY, "09:00")) == "Noted."
    assert engine.handle_text("hello?", None, at(MONDAY, "13:00")).startswith("Not sure")


def test_reflection_rating_then_note(engine, db):
    engine.plan_day(MONDAY)
    pid = prompts(db, "reflection")[0].id
    send_due(engine, at(MONDAY, "20:30"))
    res = engine.handle_action(pid, "r4", at(MONDAY, "20:31"))
    assert "Focus 4/5" in res.edit.text
    engine.handle_text("Good morning, slow afternoon", 1000 + pid, at(MONDAY, "20:32"))
    with db.session() as s:
        e = s.scalar(select(LogEntry).where(LogEntry.prompt_id == pid))
        assert e.rating == 4 and "slow afternoon" in e.note


def test_focus_block_ignores_quiet_hours(engine, db):
    now = at(MONDAY, "20:50")
    assert "ends 21:15" in engine.start_focus(["25"], now)
    out = send_due(engine, at(MONDAY, "21:15"))
    assert len(out) == 1 and "25 min" in out[0][1].text
    engine.handle_action(out[0][0], "done", at(MONDAY, "21:16"))
    with db.session() as s:
        assert s.scalar(select(LogEntry.duration_min)) == 25


# --- learning -----------------------------------------------------------------


def learning_prompt(engine, day=MONDAY):
    engine.plan_day(day)
    return next((p, m) for p, m in send_due(engine, at(day, "17:30")) if "Learning" in m.text)


def test_learning_prefers_professional_and_completion_unlocks(engine, db):
    with db.session() as s:
        pro = Course(name="Kubernetes", category=Category.PROFESSIONAL, kind=CourseKind.TIME, daily_goal_min=30)
        theory = Course(
            name="Day Skipper theory", category=Category.HOBBY, kind=CourseKind.STEPS,
            steps=[CourseStep(position=0, title="Final exam", url="https://example.org/exam")],
        )
        sailing = Hobby(name="Sailing", projects=[HobbyProject(name="Solo outing", requires_course=theory)])
        s.add_all([pro, theory, sailing])

    pid, msg = learning_prompt(engine)
    assert "Kubernetes" in msg.text and "30 min" in msg.text

    res = engine.handle_action(pid, "another", at(MONDAY, "17:31"))
    assert "Day Skipper" in res.edit.text and "Final exam" in res.edit.text
    assert 'href="https://example.org/exam"' in res.edit.text
    assert engine.handle_action(pid, "another", at(MONDAY, "17:31")).toast == "No other suggestions today."

    res = engine.handle_action(pid, "done", at(MONDAY, "18:30"))
    assert "Course complete" in res.extra[0] and "Unlocked: Sailing · Solo outing" in res.extra[0]


def test_sequential_path_offers_first_unfinished_course(engine, db):
    with db.session() as s:
        s.add(LearningPath(
            name="Cloud architect", category=Category.PROFESSIONAL,
            courses=[
                Course(name="Networking", category=Category.PROFESSIONAL, position=0,
                       steps=[CourseStep(position=0, title="Subnets")]),
                Course(name="Security", category=Category.PROFESSIONAL, position=1),
            ],
        ))
    pid, msg = learning_prompt(engine)
    assert "Networking" in msg.text and "Path: Cloud architect" in msg.text
    assert engine.handle_action(pid, "another", at(MONDAY, "17:31")).toast == "No other suggestions today."

    res = engine.handle_action(pid, "done", at(MONDAY, "18:00"))
    assert "Course complete: <b>Networking</b>" in res.extra[0] and "Path complete" not in res.extra[0]

    _, msg = learning_prompt(engine, MONDAY + timedelta(days=1))
    assert "Security" in msg.text


def test_project_unlocks_when_whole_path_completes(engine, db):
    with db.session() as s:
        path = LearningPath(
            name="Yachtmaster", category=Category.HOBBY,
            courses=[Course(name="Theory", category=Category.HOBBY, steps=[CourseStep(position=0, title="Exam")])],
        )
        s.add_all([path, Hobby(name="Sailing", projects=[HobbyProject(name="Offshore", requires_path=path)])])
    pid, _ = learning_prompt(engine)
    res = engine.handle_action(pid, "done", at(MONDAY, "18:00"))
    assert "Path complete: <b>Yachtmaster</b>" in res.extra[0]
    assert "Unlocked: Sailing · Offshore" in res.extra[0]


def test_learning_balances_toward_ratio(engine, db):
    with db.session() as s:
        pro = Course(name="Pro", category=Category.PROFESSIONAL, kind=CourseKind.TIME)
        hob = Course(name="Hob", category=Category.HOBBY, kind=CourseKind.TIME)
        s.add_all([pro, hob])
        s.flush()
        # Six pro sessions already this week -> hobby is now furthest behind its 15%.
        for i in range(6):
            s.add(LogEntry(area=Area.LEARNING, course_id=pro.id, outcome="done", created_at=at(MONDAY, f"0{i}:10")))

    _, msg = learning_prompt(engine)
    assert "Hob" in msg.text


# --- movement links -----------------------------------------------------------


def test_routine_shows_video_links(engine, db):
    with db.session() as s:
        s.add(Routine(
            name="Yoga flow", duration_min=20, url="https://www.dailyom.com/course/x",
            steps=[RoutineStep(position=0, text="Warm-up video", url="https://youtu.be/abc")],
        ))
    engine.plan_day(MONDAY)
    (_, msg), = send_due(engine, at(MONDAY, "06:30"))
    assert 'href="https://www.dailyom.com/course/x"' in msg.text
    assert '1. Warm-up video · <a href="https://youtu.be/abc">link</a>' in msg.text


# --- hobbies ------------------------------------------------------------------


def test_weekday_slots_and_locked_projects(engine, db):
    with db.session() as s:
        theory = Course(name="Theory", category=Category.HOBBY)
        chess = Hobby(name="Chess")
        guitar = Hobby(
            name="Guitar",
            projects=[
                HobbyProject(name="Gig", requires_course=theory),
                HobbyProject(name="Scales"),
                HobbyProject(name="Old song", done_at=at(MONDAY, "00:00")),
            ],
        )
        s.add_all([theory, chess, guitar])
        s.flush()
        s.add(ScheduleRule(hobby_id=chess.id, method=PickMethod.WEEKDAY_SLOTS, weekdays=[5]))  # Saturday only

    engine.plan_day(MONDAY)
    pid, msg = next((p, m) for p, m in send_due(engine, at(MONDAY, "19:00")) if "Hobby" in m.text)
    assert "Guitar" in msg.text and "Scales" in msg.text
    assert "Gig" not in msg.text and "Old song" not in msg.text
    assert engine.handle_action(pid, "another", at(MONDAY, "19:01")).toast == "No other suggestions today."


# --- /log ---------------------------------------------------------------------


def test_log_matches_known_items_or_asks(engine, db):
    with db.session() as s:
        s.add(Hobby(name="Guitar"))
    text, buttons = engine.log(["guitar", "practice", "45m"], at(MONDAY, "12:00"))
    assert text == "Logged hobby: guitar practice, 45 min." and buttons == []

    text, buttons = engine.log(["run", "30m"], at(MONDAY, "12:00"))
    assert "Which area" in text
    token = buttons[0][0].data.split(":")[1]
    assert engine.finish_log(token, "movement", at(MONDAY, "12:01")) == "Logged movement: run, 30 min."

    with db.session() as s:
        assert s.query(LogEntry).count() == 2

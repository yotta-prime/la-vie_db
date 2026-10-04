"""Admin page: edit routines, micro-moves, learning paths/courses, hobbies/projects, settings.

Server-rendered forms (POST then redirect). LAN only; protected by ADMIN_PASSWORD with a
signed, SameSite=Strict cookie (which also blocks cross-site form posts).
"""

import asyncio
import hashlib
import hmac
import re
import time as _time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.config import get_settings
from app.engine import complete_course
from app.models import (
    Category,
    Course,
    CourseKind,
    CourseStep,
    Flashcard,
    Hobby,
    HobbyProject,
    LearningPath,
    MicroMove,
    PickMethod,
    Prompt,
    Routine,
    RoutineStep,
    ScheduleRule,
    Setting,
)
from app.timeutil import local_day_bounds, parse_hhmm

COOKIE = "lavie_admin"
SESSION_SECONDS = 30 * 24 * 3600
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals.update(
    WEEKDAYS=WEEKDAYS, Category=Category, CourseKind=CourseKind, PickMethod=PickMethod
)


# --- auth ---------------------------------------------------------------------


class NotAuthenticated(Exception):
    pass


def _secret() -> bytes:
    s = get_settings()
    # Changing the password (or bot token) signs everyone out.
    return hashlib.sha256(f"lavie-admin\0{s.admin_password}\0{s.telegram_bot_token}".encode()).digest()


def make_token(now: float | None = None) -> str:
    exp = str(int((now or _time.time()) + SESSION_SECONDS))
    return f"{exp}.{hmac.new(_secret(), exp.encode(), 'sha256').hexdigest()}"


def valid_token(token: str | None) -> bool:
    if not token or "." not in token or not get_settings().admin_password:
        return False
    exp, sig = token.split(".", 1)
    good = hmac.new(_secret(), exp.encode(), "sha256").hexdigest()
    return hmac.compare_digest(sig, good) and exp.isdigit() and int(exp) > _time.time()


async def require_admin(request: Request) -> None:
    if not valid_token(request.cookies.get(COOKIE)):
        raise NotAuthenticated


public = APIRouter(prefix="/admin")
router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


def install(app: FastAPI) -> None:
    app.include_router(public)
    app.include_router(router)

    @app.exception_handler(NotAuthenticated)
    async def _to_login(request: Request, exc: NotAuthenticated):
        return RedirectResponse("/admin/login", status_code=303)

    @app.get("/", include_in_schema=False)
    async def _root():
        return RedirectResponse("/admin", status_code=303)


@public.get("/login")
async def login_form(request: Request):
    return render(request, "login.html", configured=bool(get_settings().admin_password))


@public.post("/login")
async def login(request: Request):
    form = await request.form()
    password = get_settings().admin_password
    if password and hmac.compare_digest(str(form.get("password", "")).encode(), password.encode()):
        resp = RedirectResponse("/admin", status_code=303)
        resp.set_cookie(COOKIE, make_token(), max_age=SESSION_SECONDS, httponly=True, samesite="strict")
        return resp
    await asyncio.sleep(1)  # slow down guessing
    return render(request, "login.html", configured=bool(password), error="Wrong password.")


@public.post("/logout")
async def logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# --- helpers ------------------------------------------------------------------


def render(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, {"msg": request.query_params.get("msg"), **ctx})


def back(url: str, msg: str | None = None) -> RedirectResponse:
    if msg:
        path, hash_, frag = url.partition("#")
        path += ("&" if "?" in path else "?") + "msg=" + quote(re.sub(r"<[^>]+>", "", msg))
        url = path + hash_ + frag
    return RedirectResponse(url, status_code=303)


def _db(request: Request):
    return request.app.state.db


def txt(form, key: str) -> str | None:
    v = form.get(key)
    v = str(v).strip() if v is not None else ""
    return v or None


def num(form, key: str) -> int | None:
    v = txt(form, key)
    return int(v) if v and v.lstrip("-").isdigit() else None


def flag(form, key: str) -> bool:
    return form.get(key) in ("on", "1", "true")


def day(form, key: str) -> date | None:
    v = txt(form, key)
    return date.fromisoformat(v) if v else None


def move(items: list, item, direction: str) -> None:
    """Move item up/down among siblings and renumber positions 0..n."""
    items = list(items)
    i = items.index(item)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(items):
        items[i], items[j] = items[j], items[i]
    for pos, it in enumerate(items):
        it.position = pos


def get_or_404(s, model, id_: int):
    obj = s.get(model, id_)
    if obj is None:
        from fastapi import HTTPException

        raise HTTPException(404)
    return obj


# --- dashboard ----------------------------------------------------------------


@router.get("")
async def dashboard(request: Request):
    eng = request.app.state.engine
    now = datetime.now(timezone.utc)
    today = eng.today(now)
    start, end = local_day_bounds(today, eng.tz)
    with _db(request).session() as s:
        prompts = s.scalars(
            select(Prompt).where(Prompt.scheduled_for >= start, Prompt.scheduled_for < end).order_by(Prompt.scheduled_for)
        ).all()
        counts = {
            "routines": s.scalar(select(func.count()).select_from(Routine)),
            "paths": s.scalar(select(func.count()).select_from(LearningPath)),
            "courses": s.scalar(select(func.count()).select_from(Course)),
            "hobbies": s.scalar(select(func.count()).select_from(Hobby)),
        }
        rows = [(p.scheduled_for.astimezone(eng.tz).strftime("%H:%M"), p.kind.replace("_", " "), p.status.value) for p in prompts]
    return render(request, "dashboard.html", prompts=rows, counts=counts, today=today)


@router.post("/replan")
async def replan(request: Request):
    eng = request.app.state.engine
    now = datetime.now(timezone.utc)
    n = eng.plan_day(eng.today(now), replan_after=now)
    return back("/admin", f"Re-planned the rest of today: {n} prompts.")


# --- movement -----------------------------------------------------------------


@router.get("/movement")
async def movement(request: Request):
    with _db(request).session() as s:
        routines = s.scalars(select(Routine).order_by(Routine.id)).all()
        moves = s.scalars(select(MicroMove).order_by(MicroMove.id)).all()
        return render(request, "movement.html", routines=routines, moves=moves)


@router.post("/routines")
async def routine_create(request: Request):
    form = await request.form()
    with _db(request).session() as s:
        r = Routine(name=txt(form, "name") or "New routine")
        s.add(r)
        s.flush()
        rid = r.id
    return back(f"/admin/routines/{rid}", "Routine created.")


@router.get("/routines/{rid}")
async def routine_edit(request: Request, rid: int):
    with _db(request).session() as s:
        return render(request, "routine.html", r=get_or_404(s, Routine, rid))


@router.post("/routines/{rid}")
async def routine_update(request: Request, rid: int):
    form = await request.form()
    with _db(request).session() as s:
        r = get_or_404(s, Routine, rid)
        r.name = txt(form, "name") or r.name
        r.duration_min = num(form, "duration_min")
        r.url = txt(form, "url")
        r.notes = txt(form, "notes")
        r.active = flag(form, "active")
    return back(f"/admin/routines/{rid}", "Saved.")


@router.post("/routines/{rid}/delete")
async def routine_delete(request: Request, rid: int):
    with _db(request).session() as s:
        s.delete(get_or_404(s, Routine, rid))
    return back("/admin/movement", "Routine deleted.")


@router.post("/routines/{rid}/steps")
async def routine_step_add(request: Request, rid: int):
    form = await request.form()
    with _db(request).session() as s:
        r = get_or_404(s, Routine, rid)
        if txt(form, "text"):
            r.steps.append(RoutineStep(position=len(r.steps), text=txt(form, "text"), url=txt(form, "url")))
    return back(f"/admin/routines/{rid}")


@router.post("/routine-steps/{sid}")
async def routine_step_update(request: Request, sid: int):
    form = await request.form()
    with _db(request).session() as s:
        st = get_or_404(s, RoutineStep, sid)
        action = form.get("action")
        rid = st.routine_id
        if action == "delete":
            r = st.routine
            r.steps.remove(st)
            for pos, x in enumerate(r.steps):
                x.position = pos
        elif action in ("up", "down"):
            move(st.routine.steps, st, action)
        else:
            st.text = txt(form, "text") or st.text
            st.url = txt(form, "url")
    return back(f"/admin/routines/{rid}")


@router.post("/micro-moves")
async def micro_add(request: Request):
    form = await request.form()
    with _db(request).session() as s:
        if txt(form, "text"):
            s.add(MicroMove(text=txt(form, "text")))
    return back("/admin/movement#micro")


@router.post("/micro-moves/{mid}")
async def micro_update(request: Request, mid: int):
    form = await request.form()
    with _db(request).session() as s:
        m = get_or_404(s, MicroMove, mid)
        if form.get("action") == "delete":
            s.delete(m)
        else:
            m.text = txt(form, "text") or m.text
            m.active = flag(form, "active")
    return back("/admin/movement#micro")


# --- learning -----------------------------------------------------------------


@router.get("/learning")
async def learning(request: Request):
    with _db(request).session() as s:
        paths = s.scalars(select(LearningPath).order_by(LearningPath.id)).all()
        standalone = s.scalars(select(Course).where(Course.path_id.is_(None)).order_by(Course.id)).all()
        return render(request, "learning.html", paths=paths, standalone=standalone)


@router.post("/paths")
async def path_create(request: Request):
    form = await request.form()
    with _db(request).session() as s:
        p = LearningPath(name=txt(form, "name") or "New path", category=Category(form.get("category", "professional")))
        s.add(p)
        s.flush()
        pid = p.id
    return back(f"/admin/paths/{pid}", "Path created.")


@router.get("/paths/{pid}")
async def path_edit(request: Request, pid: int):
    with _db(request).session() as s:
        return render(request, "path.html", p=get_or_404(s, LearningPath, pid))


@router.post("/paths/{pid}")
async def path_update(request: Request, pid: int):
    form = await request.form()
    with _db(request).session() as s:
        p = get_or_404(s, LearningPath, pid)
        p.name = txt(form, "name") or p.name
        p.category = Category(form.get("category", p.category.value))
        p.description = txt(form, "description")
        p.sequential = flag(form, "sequential")
        p.active = flag(form, "active")
    return back(f"/admin/paths/{pid}", "Saved.")


@router.post("/paths/{pid}/delete")
async def path_delete(request: Request, pid: int):
    with _db(request).session() as s:
        p = get_or_404(s, LearningPath, pid)
        for c in p.courses:
            c.path = None
        s.delete(p)
    return back("/admin/learning", "Path deleted; its courses are now standalone.")


@router.post("/courses")
async def course_create(request: Request):
    form = await request.form()
    with _db(request).session() as s:
        path = s.get(LearningPath, num(form, "path_id")) if num(form, "path_id") else None
        c = Course(
            name=txt(form, "name") or "New course",
            category=path.category if path else Category(form.get("category", "professional")),
            kind=CourseKind(form.get("kind", "steps")),
            path=path,
            position=len(path.courses) if path else 0,
        )
        s.add(c)
        s.flush()
        cid = c.id
    return back(f"/admin/courses/{cid}", "Course created.")


@router.get("/courses/{cid}")
async def course_edit(request: Request, cid: int):
    with _db(request).session() as s:
        c = get_or_404(s, Course, cid)
        paths = s.scalars(select(LearningPath).order_by(LearningPath.name)).all()
        rule = s.scalar(select(ScheduleRule).where(ScheduleRule.course_id == cid))
        return render(request, "course.html", c=c, paths=paths, rule=rule)


@router.post("/courses/{cid}")
async def course_update(request: Request, cid: int):
    form = await request.form()
    with _db(request).session() as s:
        c = get_or_404(s, Course, cid)
        c.name = txt(form, "name") or c.name
        c.category = Category(form.get("category", c.category.value))
        c.kind = CourseKind(form.get("kind", c.kind.value))
        c.daily_goal_min = num(form, "daily_goal_min")
        c.url = txt(form, "url")
        c.notes = txt(form, "notes")
        c.active = flag(form, "active")
        new_path = num(form, "path_id")
        if new_path != c.path_id:
            path = s.get(LearningPath, new_path) if new_path else None
            c.path = path
            c.position = len(path.courses) - 1 if path else 0
    return back(f"/admin/courses/{cid}", "Saved.")


@router.post("/courses/{cid}/action")
async def course_action(request: Request, cid: int):
    form = await request.form()
    action = form.get("action")
    msg = None
    with _db(request).session() as s:
        c = get_or_404(s, Course, cid)
        if action == "delete":
            s.delete(c)
            return back("/admin/learning", "Course deleted.")
        if action == "complete":
            msgs = complete_course(s, c, datetime.now(timezone.utc))
            msg = " · ".join(msgs[0].split("\n")) if msgs else None
        elif action == "reopen":
            c.completed_at = None
            msg = "Course reopened."
        elif action in ("up", "down") and c.path:
            move(c.path.courses, c, action)
            return back(f"/admin/paths/{c.path_id}")
    return back(f"/admin/courses/{cid}", msg)


@router.post("/courses/{cid}/steps")
async def course_step_add(request: Request, cid: int):
    form = await request.form()
    with _db(request).session() as s:
        c = get_or_404(s, Course, cid)
        titles = [t.strip() for t in (txt(form, "title") or "").splitlines() if t.strip()]
        for t in titles:  # paste several lessons, one per line
            c.steps.append(CourseStep(position=len(c.steps), title=t, url=txt(form, "url") if len(titles) == 1 else None))
    return back(f"/admin/courses/{cid}#lessons")


@router.post("/course-steps/{sid}")
async def course_step_update(request: Request, sid: int):
    form = await request.form()
    with _db(request).session() as s:
        st = get_or_404(s, CourseStep, sid)
        cid = st.course_id
        action = form.get("action")
        if action == "delete":
            c = st.course
            c.steps.remove(st)
            for pos, x in enumerate(c.steps):
                x.position = pos
        elif action in ("up", "down"):
            move(st.course.steps, st, action)
        elif action == "toggle":
            st.done_at = None if st.done_at else datetime.now(timezone.utc)
        else:
            st.title = txt(form, "title") or st.title
            st.detail = txt(form, "detail")
            st.url = txt(form, "url")
    return back(f"/admin/courses/{cid}#lessons")


@router.post("/courses/{cid}/cards")
async def card_add(request: Request, cid: int):
    form = await request.form()
    with _db(request).session() as s:
        c = get_or_404(s, Course, cid)
        if txt(form, "front") and txt(form, "back"):
            c.flashcards.append(Flashcard(front=txt(form, "front"), back=txt(form, "back")))
    return back(f"/admin/courses/{cid}#cards")


@router.post("/cards/{fid}/delete")
async def card_delete(request: Request, fid: int):
    with _db(request).session() as s:
        f = get_or_404(s, Flashcard, fid)
        cid = f.course_id
        s.delete(f)
    return back(f"/admin/courses/{cid}#cards")


# --- schedule rules (courses and hobbies) -------------------------------------


@router.post("/rules/{target}/{item_id}")
async def rule_save(request: Request, target: str, item_id: int):
    if target not in ("course", "hobby"):
        return back("/admin")
    form = await request.form()
    col = ScheduleRule.course_id if target == "course" else ScheduleRule.hobby_id
    url = f"/admin/{'courses' if target == 'course' else 'hobbies'}/{item_id}#schedule"
    with _db(request).session() as s:
        rule = s.scalar(select(ScheduleRule).where(col == item_id))
        if form.get("action") == "reset":
            if rule:
                s.delete(rule)
            return back(url, "Schedule reset to default (round-robin).")
        if rule is None:
            rule = ScheduleRule(**{f"{target}_id": item_id})
            s.add(rule)
        rule.method = PickMethod(form.get("method", "round_robin"))
        rule.sessions_per_week = num(form, "sessions_per_week")
        rule.weekdays = sorted(int(d) for d in form.getlist("weekdays")) or None
        rule.start_date = day(form, "start_date")
        rule.end_date = day(form, "end_date")
        try:
            rule.weight = float(form.get("weight") or 1)
        except ValueError:
            rule.weight = 1.0
        if rule.method == PickMethod.WEEKDAY_SLOTS and not rule.weekdays:
            return back(url, "Pick at least one weekday for weekday slots.")
    return back(url, "Schedule saved.")


# --- hobbies ------------------------------------------------------------------


@router.get("/hobbies")
async def hobbies(request: Request):
    with _db(request).session() as s:
        return render(request, "hobbies.html", hobbies=s.scalars(select(Hobby).order_by(Hobby.name)).all())


@router.post("/hobbies")
async def hobby_create(request: Request):
    form = await request.form()
    with _db(request).session() as s:
        h = Hobby(name=txt(form, "name") or "New hobby")
        s.add(h)
        s.flush()
        hid = h.id
    return back(f"/admin/hobbies/{hid}", "Hobby created.")


@router.get("/hobbies/{hid}")
async def hobby_edit(request: Request, hid: int):
    with _db(request).session() as s:
        h = get_or_404(s, Hobby, hid)
        rule = s.scalar(select(ScheduleRule).where(ScheduleRule.hobby_id == hid))
        paths = s.scalars(select(LearningPath).order_by(LearningPath.name)).all()
        courses = s.scalars(select(Course).order_by(Course.name)).all()
        return render(request, "hobby.html", h=h, rule=rule, paths=paths, courses=courses)


@router.post("/hobbies/{hid}")
async def hobby_update(request: Request, hid: int):
    form = await request.form()
    with _db(request).session() as s:
        h = get_or_404(s, Hobby, hid)
        if form.get("action") == "delete":
            s.delete(h)
            return back("/admin/hobbies", "Hobby deleted.")
        h.name = txt(form, "name") or h.name
        h.active = flag(form, "active")
    return back(f"/admin/hobbies/{hid}", "Saved.")


def _apply_requirement(p: HobbyProject, value: str | None) -> None:
    p.requires_course_id = p.requires_path_id = None
    if value and ":" in value:
        kind, _, id_ = value.partition(":")
        if id_.isdigit():
            if kind == "course":
                p.requires_course_id = int(id_)
            elif kind == "path":
                p.requires_path_id = int(id_)


@router.post("/hobbies/{hid}/projects")
async def project_add(request: Request, hid: int):
    form = await request.form()
    with _db(request).session() as s:
        h = get_or_404(s, Hobby, hid)
        if txt(form, "name"):
            p = HobbyProject(name=txt(form, "name"), url=txt(form, "url"), notes=txt(form, "notes"))
            _apply_requirement(p, txt(form, "requires"))
            h.projects.append(p)
    return back(f"/admin/hobbies/{hid}#projects")


@router.post("/projects/{pid}")
async def project_update(request: Request, pid: int):
    form = await request.form()
    with _db(request).session() as s:
        p = get_or_404(s, HobbyProject, pid)
        hid = p.hobby_id
        action = form.get("action")
        if action == "delete":
            s.delete(p)
        elif action == "toggle":
            p.done_at = None if p.done_at else datetime.now(timezone.utc)
        else:
            p.name = txt(form, "name") or p.name
            p.url = txt(form, "url")
            p.notes = txt(form, "notes")
            p.active = flag(form, "active")
            _apply_requirement(p, txt(form, "requires"))
    return back(f"/admin/hobbies/{hid}#projects")


# --- settings -----------------------------------------------------------------

TIME_FIELDS = {
    "movement_routine": "Movement routine",
    "focus_intention": "Focus intention",
    "learning_session": "Learning session",
    "hobby_session": "Hobby session",
    "focus_reflection": "Focus reflection",
}


@router.get("/settings")
async def settings_form(request: Request):
    eng = request.app.state.engine
    with _db(request).session() as s:
        return render(request, "settings.html", cfg=eng.settings(s), time_fields=TIME_FIELDS)


@router.post("/settings")
async def settings_save(request: Request):
    form = await request.form()
    eng = request.app.state.engine
    try:
        for key in [*TIME_FIELDS, "work_start", "work_end", "quiet_start", "quiet_end", "backup_time", "summary_time"]:
            parse_hhmm(str(form.get(key)))
        summary_day = num(form, "summary_weekday")
        if summary_day is None or not 0 <= summary_day <= 6:
            raise ValueError("weekday")
        pro = max(0, min(100, num(form, "professional_pct") or 0))
        values = {
            "prompt_times": {k: str(form.get(k)) for k in TIME_FIELDS},
            "work_days": sorted(int(d) for d in form.getlist("work_days")),
            "work_hours": {"start": str(form.get("work_start")), "end": str(form.get("work_end"))},
            "quiet_hours": {"start": str(form.get("quiet_start")), "end": str(form.get("quiet_end"))},
            "micro_move_interval_min": max(15, num(form, "micro_move_interval_min") or 60),
            "distraction_checks_per_day": max(0, min(6, num(form, "distraction_checks_per_day") or 0)),
            "learning_ratio": {"professional": pro / 100, "hobby": (100 - pro) / 100},
            "focus_block_default_min": max(5, min(240, num(form, "focus_block_default_min") or 25)),
            "backup_time": str(form.get("backup_time")),
            "weekly_summary": {"weekday": summary_day, "time": str(form.get("summary_time"))},
        }
    except (ValueError, TypeError):
        return back("/admin/settings", "Times must be HH:MM.")

    with _db(request).session() as s:
        for key, value in values.items():
            row = s.get(Setting, key)
            if row:
                row.value = value
            else:
                s.add(Setting(key=key, value=value))

    msg = "Settings saved; they apply from tomorrow."
    if flag(form, "replan"):
        now = datetime.now(timezone.utc)
        n = eng.plan_day(eng.today(now), replan_after=now)
        msg = f"Settings saved; rest of today re-planned ({n} prompts)."
    return back("/admin/settings", msg)

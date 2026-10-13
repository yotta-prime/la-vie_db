"""Your answers (what was asked, what you replied) and week-by-week progress, for the admin
Answers and Trends pages. Everything is derived from prompts and log entries already stored;
nothing extra is recorded."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Area,
    Course,
    CourseStep,
    Hobby,
    HobbyProject,
    LogEntry,
    MicroMove,
    Outcome,
    Prompt,
    PromptStatus,
    Routine,
)
from app.timeutil import local_dt, week_start

DONE = (Outcome.DONE, Outcome.PARTIAL)

QUESTIONS = {
    "routine": "Movement routine",
    "micro_move": "Desk break",
    "intention": "What's your one most important thing today?",
    "distraction": "What are you doing right now?",
    "reflection": "How was your focus today?",
    "focus_end": "Focus block: how did it go?",
    "learning": "Learning session",
    "hobby": "Hobby session",
    "event_attendance": "Did you attend?",
    "recording_ready": "Recording ready",
}
OUTCOMES = {Outcome.DONE: "✓ Done", Outcome.PARTIAL: "◐ Partial", Outcome.SKIP: "✗ Skipped"}


# --- Answers ------------------------------------------------------------------------


@dataclass
class Answer:
    when: datetime  # local time
    area: str
    question: str
    item: str = ""  # routine / course · lesson / hobby · project / event
    answer: list[str] = field(default_factory=list)
    note: str = ""
    replied: bool = True
    via_log: bool = False


def answers(s: Session, start: datetime, end: datetime, tz: ZoneInfo, area: Area | None = None) -> list[Answer]:
    """Newest first: every prompt sent in [start, end) with your reply (or none), plus /log entries."""
    pq = select(Prompt).where(
        Prompt.sent_at.is_not(None), Prompt.sent_at >= start, Prompt.sent_at < end, Prompt.kind != "weekly_summary"
    )
    lq = select(LogEntry).where(
        ((LogEntry.prompt_id.is_(None)) & (LogEntry.created_at >= start) & (LogEntry.created_at < end))
        | LogEntry.prompt_id.in_(pq.with_only_columns(Prompt.id))
    )
    if area:
        pq, lq = pq.where(Prompt.area == area), lq.where(LogEntry.area == area)
    prompts = s.scalars(pq).all()
    logs = s.scalars(lq).all()
    by_prompt: dict[int, list[LogEntry]] = {}
    for e in logs:
        if e.prompt_id:
            by_prompt.setdefault(e.prompt_id, []).append(e)

    out = []
    for p in prompts:
        entries = by_prompt.get(p.id, [])
        a = Answer(p.sent_at.astimezone(tz), p.area.value, QUESTIONS.get(p.kind, p.kind.replace("_", " ")),
                   item=_prompt_item(s, p, entries))
        for e in entries:
            a.answer += _answer_parts(e)
            if e.note:
                a.note = f"{a.note}\n{e.note}".strip()
        if p.kind in ("event_attendance", "recording_ready") and p.status == PromptStatus.ANSWERED and not a.answer:
            st = s.get(CourseStep, (p.payload or {}).get("step_id"))
            if st and st.attendance:
                a.answer.append(st.attendance.value.capitalize())
        a.replied = p.status == PromptStatus.ANSWERED or bool(entries)
        out.append(a)

    for e in logs:
        if e.prompt_id is None:
            out.append(Answer(e.created_at.astimezone(tz), e.area.value, "Logged with /log",
                              item=_log_item(s, e), answer=_answer_parts(e), note=e.note or "", via_log=True))
    return sorted(out, key=lambda a: a.when, reverse=True)


def _answer_parts(e: LogEntry) -> list[str]:
    parts = []
    if e.outcome:
        parts.append(OUTCOMES[e.outcome])
    if e.rating:
        parts.append(f"Focus {e.rating}/5")
    if e.duration_min:
        parts.append(f"{e.duration_min} min")
    return parts


def _name(s: Session, model, id_) -> str:
    obj = s.get(model, id_) if id_ else None
    return obj.name if obj is not None and hasattr(obj, "name") else (getattr(obj, "title", "") if obj else "")


def _prompt_item(s: Session, p: Prompt, entries: list[LogEntry]) -> str:
    pl = p.payload or {}
    e = entries[0] if entries else None
    if p.kind == "routine":
        return _name(s, Routine, (e and e.routine_id) or pl.get("routine_id"))
    if p.kind == "micro_move":
        mm = s.get(MicroMove, pl.get("micro_move_id")) if pl.get("micro_move_id") else None
        return mm.text if mm else (e.label if e else "")
    if p.kind == "learning":
        cid = (e and e.course_id) or (pl["candidates"][pl.get("idx", 0)] if pl.get("candidates") else None)
        step = _name(s, CourseStep, (e and e.course_step_id) or pl.get("step_id"))
        return " · ".join(x for x in (_name(s, Course, cid), step) if x)
    if p.kind == "hobby":
        hid = (e and e.hobby_id) or (pl["candidates"][pl.get("idx", 0)] if pl.get("candidates") else None)
        proj = _name(s, HobbyProject, (e and e.hobby_project_id) or pl.get("project_id"))
        return " · ".join(x for x in (_name(s, Hobby, hid), proj) if x)
    if p.kind in ("event_attendance", "recording_ready"):
        return _name(s, CourseStep, pl.get("step_id"))
    if p.kind == "focus_end":
        return f"{pl.get('minutes')} min" if pl.get("minutes") else ""
    return ""


def _log_item(s: Session, e: LogEntry) -> str:
    for model, id_ in ((Routine, e.routine_id), (Course, e.course_id), (Hobby, e.hobby_id)):
        if id_:
            name = _name(s, model, id_)
            step = _name(s, CourseStep, e.course_step_id) if model is Course else ""
            return " · ".join(x for x in (name, step) if x)
    return e.label or ""


# --- Weekly trends ------------------------------------------------------------------

# (key, area heading, label, format). Formats: "n" count, "pct" percent, "avg" one decimal.
METRICS = [
    ("routine_days", "Movement", "Days with a routine", "n"),
    ("desk_breaks", "Movement", "Desk breaks taken", "n"),
    ("activity_min", "Movement", "Extra activity (min)", "n"),
    ("intentions", "Focus", "Days with an intention", "n"),
    ("focus_avg", "Focus", "Average focus (1–5)", "avg"),
    ("focus_block_min", "Focus", "Focus blocks (min)", "n"),
    ("learning_sessions", "Learning", "Learning sessions", "n"),
    ("lessons", "Learning", "Lessons completed", "n"),
    ("professional_pct", "Learning", "Professional share", "pct"),
    ("hobby_sessions", "Hobbies", "Hobby sessions", "n"),
    ("answer_rate", "Replies", "Prompts answered", "pct"),
]


@dataclass
class Week:
    start: date
    partial: bool  # the current week, still in progress
    values: dict


def week_metrics(s: Session, start_day: date, tz: ZoneInfo, now: datetime) -> dict:
    start = local_dt(start_day, "00:00", tz)
    end = min(local_dt(start_day + timedelta(days=7), "00:00", tz), now)
    logs = s.scalars(select(LogEntry).where(LogEntry.created_at >= start, LogEntry.created_at < end)).all()
    done = [e for e in logs if e.outcome in DONE]
    day = lambda e: e.created_at.astimezone(tz).date()  # noqa: E731

    learning = [e for e in done if e.area == Area.LEARNING]
    course_cat = {c.id: c.category.value for c in s.scalars(select(Course).where(Course.id.in_({e.course_id for e in learning if e.course_id})))}
    cats = [course_cat[e.course_id] for e in learning if e.course_id in course_cat]
    ratings = [e.rating for e in logs if e.area == Area.FOCUS and e.rating]
    intention_ids = s.scalars(select(Prompt.id).where(Prompt.kind == "intention", Prompt.sent_at >= start, Prompt.sent_at < end)).all()
    sent = s.scalars(select(Prompt.status).where(
        Prompt.sent_at >= start, Prompt.sent_at < end, Prompt.kind != "weekly_summary",
        Prompt.status.in_([PromptStatus.SENT, PromptStatus.ANSWERED, PromptStatus.EXPIRED]),
    )).all()

    return {
        "routine_days": len({day(e) for e in done if e.area == Area.MOVEMENT and e.routine_id}),
        "desk_breaks": sum(1 for e in done if e.area == Area.MOVEMENT and e.prompt_id and not e.routine_id),
        "activity_min": sum(e.duration_min or 0 for e in done if e.area == Area.MOVEMENT and not e.prompt_id),
        "intentions": len({day(e) for e in logs if e.prompt_id in intention_ids and e.note}),
        "focus_avg": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "focus_block_min": sum(e.duration_min or 0 for e in done if e.area == Area.FOCUS and e.label == "focus block"),
        "learning_sessions": len(learning),
        "lessons": s.scalar(select(func.count()).select_from(CourseStep).where(CourseStep.done_at >= start, CourseStep.done_at < end)),
        "professional_pct": round(cats.count("professional") / len(cats) * 100) if cats else None,
        "hobby_sessions": sum(1 for e in done if e.area == Area.HOBBY),
        "answer_rate": round(sum(st == PromptStatus.ANSWERED for st in sent) / len(sent) * 100) if sent else None,
    }


def weekly(s: Session, now: datetime, tz: ZoneInfo, weeks: int = 12) -> list[Week]:
    """Oldest first, ending with the current (partial) week; starts no earlier than the first data."""
    this_week = week_start(now.astimezone(tz).date())
    first = s.scalar(select(func.min(Prompt.sent_at)))
    first_log = s.scalar(select(func.min(LogEntry.created_at)))
    firsts = [d.astimezone(tz).date() for d in (first, first_log) if d]
    earliest = week_start(min(firsts)) if firsts else this_week
    start = max(earliest, this_week - timedelta(weeks=weeks - 1))
    out = []
    d = start
    while d <= this_week:
        out.append(Week(d, d == this_week, week_metrics(s, d, tz, now)))
        d += timedelta(weeks=1)
    return out

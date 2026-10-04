"""Weekly summary (spec: "Reports"), sent on Sunday evening and on demand with /summary."""

import html
from collections import Counter, defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import selection as sel
from app.models import (
    Area,
    Course,
    CourseStep,
    Hobby,
    HobbyProject,
    LogEntry,
    Outcome,
    Prompt,
    PromptStatus,
)
from app.timeutil import local_dt, week_start

DONE = (Outcome.DONE, Outcome.PARTIAL)


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def weekly_summary(s: Session, now: datetime, tz: ZoneInfo, ratio: dict) -> str:
    today = now.astimezone(tz).date()
    start_day = week_start(today)
    start = local_dt(start_day, "00:00", tz)
    logs = s.scalars(
        select(LogEntry).where(LogEntry.created_at >= start, LogEntry.created_at <= now)
    ).all()
    done = [e for e in logs if e.outcome in DONE]

    title = f"<b>Week of {start_day:%d %b}</b>"
    if today.weekday() != 6:
        title += f" <i>(so far, to {today:%a})</i>"
    out = [title]

    # Movement
    routines = [e for e in done if e.area == Area.MOVEMENT and e.routine_id]
    routine_days = {e.created_at.astimezone(tz).date() for e in routines}
    micro = [e for e in done if e.area == Area.MOVEMENT and e.prompt_id and not e.routine_id and e.label]
    other_moves = [e for e in done if e.area == Area.MOVEMENT and not e.prompt_id]
    out.append("\n<b>Movement</b>")
    out.append(f"Routines on {_plural(len(routine_days), 'day')}, {_plural(len(micro), 'desk break')} taken"
               + (f", {_plural(len(other_moves), 'extra activity', 'extra activities')} logged" if other_moves else ""))
    mins = sum(e.duration_min or 0 for e in other_moves)
    if mins:
        out.append(f"Extra activity time: {mins} min")

    # Focus
    ratings = [e.rating for e in logs if e.area == Area.FOCUS and e.rating]
    blocks = [e for e in done if e.area == Area.FOCUS and e.label == "focus block"]
    out.append("\n<b>Focus</b>")
    if ratings:
        out.append(f"Average focus {sum(ratings) / len(ratings):.1f}/5 over {_plural(len(ratings), 'day')}")
    else:
        out.append("No focus ratings yet")
    if blocks:
        out.append(f"{_plural(len(blocks), 'focus block')}, {sum(e.duration_min or 0 for e in blocks)} min")

    # Learning
    learning = [e for e in done if e.area == Area.LEARNING]
    out.append("\n<b>Learning</b>")
    if learning:
        courses = {c.id: c for c in s.scalars(select(Course).where(Course.id.in_({e.course_id for e in learning if e.course_id})))}
        per_course: dict[str, list[LogEntry]] = defaultdict(list)
        cats = Counter()
        for e in learning:
            c = courses.get(e.course_id)
            per_course[c.name if c else (e.label or "other")].append(e)
            if c:
                cats[c.category.value] += 1
        for name, entries in sorted(per_course.items(), key=lambda kv: -len(kv[1])):
            m = sum(x.duration_min or 0 for x in entries)
            out.append(f"• {html.escape(name)}: {_plural(len(entries), 'session')}" + (f", {m} min" if m else ""))
        total = sum(cats.values())
        if total:
            pro = cats["professional"] / total * 100
            target = ratio.get("professional", 0) * 100
            out.append(f"Professional {pro:.0f}% / hobby {100 - pro:.0f}% (target {target:.0f}/{100 - target:.0f})")
    else:
        out.append("No learning sessions yet")

    lessons = s.scalar(select(func.count()).select_from(CourseStep).where(CourseStep.done_at >= start))
    if lessons:
        out.append(f"{_plural(lessons, 'lesson')} completed")
    finished = s.scalars(select(Course).where(Course.completed_at >= start)).all()
    for c in finished:
        out.append(f"Completed: {html.escape(c.name)}")

    # Hobbies
    hobby_logs = [e for e in done if e.area == Area.HOBBY]
    out.append("\n<b>Hobbies</b>")
    if hobby_logs:
        names = {h.id: h.name for h in s.scalars(select(Hobby))}
        counts = Counter(names.get(e.hobby_id, e.label or "other") for e in hobby_logs)
        out.append(", ".join(f"{html.escape(n)} ×{k}" for n, k in counts.most_common()))
    else:
        out.append("No hobby sessions yet")
    for p in s.scalars(select(HobbyProject).where(HobbyProject.done_at >= start)):
        out.append(f"Finished project: {html.escape(p.hobby.name)} · {html.escape(p.name)}")

    # Streaks and response rate
    streaks = [(a, sel.streak(s, a, today, tz)) for a in (Area.MOVEMENT, Area.LEARNING, Area.HOBBY)]
    live = [f"{a.value} {n}d" for a, n in streaks if n]
    sent = s.scalars(
        select(Prompt.status).where(
            Prompt.scheduled_for >= start, Prompt.scheduled_for <= now, Prompt.kind != "weekly_summary",
            Prompt.status.in_([PromptStatus.SENT, PromptStatus.ANSWERED]),
        )
    ).all()
    out.append("")
    if live:
        out.append("Streaks: " + ", ".join(live))
    if sent:
        answered = sum(1 for st in sent if st == PromptStatus.ANSWERED)
        out.append(f"Answered {answered} of {_plural(len(sent), 'prompt')} ({answered / len(sent) * 100:.0f}%)")
    return "\n".join(out).rstrip()

"""Browse O'Reilly live-event lessons from Telegram (/oreilly), independent of Telegram itself.

Every view is one message edited in place. Callback data: "o:<view>[:<id>]" for navigation and
"o:set:<step_id>:<action>" for changes. Live-event lessons are those with an attendance value.
"""

import html
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import Button, Outgoing, complete_course
from app.models import Area, Attendance, Course, CourseStep, LearningPath, LogEntry, Outcome

LIST_LIMIT = 12
ICON = {"pending": "📅", "awaiting": "⏳", "missed": "🎬", "attended": "🔁", "watched": "✓"}
LISTS = {
    "watch": ("🎬 To watch (missed live)", lambda st: st.event_state == "missed"),
    "review": ("🔁 To review (attended)", lambda st: st.event_state == "attended"),
    "upcoming": ("📅 Upcoming", lambda st: st.event_state == "pending"),
    "awaiting": ("⏳ Awaiting recordings", lambda st: st.event_state == "awaiting"),
}
HOME = [Button("« O'Reilly", "o:home")]


def _events(s: Session) -> list[CourseStep]:
    return list(s.scalars(select(CourseStep).where(CourseStep.attendance.is_not(None))))


def _date(st: CourseStep) -> str:
    return f"{st.event_date.day} {st.event_date:%b %Y}" if st.event_date else "TBC"


def _short(st: CourseStep, n: int = 38) -> str:
    title = st.title if len(st.title) <= n else st.title[: n - 1] + "…"
    return f"{ICON[st.event_state]} {_date(st)} · {title}"


def home(s: Session) -> Outgoing:
    evs = _events(s)
    count = {k: sum(1 for st in evs if test(st)) for k, (_, test) in LISTS.items()}
    watched = sum(1 for st in evs if st.done_at)
    text = (
        "<b>O'Reilly live events</b>\n"
        f"🎬 To watch (missed live): {count['watch']}\n"
        f"🔁 To review (attended): {count['review']}\n"
        f"📅 Upcoming: {count['upcoming']}\n"
        f"⏳ Awaiting recordings: {count['awaiting']}\n"
        f"✓ Watched: {watched} of {len(evs)}"
    )
    buttons = [
        [Button("🎬 To watch", "o:watch"), Button("🔁 Review", "o:review")],
        [Button("📅 Upcoming", "o:upcoming"), Button("⏳ Awaiting", "o:awaiting")],
        [Button("📚 Paths & courses", "o:paths")],
    ]
    return Outgoing(text, buttons)


def listing(s: Session, which: str) -> Outgoing:
    title, test = LISTS[which]
    items = [st for st in _events(s) if test(st)]
    far = datetime.max.date()
    if which == "upcoming":
        items.sort(key=lambda st: (st.event_date or far, st.title))
    else:
        items.sort(key=lambda st: (st.event_date or far), reverse=True)
    text = f"<b>{title}</b>: {len(items)}"
    if not items:
        text += "\nNothing here."
    elif len(items) > LIST_LIMIT:
        text += f"\nShowing the {LIST_LIMIT} most relevant; the admin O'Reilly page has them all."
    rows = [[Button(_short(st), f"o:step:{st.id}")] for st in items[:LIST_LIMIT]]
    return Outgoing(text, rows + [HOME])


def paths(s: Session) -> Outgoing:
    rows = []
    for p in s.scalars(select(LearningPath).order_by(LearningPath.id)):
        cs = [c for c in p.courses if any(st.is_event for st in c.steps)]
        if cs:
            rows.append([Button(f"📚 {p.name}", "o:noop")])
            rows += [[Button(f"   {c.name} ({_progress(c)})", f"o:course:{c.id}")] for c in cs]
    singles = [c for c in s.scalars(select(Course).where(Course.path_id.is_(None)).order_by(Course.id))
               if any(st.is_event for st in c.steps)]
    if singles:
        rows.append([Button("📘 Individual courses", "o:noop")])
        rows += [[Button(f"   {c.name} ({_progress(c)})", f"o:course:{c.id}")] for c in singles]
    return Outgoing("<b>Paths & courses</b>\nPick a course.", rows + [HOME])


def _progress(c: Course) -> str:
    return f"{sum(1 for st in c.steps if st.done_at)}/{len(c.steps)}"


def course(s: Session, cid: int) -> Outgoing:
    c = s.get(Course, cid)
    if c is None:
        return home(s)
    head = f"<b>{html.escape(c.name)}</b>"
    if c.path:
        head += f"\n<i>{html.escape(c.path.name)}</i>"
    head += f"\nWatched {_progress(c)}"
    rows = [[Button(_short(st), f"o:step:{st.id}")] for st in c.steps if st.is_event]
    return Outgoing(head, rows + [[Button("« Paths", "o:paths"), *HOME]])


def step(s: Session, sid: int) -> Outgoing:
    st = s.get(CourseStep, sid)
    if st is None:
        return home(s)
    state = {
        "pending": f"{st.attendance.value.title()}, not happened yet",
        "awaiting": f"{st.attendance.value.title()}; recording not issued yet",
        "missed": "Missed live: watch the recording",
        "attended": "Attended: queued for review",
        "watched": "Watched ✓",
    }[st.event_state]
    lines = [f"<b>{html.escape(st.title)}</b>", f"{_date(st)}"]
    if st.presenters:
        lines.append(f"<i>{html.escape(st.presenters)}</i>")
    lines += [f"Course: {html.escape(st.course.name)}", f"Status: {state}"]

    rows = []
    if st.url:
        rows.append([Button("▶ Open recording", url=st.url)])
        rows.append([Button("↺ Not watched" if st.done_at else "✓ Watched", f"o:set:{st.id}:watched")])
    if st.attendance in (Attendance.REGISTERED, Attendance.WAITLISTED):
        rows.append([Button("✓ Attended", f"o:set:{st.id}:attended"), Button("✗ Missed", f"o:set:{st.id}:missed")])
    elif st.attendance == Attendance.ATTENDED:
        rows.append([Button("Actually missed it", f"o:set:{st.id}:missed")])
    elif st.attendance == Attendance.MISSED:
        rows.append([Button("Actually attended", f"o:set:{st.id}:attended")])
    rows.append([Button("« Course", f"o:course:{st.course_id}"), *HOME])
    return Outgoing("\n".join(lines), rows)


def change(s: Session, sid: int, action: str, now: datetime) -> tuple[str, Outgoing]:
    """Apply a change from the lesson view; returns (toast, refreshed lesson view)."""
    st = s.get(CourseStep, sid)
    if st is None:
        return "That lesson no longer exists.", home(s)
    if action in ("attended", "missed"):
        st.attendance = Attendance(action)
        st.attendance_asked_at = st.attendance_asked_at or now  # answered: don't ask again
        if st.url:
            st.recording_notified_at = st.recording_notified_at or now
        toast = "Marked attended." if action == "attended" else "Marked missed: it's on your watch list."
    elif action == "watched":
        if st.done_at:
            st.done_at = None
            toast = "Marked not watched."
        else:
            st.done_at = now
            s.add(LogEntry(area=Area.LEARNING, outcome=Outcome.DONE, created_at=now,
                           course_id=st.course_id, course_step_id=st.id, label="watched (O'Reilly)"))
            toast = "Marked watched."
            if all(x.done_at for x in st.course.steps):
                complete_course(s, st.course, now)
                toast += f" Course complete: {st.course.name}!"
    else:
        return "Unknown action.", step(s, sid)
    s.flush()
    return toast, step(s, sid)


def view(s: Session, data: str, now: datetime) -> tuple[str | None, Outgoing | None]:
    """Route a callback ("o:...") to a view. Returns (toast, message to show)."""
    parts = data.split(":")[1:]
    if not parts or parts[0] == "home":
        return None, home(s)
    kind = parts[0]
    if kind in LISTS:
        return None, listing(s, kind)
    if kind == "paths":
        return None, paths(s)
    if kind == "course" and len(parts) == 2 and parts[1].isdigit():
        return None, course(s, int(parts[1]))
    if kind == "step" and len(parts) == 2 and parts[1].isdigit():
        return None, step(s, int(parts[1]))
    if kind == "set" and len(parts) == 3 and parts[1].isdigit():
        return change(s, int(parts[1]), parts[2], now)
    return None, None  # e.g. "noop" headings

"""The prompt loop, independent of Telegram.

- plan_day() writes the day's Prompt rows from settings (once per local day).
- due() picks up prompts whose time has come, applies quiet hours / pauses / expiry,
  and renders them into Outgoing messages for the bot to send.
- handle_action() / handle_text() turn button presses and replies into LogEntry rows.
- Commands (/pause, /log, /focus, /status) are parsed here too.
"""

import html
import random
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from app import selection as sel
from app.db import Database
from app.defaults import DEFAULT_SETTINGS
from app.models import (
    Area,
    Course,
    CourseKind,
    CourseStep,
    Hobby,
    HobbyProject,
    LogEntry,
    MicroMove,
    Outcome,
    Pause,
    Prompt,
    PromptStatus,
    Routine,
    Setting,
)
from app.reports import weekly_summary
from app.timeutil import in_quiet_hours, local_day_bounds, local_dt, parse_duration

EXPIRE_AFTER = timedelta(minutes=30)
TEXT_REPLY_WINDOW = timedelta(hours=3)
TEXT_KINDS = ("intention", "distraction")
OUTCOME_LABELS = {Outcome.DONE: "✓ Done", Outcome.PARTIAL: "◐ Partial", Outcome.SKIP: "✗ Skipped"}

AREA_ALIASES = {
    "movement": Area.MOVEMENT, "move": Area.MOVEMENT,
    "focus": Area.FOCUS,
    "learning": Area.LEARNING, "learn": Area.LEARNING,
    "hobby": Area.HOBBY, "hobbies": Area.HOBBY,
}


@dataclass
class Button:
    label: str
    data: str


@dataclass
class Outgoing:
    text: str
    buttons: list[list[Button]] = field(default_factory=list)
    force_reply: bool = False


@dataclass
class ActionResult:
    toast: str | None = None
    edit: Outgoing | None = None  # replaces the pressed message
    extra: list[str] = field(default_factory=list)  # follow-up messages


def link(url: str | None, label: str = "link") -> str:
    return f' · <a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>' if url else ""


def outcome_buttons(prompt_id: int, partial: bool = True, another: bool = False) -> list[list[Button]]:
    row = [Button("Done", f"p:{prompt_id}:done")]
    if partial:
        row.append(Button("Partial", f"p:{prompt_id}:partial"))
    row.append(Button("Skip", f"p:{prompt_id}:skip"))
    rows = [row]
    if another:
        rows.append([Button("Something else", f"p:{prompt_id}:another")])
    return rows


class Engine:
    def __init__(self, db: Database, tz: ZoneInfo, rng: random.Random | None = None):
        self.db = db
        self.tz = tz
        self.rng = rng or random.Random()
        self._pending_logs: dict[str, tuple[str, int | None]] = {}

    # --- settings -------------------------------------------------------------

    def settings(self, s) -> dict:
        merged = dict(DEFAULT_SETTINGS)
        merged.update({row.key: row.value for row in s.scalars(select(Setting))})
        return merged

    def today(self, now: datetime) -> date:
        return now.astimezone(self.tz).date()

    # --- planning -------------------------------------------------------------

    def plan_day(self, day: date, replan_after: datetime | None = None) -> int:
        """Create the day's prompts unless already planned. Returns how many were created.

        With replan_after, still-scheduled prompts after that time are replaced using the
        current settings (used after editing settings in the admin page).
        """
        start, end = local_day_bounds(day, self.tz)
        with self.db.session() as s:
            day_prompts = select(Prompt).where(
                Prompt.scheduled_for >= start, Prompt.scheduled_for < end, Prompt.kind != "focus_end"
            )
            if replan_after is not None:
                for p in s.scalars(day_prompts.where(Prompt.status == PromptStatus.SCHEDULED)):
                    s.delete(p)
                # Kinds already handled earlier today shouldn't come round again.
                done_kinds = {p.kind for p in s.scalars(day_prompts) if p.kind not in ("micro_move", "distraction")}
            elif s.scalar(day_prompts.limit(1)):
                return 0
            else:
                done_kinds = set()

            cfg = self.settings(s)
            times = cfg["prompt_times"]
            workday = day.weekday() in cfg["work_days"]
            planned: list[tuple[Area, str, datetime]] = [
                (Area.MOVEMENT, "routine", local_dt(day, times["movement_routine"], self.tz)),
                (Area.LEARNING, "learning", local_dt(day, times["learning_session"], self.tz)),
                (Area.HOBBY, "hobby", local_dt(day, times["hobby_session"], self.tz)),
            ]
            if workday:
                planned += [
                    (Area.FOCUS, "intention", local_dt(day, times["focus_intention"], self.tz)),
                    (Area.FOCUS, "reflection", local_dt(day, times["focus_reflection"], self.tz)),
                ]
                planned += [(Area.MOVEMENT, "micro_move", t) for t in self._micro_times(day, cfg)]
                planned += [(Area.FOCUS, "distraction", t) for t in self._distraction_times(day, cfg)]
            summary = cfg["weekly_summary"]
            if day.weekday() == summary["weekday"]:
                planned.append((Area.FOCUS, "weekly_summary", local_dt(day, summary["time"], self.tz)))

            created = 0
            for area, kind, when in sorted(planned, key=lambda x: x[2]):
                if in_quiet_hours(when, cfg["quiet_hours"], self.tz):
                    continue
                if replan_after is not None and (when <= replan_after or kind in done_kinds):
                    continue
                s.add(Prompt(area=area, kind=kind, scheduled_for=when))
                created += 1
            return created

    def _work_window(self, day: date, cfg: dict) -> tuple[datetime, datetime]:
        wh = cfg["work_hours"]
        return local_dt(day, wh["start"], self.tz), local_dt(day, wh["end"], self.tz)

    def _micro_times(self, day: date, cfg: dict) -> list[datetime]:
        start, end = self._work_window(day, cfg)
        step = timedelta(minutes=cfg["micro_move_interval_min"])
        out, t = [], start + step
        while t < end:
            out.append(t)
            t += step
        return out

    def _distraction_times(self, day: date, cfg: dict) -> list[datetime]:
        """Random times in work hours, at least an hour apart, not on the hour (micro-moves)."""
        start, end = self._work_window(day, cfg)
        minutes = int((end - start).total_seconds() // 60)
        n = cfg["distraction_checks_per_day"]
        for _ in range(50):
            picks = sorted(self.rng.sample(range(15, minutes - 15), n)) if minutes > 30 else []
            if all(b - a >= 60 for a, b in zip(picks, picks[1:])) and all(p % 60 for p in picks):
                return [start + timedelta(minutes=p) for p in picks]
        return []

    # --- dispatch -------------------------------------------------------------

    def due(self, now: datetime) -> list[tuple[int, Outgoing]]:
        """Prompts to send now, rendered. Call mark_sent() for each one delivered."""
        out = []
        with self.db.session() as s:
            cfg = self.settings(s)
            prompts = s.scalars(
                select(Prompt)
                .where(Prompt.status == PromptStatus.SCHEDULED, Prompt.scheduled_for <= now)
                .order_by(Prompt.scheduled_for)
            ).all()
            for p in prompts:
                if now - p.scheduled_for > EXPIRE_AFTER:
                    p.status = PromptStatus.EXPIRED
                    continue
                # Focus blocks were started by you, and the summary isn't a nudge: pauses don't apply.
                exempt = p.kind in ("focus_end", "weekly_summary")
                if not exempt and (
                    in_quiet_hours(now, cfg["quiet_hours"], self.tz) or self._paused(s, p.area, now)
                ):
                    p.status = PromptStatus.SKIPPED
                    continue
                msg = self._render(s, p, now)
                if msg is None:  # nothing to suggest
                    p.status = PromptStatus.SKIPPED
                    continue
                out.append((p.id, msg))
        return out

    def mark_sent(self, prompt_id: int, message_id: int | None, now: datetime) -> None:
        with self.db.session() as s:
            p = s.get(Prompt, prompt_id)
            p.status = PromptStatus.SENT
            p.sent_at = now
            p.telegram_message_id = message_id

    def _paused(self, s, area: Area, now: datetime) -> bool:
        return any(
            p.until is None or p.until > now
            for p in s.scalars(select(Pause).where((Pause.area.is_(None)) | (Pause.area == area)))
        )

    # --- rendering ------------------------------------------------------------

    def _render(self, s, p: Prompt, now: datetime) -> Outgoing | None:
        today = self.today(now)
        payload = dict(p.payload or {})
        kind = p.kind

        if kind == "routine":
            r = sel.pick_routine(s)
            if r is None:
                text = "<b>Movement time</b>\nNo routines set up yet; add some in the admin page."
            else:
                payload["routine_id"] = r.id
                text = self._routine_text(r)
            st = sel.streak(s, Area.MOVEMENT, today, self.tz)
            if st:
                text += f"\n\nStreak: {st} day{'s' if st != 1 else ''}"
            buttons = outcome_buttons(p.id)

        elif kind == "micro_move":
            last = s.scalar(
                select(Prompt)
                .where(Prompt.kind == "micro_move", Prompt.status != PromptStatus.SCHEDULED)
                .order_by(Prompt.scheduled_for.desc())
                .limit(1)
            )
            m = sel.pick_micro_move(s, (last.payload or {}).get("micro_move_id") if last else None, self.rng)
            if m is None:
                return None
            payload["micro_move_id"] = m.id
            text = f"<b>Desk break</b>\n{html.escape(m.text)}"
            buttons = outcome_buttons(p.id, partial=False)

        elif kind == "intention":
            text = "<b>Focus</b>\nWhat's your one most important thing today?\n<i>Reply to this message.</i>"
            buttons = []

        elif kind == "distraction":
            text = "<b>Quick check</b>\nWhat are you doing right now?\n<i>Reply to this message.</i>"
            buttons = []

        elif kind == "reflection":
            intention = self._todays_intention(s, today)
            text = "<b>End of day</b>\nHow was your focus today?"
            if intention:
                text += f"\nThis morning's intention: <i>{html.escape(intention)}</i>"
            buttons = [[Button(str(n), f"p:{p.id}:r{n}") for n in range(1, 6)]]

        elif kind == "focus_end":
            text = f"<b>Focus block finished</b> ({payload['minutes']} min)\nHow did it go?"
            buttons = outcome_buttons(p.id)

        elif kind == "weekly_summary":
            text = weekly_summary(s, now, self.tz, self.settings(s)["learning_ratio"])
            buttons = []

        elif kind in ("learning", "hobby"):
            if "candidates" not in payload:
                if kind == "learning":
                    ranked = sel.rank_learning(s, today, self.tz, self.settings(s)["learning_ratio"])
                else:
                    ranked = sel.rank_hobbies(s, today, self.tz)
                if not ranked:
                    return None
                payload.update(candidates=[i.id for i in ranked], idx=0)
            text = self._session_text(s, kind, payload)
            buttons = outcome_buttons(p.id, another=payload["idx"] + 1 < len(payload["candidates"]))

        else:
            raise ValueError(f"unknown prompt kind {kind!r}")

        payload["text"] = text
        p.payload = payload
        return Outgoing(text, buttons, force_reply=kind in TEXT_KINDS)

    def _routine_text(self, r: Routine) -> str:
        head = f"<b>Movement: {html.escape(r.name)}</b>"
        if r.duration_min:
            head += f" ({r.duration_min} min)"
        head += link(r.url, "open")
        lines = [head]
        if r.notes:
            lines.append(f"<i>{html.escape(r.notes)}</i>")
        lines += [f"{i}. {html.escape(st.text)}{link(st.url)}" for i, st in enumerate(r.steps, 1)]
        return "\n".join(lines)

    def _session_text(self, s, kind: str, payload: dict) -> str:
        """Render the current candidate; also records the chosen project/step in payload."""
        item_id = payload["candidates"][payload["idx"]]
        if kind == "learning":
            course = s.get(Course, item_id)
            head = f"<b>Learning ({course.category.value}): {html.escape(course.name)}</b>{link(course.url, 'open')}"
            if course.path:
                head += f"\n<i>Path: {html.escape(course.path.name)}</i>"
            payload.pop("step_id", None)
            if course.kind == CourseKind.STEPS:
                step = sel.next_step(course)
                if step is None:
                    return f"{head}\nNo lessons left; add more or mark the course complete in the admin page."
                payload["step_id"] = step.id
                body = f"Next: {html.escape(step.title)}{link(step.url)}"
                if step.detail:
                    body += f"\n{html.escape(step.detail)}"
            elif course.kind == CourseKind.TIME:
                body = f"Goal: {course.daily_goal_min or 20} min today"
            else:
                body = "Flashcard review (Telegram reviews arrive in a later version)."
            return f"{head}\n{body}"

        hobby = s.get(Hobby, item_id)
        project = sel.pick_project(s, hobby)
        payload["project_id"] = project.id if project else None
        text = f"<b>Hobby time: {html.escape(hobby.name)}</b>"
        if project:
            text += f"\nProject: {html.escape(project.name)}{link(project.url)}"
            if project.notes:
                text += f"\n<i>{html.escape(project.notes)}</i>"
        return text

    def _todays_intention(self, s, today: date) -> str | None:
        start, end = local_day_bounds(today, self.tz)
        return s.scalar(
            select(LogEntry.note)
            .join(Prompt, LogEntry.prompt_id == Prompt.id)
            .where(Prompt.kind == "intention", Prompt.scheduled_for >= start, Prompt.scheduled_for < end)
            .order_by(LogEntry.created_at.desc())
            .limit(1)
        )

    # --- button presses -------------------------------------------------------

    def handle_action(self, prompt_id: int, action: str, now: datetime) -> ActionResult:
        with self.db.session() as s:
            p = s.get(Prompt, prompt_id)
            if p is None:
                return ActionResult(toast="That prompt no longer exists.")
            payload = dict(p.payload or {})

            if action == "another":
                if p.status == PromptStatus.ANSWERED:
                    return ActionResult(toast="Already logged.")
                if payload.get("idx", 0) + 1 >= len(payload.get("candidates", [])):
                    return ActionResult(toast="No other suggestions today.")
                payload["idx"] += 1
                text = self._session_text(s, p.kind, payload)
                payload["text"] = text
                p.payload = payload
                more = payload["idx"] + 1 < len(payload["candidates"])
                return ActionResult(edit=Outgoing(text, outcome_buttons(p.id, another=more)))

            if p.status == PromptStatus.ANSWERED:
                return ActionResult(toast="Already logged.")

            base_text = payload.get("text", "")
            if action.startswith("r") and action[1:].isdigit():
                rating = int(action[1:])
                s.add(LogEntry(area=p.area, prompt_id=p.id, rating=rating, created_at=now))
                p.status = PromptStatus.ANSWERED
                return ActionResult(
                    edit=Outgoing(f"{base_text}\n\nFocus {rating}/5 logged. <i>Reply to add a note.</i>")
                )

            outcome = Outcome(action)
            entry = self._entry_for(s, p, payload, outcome, now)
            s.add(entry)
            p.status = PromptStatus.ANSWERED

            extra = []
            if outcome == Outcome.DONE and payload.get("step_id"):
                extra += self._complete_step(s, payload["step_id"], now)

            status = OUTCOME_LABELS[outcome]
            if p.area == Area.MOVEMENT and outcome != Outcome.SKIP:
                s.flush()
                st = sel.streak(s, Area.MOVEMENT, self.today(now), self.tz)
                status += f" · streak {st} day{'s' if st != 1 else ''}"
            return ActionResult(edit=Outgoing(f"{base_text}\n\n{status}"), extra=extra)

    def _entry_for(self, s, p: Prompt, payload: dict, outcome: Outcome, now: datetime) -> LogEntry:
        e = LogEntry(area=p.area, prompt_id=p.id, outcome=outcome, created_at=now)
        if p.kind == "routine":
            e.routine_id = payload.get("routine_id")
        elif p.kind == "micro_move":
            mm = s.get(MicroMove, payload.get("micro_move_id"))
            e.label = mm.text if mm else None
        elif p.kind == "focus_end":
            e.label = "focus block"
            e.duration_min = payload["minutes"] if outcome != Outcome.SKIP else None
        elif p.kind == "learning":
            e.course_id = payload["candidates"][payload["idx"]]
            e.course_step_id = payload.get("step_id")
            course = s.get(Course, e.course_id)
            if course.kind == CourseKind.TIME and outcome == Outcome.DONE:
                e.duration_min = course.daily_goal_min
        elif p.kind == "hobby":
            e.hobby_id = payload["candidates"][payload["idx"]]
            e.hobby_project_id = payload.get("project_id")
        return e

    def _complete_step(self, s, step_id: int, now: datetime) -> list[str]:
        """Mark a lesson done; if it was the course's last, complete the course."""
        step = s.get(CourseStep, step_id)
        if step is None or step.done_at:
            return []
        step.done_at = now
        if any(st.done_at is None for st in step.course.steps):
            return []
        return complete_course(s, step.course, now)

    def _match_item(self, s, label: str, area: Area | None, entry: LogEntry) -> bool:
        """Link the log to a known hobby, course or routine by name."""
        if not label:
            return False
        needle = label.lower()

        def hit(name: str) -> bool:
            return name.lower() in needle or needle in name.lower()

        if area in (None, Area.HOBBY):
            for h in s.scalars(select(Hobby)):
                if hit(h.name):
                    entry.area, entry.hobby_id = Area.HOBBY, h.id
                    return True
        if area in (None, Area.LEARNING):
            for c in s.scalars(select(Course)):
                if hit(c.name):
                    entry.area, entry.course_id = Area.LEARNING, c.id
                    return True
        if area in (None, Area.MOVEMENT):
            for r in s.scalars(select(Routine)):
                if hit(r.name):
                    entry.area, entry.routine_id = Area.MOVEMENT, r.id
                    return True
        return False

    # --- text replies ---------------------------------------------------------

    def handle_text(self, text: str, reply_to_message_id: int | None, now: datetime) -> str:
        with self.db.session() as s:
            p = None
            if reply_to_message_id is not None:
                p = s.scalar(select(Prompt).where(Prompt.telegram_message_id == reply_to_message_id))
            if p is None:
                p = s.scalar(
                    select(Prompt)
                    .where(
                        Prompt.kind.in_(TEXT_KINDS),
                        Prompt.status == PromptStatus.SENT,
                        Prompt.sent_at >= now - TEXT_REPLY_WINDOW,
                    )
                    .order_by(Prompt.sent_at.desc())
                    .limit(1)
                )
            if p is None:
                return "Not sure what that's for. Reply to a prompt, or use /log."

            entry = s.scalar(
                select(LogEntry).where(LogEntry.prompt_id == p.id).order_by(LogEntry.id.desc()).limit(1)
            )
            if entry:
                entry.note = f"{entry.note}\n{text}" if entry.note else text
            else:
                s.add(LogEntry(area=p.area, prompt_id=p.id, note=text, created_at=now))
            p.status = PromptStatus.ANSWERED
            return "Noted."

    # --- commands -------------------------------------------------------------

    def summary(self, now: datetime) -> str:
        with self.db.session() as s:
            return weekly_summary(s, now, self.tz, self.settings(s)["learning_ratio"])

    def start_focus(self, args: list[str], now: datetime) -> str:
        with self.db.session() as s:
            minutes = self.settings(s)["focus_block_default_min"]
            if args:
                if args[0].isdigit():
                    minutes = int(args[0])
                else:
                    d = parse_duration(args[0])
                    if d is None:
                        return "Usage: /focus [minutes], e.g. /focus 50"
                    minutes = int(d.total_seconds() // 60)
            if not 1 <= minutes <= 240:
                return "Pick between 1 and 240 minutes."
            end = now + timedelta(minutes=minutes)
            s.add(Prompt(area=Area.FOCUS, kind="focus_end", scheduled_for=end, payload={"minutes": minutes}))
        return f"Focus block started: {minutes} min, ends {end.astimezone(self.tz):%H:%M}."

    def pause(self, args: list[str], now: datetime) -> str:
        area, until, rest = None, None, []
        for a in args:
            if a.lower() in AREA_ALIASES:
                area = AREA_ALIASES[a.lower()]
            elif a.lower() == "all":
                area = None
            elif (d := parse_duration(a)) is not None:
                until = now + d
            else:
                rest.append(a)
        if rest:
            return "Usage: /pause [movement|focus|learning|hobby|all] [duration like 3h or 2d]"
        with self.db.session() as s:
            s.add(Pause(area=area, until=until, created_at=now))
        what = area.value if area else "everything"
        when = f"until {until.astimezone(self.tz):%a %H:%M}" if until else "until /resume"
        return f"Paused {what} {when}."

    def resume(self, args: list[str], now: datetime) -> str:
        area = AREA_ALIASES.get(args[0].lower()) if args else None
        with self.db.session() as s:
            q = select(Pause)
            if area:
                q = q.where(Pause.area == area)
            pauses = s.scalars(q).all()
            for p in pauses:
                s.delete(p)
        return f"Resumed {area.value if area else 'everything'}." if pauses else "Nothing was paused."

    def status(self, now: datetime) -> str:
        today = self.today(now)
        _, end = local_day_bounds(today, self.tz)
        with self.db.session() as s:
            lines = []
            pauses = [
                p for p in s.scalars(select(Pause)) if p.until is None or p.until > now
            ]
            for p in pauses:
                what = p.area.value if p.area else "everything"
                when = f"until {p.until.astimezone(self.tz):%a %H:%M}" if p.until else "until /resume"
                lines.append(f"Paused: {what} {when}")

            upcoming = s.scalars(
                select(Prompt)
                .where(
                    Prompt.status == PromptStatus.SCHEDULED,
                    Prompt.scheduled_for > now,
                    Prompt.scheduled_for < end,
                )
                .order_by(Prompt.scheduled_for)
            ).all()
            if upcoming:
                lines.append("<b>Still to come today</b>")
                lines += [
                    f"{p.scheduled_for.astimezone(self.tz):%H:%M} {p.kind.replace('_', ' ')}"
                    for p in upcoming
                ]
            else:
                lines.append("No more prompts today.")

            streaks = [(a, sel.streak(s, a, today, self.tz)) for a in Area]
            if any(n for _, n in streaks):
                lines.append("<b>Streaks</b>")
                lines += [f"{a.value}: {n} day{'s' if n != 1 else ''}" for a, n in streaks if n]
        return "\n".join(lines)

    def log(self, args: list[str], now: datetime) -> tuple[str, list[list[Button]]]:
        """Ad-hoc log, e.g. '/log run 30m' or '/log hobby guitar'. Asks for the area if unclear."""
        if not args:
            return "Usage: /log <what> [duration], e.g. /log run 30m", []
        minutes = None
        if (d := parse_duration(args[-1])) is not None:
            minutes = int(d.total_seconds() // 60)
            args = args[:-1]
        area = AREA_ALIASES.get(args[0].lower()) if args else None
        if area:
            args = args[1:]
        label = " ".join(args).strip()
        if not label and not area:
            return "What did you do? e.g. /log run 30m", []

        with self.db.session() as s:
            entry = LogEntry(
                area=area or Area.MOVEMENT, outcome=Outcome.DONE, label=label or None,
                duration_min=minutes, created_at=now,
            )
            matched = self._match_item(s, label, area, entry)
            if area or matched:
                s.add(entry)
                return f"Logged {entry.area.value}: {label or '(no label)'}" + (
                    f", {minutes} min" if minutes else ""
                ) + ".", []

        token = secrets.token_hex(4)
        self._pending_logs[token] = (label, minutes)
        buttons = [[Button(a.value.title(), f"l:{token}:{a.value}") for a in Area]]
        return f"Which area is “{html.escape(label)}”?", buttons

    def finish_log(self, token: str, area_value: str, now: datetime) -> str:
        pending = self._pending_logs.pop(token, None)
        if pending is None:
            return "That log request expired; please /log it again."
        label, minutes = pending
        with self.db.session() as s:
            s.add(LogEntry(area=Area(area_value), outcome=Outcome.DONE, label=label,
                           duration_min=minutes, created_at=now))
        return f"Logged {area_value}: {label}" + (f", {minutes} min" if minutes else "") + "."


def complete_course(s, course: Course, now: datetime) -> list[str]:
    """Mark a course complete and describe what that finishes or unlocks (paths, projects)."""
    if course.completed_at:
        return []
    course.completed_at = now
    s.flush()
    lines = [f"Course complete: <b>{html.escape(course.name)}</b>"]
    path = course.path
    if path is not None and path.completed:
        lines.append(f"Path complete: <b>{html.escape(path.name)}</b>")

    conds = [HobbyProject.requires_course_id == course.id]
    if path is not None:
        conds.append(HobbyProject.requires_path_id == path.id)
    for proj in s.scalars(select(HobbyProject).where(or_(*conds))):
        if proj.unlocked:
            lines.append(f"Unlocked: {html.escape(proj.hobby.name)} · {html.escape(proj.name)}")
    return ["\n".join(lines)]

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

from sqlalchemy import select

from app import selection as sel
from app.db import Database
from app.defaults import DEFAULT_SETTINGS
from app.models import (
    Area,
    Hobby,
    HobbyElement,
    LearningPath,
    LogEntry,
    MicroMove,
    Outcome,
    PathKind,
    PathStep,
    Pause,
    Prompt,
    PromptStatus,
    Routine,
    Setting,
)
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

    def plan_day(self, day: date) -> int:
        """Create the day's prompts unless already planned. Returns how many were created."""
        start, end = local_day_bounds(day, self.tz)
        with self.db.session() as s:
            already = s.scalar(
                select(Prompt.id).where(
                    Prompt.scheduled_for >= start,
                    Prompt.scheduled_for < end,
                    Prompt.kind != "focus_end",
                )
            )
            if already:
                return 0

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

            created = 0
            for area, kind, when in sorted(planned, key=lambda x: x[2]):
                if in_quiet_hours(when, cfg["quiet_hours"], self.tz):
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
                user_started = p.kind == "focus_end"
                if not user_started and (
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
        steps = "\n".join(f"{i}. {html.escape(st.text)}" for i, st in enumerate(r.steps, 1))
        return f"{head}\n{steps}" if steps else head

    def _session_text(self, s, kind: str, payload: dict) -> str:
        """Render the current candidate; also records the chosen element/step in payload."""
        item_id = payload["candidates"][payload["idx"]]
        if kind == "learning":
            path = s.get(LearningPath, item_id)
            head = f"<b>Learning ({path.category.value}): {html.escape(path.name)}</b>"
            payload.pop("step_id", None)
            if path.kind == PathKind.STEPS:
                step = sel.next_step(path)
                if step is None:
                    return f"{head}\nAll steps done; mark the path complete in the admin page."
                payload["step_id"] = step.id
                body = f"Next: {html.escape(step.title)}"
                if step.detail:
                    body += f"\n{html.escape(step.detail)}"
            elif path.kind == PathKind.TIME:
                body = f"Goal: {path.daily_goal_min or 20} min today"
            else:
                body = "Flashcard review (Telegram reviews arrive in a later version)."
            return f"{head}\n{body}"

        hobby = s.get(Hobby, item_id)
        element = sel.pick_element(s, hobby)
        payload["element_id"] = element.id if element else None
        text = f"<b>Hobby time: {html.escape(hobby.name)}</b>"
        if element:
            text += f"\nSuggestion: {html.escape(element.name)}"
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
            e.path_id = payload["candidates"][payload["idx"]]
            e.path_step_id = payload.get("step_id")
            path = s.get(LearningPath, e.path_id)
            if path.kind == PathKind.TIME and outcome == Outcome.DONE:
                e.duration_min = path.daily_goal_min
        elif p.kind == "hobby":
            e.hobby_id = payload["candidates"][payload["idx"]]
            e.hobby_element_id = payload.get("element_id")
        return e

    def _complete_step(self, s, step_id: int, now: datetime) -> list[str]:
        """Mark a step done; if it was the path's last, complete the path and announce unlocks."""
        step = s.get(PathStep, step_id)
        if step is None or step.done_at:
            return []
        step.done_at = now
        path = step.path
        if any(st.done_at is None for st in path.steps):
            return []
        path.completed_at = now
        msgs = [f"Path complete: <b>{html.escape(path.name)}</b>"]
        for el in s.scalars(select(HobbyElement).where(HobbyElement.requires_path_id == path.id)):
            msgs.append(f"Unlocked: {html.escape(el.hobby.name)} · {html.escape(el.name)}")
        return ["\n".join(msgs)]

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

    def _match_item(self, s, label: str, area: Area | None, entry: LogEntry) -> bool:
        """Link the log to a known hobby, learning path or routine by name."""
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
            for p in s.scalars(select(LearningPath)):
                if hit(p.name):
                    entry.area, entry.path_id = Area.LEARNING, p.id
                    return True
        if area in (None, Area.MOVEMENT):
            for r in s.scalars(select(Routine)):
                if hit(r.name):
                    entry.area, entry.routine_id = Area.MOVEMENT, r.id
                    return True
        return False

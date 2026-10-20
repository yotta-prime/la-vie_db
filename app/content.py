"""Load learning content from content/*.yaml into the database at startup.

Add-only: an item is created the first time its `key` is seen. After that, the only change
import makes is filling in a `url` the item doesn't have yet (e.g. a recording issued later);
renames, reordering, completions, links and deletions made in the admin page are kept. (A deleted
item whose key is still in the file comes back on the next start; remove it from the file
too.) New lessons are appended to the end of their course.

File format (see content/oreilly.yaml):

    paths:
      - key, name, category, sequential?, description?
        courses: [course, ...]
    courses:            # individual courses, not in a path
      - key, name, category, kind?, url?, notes?, daily_goal_min?
        lessons:
          - key, title, detail?, url?
            date?, time?, presenters?, attendance?   # live events; time "HH:MM" UK local;
                                                     # attendance registered|waitlisted|attended|missed
    routines:           # movement lessons from an outside course (e.g. DailyOM), offered in order
      - key, name, url?                              # the course
        lessons:
          - key, title, url?, section?, section_url?, duration_min?
            intro?, outro?                           # text before / after the video
            moves: [text, ...]                       # individual movements, in order

Files in content/ are public (the repo is). Paid or private material goes in the data folder
instead (`<DATA_DIR>/content/*.yaml`; on the NAS `/volume1/docker/lavie/data/content/`), which
is imported the same way but never committed.
"""

import logging
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Database
from app.models import (
    Attendance,
    Category,
    Course,
    CourseKind,
    CourseStep,
    LearningPath,
    Routine,
    RoutineStep,
    utcnow,
)

log = logging.getLogger(__name__)

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"


def _by_key(s: Session, model, key: str):
    return s.scalar(select(model).where(model.source_key == key))


def _course(s: Session, data: dict, path: LearningPath | None, counts: dict) -> None:
    course = _by_key(s, Course, data["key"])
    if course is None:
        position = len(path.courses) if path is not None else 0
        course = Course(
            source_key=data["key"],
            name=data["name"],
            category=Category(data.get("category") or (path.category.value if path else "professional")),
            kind=CourseKind(data.get("kind", "steps")),
            daily_goal_min=data.get("daily_goal_min"),
            url=data.get("url"),
            notes=data.get("notes"),
            path=path,
            position=position,
        )
        s.add(course)
        s.flush()
        counts["courses"] += 1
    elif course.url is None and data.get("url"):
        course.url = data["url"]
        counts["links"] += 1

    for lesson in data.get("lessons", []):
        step = _by_key(s, CourseStep, lesson["key"])
        if step is not None:
            # Fill in what the item doesn't have yet (e.g. a recording issued later, or event
            # fields added to the file); never overwrite values set in the admin page or Telegram.
            if step.url is None and lesson.get("url"):
                step.url = lesson["url"]
                counts["links"] += 1
            for field, value in _event_fields(lesson).items():
                if getattr(step, field) is None and value is not None:
                    setattr(step, field, value)
            continue
        course.steps.append(
            CourseStep(
                source_key=lesson["key"],
                position=len(course.steps),
                title=lesson["title"],
                detail=lesson.get("detail"),
                url=lesson.get("url"),
                # A link that comes with a new lesson is already known; only links filled in
                # later (e.g. a recording issued after the event) trigger a "recording ready" message.
                recording_notified_at=utcnow() if lesson.get("url") else None,
                **_event_fields(lesson),
            )
        )
        counts["lessons"] += 1


def _event_fields(lesson: dict) -> dict:
    """Optional live-event fields: date (YYYY-MM-DD), presenters, attendance."""
    attendance = lesson.get("attendance")
    return {
        "event_date": lesson.get("date"),  # YAML parses ISO dates to datetime.date
        "event_time": _hhmm(lesson.get("time")),
        "presenters": lesson.get("presenters"),
        "attendance": Attendance(attendance) if attendance else None,
    }


def _hhmm(value) -> str | None:
    """`time: "17:00"`. Unquoted, YAML reads 17:00 as base-60 (1020), so accept that too."""
    if value is None:
        return None
    if isinstance(value, int):
        value = f"{value // 60:02d}:{value % 60:02d}"
    h, m = str(value).split(":")
    return f"{int(h):02d}:{int(m):02d}"


def _routines(s: Session, series: dict, counts: dict) -> None:
    for pos, lesson in enumerate(series.get("lessons", [])):
        r = _by_key(s, Routine, lesson["key"])
        if r is not None:
            for field, value in (("url", lesson.get("url")), ("section_url", lesson.get("section_url")),
                                 ("series_url", series.get("url"))):
                if getattr(r, field) is None and value:
                    setattr(r, field, value)
                    counts["links"] += 1
            # The lesson text isn't editable in the admin page, so the file is its source: refresh it
            # (e.g. after a better export). Names, links, order and moves stay as edited.
            if (r.intro, r.outro) != (lesson.get("intro"), lesson.get("outro")):
                r.intro, r.outro = lesson.get("intro"), lesson.get("outro")
                counts["texts"] += 1
            continue
        s.add(
            Routine(
                source_key=lesson["key"],
                name=lesson["title"],
                duration_min=lesson.get("duration_min"),
                url=lesson.get("url"),
                series=series["name"],
                series_url=series.get("url"),
                section=lesson.get("section"),
                section_url=lesson.get("section_url"),
                position=pos,
                intro=lesson.get("intro"),
                outro=lesson.get("outro"),
                steps=[RoutineStep(position=i, text=m) for i, m in enumerate(lesson.get("moves") or [])],
            )
        )
        counts["routines"] += 1


def import_file(db: Database, file: Path) -> dict:
    data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    counts = {"paths": 0, "courses": 0, "lessons": 0, "routines": 0, "links": 0, "texts": 0}
    with db.session() as s:
        for p in data.get("paths", []):
            path = _by_key(s, LearningPath, p["key"])
            if path is None:
                path = LearningPath(
                    source_key=p["key"],
                    name=p["name"],
                    category=Category(p.get("category", "professional")),
                    description=p.get("description"),
                    sequential=p.get("sequential", True),
                )
                s.add(path)
                s.flush()
                counts["paths"] += 1
            for c in p.get("courses", []):
                _course(s, c, path, counts)
        for c in data.get("courses", []):
            _course(s, c, None, counts)
        for r in data.get("routines", []):
            _routines(s, r, counts)
    return counts


def import_content(db: Database, *dirs: Path) -> None:
    """Import every *.yaml file in content/ (and any extra folders, e.g. the private one in the
    data folder). A broken file is logged and skipped, never fatal."""
    for content_dir in dirs or (CONTENT_DIR,):
        if not content_dir.is_dir():
            continue
        for file in sorted(content_dir.glob("*.yaml")):
            try:
                counts = import_file(db, file)
            except Exception:
                log.exception("Content import failed for %s; skipped", file.name)
                continue
            if any(counts.values()):
                log.info("Imported %s: %d paths, %d courses, %d lessons, %d routines added; %d links filled in; %d lesson texts refreshed",
                         file.name, counts["paths"], counts["courses"], counts["lessons"], counts["routines"],
                         counts["links"], counts["texts"])

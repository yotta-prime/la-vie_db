"""Load learning content from content/*.yaml into the database at startup.

Add-only: an item is created the first time its `key` is seen and never touched again, so
renames, reordering, completions and deletions made in the admin page are kept. (A deleted
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
"""

import logging
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Database
from app.models import Category, Course, CourseKind, CourseStep, LearningPath

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

    for lesson in data.get("lessons", []):
        if _by_key(s, CourseStep, lesson["key"]) is not None:
            continue
        course.steps.append(
            CourseStep(
                source_key=lesson["key"],
                position=len(course.steps),
                title=lesson["title"],
                detail=lesson.get("detail"),
                url=lesson.get("url"),
            )
        )
        counts["lessons"] += 1


def import_file(db: Database, file: Path) -> dict:
    data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    counts = {"paths": 0, "courses": 0, "lessons": 0}
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
    return counts


def import_content(db: Database, content_dir: Path = CONTENT_DIR) -> None:
    """Import every content/*.yaml file. A broken file is logged and skipped, never fatal."""
    if not content_dir.is_dir():
        return
    for file in sorted(content_dir.glob("*.yaml")):
        try:
            counts = import_file(db, file)
        except Exception:
            log.exception("Content import failed for %s; skipped", file.name)
            continue
        if any(counts.values()):
            log.info("Imported %s: %d paths, %d courses, %d lessons added",
                     file.name, counts["paths"], counts["courses"], counts["lessons"])

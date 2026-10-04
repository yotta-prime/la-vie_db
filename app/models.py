"""Database tables. See docs/SPEC.md for the domain.

Learning is organised as:
    LearningPath (optional container, e.g. "Cloud architect")
      └─ Course (the unit you study in a session; can also stand alone)
           ├─ CourseStep (lessons/chapters, for "steps" courses)
           └─ Flashcard (for "srs" courses)

Hobbies have HobbyProjects, which can require a course or a whole path to be completed first.
"""

import enum
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stores datetimes as UTC and returns them timezone-aware (SQLite drops tzinfo)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; use timezone-aware values")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


def _enum(cls: type[enum.Enum]) -> Enum:
    # Store enum values as plain strings so the DB stays readable and easy to migrate.
    return Enum(cls, native_enum=False, values_callable=lambda e: [m.value for m in e], length=32)


class Area(str, enum.Enum):
    MOVEMENT = "movement"
    FOCUS = "focus"
    LEARNING = "learning"
    HOBBY = "hobby"


class Category(str, enum.Enum):
    PROFESSIONAL = "professional"
    HOBBY = "hobby"


class CourseKind(str, enum.Enum):
    STEPS = "steps"  # ordered lessons
    TIME = "time"  # time-based goal
    SRS = "srs"  # spaced-repetition flashcards


class PickMethod(str, enum.Enum):
    ROUND_ROBIN = "round_robin"
    NEGLECT = "neglect"
    WEEKDAY_SLOTS = "weekday_slots"


class PromptStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    SENT = "sent"
    ANSWERED = "answered"
    SKIPPED = "skipped"  # dropped by pause, quiet hours, or nothing to suggest
    EXPIRED = "expired"


class Outcome(str, enum.Enum):
    DONE = "done"
    PARTIAL = "partial"
    SKIP = "skip"


# --- Settings -----------------------------------------------------------------


class Setting(Base):
    """Key/value settings edited in the admin page (prompt times, quiet hours, ratios...)."""

    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


# --- Movement -----------------------------------------------------------------


class Routine(Base):
    __tablename__ = "routine"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    duration_min: Mapped[int | None]
    url: Mapped[str | None] = mapped_column(String(500))  # e.g. a full-class video
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(default=True)

    steps: Mapped[list["RoutineStep"]] = relationship(
        back_populates="routine", order_by="RoutineStep.position", cascade="all, delete-orphan"
    )


class RoutineStep(Base):
    """One item in a routine: an exercise, or a video/link (YouTube, DailyOM...)."""

    __tablename__ = "routine_step"

    id: Mapped[int] = mapped_column(primary_key=True)
    routine_id: Mapped[int] = mapped_column(ForeignKey("routine.id", ondelete="CASCADE"))
    position: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(500))
    duration_sec: Mapped[int | None]

    routine: Mapped[Routine] = relationship(back_populates="steps")


class MicroMove(Base):
    """Short desk-break movements, picked at random during work hours."""

    __tablename__ = "micro_move"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(default=True)


# --- Learning -----------------------------------------------------------------


class LearningPath(Base):
    """A group of courses. Sequential paths offer only their first unfinished course."""

    __tablename__ = "learning_path"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[Category] = mapped_column(_enum(Category))
    description: Mapped[str | None] = mapped_column(Text)
    sequential: Mapped[bool] = mapped_column(default=True)
    active: Mapped[bool] = mapped_column(default=True)

    courses: Mapped[list["Course"]] = relationship(
        back_populates="path", order_by="Course.position"
    )

    @property
    def completed(self) -> bool:
        return bool(self.courses) and all(c.completed_at for c in self.courses)


class Course(Base):
    __tablename__ = "course"

    id: Mapped[int] = mapped_column(primary_key=True)
    path_id: Mapped[int | None] = mapped_column(ForeignKey("learning_path.id", ondelete="SET NULL"))
    position: Mapped[int] = mapped_column(default=0)  # order within the path
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[Category] = mapped_column(_enum(Category))
    kind: Mapped[CourseKind] = mapped_column(_enum(CourseKind), default=CourseKind.STEPS)
    daily_goal_min: Mapped[int | None]  # for TIME courses
    url: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(default=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    path: Mapped[LearningPath | None] = relationship(back_populates="courses")
    steps: Mapped[list["CourseStep"]] = relationship(
        back_populates="course", order_by="CourseStep.position", cascade="all, delete-orphan"
    )
    flashcards: Mapped[list["Flashcard"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )


class CourseStep(Base):
    __tablename__ = "course_step"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id", ondelete="CASCADE"))
    position: Mapped[int]
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(500))
    done_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    course: Mapped[Course] = relationship(back_populates="steps")


class Flashcard(Base):
    __tablename__ = "flashcard"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id", ondelete="CASCADE"))
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text)
    # Serialized FSRS card state; `due` is duplicated as a column for querying.
    fsrs_state: Mapped[dict | None] = mapped_column(JSON)
    due: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    course: Mapped[Course] = relationship(back_populates="flashcards")


# --- Hobbies ------------------------------------------------------------------


class Hobby(Base):
    __tablename__ = "hobby"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(default=True)

    projects: Mapped[list["HobbyProject"]] = relationship(
        back_populates="hobby", order_by="HobbyProject.id", cascade="all, delete-orphan"
    )


class HobbyProject(Base):
    """Something to do within a hobby, optionally locked until a course or path is completed."""

    __tablename__ = "hobby_project"

    id: Mapped[int] = mapped_column(primary_key=True)
    hobby_id: Mapped[int] = mapped_column(ForeignKey("hobby.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(160))
    url: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    requires_course_id: Mapped[int | None] = mapped_column(ForeignKey("course.id", ondelete="SET NULL"))
    requires_path_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_path.id", ondelete="SET NULL")
    )
    active: Mapped[bool] = mapped_column(default=True)
    done_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    hobby: Mapped[Hobby] = relationship(back_populates="projects")
    requires_course: Mapped[Course | None] = relationship()
    requires_path: Mapped[LearningPath | None] = relationship()

    @property
    def unlocked(self) -> bool:
        if self.requires_course is not None and self.requires_course.completed_at is None:
            return False
        if self.requires_path is not None and not self.requires_path.completed:
            return False
        return True


# --- Scheduling ---------------------------------------------------------------


class ScheduleRule(Base):
    """Per-item selection rules for a hobby or a course (exactly one of the two)."""

    __tablename__ = "schedule_rule"
    __table_args__ = (
        CheckConstraint("(hobby_id IS NULL) != (course_id IS NULL)", name="rule_targets_one_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    hobby_id: Mapped[int | None] = mapped_column(ForeignKey("hobby.id", ondelete="CASCADE"))
    course_id: Mapped[int | None] = mapped_column(ForeignKey("course.id", ondelete="CASCADE"))
    method: Mapped[PickMethod] = mapped_column(_enum(PickMethod), default=PickMethod.ROUND_ROBIN)
    sessions_per_week: Mapped[int | None]
    weekdays: Mapped[list[int] | None] = mapped_column(JSON)  # 0=Mon, for WEEKDAY_SLOTS
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    weight: Mapped[float] = mapped_column(Float, default=1.0)


class Pause(Base):
    """An active pause. area NULL means everything is paused."""

    __tablename__ = "pause"

    id: Mapped[int] = mapped_column(primary_key=True)
    area: Mapped[Area | None] = mapped_column(_enum(Area))
    until: Mapped[datetime | None] = mapped_column(UTCDateTime)  # NULL = until /resume
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# --- Prompts and logs ---------------------------------------------------------


class Prompt(Base):
    __tablename__ = "prompt"

    id: Mapped[int] = mapped_column(primary_key=True)
    area: Mapped[Area] = mapped_column(_enum(Area))
    kind: Mapped[str] = mapped_column(String(40))  # e.g. "routine", "micro_move", "intention"
    payload: Mapped[dict | None] = mapped_column(JSON)  # item ids / rendered context
    scheduled_for: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[PromptStatus] = mapped_column(
        _enum(PromptStatus), default=PromptStatus.SCHEDULED
    )


class LogEntry(Base):
    __tablename__ = "log_entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    area: Mapped[Area] = mapped_column(_enum(Area))
    prompt_id: Mapped[int | None] = mapped_column(ForeignKey("prompt.id", ondelete="SET NULL"))

    # What was done (all optional; ad-hoc logs may only have `label`).
    label: Mapped[str | None] = mapped_column(String(200))
    routine_id: Mapped[int | None] = mapped_column(ForeignKey("routine.id", ondelete="SET NULL"))
    course_id: Mapped[int | None] = mapped_column(ForeignKey("course.id", ondelete="SET NULL"))
    course_step_id: Mapped[int | None] = mapped_column(ForeignKey("course_step.id", ondelete="SET NULL"))
    hobby_id: Mapped[int | None] = mapped_column(ForeignKey("hobby.id", ondelete="SET NULL"))
    hobby_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("hobby_project.id", ondelete="SET NULL")
    )

    outcome: Mapped[Outcome | None] = mapped_column(_enum(Outcome))
    duration_min: Mapped[int | None]
    rating: Mapped[int | None]  # focus reflection 1-5
    note: Mapped[str | None] = mapped_column(Text)

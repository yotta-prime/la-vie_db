"""Database tables. See docs/SPEC.md for the domain."""

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

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _enum(cls: type[enum.Enum]) -> Enum:
    # Store enum values as plain strings so the DB stays readable and easy to migrate.
    return Enum(cls, native_enum=False, values_callable=lambda e: [m.value for m in e], length=32)


class Area(str, enum.Enum):
    MOVEMENT = "movement"
    FOCUS = "focus"
    LEARNING = "learning"
    HOBBY = "hobby"


class PathCategory(str, enum.Enum):
    PROFESSIONAL = "professional"
    HOBBY = "hobby"


class PathKind(str, enum.Enum):
    STEPS = "steps"  # ordered step list
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
    SKIPPED = "skipped"  # dropped by pause or quiet hours
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
    active: Mapped[bool] = mapped_column(default=True)

    steps: Mapped[list["RoutineStep"]] = relationship(
        back_populates="routine", order_by="RoutineStep.position", cascade="all, delete-orphan"
    )


class RoutineStep(Base):
    __tablename__ = "routine_step"

    id: Mapped[int] = mapped_column(primary_key=True)
    routine_id: Mapped[int] = mapped_column(ForeignKey("routine.id", ondelete="CASCADE"))
    position: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    duration_sec: Mapped[int | None]

    routine: Mapped[Routine] = relationship(back_populates="steps")


class MicroMove(Base):
    """Short desk-break movements, picked at random during work hours."""

    __tablename__ = "micro_move"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(default=True)


# --- Learning paths -----------------------------------------------------------


class LearningPath(Base):
    __tablename__ = "learning_path"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[PathCategory] = mapped_column(_enum(PathCategory))
    kind: Mapped[PathKind] = mapped_column(_enum(PathKind))
    daily_goal_min: Mapped[int | None]  # for TIME paths
    active: Mapped[bool] = mapped_column(default=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    steps: Mapped[list["PathStep"]] = relationship(
        back_populates="path", order_by="PathStep.position", cascade="all, delete-orphan"
    )
    flashcards: Mapped[list["Flashcard"]] = relationship(
        back_populates="path", cascade="all, delete-orphan"
    )


class PathStep(Base):
    __tablename__ = "path_step"

    id: Mapped[int] = mapped_column(primary_key=True)
    path_id: Mapped[int] = mapped_column(ForeignKey("learning_path.id", ondelete="CASCADE"))
    position: Mapped[int]
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(Text)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    path: Mapped[LearningPath] = relationship(back_populates="steps")


class Flashcard(Base):
    __tablename__ = "flashcard"

    id: Mapped[int] = mapped_column(primary_key=True)
    path_id: Mapped[int] = mapped_column(ForeignKey("learning_path.id", ondelete="CASCADE"))
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text)
    # Serialized FSRS card state; `due` is duplicated as a column for querying.
    fsrs_state: Mapped[dict | None] = mapped_column(JSON)
    due: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    path: Mapped[LearningPath] = relationship(back_populates="flashcards")


# --- Hobbies ------------------------------------------------------------------


class Hobby(Base):
    __tablename__ = "hobby"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(default=True)

    elements: Mapped[list["HobbyElement"]] = relationship(
        back_populates="hobby", cascade="all, delete-orphan"
    )


class HobbyElement(Base):
    """A sub-activity of a hobby, optionally locked until a learning path is completed."""

    __tablename__ = "hobby_element"

    id: Mapped[int] = mapped_column(primary_key=True)
    hobby_id: Mapped[int] = mapped_column(ForeignKey("hobby.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    requires_path_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_path.id", ondelete="SET NULL")
    )

    hobby: Mapped[Hobby] = relationship(back_populates="elements")
    requires_path: Mapped[LearningPath | None] = relationship()

    @property
    def unlocked(self) -> bool:
        return self.requires_path is None or self.requires_path.completed_at is not None


# --- Scheduling ---------------------------------------------------------------


class ScheduleRule(Base):
    """Per-item selection rules for a hobby or a learning path (exactly one of the two)."""

    __tablename__ = "schedule_rule"
    __table_args__ = (
        CheckConstraint(
            "(hobby_id IS NULL) != (path_id IS NULL)", name="rule_targets_one_item"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    hobby_id: Mapped[int | None] = mapped_column(ForeignKey("hobby.id", ondelete="CASCADE"))
    path_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_path.id", ondelete="CASCADE")
    )
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
    until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # NULL = until /resume
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --- Prompts and logs ---------------------------------------------------------


class Prompt(Base):
    __tablename__ = "prompt"

    id: Mapped[int] = mapped_column(primary_key=True)
    area: Mapped[Area] = mapped_column(_enum(Area))
    kind: Mapped[str] = mapped_column(String(40))  # e.g. "routine", "micro_move", "intention"
    payload: Mapped[dict | None] = mapped_column(JSON)  # item ids / rendered context
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_message_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[PromptStatus] = mapped_column(
        _enum(PromptStatus), default=PromptStatus.SCHEDULED
    )


class LogEntry(Base):
    __tablename__ = "log_entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    area: Mapped[Area] = mapped_column(_enum(Area))
    prompt_id: Mapped[int | None] = mapped_column(ForeignKey("prompt.id", ondelete="SET NULL"))

    # What was done (all optional; ad-hoc logs may only have `label`).
    label: Mapped[str | None] = mapped_column(String(200))
    routine_id: Mapped[int | None] = mapped_column(ForeignKey("routine.id", ondelete="SET NULL"))
    path_id: Mapped[int | None] = mapped_column(ForeignKey("learning_path.id", ondelete="SET NULL"))
    path_step_id: Mapped[int | None] = mapped_column(ForeignKey("path_step.id", ondelete="SET NULL"))
    hobby_id: Mapped[int | None] = mapped_column(ForeignKey("hobby.id", ondelete="SET NULL"))
    hobby_element_id: Mapped[int | None] = mapped_column(
        ForeignKey("hobby_element.id", ondelete="SET NULL")
    )

    outcome: Mapped[Outcome | None] = mapped_column(_enum(Outcome))
    duration_min: Mapped[int | None]
    rating: Mapped[int | None]  # focus reflection 1-5
    note: Mapped[str | None] = mapped_column(Text)

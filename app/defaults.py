"""Default settings seeded on first run (spec: "Defaults"). Editable later in the admin page."""

DEFAULT_SETTINGS: dict[str, object] = {
    "work_days": [0, 1, 2, 3, 4],  # Mon-Fri
    "work_hours": {"start": "09:00", "end": "17:00"},
    "quiet_hours": {"start": "21:00", "end": "06:00"},
    "prompt_times": {
        "movement_routine": "06:30",
        "focus_intention": "08:00",
        "learning_session": "17:30",
        "hobby_session": "19:00",
        "focus_reflection": "20:30",
    },
    "micro_move_interval_min": 60,
    "distraction_checks_per_day": 2,
    "learning_ratio": {"professional": 0.85, "hobby": 0.15},
    "focus_block_default_min": 25,
    "weekly_summary": {"weekday": 6, "time": "18:00"},  # Sunday
    # Movement prompts go out only in the slots ticked on the admin Movement plan.
    # source: "rotation" (own routines and course lessons take turns), "own" (own routines),
    # or "series:<course name>" (that course's lessons, in order).
    "movement_slots": {
        "morning": {"time": "06:30", "source": "rotation"},
        "evening": {"time": "18:00", "source": "rotation"},
        "night": {"time": "20:30", "source": "rotation"},
    },
    "backup_time": "03:00",
}


STARTER_MICRO_MOVES = [
    "Stand up and roll your shoulders back 10 times.",
    "Neck stretch: ear to shoulder, 20 seconds each side.",
    "Walk for 2 minutes: get water, take the stairs.",
    "Calf raises: 15 slow reps.",
    "Chest opener: clasp hands behind your back, lift and hold 20 seconds.",
    "Look at something 6 m away for 20 seconds; blink slowly.",
    "Hip flexor stretch: half-kneel, 30 seconds each side.",
    "Wrist circles and finger stretches, 30 seconds.",
]

STARTER_ROUTINE = (
    "Morning mobility",
    10,
    [
        "Cat-cow, 10 reps",
        "World's greatest stretch, 5 per side",
        "Hip circles, 10 each way",
        "Bodyweight squats, 15 reps",
        "Arm circles, 20 seconds each way",
        "Deep breathing, 1 minute",
    ],
)


def seed_content(db) -> None:
    """Starter micro-moves and one routine, only if none exist yet. Edit or delete them freely."""
    from app.models import MicroMove, Routine, RoutineStep

    with db.session() as s:
        if not s.query(MicroMove).first():
            s.add_all(MicroMove(text=t) for t in STARTER_MICRO_MOVES)
        if not s.query(Routine).first():
            name, minutes, steps = STARTER_ROUTINE
            s.add(
                Routine(
                    name=name,
                    duration_min=minutes,
                    steps=[RoutineStep(position=i, text=t) for i, t in enumerate(steps)],
                )
            )


def seed_movement_plan(db, today) -> None:
    """Once, when the Movement plan arrives: keep the daily morning routine going by ticking
    mornings from today to the end of the month, at the morning time already set."""
    import calendar
    from datetime import timedelta

    from app.models import MovementPlan, Setting

    with db.session() as s:
        if s.get(Setting, "movement_plan_seeded"):
            return
        old = (s.get(Setting, "prompt_times").value or {}) if s.get(Setting, "prompt_times") else {}
        slots = {k: dict(v) for k, v in DEFAULT_SETTINGS["movement_slots"].items()}
        slots["morning"]["time"] = old.get("movement_routine", slots["morning"]["time"])
        row = s.get(Setting, "movement_slots")  # seed_settings may have added the defaults
        if row is None:
            s.add(Setting(key="movement_slots", value=slots))
        else:
            row.value = slots
        last = today.replace(day=calendar.monthrange(today.year, today.month)[1])
        day = today
        while day <= last:
            s.add(MovementPlan(day=day, slot="morning"))
            day += timedelta(days=1)
        s.add(Setting(key="movement_plan_seeded", value=True))


def seed_settings(db) -> None:
    from app.models import Setting

    with db.session() as s:
        existing = {k for (k,) in s.query(Setting.key)}
        for key, value in DEFAULT_SETTINGS.items():
            if key not in existing:
                s.add(Setting(key=key, value=value))

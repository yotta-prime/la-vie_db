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
    "backup_time": "03:00",
}


def seed_settings(db) -> None:
    from app.models import Setting

    with db.session() as s:
        existing = {k for (k,) in s.query(Setting.key)}
        for key, value in DEFAULT_SETTINGS.items():
            if key not in existing:
                s.add(Setting(key=key, value=value))

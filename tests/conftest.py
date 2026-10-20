"""Tests never read a local .env: only what each test sets (or the defaults) applies."""

from datetime import date, timedelta

from app.config import Settings, get_settings

Settings.model_config["env_file"] = None
get_settings.cache_clear()


def tick_mornings(db, first=date(2026, 1, 1), last=date(2027, 12, 31)) -> None:
    """Plan the morning movement slot on every day in range (the Movement plan before any edits)."""
    from app.models import MovementPlan

    with db.session() as s:
        d = first
        while d <= last:
            s.add(MovementPlan(day=d, slot="morning"))
            d += timedelta(days=1)

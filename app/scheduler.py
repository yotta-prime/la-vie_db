"""Job scheduler: daily planning, the per-minute prompt dispatcher and bot watchdog, and the nightly backup."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.backup import backup_sqlite
from app.config import Settings


def build_scheduler(
    settings: Settings,
    backup_time: str = "03:00",
    plan_today: Callable[[], object] | None = None,
    dispatch: Callable[[], Awaitable[None]] | None = None,
    watchdog: Callable[[], object] | None = None,
) -> AsyncIOScheduler:
    tz = ZoneInfo(settings.timezone)
    scheduler = AsyncIOScheduler(timezone=tz)

    hour, minute = (int(x) for x in backup_time.split(":"))
    scheduler.add_job(
        backup_sqlite,
        CronTrigger(hour=hour, minute=minute, timezone=tz),
        args=[settings.db_path, settings.backup_dir, settings.backup_keep],
        id="nightly_backup",
        replace_existing=True,
    )

    if plan_today is not None:
        # Shortly after midnight, plus once at startup in case the service was down.
        scheduler.add_job(
            plan_today, CronTrigger(hour=0, minute=5, timezone=tz), id="plan_day", replace_existing=True
        )
        scheduler.add_job(plan_today, id="plan_day_startup", next_run_time=datetime.now(tz))

    if dispatch is not None:
        scheduler.add_job(
            dispatch,
            IntervalTrigger(seconds=60, timezone=tz),
            id="dispatch",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )

    if watchdog is not None:
        scheduler.add_job(
            watchdog,
            IntervalTrigger(seconds=60, timezone=tz),
            id="watchdog",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
    return scheduler

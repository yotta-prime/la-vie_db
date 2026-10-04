"""Job scheduler. Prompt jobs are added in a later step; for now, the nightly backup."""

from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.backup import backup_sqlite
from app.config import Settings


def build_scheduler(settings: Settings, backup_time: str = "03:00") -> AsyncIOScheduler:
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
    return scheduler

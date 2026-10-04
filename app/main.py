import logging
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from app.bot import Bot
from app.config import get_settings
from app.db import Database
from app.defaults import seed_content, seed_settings
from app.engine import Engine
from app.models import Setting
from app.scheduler import build_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx logs each request URL at INFO, and Telegram URLs contain the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    db = Database(f"sqlite:///{settings.db_path}")
    db.create_all()
    seed_settings(db)
    seed_content(db)

    with db.session() as s:
        backup_time = s.get(Setting, "backup_time").value

    tz = ZoneInfo(settings.timezone)
    engine = Engine(db, tz)
    bot = Bot(settings, engine)

    def plan_today() -> None:
        engine.plan_day(datetime.now(tz).date())

    scheduler = build_scheduler(settings, backup_time, plan_today=plan_today, dispatch=bot.dispatch_due)
    scheduler.start()

    await bot.start()

    app.state.db, app.state.bot, app.state.scheduler = db, bot, scheduler
    try:
        yield
    finally:
        await bot.stop()
        scheduler.shutdown(wait=False)
        db.engine.dispose()


app = FastAPI(title="la-vie", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "bot": app.state.bot.app is not None,
        "jobs": [j.id for j in app.state.scheduler.get_jobs()],
    }

import logging
import os
import signal
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Response

from app import admin, heartbeat
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
log = logging.getLogger(__name__)


def restart() -> None:
    """Exit so Docker's restart policy starts a fresh container.

    SIGTERM gives uvicorn a clean shutdown; if that hangs, exit hard after 30s.
    """
    timer = threading.Timer(30, lambda: os._exit(1))
    timer.daemon = True
    timer.start()
    os.kill(os.getpid(), signal.SIGTERM)


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

    def watchdog() -> None:
        bot.check_polling(restart)
        if bot.polling and not bot.stale:
            heartbeat.ping(settings.heartbeat_url)

    scheduler = build_scheduler(
        settings,
        backup_time,
        plan_today=plan_today,
        dispatch=bot.dispatch_due,
        watchdog=watchdog,
    )
    scheduler.start()

    await bot.start()

    app.state.db, app.state.engine, app.state.bot, app.state.scheduler = db, engine, bot, scheduler
    try:
        yield
    finally:
        await bot.stop()
        scheduler.shutdown(wait=False)
        db.engine.dispose()


app = FastAPI(title="la-vie", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
admin.install(app)


@app.get("/health")
def health(response: Response) -> dict:
    bot = app.state.bot
    age = bot.seconds_since_poll()
    if bot.stale:
        # 503 so Docker's health check (and anything else watching) sees the problem.
        response.status_code = 503
    return {
        "status": "stale" if bot.stale else "ok",
        "version": os.environ.get("APP_VERSION", "dev"),
        "bot": bot.app is not None,
        "polling": bot.polling,
        "last_poll_seconds_ago": None if age is None else round(age),
        "jobs": [j.id for j in app.state.scheduler.get_jobs()],
    }

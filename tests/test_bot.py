import asyncio
from types import SimpleNamespace

from app import bot as bot_module
from app.bot import POLL_RESTART_SECONDS, POLL_STALE_SECONDS, Bot, _PollRequest
from app.config import Settings


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def running_bot(monkeypatch, polling=True):
    clock = Clock()
    monkeypatch.setattr(bot_module.time, "monotonic", clock)
    bot = Bot(Settings(telegram_bot_token="x"))
    bot.app = SimpleNamespace(updater=SimpleNamespace(running=polling))
    bot._polled()
    return bot, clock


def test_not_running_is_never_stale_or_restarted():
    bot = Bot(Settings(telegram_bot_token=""))
    restarts = []
    bot.check_polling(lambda: restarts.append(1))
    assert bot.seconds_since_poll() is None and not bot.stale and not restarts


def test_stale_then_restart_when_polls_stop(monkeypatch):
    bot, clock = running_bot(monkeypatch)
    restarts = []

    clock.now += POLL_STALE_SECONDS - 1
    assert not bot.stale

    clock.now += 2
    assert bot.stale
    bot.check_polling(lambda: restarts.append(1))
    assert not restarts  # stale is reported first; restart waits longer

    clock.now += POLL_RESTART_SECONDS
    bot.check_polling(lambda: restarts.append(1))
    assert restarts == [1]


def test_successful_poll_resets_the_clock(monkeypatch):
    bot, clock = running_bot(monkeypatch)
    clock.now += POLL_RESTART_SECONDS + 1
    bot._polled()
    restarts = []
    bot.check_polling(lambda: restarts.append(1))
    assert bot.seconds_since_poll() == 0 and not bot.stale and not restarts


def test_restart_sooner_when_updater_has_stopped(monkeypatch):
    bot, clock = running_bot(monkeypatch, polling=False)
    restarts = []
    clock.now += POLL_STALE_SECONDS + 1
    assert bot.stale
    bot.check_polling(lambda: restarts.append(1))
    assert restarts == [1]


def test_poll_request_records_only_successful_answers(monkeypatch):
    calls = []
    req = _PollRequest(lambda: calls.append(1))
    answers = iter([(200, b"{}"), (409, b"{}"), (200, b"{}")])

    async def fake(self, *args, **kwargs):
        return next(answers)

    monkeypatch.setattr(bot_module.HTTPXRequest, "do_request", fake)
    for _ in range(3):
        asyncio.run(req.do_request("url", "POST"))
    assert calls == [1, 1]


def test_health_text(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "abc1234")
    bot, clock = running_bot(monkeypatch)
    clock.now += 3
    assert bot.health_text() == "<b>ok</b>\nversion: <code>abc1234</code>\npolling: yes\nlast poll: 3s ago"
    clock.now += POLL_STALE_SECONDS
    assert bot.health_text().startswith("<b>stale</b>")

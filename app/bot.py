"""Telegram bot connection. Uses long polling, so the NAS needs no inbound ports."""

import logging
from datetime import datetime, timezone

from telegram import BotCommand, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import Settings
from app.engine import Button, Engine, Outgoing

log = logging.getLogger(__name__)

COMMANDS = [
    ("status", "Today's remaining prompts, pauses and streaks"),
    ("summary", "This week so far"),
    ("focus", "Start a focus block: /focus 50"),
    ("log", "Log something: /log run 30m"),
    ("pause", "Pause prompts: /pause hobby 2d"),
    ("resume", "Resume prompts: /resume [area]"),
    ("help", "What I can do"),
]

HELP = (
    "<b>la-vie</b> sends prompts through the day. Tap the buttons to log, "
    "or reply to a question.\n\n"
    "/status: what's still to come today, pauses, streaks\n"
    "/summary: this week so far (sent automatically on Sunday evening)\n"
    "/focus [min]: start a focus block (default 25)\n"
    "/log &lt;what&gt; [duration]: log something, e.g. <code>/log run 30m</code>\n"
    "/pause [area|all] [duration]: e.g. <code>/pause</code>, <code>/pause hobby 2d</code>\n"
    "/resume [area]: undo a pause\n\n"
    "Areas: movement, focus, learning, hobby. Quiet hours are respected."
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _markup(buttons: list[list[Button]]) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(b.label, callback_data=b.data) for b in row] for row in buttons]
    )


class Bot:
    def __init__(self, settings: Settings, engine: Engine | None = None):
        self.settings = settings
        self.engine = engine
        self.app: Application | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.telegram_bot_token)

    @property
    def ready(self) -> bool:
        return self.app is not None and self.settings.telegram_owner_chat_id is not None

    def _owner_filter(self) -> filters.BaseFilter:
        if self.settings.telegram_owner_chat_id is None:
            # Nothing is owner-only until the owner is configured.
            return filters.Chat(chat_id=[])
        return filters.Chat(chat_id=self.settings.telegram_owner_chat_id)

    def _is_owner(self, update: Update) -> bool:
        chat = update.effective_chat
        return chat is not None and chat.id == self.settings.telegram_owner_chat_id

    def build(self) -> Application:
        app = Application.builder().token(self.settings.telegram_bot_token).build()
        owner = self._owner_filter()

        app.add_handler(CommandHandler("start", self._start))
        app.add_handler(CommandHandler("ping", self._ping, filters=owner))
        if self.engine is not None:
            app.add_handler(CommandHandler("help", self._help, filters=owner))
            app.add_handler(CommandHandler("status", self._status, filters=owner))
            app.add_handler(CommandHandler("summary", self._summary, filters=owner))
            app.add_handler(CommandHandler("focus", self._focus, filters=owner))
            app.add_handler(CommandHandler("pause", self._pause, filters=owner))
            app.add_handler(CommandHandler("resume", self._resume, filters=owner))
            app.add_handler(CommandHandler("log", self._log, filters=owner))
            app.add_handler(CallbackQueryHandler(self._callback))
            app.add_handler(MessageHandler(owner & filters.TEXT & ~filters.COMMAND, self._text))
        app.add_error_handler(self._error)
        return app

    async def start(self) -> None:
        if not self.enabled:
            log.warning("TELEGRAM_BOT_TOKEN not set; bot disabled")
            return
        self.app = self.build()
        await self.app.initialize()
        if self.engine is not None:
            await self.app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        log.info("Telegram bot polling")

    async def stop(self) -> None:
        if self.app is None:
            return
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()
        self.app = None

    async def send(self, msg: Outgoing | str) -> int | None:
        """Send a message to the owner. Returns the Telegram message id."""
        if isinstance(msg, str):
            msg = Outgoing(msg)
        if not self.ready:
            log.info("Not sent (bot not ready): %s", msg.text)
            return None
        markup = ForceReply(selective=True) if msg.force_reply else _markup(msg.buttons)
        sent = await self.app.bot.send_message(
            self.settings.telegram_owner_chat_id, msg.text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
        return sent.message_id

    async def dispatch_due(self) -> None:
        """Scheduler job: send prompts whose time has come."""
        if self.engine is None or not self.ready:
            return
        now = now_utc()
        for prompt_id, msg in self.engine.due(now):
            try:
                message_id = await self.send(msg)
            except Exception:
                log.exception("Failed to send prompt %s; will retry", prompt_id)
                continue
            self.engine.mark_sent(prompt_id, message_id, now)

    # --- handlers ---

    async def _start(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        owner = self.settings.telegram_owner_chat_id
        if owner is None:
            await update.message.reply_text(
                f"Your chat ID is {chat_id}.\n"
                "Set TELEGRAM_OWNER_CHAT_ID to this value and restart the service."
            )
        elif chat_id == owner:
            await update.message.reply_text(
                "la-vie is running. Daily prompts will arrive here. /help for commands."
            )
        # Anyone else gets no reply.

    async def _ping(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text("pong")

    async def _help(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_html(HELP)

    async def _status(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_html(self.engine.status(now_utc()))

    async def _summary(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_html(self.engine.summary(now_utc()))

    async def _focus(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_html(self.engine.start_focus(ctx.args, now_utc()))

    async def _pause(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_html(self.engine.pause(ctx.args, now_utc()))

    async def _resume(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_html(self.engine.resume(ctx.args, now_utc()))

    async def _log(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        text, buttons = self.engine.log(ctx.args, now_utc())
        await update.message.reply_html(text, reply_markup=_markup(buttons))

    async def _text(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        reply_to = update.message.reply_to_message
        answer = self.engine.handle_text(
            update.message.text, reply_to.message_id if reply_to else None, now_utc()
        )
        await update.message.reply_html(answer)

    async def _callback(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self._is_owner(update):
            await query.answer()
            return
        kind, *parts = (query.data or "").split(":")
        now = now_utc()

        if kind == "l" and len(parts) == 2:
            await query.answer()
            await query.edit_message_text(self.engine.finish_log(parts[0], parts[1], now), parse_mode=ParseMode.HTML)
            return

        if kind != "p" or len(parts) != 2 or not parts[0].isdigit():
            await query.answer()
            return

        result = self.engine.handle_action(int(parts[0]), parts[1], now)
        await query.answer(result.toast)
        if result.edit:
            try:
                await query.edit_message_text(
                    result.edit.text, parse_mode=ParseMode.HTML, reply_markup=_markup(result.edit.buttons)
                )
            except BadRequest as e:  # e.g. "message is not modified"
                log.debug("edit failed: %s", e)
        for text in result.extra:
            await self.send(text)

    async def _error(self, update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("Bot error", exc_info=ctx.error)

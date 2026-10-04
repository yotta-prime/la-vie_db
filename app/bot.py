"""Telegram bot connection. Uses long polling, so the NAS needs no inbound ports."""

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from app.config import Settings

log = logging.getLogger(__name__)


class Bot:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.app: Application | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.telegram_bot_token)

    def _owner_filter(self) -> filters.BaseFilter:
        if self.settings.telegram_owner_chat_id is None:
            # Nothing is owner-only until the owner is configured.
            return filters.Chat(chat_id=[])
        return filters.Chat(chat_id=self.settings.telegram_owner_chat_id)

    def build(self) -> Application:
        app = Application.builder().token(self.settings.telegram_bot_token).build()
        owner = self._owner_filter()

        app.add_handler(CommandHandler("start", self._start))
        app.add_handler(CommandHandler("ping", self._ping, filters=owner))
        return app

    async def start(self) -> None:
        if not self.enabled:
            log.warning("TELEGRAM_BOT_TOKEN not set; bot disabled")
            return
        self.app = self.build()
        await self.app.initialize()
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

    async def send(self, text: str, **kwargs) -> int | None:
        """Send a message to the owner. Returns the Telegram message id."""
        if self.app is None or self.settings.telegram_owner_chat_id is None:
            log.info("Not sent (bot not ready): %s", text)
            return None
        msg = await self.app.bot.send_message(self.settings.telegram_owner_chat_id, text, **kwargs)
        return msg.message_id

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
            await update.message.reply_text("la-vie is running. Daily prompts will arrive here.")
        # Anyone else gets no reply.

    async def _ping(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text("pong")

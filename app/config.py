from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    telegram_bot_token: str = ""
    # Only this chat is answered. Leave empty on first run, send /start to the bot,
    # and it will reply with your chat ID to put here.
    telegram_owner_chat_id: int | None = None

    timezone: str = "Europe/London"
    data_dir: Path = Path("data")
    backup_keep: int = 14

    @property
    def db_path(self) -> Path:
        return self.data_dir / "lavie.db"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Tests never read a local .env: only what each test sets (or the defaults) applies."""

from app.config import Settings, get_settings

Settings.model_config["env_file"] = None
get_settings.cache_clear()

from fastapi.testclient import TestClient

from app.backup import backup_sqlite
from app.config import get_settings


def test_app_starts_without_bot_token(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.chdir(tmp_path)  # ignore any local .env
    get_settings.cache_clear()

    from app.main import app

    with TestClient(app) as client:
        body = client.get("/health").json()

    assert body["status"] == "ok" and body["bot"] is False and body["version"]
    assert {"nightly_backup", "plan_day", "dispatch"} <= set(body["jobs"])
    assert (tmp_path / "lavie.db").exists()
    get_settings.cache_clear()


def test_backup_rotation(tmp_path):
    import sqlite3

    db_path = tmp_path / "lavie.db"
    sqlite3.connect(db_path).close()
    backups = tmp_path / "backups"
    for i in range(4):
        (backups).mkdir(exist_ok=True)
        (backups / f"lavie-2026010{i}-000000.db").touch()

    backup_sqlite(db_path, backups, keep=3)
    assert len(list(backups.glob("lavie-*.db"))) == 3

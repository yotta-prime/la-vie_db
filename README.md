# la-vie_db

Personal daily-life service: Telegram prompts for movement, focus, learning paths and hobbies, running in Docker on a Synology NAS. See [docs/SPEC.md](docs/SPEC.md).

## Setup

1. **Create the bot**: in Telegram, message `@BotFather`, send `/newbot`, and copy the token.
2. **Configure**: copy `.env.example` to `.env` and set `TELEGRAM_BOT_TOKEN`.
3. **Start** (locally or on the NAS, see below).
4. **Claim the bot**: send `/start` to your bot. It replies with your chat ID. Put it in `.env` as `TELEGRAM_OWNER_CHAT_ID` and restart. After that, the bot only answers you. `/ping` should reply `pong`.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\uvicorn app.main:app --reload
.\.venv\Scripts\pytest
```

Health check: http://localhost:8000/health

## Deploy on Synology

1. Copy this folder (with your `.env`) to the NAS, e.g. `/volume1/docker/lavie`.
2. Container Manager → **Project** → **Create** → choose that folder; it uses `docker-compose.yml`.
3. The data (SQLite DB and nightly backups) lives in `./data`. Include `data/backups` in Hyper Backup.
4. Health check from your LAN: `http://<nas-ip>:8080/health`. Don't forward port 8080 on your router.

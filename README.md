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

The NAS pulls `main` from GitHub every 15 minutes and redeploys on changes; secrets live outside the repo, readable only by root. Full steps: [docs/DEPLOY.md](docs/DEPLOY.md).

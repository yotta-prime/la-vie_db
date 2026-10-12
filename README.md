# la-vie_db

Personal daily-life service: Telegram prompts for movement, focus, learning paths and hobbies, running in Docker on a Synology NAS. See [docs/SPEC.md](docs/SPEC.md).

## Setup

1. **Create the bot**: in Telegram, message `@BotFather`, send `/newbot`, and copy the token.
2. **Configure**: copy `.env.example` to `.env` and set `TELEGRAM_BOT_TOKEN`.
3. **Start** (locally or on the NAS, see below).
4. **Claim the bot**: send `/start` to your bot. It replies with your chat ID. Put it in `.env` as `TELEGRAM_OWNER_CHAT_ID` and restart. After that, the bot only answers you. `/ping` should reply `pong`.

## Admin page

**http://192.168.0.198:8080/admin** (on the NAS; generally `http://<nas-ip>:8080/admin`)

- Edit routines and their video links, micro-moves, learning paths, courses and lessons, hobbies and projects, dependencies, schedules and settings. The **Today** page shows the day's prompts.
- Reachable from your home network only: keep port 8080 closed on the router.
- Sign in with `ADMIN_PASSWORD` from the NAS secrets file (`/volume1/docker/lavie/secrets/.env`); the admin page stays locked until it's set. Sign-in lasts 30 days per browser. To set or change the password, see [docs/DEPLOY.md](docs/DEPLOY.md) step 7.
- Running locally, it's at http://localhost:8000/admin, using `ADMIN_PASSWORD` from your local `.env`.
- Learning paths can also come from files: `content/*.yaml` (e.g. `content/oreilly.yaml`, the O'Reilly live events) is loaded at startup. Import only adds new items, so changes made in the admin page are kept.

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

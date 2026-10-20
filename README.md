# la-vie_db

Personal daily-life service: Telegram prompts for movement, focus, learning paths and hobbies, running in Docker on a Synology NAS. What it does: [docs/SPEC.md](docs/SPEC.md). How it's deployed and run: [docs/DEPLOY.md](docs/DEPLOY.md). Design review and recommended improvements: [docs/REVIEW-2026-10.md](docs/REVIEW-2026-10.md).

## Setup

1. **Create the bot**: in Telegram, message `@BotFather`, send `/newbot`, and copy the token.
2. **Configure**: copy `.env.example` to `.env` and set `TELEGRAM_BOT_TOKEN`.
3. **Start** (locally or on the NAS, see below).
4. **Claim the bot**: send `/start` to your bot. It replies with your chat ID, a number. Put it in `.env` as `TELEGRAM_OWNER_CHAT_ID` and restart. After that, the bot only answers you. `/ping` should reply `pong`.

## Admin page

**http://192.168.0.198:8080/admin** (on the NAS; generally `http://<nas-ip>:8080/admin`)

- **Answers** tab (`/admin/answers`): what la-vie asked in Telegram and what you replied (buttons, focus ratings, typed replies such as your daily intention), plus `/log` entries, by day; filter by period and area. Unanswered prompts are greyed out.
- **Trends** tab (`/admin/trends`): week-by-week progress (Monday to Sunday) for movement, focus, learning, hobbies and reply rate: a small bar chart per measure, last week vs the week before, and this week so far. Worked out from the stored answers, so it covers everything since la-vie started.
- **Movement plan** (`/admin/movement/plan`, linked from the Movement tab): a month grid of dates with **Morning / Evening / Night** checkboxes. Tick a slot and that day gets a movement prompt in Telegram at the slot's time (06:30 / 18:00 / 20:30 by default); a new month starts with nothing ticked, and an **All** button per column ticks the rest of the month. Each slot can offer the rotation, your own routines, or one course (e.g. Psoas in the evening). Past slots turn into coloured dots (done green, partly done yellow, missed or skipped orange) with the month's completion rate. Saving re-plans the rest of today.
- **O'Reilly** tab (`/admin/oreilly`): your live events laid out like the events file, with Attended / Missed / Watched controls on every row, plus the Radar newsletter summary.
- Edit routines and their video links, micro-moves, learning paths, courses and lessons, flashcards, hobbies and projects, dependencies, schedules and settings. The **Today** page shows the day's prompts and can re-plan the rest of the day after a settings change.
- Reachable from your home network only: keep port 8080 closed on the router.
- Sign in with `ADMIN_PASSWORD` from the NAS secrets file (`/volume1/docker/lavie/secrets/.env`); the admin page stays locked until it's set. Sign-in lasts 30 days per browser. To set or change the password, see [docs/DEPLOY.md](docs/DEPLOY.md) step 7.
- Running locally, it's at http://localhost:8000/admin, using `ADMIN_PASSWORD` from your local `.env`.
- Styling: the "Industry" theme, inlined in `app/admin/templates/base.html`; reference stylesheets in [docs/design/industry](docs/design/industry).

## Learning content from files

Besides the admin page, learning paths, courses and lessons can be kept in `content/*.yaml`, which the app loads every time it starts (so after every deploy).

- **`content/oreilly.yaml`**: O'Reilly live events, from `oreilly_events_06-Oct-26.md`: 3 paths, 10 courses, 52 lessons, with recording links. Lessons are newest first, upcoming events last, and all queued for review.
- **Add-only import.** Each path, course and lesson has a unique `key`. An item is created the first time its key appears; after that, the only change import makes is **filling in a link** the item doesn't have yet. Renames, reordering, ticks and links set in the admin page are never overwritten.
- **Add an event**: append a lesson with a new `key`, `title`, `detail` and optional `url`, then push. It's added at the end of its course.
- **Add a recording link later**: add `url:` to that lesson and push, or paste it on the admin **O'Reilly** page. Telegram then announces the recording.
- **Live events** also take `date`, `presenters` and `attendance` (registered / waitlisted / attended / missed). See *Live-event lessons* in [docs/SPEC.md](docs/SPEC.md) for how pending, missed and attended events are handled.
- **Remove an item**: delete it in the admin page *and* from the file (otherwise it's re-created on the next start).

Format (see the top of `content/oreilly.yaml` and `app/content.py`):

```yaml
paths:
  - key: my-path
    name: Cloud architect
    category: professional        # or hobby
    sequential: false             # true: only the next unfinished course is suggested
    courses:
      - key: my-course
        name: Networking
        url: https://...
        lessons:
          - key: my-lesson-1
            title: Subnets
            detail: Presenter · date
            url: https://...
courses: []                       # individual courses, same shape as above plus category
```

The repo is public, so anything in `content/` is published. Paid or private material goes in `data/content/*.yaml` on the NAS instead (same format, imported the same way, never committed). That's how the **DailyOM movement lessons** are loaded: `tools/dailyom_to_yaml.py` turns a one-off export of your DailyOM courses into a `routines:` file, whose lessons then take turns with your own routines in the morning movement prompt (course and section links, the movements, the lesson text, and a ▶ Open video button). See *Course lessons as routines* in [docs/SPEC.md](docs/SPEC.md).

## Telegram commands

`/oreilly` (O'Reilly events: to watch, review, upcoming, courses; mark attended/missed/watched) · `/status` (what's left today, pauses, streaks) · `/summary` (this week so far; sent automatically on Sunday evening) · `/focus [min]` · `/log <what> [duration]` · `/pause [area|all] [duration]` · `/resume [area]` · `/health` (version and connection check) · `/help` · `/ping`

The bot also sends **"la-vie started, version …"** whenever it starts, e.g. after each deploy.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\uvicorn app.main:app --reload
.\.venv\Scripts\pytest
```

Health check: http://localhost:8000/health

The tests ignore your local `.env`. GitHub runs them on every push (`.github/workflows/test.yml`), and the NAS deploys a commit only after they pass.

**Dependencies**: list top-level packages in `requirements.in`; `requirements.txt` holds the exact versions the image installs. After changing `requirements.in`, regenerate it:

```powershell
.\.venv\Scripts\python -m pip install uv
.\.venv\Scripts\python -m uv pip compile requirements.in --universal --python-version 3.12 -o requirements.txt
```

Dependabot opens monthly pull requests for Python packages, the base image and GitHub Actions; CI tests each one before you merge.

## Working sessions with Claude Code

Each working session ends with a close-out: docs brought up to date, the chat history exported to [docs/chat-history](docs/chat-history) by `tools/export_chat.py` (secrets redacted), committed and pushed, and the NAS checked to be running the same commit. The steps are in [CLAUDE.md](CLAUDE.md); type `/close-out` to run them. If a session ends without one (timed out or closed), the next session finishes it first.

## Deploy on Synology

The NAS pulls `main` from GitHub every 15 minutes and redeploys on changes once GitHub's tests have passed (failures are sent to Telegram); secrets live outside the repo, readable only by root. `http://192.168.0.198:8080/health` shows the deployed commit (`version`) and whether the bot is talking to Telegram (`polling`, `last_poll_seconds_ago`). Full steps, monitoring and troubleshooting: [docs/DEPLOY.md](docs/DEPLOY.md).

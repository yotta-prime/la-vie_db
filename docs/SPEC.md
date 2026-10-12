# la-vie — daily life service: v1 spec

Captured from the requirements interview, 2026-10-04. Last updated 2026-10-12 (learning content files, O'Reilly import, monitoring). See **Implementation status** at the end for what's built.

## Overview

A personal service running on a Synology NAS that sends Telegram prompts through the day across four areas — **movement**, **attention/focus**, **learning paths**, **hobbies** — logs responses, and reports progress. All content and selection is rule-based (no AI). Configuration is edited through a small web admin page on the home network.

## Architecture

| Part | Choice |
|---|---|
| Host | Synology Plus-series (x86), Container Manager (Docker) |
| Backend | Python: FastAPI + scheduler (e.g. APScheduler) in one container |
| Storage | SQLite on a mounted NAS volume |
| Messaging | Telegram bot, long polling (no inbound ports needed) |
| Admin UI | Server-rendered web page from the same FastAPI app, LAN only |
| AI | None — fixed rules and templates |

## Daily rhythm

Desk job, ~9–5 on weekdays. Prompts are spread through the day:

- **Weekdays**: focus intention (morning) → desk-break micro-moves (every few hours during work) → distraction check-ins (random, work hours) → movement routine and learning/hobby sessions (before/after work) → end-of-day focus reflection.
- **Weekends**: no work-hour prompts; movement, learning and hobby sessions only.
- **Quiet hours** (configurable): no messages sent; anything due is dropped or deferred to the next allowed time.

## Areas

### Movement
- **Named routines** defined in admin (name, duration, steps); the prompt names today's routine and lists the steps.
- **Desk-break micro-moves**: short 2–5 min reminders at intervals during work hours.
- **Logging**: inline buttons Done / Partial / Skip; streaks tracked.

### Attention / focus
- **Daily focus intention**: morning "What's your one most important thing today?"; free-text reply stored; checked back on in the evening.
- **Focus block timer**: start a Pomodoro / deep-work block from Telegram; ping at the end; block logged.
- **Distraction check-ins**: occasional random "What are you doing right now?" during work hours.
- **End-of-day reflection**: rate focus 1–5 + optional note.

### Learning paths and courses
- Tracked separately from hobbies.
- A **course** is what a learning session works on. It is **professional** or **hobby**, and one of:
  - **Lessons** — ordered list; the bot serves the next lesson; finishing the last completes the course.
  - **Time-based goal** — e.g. 20 min/day; log minutes.
  - **Spaced repetition** — flashcard reviews in Telegram.
- A **learning path** groups courses (e.g. "Cloud architect" → Networking, Security). Paths are **in order** by default (only the next unfinished course is suggested) or **any order**. Courses can also stand alone as **individual courses**.
- Courses, lessons and routines can carry **links** (course pages, recordings, YouTube, DailyOM…), shown in the prompts.
- **Professional / hobby split** is a configurable target ratio; the scheduler balances sessions toward it over each week.
- Selected professional paths are explicitly **not linked** to any hobby.

### Learning content files
- Paths, courses and lessons can also be defined in `content/*.yaml` in the repo, loaded at every startup (so after each deploy).
- **Add-only by key**: each item has a stable `key` (stored as `source_key`). An item is created the first time its key appears. After that, import only **fills in a missing `url`**; it never overwrites or deletes, so admin-page edits (renames, order, ticks, links) win.
- **O'Reilly live events** (`content/oreilly.yaml`), from `oreilly_events_06-Oct-26.md`, allocation approved item by item on 2026-10-12:

  | Path / individual course | Course | Lessons |
  |---|---|---|
  | Agentic AI engineering | Agentic coding practice | 9 |
  | | Building & orchestrating agents | 10 |
  | | LLM & prompting foundations | 6 |
  | Software architecture | Architecture in the AI era | 7 |
  | Engineering leadership & organisation | Engineering leadership | 5 |
  | | AI & the organisation | 5 |
  | | Project delivery tools | 2 |
  | *Individual* | AI & cybersecurity | 4 |
  | *Individual* | Data | 3 |
  | *Individual* | Linux administration | 1 |

  - All professional; paths are any-order. Each event is a lesson (the two *Antigravity CLI* runs are one lesson). 52 lessons from 53 events.
  - Lessons are newest first, with upcoming and waitlisted events last. Attended events are **queued for review**: none are marked done.
  - 43 lessons link to their recording: personal links from the Gmail recording emails, or `learning.oreilly.com` for older events. The 5 events with recordings not yet issued and the 4 upcoming events have no link until one is added to the file.

### Live-event lessons (O'Reilly)
Each event lesson has a date, presenters and an **attendance**: registered, waitlisted, attended or missed. A recording link and a **watched** tick complete the picture, giving these states:

| State | Meaning | What la-vie does |
|---|---|---|
| **Pending** (a) | Registered/waitlisted, not happened yet | Never offered as a lesson. The day after the event, Telegram asks **Did you attend? [Attended] [Missed]** (once; waits out quiet hours) |
| **Awaiting recording** | Attended or missed, no link yet | Not offered. Add the link (file, admin O'Reilly page, or later email) and Telegram announces it |
| **Attended, with recording** (b) | Completed live | Queued for **review**, after missed ones |
| **Missed, to watch** (c) | Registered but didn't attend | Offered **first** at the learning session. When its recording arrives: **Recording ready [▶ Open] [✓ Watched]** |
| **Watched** | Ticked | Done; the course completes when all its lessons are |

Status can be changed in three places that share the same data: the admin **O'Reilly** page (buttons per row), Telegram `/oreilly`, and the confirmation messages.

Every event shows **two status LEDs**, on the page and in Telegram: **attendance** (🟢 attended, 🟠 missed, 🟡 registered/waitlisted) and **recording** (🟢 watched, ⚪ grey, not yet). Red is reserved for time-bound items (deadlines, to be configured later). Watched rows stay fully readable, with no strike-through. Events have an optional **start time** (UK local, `HH:MM`), set on the O'Reilly page for upcoming events or as `time: "17:00"` in the content file.

### O'Reilly page (admin)
`/admin/oreilly`, laid out like `oreilly_events_06-Oct-26.md`: Planned/Registered, **To watch (missed live)**, Recording not yet issued (with a field to paste the link), numbered tables per year with recording links, totals and notes, then the **O'Reilly Radar newsletter summary** (page 2 of the file, `content/oreilly_radar.md`). Each row has Attended/Missed and Watched controls.

### Hobbies
- Hobby list with **projects** (things to do within the hobby, with optional link and notes; can be marked done).
- **Dependencies**: a project can require a **course** or a **whole learning path** to be completed first; locked projects are never suggested, and completing the requirement announces the unlock in Telegram.
- Selection is configured **per item** at planning time (see below), not globally.

## Scheduling rules (per hobby and per course)

Set in the admin page for each item:

- **Method**: round-robin, neglect-weighted (longest since last done), or fixed weekday slots.
- **Sessions per week** target; the scheduler places sessions and catches up on missed ones.
- **Start / end dates**: e.g. a course runs 8 weeks from when it's added; afterwards, the item returns to its default method.
- **Priority / weight**.

## Telegram controls

- Inline buttons for logging on every prompt.
- `/pause [area|all] [until]` and `/resume` — pause mode.
- `/log <activity> [duration]` — ad-hoc log, e.g. `/log run 30m`.
- `/focus [minutes]` — start a focus block.
- `/summary` — this week so far; `/status` — what's left today, pauses, streaks.
- `/oreilly` — O'Reilly events: counts, then **To watch / Review / Upcoming / Awaiting** lists and **Paths & courses**, down to each lesson with **▶ Open recording**, **✓ Watched** and **Attended / Missed** buttons. One message, updated in place.
- `/health` — version and connection check; `/help`; `/ping`.
- On every start the bot sends **"la-vie started, version …"**.
- Quiet hours enforced server-side.
- Bot only answers the owner's Telegram chat ID.

## Reliability and monitoring

- **`/health`** (HTTP, LAN): `status`, deployed `version` (commit), `polling`, `last_poll_seconds_ago`, scheduled jobs. Returns **503 "stale"** after 2 minutes without a successful Telegram poll; Docker's health check then marks the container unhealthy in Container Manager.
- **Watchdog**: after 10 minutes without a successful poll, the app restarts itself (Docker's restart policy brings it back).
- **Outside heartbeat** (optional): with `HEARTBEAT_URL` set (e.g. healthchecks.io), the app checks in every minute while polling is healthy; the service alerts when check-ins stop (NAS off, network down, container stopped).
- **Deploys**: the NAS pulls `main` every 15 minutes; containers get 30 s to stop cleanly. Schema changes back up the database first (`lavie.db.pre-v<N>.bak`).

## Reports

- **Streaks** shown in the prompts themselves.
- **Weekly summary** (Sunday): streaks, learning minutes/steps per path, pro/hobby ratio vs target, hobbies done, average focus score.
- **CSV export** of raw logs from the admin page.

## Admin page (LAN only)

At **http://192.168.0.198:8080/admin** (generally `http://<nas-ip>:8080/admin`), protected by `ADMIN_PASSWORD`, "Industry" theme. Edit: movement routines and their items (with video links), micro-moves, learning paths, courses within them and individual courses, lessons, flashcards, hobbies and projects, project dependencies (course or path), per-item scheduling rules, daily timing (work hours, quiet hours, prompt times), pro/hobby ratio, weekly summary day/time. The Today page lists the day's prompts and can re-plan the rest of the day. CSV export to follow. No public exposure.

## Data model (sketch)

`routine` (+ url, notes), `routine_step` (+ url), `micro_move`, `learning_path` (category, sequential, source_key), `course` (path, position, category, kind, goal, url, completed, source_key), `course_step` (url, done, source_key; live events: event_date, event_time, presenters, attendance, attendance_asked_at, recording_notified_at), `flashcard` (+ SRS state), `hobby`, `hobby_project` (url, notes, `requires_course_id` / `requires_path_id`, done), `schedule_rule` (course or hobby; method, sessions/week, weekdays, start/end, weight), `prompt` (sent, due, status), `log_entry` (area, item, outcome, duration, rating, note), `setting`, `schema_version` (currently **4**: v1 courses/projects, v2 source keys, v3 live-event fields, v4 event time).

## v1 scope

Everything above.

## Defaults

All times are editable in the admin page.

- **Timezone**: Europe/London (handles GMT/BST automatically).
- **Weekday schedule (early riser)**:

  | Time | Prompt |
  |---|---|
  | 06:30 | Movement routine |
  | 08:00 | Focus intention |
  | 09:00–17:00, hourly | Desk-break micro-moves |
  | 2× random, work hours | Distraction check-ins |
  | 17:30 | Learning session |
  | 19:00 | Hobby session |
  | 20:30 | Focus reflection |

- **Weekends**: movement, learning and hobby prompts only, at the same times.
- **Quiet hours**: 21:00–06:00.
- **Weekly summary**: Sunday 18:00.
- **Spaced repetition**: FSRS (e.g. the `fsrs` Python package), with Again / Hard / Good / Easy buttons.
- **Backups**: nightly SQLite online backup (`sqlite3` backup API) at 03:00 to a `backups/` folder, keeping 14, covered by Hyper Backup / Snapshot Replication.

## Implementation status (2026-10-12)

| Feature | Status |
|---|---|
| Daily prompts for all four areas, buttons, replies, streaks | Built |
| Pause, quiet hours, `/log`, `/focus`, `/status`, `/summary`, `/health` | Built |
| Weekly summary (Sunday) | Built |
| Admin page (all content and settings), Industry theme | Built |
| Learning paths / courses / lessons, hobby projects and dependencies | Built |
| Learning content files, O'Reilly events with recording links | Built |
| Event statuses (pending / awaiting / attended / missed / watched), Telegram confirmations | Built |
| Admin O'Reilly page (events file layout + Radar summary), Telegram `/oreilly` | Built |
| NAS reads O'Reilly email (dedicated inbox) and updates events | Planned |
| Radar summary refreshed from newsletters | Planned (needs an AI step) |
| Watchdog, `/health` stale detection, startup message | Built |
| Outside heartbeat (healthchecks.io) | Built; not yet configured on the NAS |
| Flashcard reviews in Telegram (FSRS) | Not built: flashcard courses show a placeholder |
| CSV export | Not built |

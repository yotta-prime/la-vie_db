# la-vie — daily life service: v1 spec

Captured from the requirements interview, 2026-10-04.

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

### Learning paths
- Tracked separately from hobbies. Each path is **professional** or **hobby**.
- Path types (mixed):
  - **Ordered steps** — bot serves the next step; mark done.
  - **Time-based goal** — e.g. 20 min/day; log minutes.
  - **Spaced repetition** — flashcard reviews in Telegram.
- **Professional / hobby split** is a configurable target ratio; the scheduler balances sessions toward it over each week.
- Selected professional paths are explicitly **not linked** to any hobby.

### Hobbies
- Hobby list with **elements** (sub-activities).
- **Unlocks**: a hobby element can require a learning path to be completed first; locked elements are never suggested.
- Selection is configured **per item** at planning time (see below), not globally.

## Scheduling rules (per hobby and per learning path)

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
- Quiet hours enforced server-side.
- Bot only answers the owner's Telegram chat ID.

## Reports

- **Streaks** shown in the prompts themselves.
- **Weekly summary** (Sunday): streaks, learning minutes/steps per path, pro/hobby ratio vs target, hobbies done, average focus score.
- **CSV export** of raw logs from the admin page.

## Admin page (LAN only)

CRUD for: movement routines, micro-move list, learning paths (type, category, steps/cards/goal), hobbies and elements, unlock prerequisites, per-item scheduling rules, daily timing (work hours, quiet hours, prompt times), pro/hobby ratio, CSV export. No public exposure; basic login still recommended.

## Data model (sketch)

`routine`, `routine_step`, `learning_path` (category, type, rules), `path_step`, `flashcard` (+ SRS state), `hobby`, `hobby_element` (`requires_path_id`), `schedule_rule` (method, sessions/week, start/end, weight), `prompt` (sent, due, status), `log_entry` (area, item, outcome, duration, rating, note), `settings`.

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
- **Spaced repetition**: FSRS (e.g. the `fsrs` Python package), with Again / Hard / Good / Easy buttons.
- **Backups**: nightly SQLite online backup (`sqlite3` backup API) to a `backups/` folder with rotation, covered by Hyper Backup / Snapshot Replication.

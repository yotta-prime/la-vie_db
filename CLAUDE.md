# la-vie: notes for Claude Code

Personal Telegram prompt service on a Synology DS220+ (`192.168.0.198`). What it does: [docs/SPEC.md](docs/SPEC.md); deploy and ops: [docs/DEPLOY.md](docs/DEPLOY.md); improvement plan and progress: [docs/REVIEW-2026-10.md](docs/REVIEW-2026-10.md).

Admin site (LAN): http://192.168.0.198:8080/admin — direct links to every page are in the README's *Admin page* table.

**Open items:** [docs/FUTURE-FEATURES.md](docs/FUTURE-FEATURES.md) is the to-do list between sessions (next up,
decisions waiting, things waiting on the user, backlog). Read it when resuming; update it at close-out.

## Ground rules

- **This repo is public.** Never put passwords, tokens or app passwords in files or chat. Secrets live only in `/volume1/docker/lavie/secrets/.env` on the NAS (and the local, untracked `.env`); the user types them into the NAS terminal themselves.
- **Scope:** la-vie only. Other projects (and their repos) stay out of this repo, its docs and its chat histories.
- Stage files by name; never `git add -A` or `git add .`.
- Tests: `.\.venv\Scripts\pytest` (the system Python has no pytest). CI runs them on every push; the NAS deploys a commit only after CI passes.
- In PowerShell, write files with absolute paths and UTF-8 without BOM; check text with the Read or Grep tools, since `Get-Content` without `-Encoding utf8` can look garbled.
- Status colours: red only for time-bound items; missed = orange, not yet = grey.
- End each step with a short recap, and check results yourself (for example `/health` on the NAS) rather than assuming.

## Deploys

`main` → GitHub Actions (`test`) → the NAS pulls every 15 minutes (`:00 :15 :30 :45`) and deploys commits whose CI passed. Only app changes (`app/`, `content/`, `Dockerfile`, compose, `requirements.txt`, `.dockerignore`) rebuild and restart the container; anything else just updates the NAS copy. Check from the PC:

- `http://192.168.0.198:8080/health` → `version` should equal `git rev-parse --short HEAD` (after an app change) and `polling: true`.
- `\\192.168.0.198\docker\lavie\logs\update.log` → `updated repo to <sha>` (no restart) or `deploying` / `deployed`.

## Close-out (end of a daily session)

Run when the user wraps up ("save", "sync everything", "taking a break", "done for today") or types `/close-out`. Steps, in order:

1. **Docs:** bring README, `docs/SPEC.md` (dates, implementation status), `docs/DEPLOY.md`, the progress table in `docs/REVIEW-2026-10.md` and the open items in `docs/FUTURE-FEATURES.md` in line with what changed this session.
2. **Tests:** if code changed, `.\.venv\Scripts\pytest` passes.
3. **Chat history:** `.\.venv\Scripts\python tools\export_chat.py` (newest transcript → the file in `docs/chat-history/` that carries its session ID). Then grep the result for secrets (`ADMIN_PASSWORD=`, bot tokens, `ghp_`, app passwords) and for other projects' material; fix by adding a regex to `tools/chat-exclude.local.txt` (local, gitignored) and re-running.
4. **Commit and push:** stage by name, a clear message, `git push`.
5. **Sync check:** wait for CI to pass (`gh run list --limit 1`), then for the next NAS run. Confirm `update.log` shows the new commit and, if the app changed, that `/health` reports it. Local, GitHub and NAS on the same commit = done.
6. **Recap for the user:** what changed, the commit, the sync result, what's waiting on them, and where to resume (`claude --resume` or `/resume`).

## Time-out (session ended without a close-out)

Transcripts survive a time-out, so nothing is lost. At the start of a new session, run `git status` and compare the newest transcript in `~/.claude/projects/C--Users-dbarb-Projects-daily-life/` with the chat-history file that names it. If there are uncommitted changes, or the transcript has messages newer than the export, tell the user and finish the close-out for that session (steps 1–5, exporting that transcript by path) before new work.

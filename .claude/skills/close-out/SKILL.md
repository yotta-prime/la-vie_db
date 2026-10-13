---
name: close-out
description: End-of-session close-out for la-vie - update docs, export and redact the chat history, commit and push, confirm local, GitHub and the NAS are in sync, then recap. Use when the user wraps up a daily session (save, sync everything, taking a break, done for today) or a previous session ended without one.
---

# Close-out

Follow the **Close-out** section of `CLAUDE.md` at the repo root, steps 1 to 6, in order. For a session that timed out, follow its **Time-out** section first and export that session's transcript by path:

```powershell
.\.venv\Scripts\python tools\export_chat.py "<transcript.jsonl>"
```

Checks before calling it done:

- `git status` is clean, and `git log origin/main -1` matches `HEAD`.
- The CI run for `HEAD` succeeded.
- `\\192.168.0.198\docker\lavie\logs\update.log` names `HEAD` (or the last app commit, when only docs changed), and `http://192.168.0.198:8080/health` shows `status: ok` and `polling: true`.
- The exported history contains no secrets and nothing from other projects.

Report each check's actual result in the recap. If one is still pending (for example the next NAS run is at :45), say when it's due and confirm it once it happens.

# la-vie: future features and open items (TBD)

The running to-do list between sessions. Newest decisions first; tick items off (or delete them) as they're done.
Design review and the original top-ten: [REVIEW-2026-10.md](REVIEW-2026-10.md).

_Last updated 25 Oct 2026._

## Next up

### Nightly backups to Google Drive (TBD: user to set up in DSM)

Copy every nightly database backup, including the 14 already on the NAS, to Google Drive (dbarbour@gmail.com),
keeping all of them there. The NAS keeps its rolling 14 for quick restores.

Approach: Synology **Cloud Sync** (runs on the NAS, so it works with the PC off). Steps (the user signs in to Google;
Claude never handles the password):

1. DSM → **Package Center** → install **Cloud Sync**.
2. Cloud Sync → **+** → **Google Drive** → sign in as dbarbour@gmail.com → review and Allow.
3. Local path `docker/lavie/data/backups` · remote folder e.g. `la-vie backups` · sync direction
   **Upload local changes only** · tick **Don't remove files in the destination folder when they are removed in the
   source folder** (this keeps every backup in Drive) · data encryption **off** (files stay usable from Drive).
4. No schedule (continuous) → **Apply**.

Then Claude: check the 14 files arrived in Drive (Drive connector), check the next 03:00 backup arrives by itself,
and document it in DEPLOY.md.

Open choices: **copy** (recommended) vs **move** (would need a change to la-vie's backup job; a failed upload would
lose a backup); whether `data/content/dailyom.yaml` should go to the same folder (the secrets file should not).

### Decisions waiting (from the 20 Oct review)

- **DailyOM:** add any of the 5 courses left out (Brain Exercises, Visceral Fat, Liver plan, Fix It With Food,
  Clear Your Home)? Keep long lessons trimmed in Telegram, or show only the start plus the video link? Pull movement
  lists out of the Psoas lesson text by hand?
- **Telegram O'Reilly list buttons:** status is shown by emoji colour alone (🟢🟠🟡 / 🟢⚪). Different shapes or a
  word would fix it (WCAG 1.4.1) but changes the chosen style.

### Small fixes

- Backup filenames use UTC (container has no time zone), so BST backups read `…-020000`. Set the container's time
  zone or name files in UK time.

## Waiting on the user

- Change the DailyOM password (it was pasted into the chat on 20 Oct; the chat export redacts it).
- DSM → Control Panel → Network → General: add a second DNS server (e.g. `1.1.1.1`); the NAS occasionally fails to
  reach GitHub.
- healthchecks.io account and `HEARTBEAT_URL` in the NAS secrets file (top-ten #3, remaining half).
- Hyper Backup / restore drill (top-ten #4): partly covered by the Google Drive copy above; a restore drill is still
  worth doing once.
- Event times for the 13 and 15 Oct O'Reilly events (admin O'Reilly page).
- Gmail address and app password for the O'Reilly email importer (typed into the NAS secrets file by the user).
- Yes / no on using the Claude API for the Radar summary.

## Feature backlog (from the top ten)

- **#5** Build images in CI (GHCR); the NAS pulls a tag instead of building.
- **#6 remainder:** calendar heatmaps per area, course/path progress bars, O'Reilly backlog burndown, chart in the
  Sunday summary.
- **#7** After "✓ Watched", ask for 1–3 takeaways and turn chosen ones into FSRS flashcards.
- **#8** Private calendar feed (ICS) of events and planned sessions.
- **#9** Adaptive nudges: answer rate by prompt type and time, with suggested changes in the weekly summary.
- **#10** Tighten the trust boundary: tested-branch deploy plus read-only deploy key before making the repo private.
- O'Reilly email importer (dedicated inbox → event and recording updates).
- Honourable mentions: Tailscale remote access, persist `/log` pending state, `/undo`, per-area quiet hours, PWA
  shortcut.

# Deploying on the Synology DS220+

The NAS keeps a git clone of this repo and checks GitHub every 15 minutes. When `main` changes, it rebuilds and restarts the container. You don't copy files by hand.

## How the pieces fit

| What | Where | Who runs it |
|---|---|---|
| Daily prompts, backups (app scheduler) | Inside the container, Europe/London time | The app itself (APScheduler) |
| Auto-update from GitHub | `deploy/update.sh` | DSM Task Scheduler, every 15 min, as root |
| Restart after reboot or crash | `restart: unless-stopped` | Container Manager |

Folder layout on the NAS:

```
/volume1/docker/lavie/
├── repo/       git clone of main (replaced on every deploy, holds no data)
├── secrets/    .env: root only (700 folder / 600 file, ACLs removed)
├── data/       lavie.db + backups/: container user only
└── logs/       update.log
```

`.env` and `data/` sit **outside** the clone, so a deploy can never overwrite or commit them.

## One-time setup

### 1. DSM packages and settings

1. **Package Center**: install **Container Manager** and **Git Server**. Git Server provides the `git` command; you don't need to configure it.
2. **Control Panel → Terminal & SNMP**: enable SSH, for setup only.
3. **Control Panel → Regional Options → Time**: make sure NTP time sync is on.
4. **Control Panel → Shared Folder**: a `docker` shared folder usually exists after installing Container Manager. If not, create one on Volume 1.

### 2. Install

From your PC (PowerShell has `ssh` built in):

```powershell
ssh <your-dsm-admin>@<nas-ip>
```

On the NAS:

```sh
cd /tmp
curl -fsSLO https://raw.githubusercontent.com/yotta-prime/la-vie_db/main/deploy/install.sh
sudo sh install.sh
```

This creates the folders, clones the repo and sets permissions. It will say the `.env` is missing; that's next.

### 3. Put the secrets on the NAS

Create the file directly in the root-only folder, without an editor or temporary file:

```sh
sudo sh -c 'umask 077; cat > /volume1/docker/lavie/secrets/.env'
```

Paste the contents of your local `.env`, press **Enter**, then **Ctrl+D**. Then re-run the installer to lock down ownership and permissions:

```sh
sudo sh /volume1/docker/lavie/repo/deploy/install.sh
sudo ls -la /volume1/docker/lavie/secrets   # expect: -rw------- root root .env
```

Also keep a copy of the token in your password manager. If it ever leaks, use `/revoke` in @BotFather and update the file.

### 4. First deploy

```sh
sudo sh /volume1/docker/lavie/repo/deploy/update.sh --force
curl http://localhost:8080/health
```

The first build takes a few minutes. Expect `{"status":"ok","bot":true,...}`. Then in Telegram, send `/start` to your bot. If `TELEGRAM_OWNER_CHAT_ID` is empty, the bot replies with your chat ID. Add it to the secrets file:

```sh
sudo sh -c 'umask 077; echo "TELEGRAM_OWNER_CHAT_ID=<id>" >> /volume1/docker/lavie/secrets/.env'
sudo sh /volume1/docker/lavie/repo/deploy/update.sh --force
```

`/ping` should now reply `pong`.

### 5. Schedule auto-updates (DSM Task Scheduler)

**Control Panel → Task Scheduler → Create → Scheduled Task → User-defined script**

- **General**: Task = `lavie update`, User = **root**, Enabled.
- **Schedule**: Run on the following days = **Daily**; First run time `00:00`; Frequency **Every 15 minutes**; Last run time `23:45`.
- **Task Settings → Run command**:
  ```sh
  /bin/bash /volume1/docker/lavie/repo/deploy/update.sh >> /volume1/docker/lavie/logs/update.log 2>&1
  ```
  Optionally tick *Send run details by email → only when the script terminates abnormally*.

Select the task and click **Run** once to check it. `logs/update.log` stays empty when nothing changed and gets a line per deploy. `logs/last-check` holds the time of the latest check, so you can confirm the schedule is running:

```sh
sudo cat /volume1/docker/lavie/logs/last-check   # should be less than 15 minutes old
```

If it isn't updating, check that the schedule says **Daily** with **Every 15 minutes**, not a single date or once a day. The command uses full paths (`/bin/bash`, `/volume1/...`), following Synology's [Task Scheduler scripting tips](https://kb.synology.com/en-uk/DSM/tutorial/common_mistake_in_task_scheduler_script).

### 6. Lock down

- **Disable SSH** again (Control Panel → Terminal & SNMP). Task Scheduler doesn't need it.
- **Firewall** (Control Panel → Security → Firewall): allow port **8080** only from your LAN subnet (e.g. `192.168.1.0/24`). Never forward 8080 on your router.
- **Hyper Backup**: include `docker/lavie/data/backups`. The app writes a consistent DB copy there at 03:00 each night.

### 7. Admin page

Add a password to the secrets file. It's generated on the NAS, so nothing has to be typed or pasted:

```sh
sudo sh -c 'umask 077; echo "ADMIN_PASSWORD=$(head -c 18 /dev/urandom | base64)" >> /volume1/docker/lavie/secrets/.env'
sudo grep ADMIN_PASSWORD /volume1/docker/lavie/secrets/.env   # copy it into your password manager
sudo sh /volume1/docker/lavie/repo/deploy/update.sh --force
```

Then open `http://<nas-ip>:8080/admin` from a device on your home network. Signing in lasts 30 days per browser. Changing the password signs every browser out.

## Day to day

- **Ship a change**: push or merge to `main`; it's live within 15 minutes.
- **Deploy now**: Task Scheduler → `lavie update` → Run. Or over SSH: `sudo sh .../update.sh --force`.
- **Logs**: Container Manager → Container → `lavie` → Log. Deploy history is in `logs/update.log`.
- **Change a secret**: edit `secrets/.env` (as root), then run the update with `--force` to restart.
- **Roll back**: revert the commit on GitHub; the NAS follows `main`.

## Security notes

- **Secrets file**: readable only by root. The update script refuses to run if it's group or world readable. DSM administrators can still read it with `sudo`, so keep the admin account list short and use 2FA on DSM.
- **Container**: runs as a non-root user (UID 1000) with a read-only filesystem, no Linux capabilities and `no-new-privileges`. It can write only to `/data` and `/tmp`.
- **Network**: the bot polls Telegram over outbound HTTPS, so there are no inbound ports from the internet.
- **Admin page**: plain HTTP on your LAN, password-protected with a signed `SameSite=Strict` cookie (other sites can't submit its forms). Keep port 8080 LAN-only in the firewall, as in step 6.
- **Schema upgrades**: when a deploy changes the database structure, the app saves `data/lavie.db.pre-v<N>.bak` before migrating.
- **Trust boundary**: whatever lands on `main` runs on your NAS within 15 minutes. Use 2FA on GitHub and consider a branch protection rule on `main` that requires a pull request. The Claude GitHub Action can open PRs, but only you merge them.
- **If the repo becomes private**: the anonymous HTTPS clone stops working. Create a read-only **deploy key**: `sudo ssh-keygen -t ed25519 -f /root/.ssh/lavie_deploy -N ""`. Add the `.pub` contents under GitHub repo → Settings → Deploy keys. Then point the clone at SSH:
  ```sh
  cd /volume1/docker/lavie/repo
  sudo git remote set-url origin git@github.com:yotta-prime/la-vie_db.git
  sudo git config core.sshCommand "ssh -i /root/.ssh/lavie_deploy -o IdentitiesOnly=yes"
  ```

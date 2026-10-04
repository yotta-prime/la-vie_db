#!/bin/sh
# One-time setup on the Synology. Run as root:
#   sudo sh install.sh
# Safe to re-run; it won't overwrite an existing repo, data or secrets.
set -eu

BASE="${LAVIE_BASE:-/volume1/docker/lavie}"
REPO_URL="${LAVIE_REPO_URL:-https://github.com/yotta-prime/la-vie_db.git}"
APP_UID=1000  # matches USER in the Dockerfile
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: sudo sh $0" >&2
    exit 1
fi
command -v git >/dev/null || { echo "git not found: install 'Git Server' from Package Center" >&2; exit 1; }
command -v docker >/dev/null || { echo "docker not found: install Container Manager" >&2; exit 1; }

mkdir -p "$BASE/data/backups" "$BASE/secrets" "$BASE/logs"

# Code: a plain clone of main, owned by root.
if [ ! -d "$BASE/repo/.git" ]; then
    git clone --branch main "$REPO_URL" "$BASE/repo"
fi

# Synology shared folders carry ACLs that can grant access regardless of chmod
# (e.g. via File Station or SMB). Strip them from the folders holding secrets and data.
strip_acl() {
    if command -v synoacltool >/dev/null; then
        synoacltool -del "$1" >/dev/null 2>&1 || true
    fi
}
for d in "$BASE/secrets" "$BASE/secrets/.env" "$BASE/data" "$BASE/logs"; do
    [ -e "$d" ] && strip_acl "$d"
done

# Secrets: only root can read the folder and the file.
chown root:root "$BASE/secrets"
chmod 700 "$BASE/secrets"
if [ -f "$BASE/secrets/.env" ]; then
    chown root:root "$BASE/secrets/.env"
    chmod 600 "$BASE/secrets/.env"
else
    echo "NOTE: put your .env at $BASE/secrets/.env, then re-run this script."
fi

# Data: writable by the container's non-root user only.
chown -R "$APP_UID:$APP_UID" "$BASE/data"
chmod 700 "$BASE/data"

chmod 700 "$BASE/logs"

echo "Done. Layout:"
ls -la "$BASE"

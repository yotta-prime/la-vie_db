#!/bin/sh
# Pull the latest main from GitHub and redeploy if anything changed.
# Run as root from DSM Task Scheduler (see docs/DEPLOY.md). Pass --force to redeploy anyway.
set -eu

BASE="${LAVIE_BASE:-/volume1/docker/lavie}"
REPO="$BASE/repo"
LOCK="$BASE/.update.lock"
export LAVIE_ENV_FILE="$BASE/secrets/.env"
export LAVIE_DATA_DIR="$BASE/data"
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

log() { echo "$(date '+%F %T') $*"; }

# Avoid overlapping runs if a build takes longer than the schedule interval.
if ! mkdir "$LOCK" 2>/dev/null; then
    log "another update is running; skipping"
    exit 0
fi
trap 'rmdir "$LOCK"' EXIT

if docker compose version >/dev/null 2>&1; then
    compose() { docker compose -p lavie "$@"; }
else
    compose() { docker-compose -p lavie "$@"; }
fi

# Refuse to run with a secrets file anyone else can read.
if [ ! -f "$LAVIE_ENV_FILE" ]; then
    log "missing $LAVIE_ENV_FILE"
    exit 1
fi
perms=$(stat -c '%a' "$LAVIE_ENV_FILE")
if [ "$perms" != "600" ] && [ "$perms" != "400" ]; then
    log "$LAVIE_ENV_FILE has mode $perms; run: chmod 600 $LAVIE_ENV_FILE"
    exit 1
fi

cd "$REPO"
git fetch --quiet origin main
# Heartbeat: shows the schedule is running even when there's nothing to deploy.
date '+%F %T' > "$BASE/logs/last-check"
local_rev=$(git rev-parse HEAD)
remote_rev=$(git rev-parse origin/main)
running=$(compose ps -q lavie 2>/dev/null || true)

if [ "$local_rev" = "$remote_rev" ] && [ -n "$running" ] && [ "${1:-}" != "--force" ]; then
    exit 0
fi

log "deploying $(git rev-parse --short origin/main) (was $(git rev-parse --short HEAD))"
git reset --hard --quiet origin/main
export LAVIE_VERSION="$(git rev-parse --short HEAD)"
compose up -d --build --remove-orphans
docker image prune -f >/dev/null
log "deployed"

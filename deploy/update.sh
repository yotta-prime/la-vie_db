#!/bin/sh
# Pull the latest main from GitHub and redeploy if anything changed.
# Run as root from DSM Task Scheduler (see docs/DEPLOY.md). Pass --force to redeploy anyway
# (this also skips the GitHub test check).
#
# A new commit is deployed only once its GitHub Actions tests have passed. Failed tests, a
# failed build, or a new version that doesn't answer /health are sent to you in Telegram.
#
# Everything runs inside main(), and the last line calls it and exits. The shell reads a
# script as it goes, and `git reset` below replaces this very file; wrapping it this way
# means the whole script is parsed before anything runs, so the old copy finishes cleanly.
set -eu

main() {
    BASE="${LAVIE_BASE:-/volume1/docker/lavie}"
    REPO="$BASE/repo"
    LOCK="$BASE/.update.lock"
    export LAVIE_ENV_FILE="$BASE/secrets/.env"
    export LAVIE_DATA_DIR="$BASE/data"
    export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

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
    stamp > "$BASE/logs/last-check"
    local_rev=$(git rev-parse HEAD)
    remote_rev=$(git rev-parse origin/main)
    running=$(compose ps -q lavie 2>/dev/null || true)

    if [ "$local_rev" = "$remote_rev" ] && [ -n "$running" ] && [ "${1:-}" != "--force" ]; then
        exit 0
    fi

    # Only rebuild/restart when something that goes into the container changed. Every restart
    # makes DSM email "container stopped unexpectedly", so docs-only commits just update the
    # repo copy. (/health keeps reporting the last *deployed* commit in that case.)
    if [ -n "$running" ] && [ "${1:-}" != "--force" ] && [ "$local_rev" != "$remote_rev" ]; then
        if ! git diff --name-only "$local_rev" "$remote_rev" \
            | grep -qE '^(app/|content/|Dockerfile|docker-compose\.yml|requirements\.txt|\.dockerignore)'; then
            git reset --hard --quiet origin/main
            log "updated repo to $(git rev-parse --short HEAD) (no app changes; container not restarted)"
            exit 0
        fi
    fi

    # Deploy only commits whose tests passed on GitHub (.github/workflows/test.yml).
    if [ "${1:-}" != "--force" ] && [ "$local_rev" != "$remote_rev" ]; then
        case "$(ci_result "$remote_rev")" in
            success) ;;
            failure)
                once "$remote_rev failure" && {
                    log "not deploying $(short "$remote_rev"): tests failed on GitHub"
                    notify "⚠️ la-vie: tests failed on GitHub for $(short "$remote_rev"); the NAS stays on $(short "$local_rev")."
                }
                exit 0 ;;
            *)
                once "$remote_rev pending" && log "waiting for GitHub tests on $(short "$remote_rev")"
                exit 0 ;;
        esac
    fi

    log "deploying $(short "$remote_rev") (was $(short "$local_rev"))"
    git reset --hard --quiet origin/main
    LAVIE_VERSION=$(git rev-parse --short HEAD)
    export LAVIE_VERSION
    if ! compose up -d --build --remove-orphans; then
        log "deploy failed"
        notify "⚠️ la-vie: deploy of $LAVIE_VERSION failed on the NAS. See logs/update.log."
        exit 1
    fi
    docker image prune -f >/dev/null

    # Confirm the new version answers (the app also says "la-vie started" in Telegram).
    i=0
    while [ $i -lt 24 ]; do
        if curl -fsS --max-time 5 http://localhost:8080/health 2>/dev/null | grep -q "\"$LAVIE_VERSION\""; then
            log "deployed"
            return 0
        fi
        i=$((i + 1))
        sleep 5
    done
    log "deployed $LAVIE_VERSION but /health didn't confirm it within 2 minutes"
    notify "⚠️ la-vie: deployed $LAVIE_VERSION but /health didn't answer with it within 2 minutes."
}

short() { echo "$1" | cut -c1-7; }

# GitHub Actions result for a commit: success, failure or pending (also if GitHub can't be asked).
ci_result() {
    runs=$(curl -fsS --max-time 20 -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/yotta-prime/la-vie_db/actions/workflows/test.yml/runs?head_sha=$1" \
        2>/dev/null) || { echo pending; return; }
    if echo "$runs" | grep -q '"conclusion": *"success"'; then
        echo success
    elif echo "$runs" | grep -qE '"conclusion": *"(failure|cancelled|timed_out)"'; then
        echo failure
    else
        echo pending
    fi
}

# True the first time it's called with a given key, so a waiting or failed commit is
# logged and alerted once rather than every 15 minutes.
once() {
    state="$BASE/logs/ci-state"
    [ -f "$state" ] && [ "$(cat "$state")" = "$1" ] && return 1
    echo "$1" > "$state"
}

# Telegram message to the owner, using the bot's own settings. Never fails the script.
notify() {
    token=$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' "$LAVIE_ENV_FILE" | tr -d '"\r')
    chat=$(sed -n 's/^TELEGRAM_OWNER_CHAT_ID=//p' "$LAVIE_ENV_FILE" | tr -d '"\r')
    [ -n "$token" ] && [ -n "$chat" ] || return 0
    curl -fsS --max-time 15 -o /dev/null "https://api.telegram.org/bot$token/sendMessage" \
        --data-urlencode "chat_id=$chat" --data-urlencode "text=$1" || true
}

# Times include the zone so they read unambiguously whatever DSM's time zone is.
stamp() { date '+%F %T %Z'; }
log() { echo "$(stamp) $*"; }

main "$@"; exit

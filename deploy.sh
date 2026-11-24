#!/usr/bin/env bash
# Deploy a pushed commit to the server, switch to it only if healthy, and roll back if not.
#
#   ./deploy.sh                 deploy origin/main
#   ./deploy.sh <commit>        deploy a commit already on origin/main
#   ./deploy.sh --dry-run       run the local checks and show what would change
#   ./deploy.sh --status        show what the server is running
#   ./deploy.sh --rollback      switch back to the previous release
#
# Server address and key live in the git-ignored `.deploy.env`. See docs/deploy.md.
# A deploy changes code only. It backs up the database but never writes to it.
set -euo pipefail

die() { echo "deploy: $*" >&2; exit 1; }

ACTION=deploy
REF=""
RUN_TESTS=1
DRY_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --status) ACTION=status ;;
    --rollback) ACTION=rollback ;;
    --dry-run) DRY_RUN=1 ;;
    --skip-tests) RUN_TESTS=0 ;;
    -h | --help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) die "unknown option: $1" ;;
    *) [ -z "$REF" ] || die "only one commit can be deployed"; REF="$1" ;;
  esac
  shift
done

# Worktrees share one config, kept beside the main checkout's .git directory.
REPO_ROOT="$(git rev-parse --show-toplevel)"
COMMON_DIR="$(cd "$REPO_ROOT" && cd "$(git rev-parse --git-common-dir)" && pwd)"
CONFIG_DIR="$(dirname "$COMMON_DIR")"
CONFIG="${DEPLOY_CONFIG:-$CONFIG_DIR/.deploy.env}"
[ -f "$CONFIG" ] || die "missing $CONFIG (copy .deploy.env.example)"
# shellcheck disable=SC1090
. "$CONFIG"

: "${DEPLOY_HOST:?set DEPLOY_HOST in .deploy.env}"
: "${DEPLOY_KEY:?set DEPLOY_KEY in .deploy.env}"
DEPLOY_KEY="${DEPLOY_KEY/#\~/$HOME}"
DEPLOY_KNOWN_HOSTS="${DEPLOY_KNOWN_HOSTS:-$CONFIG_DIR/.deploy.known_hosts}"
DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/stock-ontology}"
DEPLOY_SERVICE="${DEPLOY_SERVICE:-stock-ontology}"
DEPLOY_DB="${DEPLOY_DB:-/var/lib/stock-ontology/ontology.db}"
DEPLOY_BACKUPS="${DEPLOY_BACKUPS:-/var/backups/stock-ontology}"
DEPLOY_HEALTH_URL="${DEPLOY_HEALTH_URL:-http://127.0.0.1:8000/api/health}"
[ -f "$DEPLOY_KEY" ] || die "SSH key not found: $DEPLOY_KEY"
[ -f "$DEPLOY_KNOWN_HOSTS" ] || die "pinned host key not found: $DEPLOY_KNOWN_HOSTS"

SSH_OPTS=(-i "$DEPLOY_KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=15
  -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$DEPLOY_KNOWN_HOSTS")

remote() {
  local action="$1" commit="${2:-none}"
  ssh "${SSH_OPTS[@]}" "$DEPLOY_HOST" bash -s -- "$action" "$commit" "$DEPLOY_ROOT" \
    "$DEPLOY_SERVICE" "$DEPLOY_DB" "$DEPLOY_BACKUPS" "$DEPLOY_HEALTH_URL" <<'REMOTE'
set -euo pipefail
ACTION="$1"; COMMIT="$2"; ROOT="$3"; SERVICE="$4"; DB="$5"; BACKUPS="$6"; HEALTH="$7"
RELEASES="$ROOT/releases"; CURRENT="$ROOT/current"; PREVIOUS="$ROOT/previous"; INCOMING="$ROOT/incoming"
KEEP_RELEASES=5
KEEP_BACKUPS=10

say() { echo "[server] $*"; }
fail() { echo "[server] $*" >&2; exit 1; }
point() { ln -sfn "$1" "$2.tmp"; mv -Tf "$2.tmp" "$2"; }
target_of() { if [ -e "$1" ]; then readlink -f "$1"; fi; }

healthy() {
  local i
  for i in $(seq 1 45); do
    if systemctl is-active -q "$SERVICE" \
      && curl -fsS -m 4 "$HEALTH" 2>/dev/null | python3 -c 'import json,sys; sys.exit(json.load(sys.stdin).get("status") != "ok")' 2>/dev/null \
      && curl -fsS -m 8 -o /dev/null "${HEALTH%/api/health}/" 2>/dev/null; then
      # A process that crashes just after answering must not count as healthy.
      sleep 3
      systemctl is-active -q "$SERVICE" && curl -fsS -m 4 -o /dev/null "$HEALTH" 2>/dev/null && return 0
    fi
    sleep 1
  done
  return 1
}

show_status() {
  say "service:  $(systemctl is-active "$SERVICE" || true)"
  say "current:  $(basename "$(target_of "$CURRENT")")"
  if [ -e "$PREVIOUS" ]; then say "previous: $(basename "$(target_of "$PREVIOUS")")"; else say "previous: none"; fi
  say "releases: $(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -printf '%f ' 2>/dev/null)"
  if curl -fsS -m 4 "$HEALTH" >/dev/null 2>&1; then say "health:   ok"; else say "health:   FAILING"; fi
}

backup_db() {
  install -d -m 700 "$BACKUPS"
  local file="$BACKUPS/ontology-$(date -u +%Y%m%dT%H%M%SZ)-$COMMIT.db"
  sqlite3 -readonly "$DB" ".backup '$file'"
  # A standalone file, so no -wal or -shm companions pile up beside the backups.
  sqlite3 "$file" 'pragma journal_mode=DELETE;' >/dev/null
  [ "$(sqlite3 -readonly "$file" 'pragma integrity_check;')" = "ok" ] || fail "database backup failed its integrity check"
  chmod 600 "$file"
  find "$BACKUPS" -maxdepth 1 -name 'ontology-*.db' -printf '%T@ %p\n' | sort -rn | tail -n +$((KEEP_BACKUPS + 1)) \
    | cut -d' ' -f2- | xargs -r rm -f --
  say "database backed up: $file"
}

prune_releases() {
  local keep_current keep_previous dir
  keep_current="$(target_of "$CURRENT")"
  keep_previous="$(target_of "$PREVIOUS")"
  find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn | tail -n +$((KEEP_RELEASES + 1)) \
    | cut -d' ' -f2- | while IFS= read -r dir; do
      if [ "$dir" != "$keep_current" ] && [ "$dir" != "$keep_previous" ]; then rm -rf -- "$dir"; fi
    done
}

exec 9>"/run/lock/$SERVICE-deploy.lock"
flock -n 9 || fail "another deploy is running"

case "$ACTION" in
  status)
    show_status
    ;;

  needs-upload)
    [[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "bad commit"
    install -d -m 755 "$INCOMING"
    if [ -f "$RELEASES/$COMMIT/.complete" ]; then echo no; else echo yes; fi
    ;;

  rollback)
    [ -e "$PREVIOUS" ] || fail "no previous release to roll back to"
    from="$(target_of "$CURRENT")"; to="$(target_of "$PREVIOUS")"
    point "$to" "$CURRENT"
    systemctl restart "$SERVICE"
    if ! healthy; then
      point "$from" "$CURRENT"
      systemctl restart "$SERVICE"
      healthy || fail "rollback failed and the original release is unhealthy too"
      fail "rollback target was unhealthy; stayed on $(basename "$from")"
    fi
    point "$from" "$PREVIOUS"
    say "rolled back: $(basename "$from") -> $(basename "$to")"
    show_status
    ;;

  deploy)
    [[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "bad commit"
    command -v sqlite3 >/dev/null || fail "sqlite3 is not installed"
    release="$RELEASES/$COMMIT"
    from="$(target_of "$CURRENT")"
    old_previous="$(target_of "$PREVIOUS")"
    if [ "$from" = "$release" ]; then
      rm -f "$INCOMING/$COMMIT.tar"
      say "already running $COMMIT"
      show_status
      exit 0
    fi

    if [ ! -f "$release/.complete" ]; then
      [ -f "$INCOMING/$COMMIT.tar" ] || fail "release archive was not uploaded"
      [ "$release" != "$old_previous" ] || fail "refusing to rebuild the previous release"
      rm -rf -- "$release"
      install -d -m 755 "$release"
      tar -xf "$INCOMING/$COMMIT.tar" -C "$release"
      say "installing locked dependencies"
      (cd "$release" && UV_CACHE_DIR=/root/.cache/uv "$ROOT/tools/bin/uv" sync --locked --no-dev --python /usr/bin/python3 -q)
      "$release/.venv/bin/stock-ontology" --help >/dev/null
      touch "$release/.complete"
    fi
    rm -f "$INCOMING/$COMMIT.tar"

    if [ -n "$from" ] && ! cmp -s "$from/ontology_registry.json" "$release/ontology_registry.json"; then
      say "NOTICE: ontology_registry.json changed. Review it, then run registry-apply on the server."
    fi

    backup_db
    point "$release" "$CURRENT"
    say "restarting $SERVICE"
    systemctl restart "$SERVICE"
    if ! healthy; then
      journalctl -u "$SERVICE" -n 8 --no-pager -o cat | sed -E 's/[A-Za-z0-9_-]{35,}/<redacted>/g' >&2 || true
      [ -n "$from" ] || fail "first deploy failed its health check; there is no release to roll back to"
      say "health check FAILED, rolling back to $(basename "$from")"
      point "$from" "$CURRENT"
      systemctl restart "$SERVICE"
      healthy || fail "ROLLBACK FAILED: the service is down, check it now"
      fail "deploy failed; still running $(basename "$from")"
    fi
    if [ -n "$from" ]; then point "$from" "$PREVIOUS"; fi
    prune_releases
    say "deployed $COMMIT"
    show_status
    ;;

  *)
    fail "unknown action: $ACTION"
    ;;
esac
REMOTE
}

case "$ACTION" in
  status) remote status; exit 0 ;;
  rollback)
    [ "$DRY_RUN" -eq 0 ] || die "--dry-run does not apply to --rollback"
    remote rollback
    exit 0
    ;;
esac

cd "$REPO_ROOT"
git fetch -q origin main
if [ -n "$REF" ]; then
  COMMIT="$(git rev-parse --verify "$REF^{commit}")" || die "unknown commit: $REF"
else
  COMMIT="$(git rev-parse origin/main)"
fi
if [ "${DEPLOY_SKIP_PUSH_CHECK:-0}" != "1" ]; then
  git merge-base --is-ancestor "$COMMIT" origin/main || die "$COMMIT is not on origin/main. Push it first."
fi

if [ "$RUN_TESTS" -eq 1 ]; then
  # Test the exact commit, so uncommitted local edits can neither pass nor fail the deploy.
  TEST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/stock-ontology-deploy.XXXXXX")"
  trap 'rm -rf "$TEST_DIR"' EXIT
  git archive "$COMMIT" | tar -x -C "$TEST_DIR"
  echo "[local] testing $(git rev-parse --short "$COMMIT")"
  (cd "$TEST_DIR" && env -u VIRTUAL_ENV uv run --locked pytest -q) || die "tests failed; nothing was deployed"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[local] would deploy $COMMIT"
  git log -1 --format='[local] %h %s' "$COMMIT"
  remote status
  exit 0
fi

if [ "$(remote needs-upload "$COMMIT")" = "yes" ]; then
  echo "[local] uploading $(git rev-parse --short "$COMMIT")"
  git archive --format=tar "$COMMIT" -- pyproject.toml uv.lock README.md ontology_registry.json src \
    | ssh "${SSH_OPTS[@]}" "$DEPLOY_HOST" "cat > '$DEPLOY_ROOT/incoming/$COMMIT.tar'"
fi
remote deploy "$COMMIT"

#!/bin/zsh
set -euo pipefail

PROJECT=/Users/cheolhwanbae/Projects/ictlab
LABEL=cloud.metol.ictlab
DOMAIN=system
SYSTEM_PLIST="/Library/LaunchDaemons/$LABEL.plist"

if [[ ${1:-} != --check && ${1:-} != --execute ]] || [[ -z ${2:-} ]]; then
  echo "Usage: $0 --check|--execute <deployment-backup-directory>" >&2
  exit 64
fi
MODE=$1
BACKUP_DIR=$2
PLIST_BACKUP="$BACKUP_DIR/system-launchdaemon.plist"
COMMIT_FILE="$BACKUP_DIR/pre-deploy-commit.txt"

cd "$PROJECT"
git diff --quiet && git diff --cached --quiet || { echo "Tracked worktree changes exist" >&2; exit 1; }
[[ -f "$PLIST_BACKUP" && -f "$COMMIT_FILE" ]] || { echo "Deployment rollback files are missing" >&2; exit 1; }
plutil -lint "$PLIST_BACKUP" >/dev/null
ROLLBACK_COMMIT=$(<"$COMMIT_FILE")
git cat-file -e "$ROLLBACK_COMMIT^{commit}"
if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
  echo "Conflicting user LaunchAgent is loaded" >&2
  exit 1
fi
if [[ "$MODE" == --check ]]; then
  echo "System LaunchDaemon rollback preflight passed"
  exit 0
fi

sudo launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
git switch --detach "$ROLLBACK_COMMIT"
sudo install -o root -g wheel -m 0644 "$PLIST_BACKUP" "$SYSTEM_PLIST"
sudo launchctl bootstrap "$DOMAIN" "$SYSTEM_PLIST"

for attempt in {1..30}; do
  if curl --fail --silent http://127.0.0.1:5000/health >/dev/null; then
    echo "ICT Lab system LaunchDaemon rolled back to $(git rev-parse HEAD)"
    echo "Additive PE Summary tables were intentionally retained."
    exit 0
  fi
  sleep 1
done
echo "Rollback health check failed" >&2
exit 1

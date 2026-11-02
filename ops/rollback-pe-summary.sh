#!/bin/zsh
set -euo pipefail

PROJECT=/Users/cheolhwanbae/Projects/ictlab
LABEL=cloud.metol.ictlab
DOMAIN=system
SERVICE_TARGET="$DOMAIN/$LABEL"

if [[ ${1:-} != --check && ${1:-} != --execute ]] || [[ -z ${2:-} ]]; then
  echo "Usage: $0 --check|--execute <deployment-backup-directory>" >&2
  exit 64
fi
MODE=$1
BACKUP_DIR=$2
COMMIT_FILE="$BACKUP_DIR/pre-deploy-commit.txt"

cd "$PROJECT"
git diff --quiet && git diff --cached --quiet || { echo "Tracked worktree changes exist" >&2; exit 1; }
[[ -f "$COMMIT_FILE" ]] || { echo "Deployment rollback commit is missing" >&2; exit 1; }
ROLLBACK_COMMIT=$(<"$COMMIT_FILE")
git cat-file -e "$ROLLBACK_COMMIT^{commit}"
launchctl print "$SERVICE_TARGET" >/dev/null
if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
  echo "Conflicting user LaunchAgent is loaded" >&2
  exit 1
fi
if [[ "$MODE" == --check ]]; then
  echo "Registered LaunchDaemon rollback preflight passed"
  exit 0
fi

git switch --detach "$ROLLBACK_COMMIT"
sudo launchctl kickstart -k "$SERVICE_TARGET"

for attempt in {1..30}; do
  if curl --fail --silent http://127.0.0.1:5000/health >/dev/null; then
    echo "ICT Lab registered LaunchDaemon rolled back to $(git rev-parse HEAD)"
    echo "Existing PE Summary tables and uploads were retained."
    exit 0
  fi
  sleep 1
done
echo "Rollback health check failed" >&2
exit 1

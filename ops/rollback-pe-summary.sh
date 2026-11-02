#!/bin/zsh
set -euo pipefail

PROJECT=/Users/cheolhwanbae/Projects/ictlab
ROLLBACK_COMMIT=790e0e4
LABEL=cloud.metol.ictlab
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ ${1:-} != --execute ]]; then
  echo "Usage: $0 --execute" >&2
  exit 64
fi

cd "$PROJECT"
git diff --quiet && git diff --cached --quiet || { echo "Tracked worktree changes exist" >&2; exit 1; }
launchctl bootout "gui/$UID/$LABEL" >/dev/null 2>&1 || true
git switch --detach "$ROLLBACK_COMMIT"
launchctl bootstrap "gui/$UID" "$PLIST"

for attempt in {1..30}; do
  if curl --fail --silent http://127.0.0.1:5000/health >/dev/null; then
    echo "ICT Lab application rolled back to $(git rev-parse HEAD)"
    echo "Additive PE Summary tables were intentionally retained."
    exit 0
  fi
  sleep 1
done
echo "Rollback health check failed" >&2
exit 1

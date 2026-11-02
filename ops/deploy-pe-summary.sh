#!/bin/zsh
set -euo pipefail

PROJECT=/Users/cheolhwanbae/Projects/ictlab
SUPPORT='/Users/cheolhwanbae/Library/Application Support/ICTLab'
UPLOAD_ROOT="$SUPPORT/pe-summary-uploads"
FEATURE_COMMIT=a0f46d8140cb94e9ee7c1409e6a9d98444937e5a
ROLLBACK_COMMIT=790e0e4
LABEL=cloud.metol.ictlab
DOMAIN=system
SYSTEM_PLIST="/Library/LaunchDaemons/$LABEL.plist"
SOURCE_PLIST="$PROJECT/ops/$LABEL.plist"
service_stopped=0
BACKUP_DIR=

verify_inputs() {
  cd "$PROJECT"
  git merge-base --is-ancestor "$FEATURE_COMMIT" HEAD || { echo "PE Summary feature commit is missing" >&2; return 1; }
  git diff --quiet && git diff --cached --quiet || { echo "Tracked worktree changes exist" >&2; return 1; }
  [[ -f "$BACKUP_DIR/manifest.json" && -f "$BACKUP_DIR/ictlab.postgres.dump" ]] || { echo "Verified backup is missing" >&2; return 1; }
  [[ -f "$SYSTEM_PLIST" ]] || { echo "Production system plist is missing" >&2; return 1; }
  [[ -d "$UPLOAD_ROOT" && -O "$UPLOAD_ROOT" ]] || { echo "PE upload root owner is unexpected" >&2; return 1; }
  upload_mode=$(stat -f '%Lp' "$UPLOAD_ROOT")
  (( (8#$upload_mode & 8#200) != 0 )) || { echo "PE upload root owner cannot write" >&2; return 1; }
  .venv/bin/python -c 'import hashlib,json,sys; from pathlib import Path; root=Path(sys.argv[1]); data=json.loads((root/"manifest.json").read_text()); assert all((root/name).is_file() and (root/name).stat().st_size==meta["bytes"] and hashlib.sha256((root/name).read_bytes()).hexdigest()==meta["sha256"] for name,meta in data["backup_files"].items())' "$BACKUP_DIR"
  plutil -lint "$SOURCE_PLIST" >/dev/null
  launchctl print "$DOMAIN/$LABEL" >/dev/null
  if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
    echo "Conflicting user LaunchAgent is loaded" >&2
    return 1
  fi
  configured_upload_root=$(.venv/bin/python -c 'from dotenv import dotenv_values; print(dotenv_values(".env").get("PE_SUMMARY_UPLOAD_ROOT", ""))')
  [[ "$configured_upload_root" == "$UPLOAD_ROOT" ]] || { echo "Unexpected PE_SUMMARY_UPLOAD_ROOT" >&2; return 1; }
}

restore_previous_service() {
  exit_code=$?
  trap - ZERR
  set +e
  if (( service_stopped )); then
    echo "Deployment failed after system service stop; restoring previous service" >&2
    sudo launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
    git switch --detach "$ROLLBACK_COMMIT"
    sudo install -o root -g wheel -m 0644 "$BACKUP_DIR/system-launchdaemon.plist" "$SYSTEM_PLIST"
    sudo launchctl bootstrap "$DOMAIN" "$SYSTEM_PLIST"
    recovered=0
    for attempt in {1..30}; do
      if curl --fail --silent http://127.0.0.1:5000/health >/dev/null; then
        recovered=1
        break
      fi
      sleep 1
    done
    (( recovered )) && echo "Previous ICT Lab service restored" >&2 || echo "CRITICAL: automatic recovery health check failed" >&2
  fi
  exit "$exit_code"
}

if [[ ${1:-} != --check && ${1:-} != --execute ]] || [[ -z ${2:-} ]]; then
  echo "Usage: $0 --check|--execute <verified-backup-directory>" >&2
  exit 64
fi
MODE=$1
BACKUP_DIR=$2
verify_inputs
if [[ "$MODE" == --check ]]; then
  echo "System LaunchDaemon deployment preflight passed"
  exit 0
fi

trap restore_previous_service ZERR
cp "$SYSTEM_PLIST" "$BACKUP_DIR/system-launchdaemon.plist"
chmod 600 "$BACKUP_DIR/system-launchdaemon.plist"
print -r -- "$ROLLBACK_COMMIT" > "$BACKUP_DIR/pre-deploy-commit.txt"
chmod 600 "$BACKUP_DIR/pre-deploy-commit.txt"

source .venv/bin/activate
alembic -c alembic.ini upgrade head

sudo launchctl bootout "$DOMAIN/$LABEL"
service_stopped=1
sudo install -o root -g wheel -m 0644 "$SOURCE_PLIST" "$SYSTEM_PLIST"
sudo launchctl bootstrap "$DOMAIN" "$SYSTEM_PLIST"

for attempt in {1..30}; do
  if curl --fail --silent http://127.0.0.1:5000/health >/dev/null; then
    trap - ZERR
    echo "ICT Lab system LaunchDaemon healthy at $(git rev-parse HEAD)"
    exit 0
  fi
  sleep 1
done
echo "Production health check failed" >&2
exit 1

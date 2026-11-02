#!/bin/zsh
set -euo pipefail

PROJECT=/Users/cheolhwanbae/Projects/ictlab
SUPPORT='/Users/cheolhwanbae/Library/Application Support/ICTLab'
UPLOAD_ROOT="$SUPPORT/pe-summary-uploads"
FEATURE_COMMIT=a0f46d8140cb94e9ee7c1409e6a9d98444937e5a
LABEL=cloud.metol.ictlab
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ ${1:-} != --execute || -z ${2:-} ]]; then
  echo "Usage: $0 --execute <verified-backup-directory>" >&2
  exit 64
fi
BACKUP_DIR=$2

cd "$PROJECT"
git merge-base --is-ancestor "$FEATURE_COMMIT" HEAD || { echo "PE Summary feature commit is missing" >&2; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "Tracked worktree changes exist" >&2; exit 1; }
[[ -f "$BACKUP_DIR/manifest.json" && -f "$BACKUP_DIR/ictlab.postgres.dump" ]] || { echo "Verified backup is missing" >&2; exit 1; }
[[ -d "$UPLOAD_ROOT" && -w "$UPLOAD_ROOT" ]] || { echo "PE upload root is not writable" >&2; exit 1; }
.venv/bin/python -c 'import hashlib,json,sys; from pathlib import Path; root=Path(sys.argv[1]); data=json.loads((root/"manifest.json").read_text()); assert all((root/name).is_file() and (root/name).stat().st_size==meta["bytes"] and hashlib.sha256((root/name).read_bytes()).hexdigest()==meta["sha256"] for name,meta in data["backup_files"].items())' "$BACKUP_DIR"

if ! grep -q '^PE_SUMMARY_UPLOAD_ROOT=' .env; then
  printf '\nPE_SUMMARY_UPLOAD_ROOT="%s"\n' "$UPLOAD_ROOT" >> .env
  chmod 600 .env
fi
configured_upload_root=$(.venv/bin/python -c 'from dotenv import dotenv_values; print(dotenv_values(".env").get("PE_SUMMARY_UPLOAD_ROOT", ""))')
[[ "$configured_upload_root" == "$UPLOAD_ROOT" ]] || { echo "Unexpected PE_SUMMARY_UPLOAD_ROOT" >&2; exit 1; }

source .venv/bin/activate
alembic -c alembic.ini upgrade head

cp ops/cloud.metol.ictlab.plist "$PLIST"
chmod 644 "$PLIST"
old_pids=("${(@f)$(lsof -tiTCP:5000 -sTCP:LISTEN 2>/dev/null || true)}")
if [[ -n ${old_pids[1]:-} ]]; then
  print -l -- $old_pids > "$BACKUP_DIR/pre-deploy-pids.txt"
  master_pid=$(ps -axo pid=,ppid=,command= | awk '$2 == 1 && /gunicorn/ && /127.0.0.1:5000/ {print $1; exit}')
  [[ -n "$master_pid" ]] || { echo "Could not identify Gunicorn master" >&2; exit 1; }
  kill -QUIT -- "$master_pid"
  for attempt in {1..20}; do
    lsof -tiTCP:5000 -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 1
  done
  lsof -tiTCP:5000 -sTCP:LISTEN >/dev/null 2>&1 && { echo "Existing service did not stop" >&2; exit 1; }
fi
launchctl bootout "gui/$UID/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$UID" "$PLIST"

for attempt in {1..30}; do
  if curl --fail --silent http://127.0.0.1:5000/health >/dev/null; then
    echo "ICT Lab deployment healthy at $(git rev-parse HEAD)"
    exit 0
  fi
  sleep 1
done
echo "Health check failed; run ops/rollback-pe-summary.sh immediately" >&2
exit 1

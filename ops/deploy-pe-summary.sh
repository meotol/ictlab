#!/bin/zsh
set -euo pipefail

PROJECT=/Users/cheolhwanbae/Projects/ictlab
SUPPORT='/Users/cheolhwanbae/Library/Application Support/ICTLab'
UPLOAD_ROOT="$SUPPORT/pe-summary-uploads"
RELEASE_BASE=7c21601b79d97d305c96ade67bc6a1e63f0e0f2a
TARGET_REF=refs/heads/feature/pe-summary
TARGET_COMMIT=$(git -C "$PROJECT" rev-parse "$TARGET_REF^{commit}")
ROLLBACK_COMMIT=790e0e4a1c06fe6c73f3a4f0c52de4bdc26d16a3
LABEL=cloud.metol.ictlab
DOMAIN=system
SERVICE_TARGET="$DOMAIN/$LABEL"
SYSTEM_PLIST="/Library/LaunchDaemons/$LABEL.plist"
BACKUP_DIR=
deployment_started=0

verify_dependencies() {
  .venv/bin/python -m pip check >/dev/null
  git show "${TARGET_COMMIT}:requirements.txt" | .venv/bin/python -c 'import sys; from importlib.metadata import version; from packaging.requirements import Requirement; requirements=[Requirement(line) for line in sys.stdin.read().splitlines() if line.strip() and not line.lstrip().startswith("#")]; bad=[f"{r.name}: installed={version(r.name)}, required={r.specifier}" for r in requirements if version(r.name) not in r.specifier]; assert not bad, "; ".join(bad)'
  [[ -x .venv/bin/gunicorn ]] || { echo "Production Gunicorn is missing" >&2; return 1; }
}

verify_database() {
  .venv/bin/python -c 'from dotenv import dotenv_values; from sqlalchemy import create_engine,text; url=dotenv_values(".env").get("DATABASE_URL"); assert url, "DATABASE_URL missing"; engine=create_engine(url); connection=engine.connect(); transaction=connection.begin(); connection.execute(text("SET TRANSACTION READ ONLY")); tables=set(connection.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_name IN (\u0027pe_summaries\u0027,\u0027pe_summary_assets\u0027,\u0027alembic_version\u0027)")).scalars()); assert tables == {"pe_summaries","pe_summary_assets","alembic_version"}, f"Unexpected PE Summary schema state: {sorted(tables)}"; versions=set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars()); assert "20261102_01" in versions, f"PE Summary Alembic revision missing: {sorted(versions)}"; transaction.rollback(); connection.close(); engine.dispose()'
}

verify_inputs() {
  cd "$PROJECT"
  current_commit=$(git rev-parse HEAD)
  [[ "$current_commit" == "$ROLLBACK_COMMIT" || "$current_commit" == "$TARGET_COMMIT" ]] || { echo "Unexpected production commit: $current_commit" >&2; return 1; }
  git cat-file -e "$TARGET_COMMIT^{commit}"
  git merge-base --is-ancestor "$RELEASE_BASE" "$TARGET_COMMIT" || { echo "Release base is missing from deployment target" >&2; return 1; }
  git diff --quiet && git diff --cached --quiet || { echo "Tracked worktree changes exist" >&2; return 1; }
  [[ -f "$BACKUP_DIR/manifest.json" && -f "$BACKUP_DIR/ictlab.postgres.dump" ]] || { echo "Verified backup is missing" >&2; return 1; }
  [[ -f "$SYSTEM_PLIST" ]] || { echo "Production system plist is missing" >&2; return 1; }
  [[ -d "$UPLOAD_ROOT" && -O "$UPLOAD_ROOT" ]] || { echo "PE upload root owner is unexpected" >&2; return 1; }
  upload_mode=$(stat -f '%Lp' "$UPLOAD_ROOT")
  (( (8#$upload_mode & 8#200) != 0 )) || { echo "PE upload root owner cannot write" >&2; return 1; }
  .venv/bin/python -c 'import hashlib,json,sys; from pathlib import Path; root=Path(sys.argv[1]); data=json.loads((root/"manifest.json").read_text()); assert all((root/name).is_file() and (root/name).stat().st_size==meta["bytes"] and hashlib.sha256((root/name).read_bytes()).hexdigest()==meta["sha256"] for name,meta in data["backup_files"].items())' "$BACKUP_DIR"
  launchctl print "$SERVICE_TARGET" >/dev/null
  if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
    echo "Conflicting user LaunchAgent is loaded" >&2
    return 1
  fi
  configured_upload_root=$(.venv/bin/python -c 'from dotenv import dotenv_values; print(dotenv_values(".env").get("PE_SUMMARY_UPLOAD_ROOT", ""))')
  [[ "$configured_upload_root" == "$UPLOAD_ROOT" ]] || { echo "Unexpected PE_SUMMARY_UPLOAD_ROOT" >&2; return 1; }
  verify_dependencies
  verify_database
}

restore_previous_service() {
  exit_code=$?
  trap - ZERR
  set +e
  if (( deployment_started )); then
    echo "Deployment failed; restoring previous code and restarting registered service" >&2
    git switch --detach "$ROLLBACK_COMMIT"
    sudo launchctl kickstart -k "$SERVICE_TARGET"
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
  echo "Registered LaunchDaemon deployment preflight passed"
  exit 0
fi

trap restore_previous_service ZERR
cd "$PROJECT"
print -r -- "$(git rev-parse HEAD)" > "$BACKUP_DIR/pre-deploy-commit.txt"
chmod 600 "$BACKUP_DIR/pre-deploy-commit.txt"
deployment_started=1
git switch --detach "$TARGET_COMMIT"
sudo launchctl kickstart -k "$SERVICE_TARGET"

for attempt in {1..30}; do
  if curl --fail --silent http://127.0.0.1:5000/health >/dev/null; then
    trap - ZERR
    echo "ICT Lab registered LaunchDaemon healthy at $(git rev-parse HEAD)"
    exit 0
  fi
  sleep 1
done
echo "Production health check failed" >&2
exit 1

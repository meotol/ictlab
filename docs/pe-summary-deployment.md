# PE Summary deployment runbook

This runbook is preparation only. Do not copy the SQLite test database, temporary
uploads, test credentials, or the port 8082 LaunchAgent to production.

## Preconditions

- Deploy the reviewed commit from `feature/pe-summary` only after merging it by the
  approved release process.
- Confirm the service working directory is `/Users/cheolhwanbae/Projects/ictlab`.
- Confirm `.env` still targets the production PostgreSQL database and `.env.admin`
  contains the existing administrator account. Never print either secret value.
- Select a persistent directory outside `static/` for `PE_SUMMARY_UPLOAD_ROOT`,
  owned by the service account with mode `0700`.
- PDF.js is vendored under `static/vendor/pdfjs` and needs no package install.
- LibreOffice/soffice is optional. Without it DOCX/HWP/HWPX remain downloadable by
  administrators but public PDF preview conversion is unavailable.

## Backup

1. Create a timestamped, permission-restricted release backup directory.
2. Run `pg_dump` against the configured production `DATABASE_URL` into a custom-format
   database backup without echoing the URL or embedding it in a script.
3. Archive the existing `PE_SUMMARY_UPLOAD_ROOT` if it exists. Preserve ownership,
   permissions, and originals.
4. Record the pre-deployment Git commit and verify both backups before proceeding.

## Database migration

1. Preview SQL without connecting: `alembic -c alembic.ini upgrade head --sql` using
   a redacted/safe database URL.
2. During the approved deployment window, run
   `.venv/bin/alembic -c alembic.ini upgrade head` exactly once.
3. Verify `pe_summaries`, `pe_summary_assets`, their indexes, foreign key, and the
   Alembic revision `20261102_01`. Do not run `Base.metadata.create_all` in production.

## Low-downtime release

1. Keep news collection stopped only for the shortest interval needed if schema backup
   consistency requires it; the new tables do not alter news or content tables.
2. Apply the migration before starting code that queries the new tables.
3. Restart only the ICT Lab web process through its approved service manager. Do not
   copy or enable the test LaunchAgent.
4. Check `/health`, `/news`, existing HTML content, `/pe-summaries`, administrator
   login, one PDF preview, original-download authorization, and media Range responses.
5. Resume/verify the existing news job and monitor the existing service logs.

## Rollback

1. Restore the pre-deployment code commit and restart only the ICT Lab web process.
   Old code ignores the additive PE Summary tables, so leave them in place for the
   safest application rollback.
2. If removal is explicitly approved and no production PE Summary data must remain,
   archive uploads first, then run `alembic downgrade base`. This deletes both new
   tables and their data.
3. If migration or data corruption occurred, restore PostgreSQL and uploads from the
   matched timestamped backups. Never restore the SQLite test database.

The existing rich HTML import uses `contents` and `CONTENT_UPLOAD_ROOT`; PE Summary
uses separate tables and `PE_SUMMARY_UPLOAD_ROOT`, so their storage and routes do not
overlap.

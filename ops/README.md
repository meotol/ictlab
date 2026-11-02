# PE Summary production switch

The deployed commit must contain PE Summary feature commit
`a0f46d8140cb94e9ee7c1409e6a9d98444937e5a` as an ancestor.

Production is managed only by the system LaunchDaemon
`/Library/LaunchDaemons/cloud.metol.ictlab.plist`. Do not bootstrap a user
LaunchAgent with the same label. The scripts are inert without `--execute`.

Run the read-only preflight before the approved maintenance window:

```sh
/Users/cheolhwanbae/Projects/ictlab-pe-release/ops/deploy-pe-summary.sh --check "/Users/cheolhwanbae/Library/Application Support/ICTLab/backups/<timestamp>"
```

After approval, run the release-worktree copy of the script. It switches the
production worktree to the reviewed commit and restarts the already registered
system LaunchDaemon with `kickstart -k`; it does not bootout, bootstrap, or
replace the plist:

```sh
/Users/cheolhwanbae/Projects/ictlab-pe-release/ops/deploy-pe-summary.sh --execute "/Users/cheolhwanbae/Library/Application Support/ICTLab/backups/<timestamp>"
```

If the health or smoke checks fail, immediately run:

```sh
/Users/cheolhwanbae/Projects/ictlab-pe-release/ops/rollback-pe-summary.sh --execute "/Users/cheolhwanbae/Library/Application Support/ICTLab/backups/<timestamp>"
```

Deployment records the live Git commit in the verified backup directory before
switching code. Its preflight requires the PE Summary tables and Alembic revision
`20261102_01` to exist, so it never applies a duplicate migration. Rollback restores
the recorded Git commit and uses the same `kickstart -k` restart, leaving the
registered plist, PE Summary tables, uploads, and the port 8082 test service in
place. Restore PostgreSQL and uploads from the matched backup only if the database
itself must be reverted. Do not copy SQLite test data or test accounts to production.

# PE Summary production switch

The deployed commit must contain PE Summary feature commit
`a0f46d8140cb94e9ee7c1409e6a9d98444937e5a` as an ancestor.

Production is managed only by the system LaunchDaemon
`/Library/LaunchDaemons/cloud.metol.ictlab.plist`. Do not bootstrap a user
LaunchAgent with the same label. The scripts are inert without `--execute`.

Run the read-only preflight before the approved maintenance window:

```sh
ops/deploy-pe-summary.sh --check "/Users/cheolhwanbae/Library/Application Support/ICTLab/backups/<timestamp>"
```

After approval, run:

```sh
ops/deploy-pe-summary.sh --execute "/Users/cheolhwanbae/Library/Application Support/ICTLab/backups/<timestamp>"
```

If the health or smoke checks fail, immediately run:

```sh
ops/rollback-pe-summary.sh --execute "/Users/cheolhwanbae/Library/Application Support/ICTLab/backups/<timestamp>"
```

Deployment backs up the live system plist and rollback commit into the verified
backup directory before stopping the service. Rollback restores both and leaves
the additive PE Summary tables in place. Restore PostgreSQL and uploads from the
matched backup only if the database itself must be reverted. Do not copy SQLite
test data, test accounts, or the port 8082 LaunchAgent into production.

# PE Summary production switch

The deployed commit must contain PE Summary feature commit
`a0f46d8140cb94e9ee7c1409e6a9d98444937e5a` as an ancestor.

These scripts are intentionally inert without `--execute`. Before the approved
maintenance window, review the verified backup manifest and run:

```sh
ops/deploy-pe-summary.sh --execute "/Users/cheolhwanbae/Library/Application Support/ICTLab/backups/<timestamp>"
```

If the health or smoke checks fail, immediately run:

```sh
ops/rollback-pe-summary.sh --execute
```

Rollback restores application commit `790e0e4` and leaves the additive PE Summary
tables in place. Restore PostgreSQL and uploads from the matched backup only if the
database itself must be reverted. Do not copy the SQLite test data or port 8082
LaunchAgent into production.

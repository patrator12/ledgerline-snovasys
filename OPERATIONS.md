# Operations runbook

## Diagnose a failed start

For local Docker Compose, inspect service state and the last startup messages:

```sh
docker compose ps
docker compose logs --tail=100 web db
```

The web container should report that the schema and append-only guards are ready, the demo users are ready, and Uvicorn is listening. Startup adds the KYC/freeze fields, converts legacy signed ledger deltas into balanced debit/credit postings, and builds or verifies the SHA-256 chain. If a later startup finds a partially populated or invalid chain, it fails closed; preserve the database and inspect it rather than rebuilding the chain. If startup otherwise stops, check database reachability and the values configured for `DATABASE_URL`, `MIGRATION_DATABASE_URL`, and the seed-password variables. Do not print or paste environment values into logs or support messages.

Before deploying a release that migrates an existing ledger, take and retain a database backup. After startup, verify `/api/ledger/verify`; stop and investigate if it returns `valid: false`.

For Render, inspect the service's deploy and runtime logs. A successful image build does not prove the database connection or startup commands succeeded. Verify the health check at `/login`; only share the relevant error lines, with credentials and connection strings removed.

## Create a backup

For local Compose, create a custom-format dump outside the repository:

```sh
docker compose exec -T db pg_dump -U ledgerline_owner -d ledgerline --format=custom > "$HOME/ledgerline-$(date +%Y%m%d-%H%M%S).dump"
```

For Neon or another PostgreSQL host, use an installed PostgreSQL client and the direct owner connection URL from the secret manager:

```sh
pg_dump --format=custom --dbname "$MIGRATION_DATABASE_URL" --file "$HOME/ledgerline-$(date +%Y%m%d-%H%M%S).dump"
```

Protect the dump: it contains account data and password hashes. Keep it outside the Git repository and restrict access to it. This project does not schedule backups; set a provider backup policy appropriate for the data before production use.

## Restore to a separate database first

1. Create an empty recovery database or an isolated Neon branch. Do not restore over the live database as the first recovery step.
2. Restore the dump with `pg_restore --exit-on-error --no-owner --dbname "$RECOVERY_DATABASE_URL" /path/to/ledgerline.dump`.
3. Run `python -m app.init_db` with `MIGRATION_DATABASE_URL` pointing at the recovery database. This reapplies the runtime grants and append-only guards; ensure the `ledgerline_app` role exists first.
4. Point a test deployment at the recovery database, sign in with known credentials, inspect balances/statements, and run `docker compose --profile test run --build --rm tests` against its disposable test database.
5. If a stored audit checkpoint is available, point `DATABASE_URL` at the recovery database and verify it as described below. Retain the old database until recovery checks pass.

## Audit checkpoint

For local Compose, create a point-in-time checkpoint and store its JSON output outside the repository:

```sh
docker compose exec -T web python -m app.audit_checkpoint > "$HOME/ledgerline-audit-checkpoint.json"
```

To verify it later against the current local database:

```sh
cat "$HOME/ledgerline-audit-checkpoint.json" | docker compose exec -T web python -m app.audit_checkpoint --verify -
```

For a hosted database, run the module in an environment with `DATABASE_URL` set to that database and Python dependencies installed. Store the JSON output in a separate, access-controlled location.

The checkpoint hashes every audit event through the recorded event ID, so later legitimate events do not invalidate it. A mismatch means the saved prefix differs from the stored checkpoint. This is a manual checkpoint, not a continuously monitored hash chain; its value depends on retaining the file outside the database with separate access controls.

## Verify ledger integrity

The public verification endpoint scans the ledger and returns chain continuity, cached-balance parity, and transfer-posting parity:

```sh
curl --fail --silent --show-error http://localhost:8000/api/ledger/verify
```

For a hosted deployment, use the same path on the service's HTTPS URL. If `valid` is false, preserve the response and stop using the affected ledger until the mismatch is investigated. The endpoint reports aggregate counts and hashes, not account names or balances.

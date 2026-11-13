# LedgerLine

LedgerLine is a small money-movement and audit-ledger challenge project. It uses FastAPI and PostgreSQL for role-checked movements, concurrency control, idempotency, append-only records, and a SHA-256 ledger-entry chain.

The signed-in workspace is organized into separate pages: **Overview** for balances and a short recent-activity summary; **Accounts** for account balances and statements; **Transactions** for protected deposits, withdrawals, and transfers; **Activity** for ledger postings; **Governance** for administrator-only account and KYC controls; and **Audit log** for administrator and auditor review. Navigation only shows pages relevant to the signed-in role, and the server enforces access independently of the interface.

## Local setup

Requirements: Docker Desktop with Docker Compose.

1. Copy .env.example to .env and replace every sample value with a long random value. The database passwords in the sample compose file should contain only letters and numbers so they can be placed safely in the connection URL.
2. Start the app:

        docker compose up --build

3. Open http://localhost:8000.
4. Sign in using one of the usernames below and the matching password you placed in .env:

| Role | Username | Password source |
| --- | --- | --- |
| Administrator | demo-admin | SEED_ADMIN_PASSWORD |
| Account holder | demo-holder | SEED_HOLDER_PASSWORD |
| Read-only auditor | demo-auditor | SEED_AUDITOR_PASSWORD |

The sample records include two holder-owned accounts, with opening balances recorded in the ledger, and one shared settlement account. The passwords are never stored in this repository. Do not use local demo credentials for a public deployment.

The container runs as an unprivileged user. For an HTTPS deployment, set `APP_ENV=production` in the deployment environment so session cookies become Secure and the app adds HSTS. Login failures are throttled in PostgreSQL: five bad passwords for the same username and client address in 15 minutes block that pair for 15 minutes. The shared database counter works across app instances; distributed attempts from different addresses can still evade it. Throttle keys store a SHA-256 digest instead of raw username/address values, and up to 100 buckets idle for seven days are pruned during successful or failed credential checks.

Stop the app with docker compose down. Database data is stored in a named Docker volume and remains after stopping the containers.

## Deployment configuration

The Render blueprint is in `render.yaml`. It expects these private environment variables to be set in Render:

- `DATABASE_URL`: pooled PostgreSQL URL for normal app requests.
- `MIGRATION_DATABASE_URL`: direct PostgreSQL owner URL used for schema setup and demo seeding.
- `SEED_ADMIN_PASSWORD`, `SEED_HOLDER_PASSWORD`, and `SEED_AUDITOR_PASSWORD`: passwords for the three demo users.
- `APP_ENV=production`: enables Secure session cookies and HSTS.

The Docker startup command applies the schema and append-only guards, seeds demo accounts, then starts Uvicorn on Render's `PORT`. Keep database URLs and passwords in the hosting provider's secret settings; never commit them or place live passwords in this README. The current public deployment URL and account passwords are intentionally not duplicated here.

## Money rules

- Amounts are stored as positive integer paise in explicit `DEBIT` and `CREDIT` postings; no floating point is used for balance arithmetic. Every transfer has equal debit and credit totals. Deposits, withdrawals, and opening balances pair account postings with the `EXTERNAL_CLEARING` contra account.
- Administrators can create accounts, deposit, withdraw, transfer, review holder KYC status, and freeze or unfreeze accounts. New owned accounts can be assigned only to active, KYC-approved holders. Holders can move funds only when approved and only between accounts they own. Frozen accounts reject all money movements. Auditors can view accounts, statements, and the global audit log but cannot move money or change governance state.
- Each movement has an actor-scoped idempotency key and a payload hash. Replaying the same key and request returns its saved result; reusing a key with a different request is refused.
- Idempotency results expire after 24 hours. Reuse after expiry is treated as a new request.
- Money-moving requests lock every involved account row in sorted ID order. The balance check, account balance updates, ledger postings, audit event, and idempotency result commit in one PostgreSQL transaction.
- Every ledger posting links to the previous posting with a SHA-256 digest. A PostgreSQL transaction advisory lock serializes appends across workers; `GET /api/ledger/verify` checks chain continuity, account balance totals, and equal-and-opposite transfer postings.
- A transfer writes equal and opposite postings, so its postings sum to zero. Withdrawals and deposits are external movements and change the total by their amount.
- ledger_entries and audit_events have PostgreSQL triggers that reject updates and deletes. The web app connects as a restricted ledgerline_app role that has insert but no update/delete access to those tables. Schema setup runs using a separate owner connection.
- Refused movement attempts are recorded with the actor, reason, requested amount, and balance observed while the account row is locked, where the account exists.
- Passwords use bcrypt for new hashes; existing Argon2 hashes upgrade to bcrypt at the next successful login. Browser sessions are signed HS256 JWTs with an HttpOnly cookie and server-side session record so logout can revoke them. The signing key can be set with `SESSION_SIGNING_KEY`; otherwise it is derived from the private database URL.

## Roles

| Role | Read | Create accounts | Deposit | Withdraw | Transfer |
| --- | --- | --- | --- | --- | --- |
| Administrator | All accounts | Yes | Yes | Any account | Any account |
| Account holder | Owned accounts | No | No | Owned accounts | Between owned accounts |
| Auditor | All accounts | No | No | No | No |

The server applies these checks on each request. UI visibility is not an authorization boundary.

## How a transfer is processed

1. The route parses the INR amount into integer paise and passes the authenticated user, account IDs, and idempotency key to the money service.
2. The service hashes the request fields and checks whether this actor/key already has a result. A changed payload under the same key is refused.
3. It inserts the idempotency record inside the transaction, then locks the existing source and destination rows with SELECT FOR UPDATE in sorted ID order.
4. After acquiring the locks, it checks account status, freeze state, role, holder KYC approval, ownership, and available source balance.
5. If valid, it updates both cached balances, inserts equal-and-opposite ledger postings, writes an audit event, and saves the response on the idempotency record. A matching retry returns that saved response and adds an append-only replay event without posting money again.
6. Each new ledger posting is linked to the prior hash while holding the chain advisory lock. One commit makes all movement and chain writes visible together. If any database write fails, none of the movement is committed.
7. If another request has the same actor/key, PostgreSQL's unique constraint makes it wait for the first transaction. It then returns the saved result or, if the first transaction rolled back, can process the request itself.

The account-row lock is the concurrency control: the second withdrawal waits, then reads the committed balance and refuses if the first withdrawal used the available funds. The database check constraint is a second guard against negative cached balances.

## Tests

The integration suite starts a separate PostgreSQL container with a temporary filesystem. It does not touch the demo database.

        docker compose --profile test run --build --rm tests

The tests cover balanced debit/credit postings and transfer conservation, deposits and withdrawals, 24-hour retry expiry and concurrent key conflicts, idempotency payload conflicts, cross-account access, concurrent withdrawals, account-owner assignment, auditor restrictions, login CSRF and throttling, signed session expiry, transaction CSRF, invalid account IDs, filtered audit pagination, audit checkpoint stability, ledger-chain verification, KYC and freeze controls, amount parsing, and database append-only behavior. `tests/test_stride.py` adds one regression group for each STRIDE category. Run them against the isolated PostgreSQL test service after changes; they do not share the demo database.

## Current limits

This is a challenge prototype, not a production banking service. Ledger entries remain signed account deltas with cached balances rather than a general-ledger debit/credit journal; deposits and withdrawals use external-movement postings. The public verifier scans the full ledger and is intended for challenge-scale data. It does not implement MFA, password reset, multi-currency conversion, reversals/refunds, holds, automatic backups, or continuous external audit monitoring. Login throttling is per username/address pair and does not stop distributed guessing. The manual audit checkpoint detects changes only when its file is stored separately with stronger access controls. The auditor view is read-only. Deployment still needs HTTPS and deployment-specific secrets; production cookies switch to Secure and the __Host- prefix when APP_ENV=production.

## Project files

- app/money.py: authorization, idempotency, row locks, ledger posting, and refusal audit logic.
- app/ledger_chain.py: serialized ledger hash-chain appends and public verification checks.
- app/login_throttle.py: shared PostgreSQL-backed login failure throttling.
- app/audit_checkpoint.py: point-in-time audit digest generation and verification.
- app/models.py: database records and relationships.
- app/main.py: login, role-scoped workspace pages, statements, audit, and money-movement routes.
- app/init_db.py: schema creation, append-only triggers, and restricted app-role grants.
- THREATS.md: threat model, controls, and accepted risks.
- OPERATIONS.md: startup troubleshooting, PostgreSQL backup/recovery, and out-of-band audit checkpoints.
- PROMPTS.md: dated AI-use record. Add entries as you work and link each to the real commit that contains your review or correction; do not invent commit history.
- API.md: endpoint behavior and access rules.
- DEMO.md: a five-minute walkthrough outline for recording the required video.

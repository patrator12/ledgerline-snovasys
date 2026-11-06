# LedgerLine

LedgerLine is a small money-movement and audit-ledger challenge project. It uses FastAPI for the web application and PostgreSQL as the authority for balance updates, idempotency, and append-only records.

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

Stop the app with docker compose down. Database data is stored in a named Docker volume and remains after stopping the containers.

## Money rules

- Amounts are stored as integer paise; no floating point is used for balance arithmetic.
- Administrators can create accounts, deposit, withdraw, and transfer. Account holders can withdraw and transfer only between accounts they own. Auditors can view accounts and statements but cannot move money.
- Each movement has an actor-scoped idempotency key and a payload hash. Replaying the same key and request returns its saved result; reusing a key with a different request is refused.
- Money-moving requests lock every involved account row in sorted ID order. The balance check, account balance updates, ledger postings, audit event, and idempotency result commit in one PostgreSQL transaction.
- A transfer writes equal and opposite postings, so its postings sum to zero. Withdrawals and deposits are external movements and change the total by their amount.
- ledger_entries and audit_events have PostgreSQL triggers that reject updates and deletes. The web app connects as a restricted ledgerline_app role that has insert but no update/delete access to those tables. Schema setup runs using a separate owner connection.
- Refused movement attempts are recorded with the actor, reason, requested amount, and balance observed while the account row is locked, where the account exists.

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
4. After acquiring the locks, it checks account status, role, ownership, and available source balance.
5. If valid, it updates both cached balances, inserts equal-and-opposite ledger postings, writes an audit event, and saves the response on the idempotency record.
6. One commit makes all those writes visible together. If any database write fails, none of the movement is committed.
7. If another request has the same actor/key, PostgreSQL's unique constraint makes it wait for the first transaction. It then returns the saved result or, if the first transaction rolled back, can process the request itself.

The account-row lock is the concurrency control: the second withdrawal waits, then reads the committed balance and refuses if the first withdrawal used the available funds. The database check constraint is a second guard against negative cached balances.

## Tests

The integration suite starts a separate PostgreSQL container with a temporary filesystem. It does not touch the demo database.

        docker compose --profile test run --rm tests

The tests cover transfer conservation, retries, idempotency-key payload conflicts, cross-account access, concurrent withdrawals, auditor restrictions, and database append-only behavior.

## Current limits

This is a challenge prototype, not a production banking service. It does not implement MFA, password reset, login rate limiting, multiple-currency conversion, reversals/refunds, holds, or signed/externally anchored audit hashes. The auditor view is read-only. Deployment still needs HTTPS and deployment-specific secrets; production cookies switch to Secure and the __Host- prefix when APP_ENV=production.

## Project files

- app/money.py: authorization, idempotency, row locks, ledger posting, and refusal audit logic.
- app/models.py: database records and relationships.
- app/main.py: login, statements, dashboard, and money-movement routes.
- app/init_db.py: schema creation, append-only triggers, and restricted app-role grants.
- THREATS.md: threat model, controls, and accepted risks.
- PROMPTS.md: dated AI-use record. Add entries as you work and link each to the real commit that contains your review or correction; do not invent commit history.
- API.md: endpoint behavior and access rules.
- DEMO.md: a five-minute walkthrough outline for recording the required video.

# Threat model

Scope: the challenge application, its web endpoints, and the PostgreSQL database exposed through the application's restricted database role. The app is a learning prototype; see README.md for features intentionally left out.

| Threat | Control in this version | Evidence / remaining risk |
| --- | --- | --- |
| Two withdrawals race and overdraw one account | PostgreSQL row lock (SELECT ... FOR UPDATE) is held through the transaction; balance validation occurs after lock acquisition. | tests/test_money.py::test_concurrent_withdrawals_cannot_overdraw uses two independent sessions. Needs run against PostgreSQL before hand-in. |
| A transfer debits one account but fails before credit | Both balance changes, postings, audit entry, and idempotency result share one database transaction. | tests/test_money.py::test_transfer_balances_both_accounts_and_conserves_total. |
| A retry or double-click pays twice, or is hard to audit | Unique (actor_id, key) constraint, payload hash comparison, saved result, and an append-only replay event containing a transfer reference and key fingerprint. | tests/test_money.py::test_replayed_idempotency_key_returns_original_result_without_second_posting. The same key must be used on retry. |
| A holder names another user's account | Server checks ownership after locking the involved rows; UI filtering is only convenience. | tests/test_money.py::test_account_holder_cannot_move_someone_elses_funds. Account IDs are identifiers, not capabilities. |
| Auditor or holder escalates to an administrator action | Role checks run inside the service for every movement; account creation is administrator-only. | Auditor movement test exists. No multi-tenant admin delegation is implemented. |
| An operator silently changes or removes a posted ledger/audit row | PostgreSQL triggers reject UPDATE/DELETE; app database role has only SELECT/INSERT on those tables. | tests/test_money.py::test_financial_and_audit_rows_are_database_append_only. A database owner can alter triggers; protect owner credentials and backups. This is not cryptographic tamper evidence. |
| Request forgery triggers movement in a signed-in browser | Session CSRF token required on POST forms; login uses a short-lived double-submit token; cookies are HttpOnly and SameSite=Lax. Production mode sets Secure cookies. | CSRF rejection is logged for transaction requests. No automated browser CSRF test yet. |
| Session token is guessed or stolen from the database | 256-bit random cookie token; only SHA-256 verifier is stored server-side; 12-hour server expiry; logout deletes the session. | No MFA, suspicious-session alerts, or forced global revocation UI. HTTPS is required in deployment. |
| Concurrent transfers lock accounts in opposite order | All involved account IDs are sorted before locks are acquired. | Reduces the common transfer deadlock cycle; deadlocks can still arise from other database work and need retry/monitoring policy for a larger system. |
| Invalid amount or insufficient funds is hidden from the statement | Refused attempts are stored in the append-only audit event stream with actor, reason, requested amount, and locked balance when the account exists. | GET /accounts/{id} displays refused attempts. Malformed CSRF/parser failures have less context than normal service-level refusals. |
| Login brute force or audit storage exhaustion | Not implemented in this prototype. | Accepted risk for the challenge demo; add rate limits, bounded retention/archival, and alerting before production use. |
| SQL injection or reflected input | SQLAlchemy parameterized expressions; Jinja HTML autoescaping; no raw user-generated SQL. | No dedicated injection or XSS test suite yet. |

## Invariants

1. Every transfer has postings whose signed amounts sum to zero.
2. An account's cached balance changes in the same transaction as its ledger posting.
3. An account balance never becomes negative through the movement service.
4. A given actor/key pair can produce at most one committed result.
5. A holder can move money only from accounts owned by that holder; transfers also require ownership of the destination.
6. The web application's database role cannot update or delete ledger or audit rows.

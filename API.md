# HTTP routes

All application routes are same-origin HTML routes. Authenticated POST routes use form encoding and require the session CSRF token; login uses its short-lived double-submit CSRF cookie. Unauthenticated requests to protected pages redirect to /login. Money requests are checked on the server, regardless of controls shown in the browser.

| Method and route | Access | Behavior and money effect |
| --- | --- | --- |
| GET /login | Public | Issues a short-lived login CSRF cookie and renders the sign-in form. |
| POST /login | Public + login CSRF | Verifies the Argon2 password hash and creates a random opaque server-side session. Five failed passwords for the same username/client-address pair within 15 minutes cause a 15-minute block; blocked attempts return 429 and `Retry-After`. |
| GET /api/ledger/verify | Public | Recomputes the ledger SHA-256 chain, compares each account balance to its signed posting total, and checks transfer posting parity. Returns only verification status and aggregate counts. |
| POST /logout | Authenticated + session CSRF | Deletes the current server-side session. |
| GET /dashboard | Authenticated | Shows only owned accounts to holders; administrators and auditors can view all accounts. Shows recent successful ledger postings. |
| GET /accounts/{account_id} | Authenticated | Shows a per-account statement with signed ledger postings and refused attempts, including the actor and resulting balance when known. Holder ownership is checked on the server. |
| GET /audit | Administrator or auditor | Shows up to 100 append-only audit events, including refused actions and idempotent retries. Supports `action`, `outcome`, and `before_id` query parameters for filtering and older-page navigation. Other roles are refused and that attempt is recorded. |
| POST /accounts | Administrator + session CSRF | Creates a zero-balance INR account and records an audit event. An assigned holder must be active and KYC-approved. |
| POST /accounts/{account_id}/freeze | Administrator + session CSRF | Freezes or unfreezes an account and records the governance action in the audit log. Frozen accounts cannot be used for money movement. |
| POST /users/{user_id}/kyc | Administrator + session CSRF | Sets an account holder's KYC status to `PENDING`, `APPROVED`, or `REJECTED` and records the prior and new status in the audit log. Only `APPROVED` holders may move funds. |
| POST /transactions | Authenticated + session CSRF | Performs a deposit, withdrawal, or transfer after role and account checks. Requires a client idempotency key and amount with at most two decimals. |

## Transaction form fields

- action: deposit, withdrawal, or transfer.
- amount: positive INR amount up to ₹1,000,000,000 with up to two decimal places; stored as integer paise. Exponent notation and malformed values are refused.
- source_id: required for withdrawals and transfers.
- destination_id: required for deposits and transfers.
- idempotency_key: 8–100 characters, scoped to the authenticated actor.
- csrf: session token rendered in the form.

### Money movement authorization

- Administrators may deposit into, withdraw from, or transfer between any active accounts.
- Holders may withdraw only from accounts they own and transfer only between accounts they own. They cannot deposit.
- Auditors may not call a money movement successfully.
- A source must have enough available balance after its row lock is acquired. Zero or negative balances are refused.
- Holders can move funds only when KYC is approved; frozen accounts cannot be used as a source or destination.
- A replay with the same key and same payload returns the first result, adds an append-only replay audit event, and is visible in the account statement. The same key with a different payload is refused and audited.
- Transfers lock account rows in sorted account-ID order, update both balances, write both ledger postings, record the audit event, and save the idempotency result in one database transaction.
- Every ledger posting has a SHA-256 digest chained to the prior posting. A PostgreSQL transaction advisory lock serializes chain appends across workers.

## Ledger verification

`GET /api/ledger/verify` checks the stored hash sequence, recomputes every entry digest, compares each account's cached balance with the sum of its signed postings, and confirms that each transfer has one equal-and-opposite `transfer_out`/`transfer_in` pair. The response contains a validity flag, the verified head hash, and aggregate mismatch counts; it contains no usernames, account names, or balances. Verification scans the full ledger and is intended for this challenge-scale dataset.

## Audit filters and pagination

- `action` matches an exact event action, such as `withdrawal` or `account_create`.
- `outcome` accepts `succeeded`, `refused`, or `replayed`.
- `before_id` returns the next older page before that audit event ID. The page size is 100.

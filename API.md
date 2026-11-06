# HTTP routes

All application routes are same-origin HTML routes. POST routes use form encoding and require the session CSRF token. Unauthenticated requests to protected pages redirect to /login. Money requests are checked on the server, regardless of controls shown in the browser.

| Method and route | Access | Behavior and money effect |
| --- | --- | --- |
| GET /login | Public | Issues a short-lived login CSRF cookie and renders the sign-in form. |
| POST /login | Public + login CSRF | Verifies the Argon2 password hash and creates a random opaque server-side session. |
| POST /logout | Authenticated + session CSRF | Deletes the current server-side session. |
| GET /dashboard | Authenticated | Shows only owned accounts to holders; administrators and auditors can view all accounts. Shows recent successful ledger postings. |
| GET /accounts/{account_id} | Authenticated | Shows a per-account statement with successful debit/credit rows and refused attempts, including the actor and resulting balance when known. Holder ownership is checked on the server. |
| POST /accounts | Administrator + session CSRF | Creates a zero-balance INR account and records an audit event. |
| POST /transactions | Authenticated + session CSRF | Performs a deposit, withdrawal, or transfer after role and account checks. Requires a client idempotency key and amount with at most two decimals. |

## Transaction form fields

- action: deposit, withdrawal, or transfer.
- amount: positive INR amount with up to two decimal places; stored as integer paise.
- source_id: required for withdrawals and transfers.
- destination_id: required for deposits and transfers.
- idempotency_key: 8–100 characters, scoped to the authenticated actor.
- csrf: session token rendered in the form.

### Money movement authorization

- Administrators may deposit into, withdraw from, or transfer between any active accounts.
- Holders may withdraw only from accounts they own and transfer only between accounts they own. They cannot deposit.
- Auditors may not call a money movement successfully.
- A source must have enough available balance after its row lock is acquired. Zero or negative balances are refused.
- A replay with the same key and same payload returns the first result. The same key with a different payload is refused and audited.
- Transfers lock account rows in sorted account-ID order, update both balances, write both ledger postings, record the audit event, and save the idempotency result in one database transaction.

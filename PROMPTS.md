# AI prompt and review log

This record is being kept as work proceeds. Entries describe actual assistance and review in this conversation. The first local commit now contains the work described below; its GitHub URL is pending because the private remote has not been created yet. Do not backdate or invent links. Add later entries as they happen and replace the local SHA with the actual commit URL after publishing.

## 2026-11-06 — Stack and integrity architecture

- **Asked:** Choose a suitable stack and explain the money-integrity design for the LedgerLine brief.
- **Produced:** FastAPI with PostgreSQL; row locks, transactions, double-entry postings, actor-scoped idempotency keys, server-side roles.
- **Review finding:** Calling any stack “perfect” would overstate what technology alone guarantees. The database transaction and server-enforced rules are the controls that matter; the challenge still requires race tests and an interview walkthrough.
- **What I changed:** Chose a simple server-rendered interface and kept the concurrency logic in a small service module. PostgreSQL owns idempotency uniqueness and serializes account updates.
- **Security / audit note:** Authorization is checked by the service on every money request; refused attempts are retained in the audit stream.
- **Commit:** Local `6607e29e012214850c9d8df0ff1dcd6ee469bd1c` (GitHub URL pending).

## 2026-11-06 — Dashboard concept review

- **Asked:** Create a dashboard visual concept for the accounts, ledger, and money-movement workflow.
- **Produced:** A clean ledger-first screen with left navigation, account balances, recent postings, and a transfer action. Its sample image included made-up USD balances and transactions.
- **Review finding:** Those figures and records are not user data and must not be presented as working product data. The concept also does not define account authorization or actual movement behavior.
- **What I changed:** Kept the layout cues only; the implementation renders database-backed INR amounts and real records. The generated image is retained as a design reference, not used as the interface.
- **Security / audit note:** The Audit navigation and statement history lead to server-filtered views; the mockup itself grants no access.
- **Commit:** Local `6607e29e012214850c9d8df0ff1dcd6ee469bd1c` (GitHub URL pending).

## 2026-11-06 — Transaction service scaffold and review

- **Asked:** Build the money service with idempotency, locking, and refusal logging.
- **Produced:** A first service draft with actor-specific keys, deterministic row-lock ordering, transactional postings, and audit events.
- **Review finding:** The first draft returned immediately for some role-denied actions without writing a refusal event. Negative integer formatting also produced an invalid-looking balance string.
- **What I changed:** Role refusals now go through the audited result path; amount formatting uses the absolute paise value and a separate sign. Added balance-at-attempt details for refusals when the account can be found.
- **Security / audit note:** The holder ownership check is performed after the account rows are locked; hiding an option in a form is not treated as authorization.
- **Commit:** Local `6607e29e012214850c9d8df0ff1dcd6ee469bd1c` (GitHub URL pending).

## 2026-11-06 — Append-only database guard review

- **Asked:** Add database-level protection for posted ledger and audit records.
- **Produced:** PostgreSQL triggers that reject UPDATE and DELETE, plus a separate migration/owner connection and restricted runtime grants.
- **Review finding:** The initial setup draft grouped multiple SQL statements into one prepared execution and used an implicit engine reference. That was fragile and did not express the owner/runtime boundary clearly.
- **What I changed:** The setup now executes trigger function, trigger replacement, and trigger creation separately using the migration engine; the app role receives INSERT but no UPDATE/DELETE on ledger and audit tables.
- **Security / audit note:** A database owner can still alter triggers, so owner credentials remain a trust boundary. This is not a cryptographic hash chain.
- **Commit:** Local `6607e29e012214850c9d8df0ff1dcd6ee469bd1c` (GitHub URL pending).

## 2026-11-06 — Test design review

- **Asked:** Add challenge-focused integration tests for money conservation, replay handling, account authorization, concurrent withdrawals, auditor restrictions, and append-only behavior.
- **Produced:** PostgreSQL integration tests using independent sessions for the withdrawal race.
- **Review finding:** The initial fixture truncated tables before creating them and included a no-op conditional assertion.
- **What I changed:** The fixture creates schema first and truncates only the explicitly configured disposable test database; removed the no-op assertion. Ran the suite in an isolated PostgreSQL test container; all eight cases passed.
- **Security / audit note:** The concurrency test uses two threads, separate database sessions, and a barrier so both requests contend for the same starting balance.
- **Commit:** Local `6607e29e012214850c9d8df0ff1dcd6ee469bd1c` (GitHub URL pending).

# AI prompt and review log

This record is being kept as work proceeds. Entries describe actual assistance and review in this conversation. The first commit contains the work described below. Do not backdate or invent links. Add later entries as they happen and link each one to the real commit containing that work.

## 2026-11-06 — Stack and integrity architecture

- **Asked:** Choose a suitable stack and explain the money-integrity design for the LedgerLine brief.
- **Produced:** FastAPI with PostgreSQL; row locks, transactions, double-entry postings, actor-scoped idempotency keys, server-side roles.
- **Review finding:** Calling any stack “perfect” would overstate what technology alone guarantees. The database transaction and server-enforced rules are the controls that matter; the challenge still requires race tests and an interview walkthrough.
- **What I changed:** Chose a simple server-rendered interface and kept the concurrency logic in a small service module. PostgreSQL owns idempotency uniqueness and serializes account updates.
- **Security / audit note:** Authorization is checked by the service on every money request; refused attempts are retained in the audit stream.
- **Commit:** [6607e29](https://github.com/patrator12/ledgerline-snovasys/commit/6607e29e012214850c9d8df0ff1dcd6ee469bd1c).

## 2026-11-06 — Dashboard concept review

- **Asked:** Create a dashboard visual concept for the accounts, ledger, and money-movement workflow.
- **Produced:** A clean ledger-first screen with left navigation, account balances, recent postings, and a transfer action. Its sample image included made-up USD balances and transactions.
- **Review finding:** Those figures and records are not user data and must not be presented as working product data. The concept also does not define account authorization or actual movement behavior.
- **What I changed:** Kept the layout cues only; the implementation renders database-backed INR amounts and real records. The generated image is retained as a design reference, not used as the interface.
- **Security / audit note:** The Audit navigation and statement history lead to server-filtered views; the mockup itself grants no access.
- **Commit:** [6607e29](https://github.com/patrator12/ledgerline-snovasys/commit/6607e29e012214850c9d8df0ff1dcd6ee469bd1c).

## 2026-11-06 — Transaction service scaffold and review

- **Asked:** Build the money service with idempotency, locking, and refusal logging.
- **Produced:** A first service draft with actor-specific keys, deterministic row-lock ordering, transactional postings, and audit events.
- **Review finding:** The first draft returned immediately for some role-denied actions without writing a refusal event. Negative integer formatting also produced an invalid-looking balance string.
- **What I changed:** Role refusals now go through the audited result path; amount formatting uses the absolute paise value and a separate sign. Added balance-at-attempt details for refusals when the account can be found.
- **Security / audit note:** The holder ownership check is performed after the account rows are locked; hiding an option in a form is not treated as authorization.
- **Commit:** [6607e29](https://github.com/patrator12/ledgerline-snovasys/commit/6607e29e012214850c9d8df0ff1dcd6ee469bd1c).

## 2026-11-06 — Append-only database guard review

- **Asked:** Add database-level protection for posted ledger and audit records.
- **Produced:** PostgreSQL triggers that reject UPDATE and DELETE, plus a separate migration/owner connection and restricted runtime grants.
- **Review finding:** The initial setup draft grouped multiple SQL statements into one prepared execution and used an implicit engine reference. That was fragile and did not express the owner/runtime boundary clearly.
- **What I changed:** The setup now executes trigger function, trigger replacement, and trigger creation separately using the migration engine; the app role receives INSERT but no UPDATE/DELETE on ledger and audit tables.
- **Security / audit note:** A database owner can still alter triggers, so owner credentials remain a trust boundary. This is not a cryptographic hash chain.
- **Commit:** [6607e29](https://github.com/patrator12/ledgerline-snovasys/commit/6607e29e012214850c9d8df0ff1dcd6ee469bd1c).

## 2026-11-06 — Test design review

- **Asked:** Add challenge-focused integration tests for money conservation, replay handling, account authorization, concurrent withdrawals, auditor restrictions, and append-only behavior.
- **Produced:** PostgreSQL integration tests using independent sessions for the withdrawal race.
- **Review finding:** The initial fixture truncated tables before creating them and included a no-op conditional assertion.
- **What I changed:** The fixture creates schema first and truncates only the explicitly configured disposable test database; removed the no-op assertion. Ran the suite in an isolated PostgreSQL test container; all eight cases passed.
- **Security / audit note:** The concurrency test uses two threads, separate database sessions, and a barrier so both requests contend for the same starting balance.
- **Commit:** [6607e29](https://github.com/patrator12/ledgerline-snovasys/commit/6607e29e012214850c9d8df0ff1dcd6ee469bd1c).

## 2026-11-06 — Authorization and audit review

- **Asked:** Apply relevant review and security skills, verify the existing build against the challenge, then continue hardening authorization and audit behavior.
- **Produced:** Reviewed the FastAPI routes, transaction service, database grants/triggers, challenge docs, and the local login page. The review found that account creation could assign an auditor or inactive user, same-key concurrent payload conflicts could miss a refusal audit, and the dashboard's Audit link did not open an event log.
- **What I changed:** Account creation now allows only active holders as owners and audits rejected requests; unknown roles fail closed on account and statement access; idempotency collision refusals are audited; admins and auditors can open a global, role-protected audit log. Added regression coverage for these paths, a favicon, and improved login-page text contrast.
- **Security / audit note:** A Lighthouse smoke audit of the running login page found low-contrast text and no description; source fixes are in this commit. The running container could not be rebuilt during this review.
- **Verification:** `python3 -m compileall -q app tests` and `git diff --check` passed. The PostgreSQL suite could not run: Docker returned `permission denied` for its local API socket, and local Python lacks SQLAlchemy. Browser smoke loaded the login page and stylesheet; full auth journeys and new pages need a rebuilt app and seeded test credentials.
- **Commit:** [b0b1cce](https://github.com/patrator12/ledgerline-snovasys/commit/b0b1cce06835a0ed16e22786e3c5dee7fe93cdd0).

## 2026-11-06 — PostgreSQL regression verification

- **Asked:** Correct the three failures from the rebuilt integration suite and verify the current test image.
- **Produced:** Fixed the direct request fixture to include the FastAPI app and corrected the append-only DELETE statements to use valid PostgreSQL syntax.
- **Verification:** The user rebuilt the image and ran `docker compose --profile test run --build --rm tests`; all 15 tests passed in 0.55 seconds.
- **Commit:** [8bbe1cd](https://github.com/patrator12/ledgerline-snovasys/commit/8bbe1cd).

## 2026-11-06 — Input and container hardening review

- **Asked:** Continue reviewing the project for avoidable mistakes and harden concrete risks.
- **Review finding:** The amount route converted scientific-notation decimals to integers before checking the demo limit, allowing a short extreme exponent to request excessive conversion work. Compose also fixed `APP_ENV` to development, the image ran as root, and the build context did not exclude `.env`.
- **What I changed:** The route now accepts only short ASCII decimal amounts and checks the shared maximum before conversion; added a regression case. The image now runs as an unprivileged user, `.dockerignore` excludes local secrets, and `APP_ENV` can select production cookie and HSTS settings.
- **Verification:** `python3 -m compileall -q app tests` and `git diff --check` passed. The expanded PostgreSQL suite needs a rebuild and rerun; Docker is not accessible from this review environment.
- **Commit:** [583a77a](https://github.com/patrator12/ledgerline-snovasys/commit/583a77a8941612b26bb3e6728190c178f3c2f616).

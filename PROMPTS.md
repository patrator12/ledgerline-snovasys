# AI prompt and review log

This record is being kept as work proceeds. Entries describe actual assistance and review in this conversation. Commit links point to the code change being described; they do not imply that every later review note was already present in that commit. Do not backdate or invent links. Add later entries as they happen and link each one to the real commit containing the reviewed correction.

## 2026-11-12 — Split the workspace into focused pages

- **Asked:** Separate the dashboard details into the sections they belong to, then publish the update to the live application.
- **Produced:** Kept the overview concise and added separate Accounts, Transactions, Activity, and administrator-only Governance pages. Updated role-aware navigation, retained the existing Audit log and account statement pages, and documented the page layout in README.md.
- **Review finding:** The existing Docker engine is running, but this workspace cannot connect to its Docker socket, even after a targeted access request. The PostgreSQL integration suite therefore could not be rerun here.
- **What I changed:** Compiled the Python application, parsed all eight Jinja templates, and checked the patch for whitespace errors before committing the implementation.
- **Verification:** Python compilation, Jinja parsing, and `git diff --check` passed. Docker integration tests and a local browser walkthrough remain unverified.
- **Commit:** [2bbd802](https://github.com/patrator12/ledgerline-snovasys/commit/2bbd802).

## 2026-11-12 — Ledger chain, KYC governance, and STRIDE coverage

- **Asked:** Add the low-disruption improvements previously agreed: a dedicated STRIDE suite, a SHA-256 ledger chain and public verifier, and administrator-managed KYC and account freezing.
- **Produced:** Added hash-chain fields with one-time legacy backfill, serialized chain appends, `GET /api/ledger/verify`, KYC statuses (`PENDING`/`APPROVED`/`REJECTED`), freeze/unfreeze controls, audited administration routes, and six STRIDE regression tests. Updated the API, README, threat model, operations guide, and demo outline.
- **Review finding:** The first test run revealed a stale ORM identity-map issue that hid a tampered row from verification, a test fixture that did not load the shared STRIDE fixture, an outdated refusal-message expectation, and a login test request without the FastAPI router.
- **What I changed:** Refresh verifier query state, made STRIDE tests self-contained, updated the expected audit reason, and bound the login test request to the real FastAPI app. Kept schema migration fail-closed if an existing chain is partially populated or invalid.
- **Security / audit note:** KYC and freeze transitions require administrator role and CSRF, use row locks to serialize governance changes with movements, and emit audit events. The verifier checks the existing signed-posting model; it is not a general-ledger debit/credit implementation and is O(number of ledger entries).
- **Verification:** The user ran `docker compose --profile test run --build --rm tests`; all 34 tests passed in 1.40 seconds. Python compilation, Jinja parsing for all five templates, and `git diff --check` passed.
- **Commit:** [eb350de](https://github.com/patrator12/ledgerline-snovasys/commit/eb350de350f73e938e737175004ab7b1d6b815b4).

## 2026-11-12 — Requirements gap review and interface refresh

- **Asked:** Check the ten listed security and ledger requirements against the current implementation, and redesign the interface to feel like a finished finance operations application.
- **Produced:** Mapped the requirements to the authentication/session, authorization, transaction, ledger, audit, and test code. The comparison found substantial gaps: the app uses Argon2 and opaque server-side sessions (not bcrypt and signed JWT), signed per-account postings with cached balances (not a balanced debit/credit journal), no 24-hour idempotency expiry, no per-entry hash chain or public verification endpoint, no KYC lifecycle/account-freeze workflow, and no dedicated six-threat STRIDE suite. PostgreSQL row locks and transaction boundaries provide concurrency control, and holder ownership is checked server-side.
- **Review finding:** The existing app must not be presented as satisfying all ten requirements. The existing manual audit checkpoint is not a replacement for a hash chain; the session and posting designs also differ from the requested specification.
- **What I changed:** Refreshed the shared navigation, overview, movement form, and sign-in layout with responsive, keyboard-focusable styling while preserving existing routes, CSRF fields, role-based controls, and request behavior.
- **Security / audit note:** Kept the UI copy limited to existing server-checked authorization, idempotent retry handling, and recorded activity; did not imply JWT, chained-ledger, KYC, or verification controls.
- **Verification:** `git diff --check`, Python compilation, and parsing of all five Jinja templates passed. The local runtime lacks SQLAlchemy and the Docker socket is inaccessible here, so I could not run the app or PostgreSQL integration suite after the interface changes.
- **Commit:** [047f472](https://github.com/patrator12/ledgerline-snovasys/commit/047f47283c5a8cee1a597a5ee11d8bd5ab9c6a5f).

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
- **Produced:** The first rebuilt run exposed a direct-request fixture missing the FastAPI app and append-only DELETE statements using invalid PostgreSQL syntax.
- **Review finding:** Those were test defects, so the suite could not reliably verify the behavior it claimed to cover.
- **What I changed:** Added the app to the request scope and used PostgreSQL-valid DELETE statements; reran the suite in the test container.
- **Verification:** The user rebuilt the image and ran `docker compose --profile test run --build --rm tests`; all 15 tests passed in 0.55 seconds.
- **Commit:** [8bbe1cd](https://github.com/patrator12/ledgerline-snovasys/commit/8bbe1cd).

## 2026-11-06 — Input and container hardening review

- **Asked:** Continue reviewing the project for avoidable mistakes and harden concrete risks.
- **Review finding:** The amount route converted scientific-notation decimals to integers before checking the demo limit, allowing a short extreme exponent to request excessive conversion work. Compose also fixed `APP_ENV` to development, the image ran as root, and the build context did not exclude `.env`.
- **What I changed:** The route now accepts only short ASCII decimal amounts and checks the shared maximum before conversion; added a regression case. The image now runs as an unprivileged user, `.dockerignore` excludes local secrets, and `APP_ENV` can select production cookie and HSTS settings.
- **Verification:** `python3 -m compileall -q app tests` and `git diff --check` passed. The user rebuilt the image and ran `docker compose --profile test run --build --rm tests`; all 16 tests passed.
- **Commit:** [583a77a](https://github.com/patrator12/ledgerline-snovasys/commit/583a77a8941612b26bb3e6728190c178f3c2f616).

## 2026-11-06 — Render startup failure review

- **Asked:** Deploy the app using the Render blueprint and Neon database configuration.
- **Produced:** The first Render start attempted to run the database setup, demo seeding, and Uvicorn command as a single malformed command; Render logged exit code 127 and reported the whole string as not found.
- **Review finding:** The command override in `render.yaml` was quoted incorrectly for the Docker runtime, so the service never reached its health check.
- **What I changed:** Removed the Render command override and put the startup sequence in the Docker image command, using Render's supplied `PORT`. The next Render deploy succeeded and `/login` returned HTTP 200.
- **Commit:** [c029d70](https://github.com/patrator12/ledgerline-snovasys/commit/c029d700d4ccb2699e4225faa26a6f69caead080).

## 2026-11-11 — Authentication, audit, and operations improvements

- **Asked:** Implement the five proposed improvements: broader security tests, shared login throttling, audit filtering and pagination, backup/recovery guidance, and an externally retained audit checkpoint.
- **Produced:** Added a PostgreSQL-backed per-username/client-address login throttle, audit action/outcome filters with older-page navigation, regression tests, an operations runbook, and a SHA-256 checkpoint command.
- **Review finding:** A per-pair throttle does not stop distributed guessing; database append-only triggers do not protect against an owner-level rewrite; and the new paths need PostgreSQL integration verification before deployment.
- **What I changed:** Serialized login attempts for each throttle key, bounded old throttle-row cleanup, documented distributed-attack and storage risks, and made the audit checkpoint verify a stored event prefix so later normal events do not invalidate it.
- **Verification:** Python compilation and `git diff --check` passed. The first attempt from Codex could not access Docker's socket; the user then rebuilt and ran `docker compose --profile test run --build --rm tests` on 2026-11-11, and all 24 tests passed in 1.12 seconds.
- **Commit:** [623be73](https://github.com/patrator12/ledgerline-snovasys/commit/623be739f11d61c98edb8425ba975d9e7ae616b4).

## 2026-11-13 — Ledger, session, and idempotency hardening

- **Asked:** Complete the remaining improvements for balanced ledger postings, bcrypt password hashes, signed sessions, and 24-hour idempotency retention, then finish the release work.
- **Produced:** Added explicit debit/credit postings including external clearing entries, migration support for existing ledger rows, bcrypt-first password hashing with Argon2 upgrade on login, signed HS256 session cookies backed by revocable server records, and 24-hour idempotency expiry. Updated templates, tests, and README.
- **Review finding:** Existing hash-chain columns are non-null, so the migration must temporarily relax those constraints while it inserts clearing postings and rebuilds the chain. This was corrected before release.
- **Verification:** `python3 -m compileall -q app tests` and `git diff --check` passed. PostgreSQL integration tests could not start because Docker denied access to both configured API sockets, and no local PostgreSQL server is available. The changes have not been pushed or deployed pending database-backed test verification.
- **Commit:** [e66fe06](https://github.com/patrator12/ledgerline-snovasys/commit/e66fe0606a2b8caf6787a64e46095a8b3ce8b134).

## 2026-11-13 — Docker dependency-download timeout

- **Asked:** Continue the pending verification after sharing the Docker test output.
- **Finding:** The image build reached `pip install` but timed out while downloading SQLAlchemy from PyPI; the test suite had not started.
- **What I changed:** Increased pip's network timeout to 120 seconds and retries to five.
- **Verification:** `git diff --check` passed. Docker remains inaccessible from this Codex session, so the rebuilt PostgreSQL test suite still needs to be run from the user's terminal.
- **Commit:** [9beb536](https://github.com/patrator12/ledgerline-snovasys/commit/9beb5366a2fd666080501cc401038ef38fb42195).

## 2026-11-13 — Docker pip cache retry

- **Asked:** Continue after the rebuilt test image failed again.
- **Finding:** The longer timeout got past the earlier SQLAlchemy download stall, but PyPI disconnected during dependency resolution and pip reported that it could not resolve Jinja2's `MarkupSafe` dependency.
- **What I changed:** Persist pip's cache across BuildKit attempts and increased network retries to ten.
- **Verification:** `git diff --check` passed. The test command cannot run from this session because Docker socket access is denied; the user needs to rerun the build and tests from their terminal.
- **Commit:** [8eaded9](https://github.com/patrator12/ledgerline-snovasys/commit/8eaded9c62b04c3f2ef76962ab72fd7764910da0).

## 2026-11-13 — Session-cookie integration test correction

- **Asked:** Continue after the rebuilt PostgreSQL suite reported one failure.
- **Finding:** The app sends separate `Set-Cookie` headers to delete the login CSRF cookie and set the session cookie. The test selected the first header, so it passed an empty token to session validation.
- **What I changed:** Updated the test to select the cookie named by `SESSION_COOKIE` from all response `Set-Cookie` headers.
- **Verification:** The submitted run built the image and reported 34 passed, 1 failed in 4.10 seconds. Python compilation and `git diff --check` pass after the test fix; the suite needs a rerun.
- **Commit:** [b1e7b86](https://github.com/patrator12/ledgerline-snovasys/commit/b1e7b86a9f531eb194a83c819d981118c93082dd).
- **Follow-up verification:** The user rebuilt and reran `docker compose --profile test run --build --rm tests` after the cookie-header test fix; all 35 tests passed in 4.06 seconds.
- **Release verification:** Pushed the changes to `main` at [cc6e94b](https://github.com/patrator12/ledgerline-snovasys/commit/cc6e94b). The deployed `/login` returned HTTP 200, and `GET /api/ledger/verify` returned `valid: true` with 8 entries, 3 accounts checked, and no parity mismatches.

## 2026-11-13 — Documentation consistency pass

- **Asked:** Check whether the GitHub README and remaining project files reflect the latest updates.
- **Finding:** API and demo docs still described Argon2-only opaque sessions and signed-delta ledger entries. README's current-limits section contradicted the implemented debit/credit postings, the deployment link was missing, and the threat and operations docs lacked current session and migration guidance.
- **What I changed:** Updated README, API, threat model, demo outline, and operations runbook to describe the shipped bcrypt/JWT flow, balanced postings, 24-hour idempotency, deployment URL, current test result, and backup/verification steps before ledger migration.
- **Verification:** `git diff --check` passed; compared the docs against the current app behavior and latest 35-test Docker run.
- **Commit:** [2975c4b](https://github.com/patrator12/ledgerline-snovasys/commit/2975c4b8a51869d97f4eac427209b5882b04b20e).

## 2026-11-13 — Authentication and transaction UX refinements

- **Asked:** Implement the suggested login, balance-label, transaction-flow, signing-key, password-length, and legacy-ledger migration improvements.
- **What I changed:** Added a PostgreSQL regression test for repeated conversion of legacy signed rows; made balances neutral where frozen accounts are included; disabled frozen accounts in transaction selectors and clarified that submit posts immediately; added an accessible login password toggle; retained long legacy Argon2 login while enforcing bcrypt's 72-byte limit for new hashes and seed passwords; validated signing-key length and added its optional Render/Compose configuration.
- **Security note:** No `SESSION_SIGNING_KEY` value was added to Render. The user previously said they would enter deployment secrets themselves; changing the key will invalidate active sessions.
- **Verification:** `python3 -m compileall -q app tests` and `git diff --check` passed. The PostgreSQL suite could not run from this session because the Docker socket is denied; rerun `docker compose --profile test run --build --rm tests` from the project directory before pushing or deploying.
- **Commit:** [5fb1e68](https://github.com/patrator12/ledgerline-snovasys/commit/5fb1e6883695ba5371a71ca4401b960b6ca9bc2e).

# Five-minute demo outline

Record the current working build only. Use the local seeded accounts or replace them with the deployed demo accounts. Do not show a feature that is not present in the build.

| Time | Show | Explain |
| --- | --- | --- |
| 0:00–0:35 | Sign in as the administrator, holder, and auditor. | The roles are loaded from the database. The auditor has no movement controls; server checks still apply if someone submits a request manually. Login throttling is shared through PostgreSQL. |
| 0:35–1:15 | Overview and account balances. | Balances are integer paise and formatted as INR. The holder sees only owned accounts; administrator and auditor can read all accounts. |
| 1:15–2:00 | Record a small transfer between the holder's two accounts. | Both account rows are locked in sorted order. The source debit, destination credit, ledger rows, audit event, and idempotency result are committed together. |
| 2:00–2:35 | Re-submit the same request with the same idempotency key, or show the retry integration test. | The same actor/key and payload returns the stored result without another posting. A key reused with a changed payload is refused. |
| 2:35–3:15 | Attempt a withdrawal from an empty account and open its statement. | The balance does not change. The refused attempt records the actor, reason, requested amount, and balance at the attempt. |
| 3:15–4:00 | As administrator, review holder KYC status and freeze then unfreeze an account. | Governance changes are server-authorized, CSRF-protected, written to the audit log, and enforced on money movement. |
| 4:00–4:35 | Open `/api/ledger/verify`, then show the automated test output. | The public verifier recomputes the ledger chain, account balance totals, and transfer posting parity. The PostgreSQL suite includes a dedicated six-category STRIDE group. |
| 4:35–5:00 | Filter the audit history, then walk through `THREATS.md`. | Explain database and service controls, the manual out-of-band audit checkpoint, and accepted limits: signed delta entries rather than a general-ledger debit/credit model, no MFA, distributed login throttling, reversals, multi-currency conversion, automatic backups, or continuous external audit monitoring. |

## Recording checklist

- Refresh the page before recording so the on-screen balance matches the seed records in the deployed database.
- Use a small amount and the demo accounts only.
- Show the same idempotency key on the retry, or clearly switch to the matching automated test.
- Keep the final limits section visible and honest.

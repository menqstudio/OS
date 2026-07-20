# AUDIT — BroPS

Security & correctness audit of **`menqstudio/BroPS`** @ `e298e201`.

- **Mode:** READ-ONLY. Nothing was pushed or committed to BroPS. All tickets are *proposed* patches.
- **Method:** 6 parallel Fable 5 auditors (one per attack surface) → Opus verification of every High/Medium against the source.
- **Date:** 2026-07-19

## How to use with agents

Each file in [`tickets/`](tickets/) is **self-contained**: an agent can be handed one ticket and fix it independently. A ticket carries: location (`file:line`), the problem, a concrete fix (with code), and acceptance criteria to verify against.

Hand a coding agent a single ticket:
> "Apply the fix described in `AUDIT/tickets/H-1-migration-atomicity.md` to the BroPS repo. Verify against its acceptance criteria. Do not touch anything outside the listed files."

Or fan several out in parallel — tickets are written to be independent (mind the shared-file note in a few Medium tickets: M-2/M-3 both touch `repo.rs`, M-1 shares `commands.rs` with M-4).

## Index

| # | Ticket | Severity | Area |
|---|---|---|---|
| H-1 | [Migration runner atomicity](tickets/H-1-migration-atomicity.md) | 🔴 High | DB durability |
| M-1 | [Approval gate self-service](tickets/M-1-approval-self-service.md) | 🟠 Medium | Approval gate |
| M-2 | [Approval matching by bare entity_id](tickets/M-2-approval-matching.md) | 🟠 Medium | Approval gate |
| M-3 | [set_step_result skips the gate](tickets/M-3-set-step-result-gate.md) | 🟠 Medium | Approval gate |
| M-4 | [Run-step prompt injection](tickets/M-4-run-step-prompt-injection.md) | 🟠 Medium | AI / data integrity |
| M-5 | [Missing write transactions](tickets/M-5-write-transactions.md) | 🟠 Medium | DB integrity |
| M-6 | [advance() mislabels failed runs](tickets/M-6-advance-status.md) | 🟠 Medium | Correctness |
| M-7 | [CI token permissions](tickets/M-7-ci-permissions.md) | 🟠 Medium | Supply chain |
| M-8 | [App-command capability + files root](tickets/M-8-app-command-capability.md) | 🟠 Medium | Tauri surface |
| L-1 | [Availability / DoS](tickets/L-1-availability-dos.md) | 🟡 Low ×5 | Availability |
| L-2 | [Info disclosure / hardening](tickets/L-2-info-disclosure-hardening.md) | 🟡 Low ×5 | Hardening |
| L-3 | [Data integrity](tickets/L-3-data-integrity.md) | 🟡 Low ×6 | Correctness |
| L-4 | [Identity / audit / hygiene](tickets/L-4-identity-audit-hygiene.md) | 🟡 Low ×7 | Hygiene |

Full narrative report: [BroPS_Audit_Report.md](BroPS_Audit_Report.md)

## Suggested order
1. **H-1** (cheap, prevents unrecoverable DB bricking) → ship first.
2. **M-5 / M-6** (write transactions + run status).
3. **M-2 / M-1 / M-3** (approval-gate hardening, as one change).
4. **M-4** (structured run-step prompt).
5. **M-7 / M-8** (CI + capability).
6. **L-1..L-4** (batch by file).

## Verified CLEAN — do not re-investigate
SQL injection (all parameterized), AI→RCE (sandbox + `--tools ""`), XSS (markdown escaped), secrets (none in tree/history), dependencies (current, no known CVE), Tauri config (CSP set, no updater misconfig, actions SHA-pinned).

**Correction:** an auditor claim that `set_run_step_status` / `advance_run` bypass the gate was verified **false** (both call gated functions: `repo.rs:915`, `repo.rs:963`) and dropped.

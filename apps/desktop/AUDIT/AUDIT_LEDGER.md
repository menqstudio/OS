# BroPS Audit Ledger · desktop + engine

> **Why this file exists (audit D-06/D-07):** the security tickets under `apps/desktop/AUDIT/tickets/`
> and `engine/AUDIT/tickets/` carried **no status/resolution field**, so a fixed finding and a forgotten
> one looked identical, and the desktop tickets were referenced from **nowhere** outside their own folder
> (orphaned). This ledger is the single index of record: it links both ticket sets, points at the current
> authoritative assessment, and records the status the Builder can evidence. It does **not** invent a
> status it cannot back — anything not individually re-verified is marked so, with the independent audit
> as the live source of truth for current-code behaviour.

**Authoritative current assessment:** [`2026-08-06-independent-audit.md`](./2026-08-06-independent-audit.md)
— the Owner's 25-agent zero-trust audit of `origin/main`, re-verified by the Builder (all code facts
confirmed). For any ticket below, that report's F-/D- findings are the current-code truth; a ticket's
"fixed" mark here means the Builder has code evidence, not merely that the ticket was filed.

## Desktop tickets — `apps/desktop/AUDIT/tickets/`

| Ticket | Status | Evidence / note |
|---|---|---|
| `H-1-migration-atomicity` | ✅ fixed | `core/src/db.rs` runs migrations under `BEGIN IMMEDIATE` (atomic); confirmed by the independent audit's D-06 check. |
| `M-1-approval-self-service` | ⚠️ by-design | Native OS confirmation is the real anti-self-approval barrier; the durable-principal self-approval guard is vacuous BY DESIGN (see independent audit **F-30**). Not a live hole. |
| `M-2-approval-matching` | ✅ fixed | `approvals::consume_for` — one grant unlocks exactly one completion. |
| `M-3-set-step-result-gate` | ✅ fixed | `set_step_result` removed (latent T-011 bypass); completion goes through the attempt-guarded path. |
| `M-4-run-step-prompt-injection` | ◑ mitigated | `sanitize_author` (control+colon strip, 64-cap) + bounded run fields; the colon turn-forgery PoC is defeated. Residual: a stricter agent-name allowlist (independent audit **F-40**) — tracked, deferred. |
| `M-5-write-transactions` | ✅ fixed | Renderer-driven writes are atomic (single-tx gate+write). |
| `M-6-advance-status` | ✅ fixed (2026-08-06) | `runs::advance` bound its completion to the single approval-checked step instead of every `status='active'` row (independent audit **F-12**; commit `5548ab4`). |
| `M-7-ci-permissions` | ◑ partial | CI jobs run least-privilege (`contents: read`); some supply-chain gaps remain open in the independent audit (**F-15/F-20/F-45/F-46** — F-46 fixed, F-15/F-45 fixed, F-20 owner-gated). |
| `M-8-app-command-capability` | ✅ fixed | T-010 capability wall + `check_capabilities.py` now captures every module prefix + `INTENTIONALLY_UNGATED`; regex-blindness (independent audit **F-03/F-05/F-43**) closed on this branch. |
| `L-1-availability-dos` | ◑ partial | Several fail-closed/bounded hardenings shipped; proof-kit DoS surfaces remain (independent audit **F-11/F-31/F-32/F-36**, keystone-class). |
| `L-2-info-disclosure-hardening` | ◑ not re-verified | See independent audit for current-code state. |
| `L-3-data-integrity` | ◑ not re-verified | See independent audit for current-code state. |
| `L-4-identity-audit-hygiene` | ◑ not re-verified | See independent audit for current-code state. |

## Engine tickets — `engine/AUDIT/tickets/` (registered in `engine/config/documentation-manifest.json`)

| Ticket | Status | Note |
|---|---|---|
| `C-1-find-readonly-bypass` | ◑ see F-04 | `git -C`/`--git-dir`/`--work-tree` read-containment fixed 2026-08-06 (independent audit **F-04**, commit `5548ab4`); review the ticket's other cases against current `bro_security.py`. |
| `H-1-unsigned-workspace-binding` | ◑ not re-verified | — |
| `H-2-windows-emit-crash` | ✅ fixed | Windows emit hardened (fail-closed). |
| `H-3-windows-fail-open-wiring` | ✅ fixed | `bro_live_validate.py` proves 17/17 laws LIVE_PROVEN incl. the Windows leg (now run in root CI — independent audit **F-22**). |
| `H-4-forgeable-audit-trail` | ⚠️ OPEN (keystone-class) | Anti-rollback/audit-head remediation is partly unwired (independent audit **F-06/F-13/F-14/F-41/F-42**). |
| `H-5-registry-anti-rollback` | ⚠️ OPEN | Registry anti-rollback floor; see independent audit. |
| `H-6-protected-set-gaps` | ⚠️ OPEN (O-1) | **bytecode-shadow (O-1, HIGH):** `assert_no_bytecode_shadow` has no caller and the wall is not run with `-B` (independent audit **D-09**). Fix is trust-critical + interacts with the CI `compileall` step — deferred to focused keystone-class work. |
| `LOW-findings` / `MEDIUM-findings` | ◑ mixed | Bundle files; see the independent audit + `BroCore_Audit_Report.md`. |

## Legend
✅ fixed (Builder has code evidence) · ◑ partial / not individually re-verified this cycle · ⚠️ open (tracked) · by-design (intentional, not a hole)

> **Maintenance:** when a ticket is resolved, mark it here in the same commit and cite the fixing commit.
> New security tickets MUST be added to this ledger (desktop) or the manifest (engine) so nothing is orphaned.

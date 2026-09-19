# TASKS — the coordination board · կոորդինացիայի տախտակ

> **Open rows only.** Closed rows:
> [`docs/archive/TASKS_ARCHIVE_2026-08.md`](docs/archive/TASKS_ARCHIVE_2026-08.md).

<!-- BANNER -->
> **⏭️ CURRENT ACTIVE: PR #243 · branch `t076/flake-and-retrue`** (base `main`, tip `a57fd86`, task T-076).
>
> the flake that reddened main, and the page re-trued after T-075
>
> **Standing verdict: RED** -- the NINTH round, `apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

**Claim a row before you touch anything — never two on one.**

Status: `Todo` · `In-Progress` · `Review` · `Done` · `Blocked`. ◑ the Builder's own claim;
✅ independently confirmed. Never promote your own work.

| ID | Task | Claimed by | Status | Branch / PR |
|----|------|-----------|--------|-------------|
| **T-076** | **A required gate failed 1 run in 40** — `pages.browser.spec.tsx` sampled the DOM once after `mount`; polling instead, 18-red proof ◑ | Bro | Review | `#243` |
| **T-075** | **A test that does not exist cannot fail** — NM-CRASH-01 bound; its first copy landed past `unittest.main()` ◑ | Bro | Review | `#242` |
| **T-074** | **No gate read the front page** — in no manifest meant in no check; `ALSO_CHECKED`, 145 → 204 paths, and a C0 byte found ◑ | Bro | Review | `#241` |
| **T-072** | **The gates had never run on Windows** — every `tools/` self-test step ran on ubuntu, five printed `a\b` and two `check_audit_actor` tests were red here ◑ | Bro | Review | `#232` |
| **T-020** | **The anti-rollback floor's writer is the party the floor constrains** — a distinct **Floor Writer**; completion REQUESTS an advance. **C3 and a 2nd Architect pass NOT done** | Bro | Review | `#219` |
| **T-058** | **The transport, then §3.3's BUILD half** — the tick dispatches armed bundles, egress decided against the grant's table. **Nothing resolves an `auth_ref` yet** ◑ | Bro | Todo | `#207` |
| **T-061** | **Checks correct by reading, defended by no test** — all six of `docs/VERIFICATION_QUEUE_1.md` CLOSED, mutation-proven | Bro | Review | `#219` |
| **T-062** | **The negative matrix's silent state** — **133 / 54 / 55** of 242 bound. §2 done but 3 shell rows (Linux+root); §3 has 40 left ◑ | Bro | In-Progress | `#233` |
| **T-056** | **Two fail-closed checks prevent nothing** — `control-invocation.json` holds each control to what its failure stops; `bro_deploy_preflight.py` has no non-test caller | Bro | Todo | `#208` |
| **T-057** | **56 fabricated audit rows say so, and the mark reaches the reader** — `repo::seed` writes `payload_json`, both read mappers carry it ◑ | Bro | Review | `#210` |
| **T-004** | **Engine deferred items O-1..O-5** (Phase 10) — all OPEN, blocked by deployment wiring and a second principal; O-1 the only HIGH | — | Blocked | — |
| **T-005** | **Option-2 feasibility (audited): engine as a submodule** + a worktree-check fix. Own PR, Owner approval | — | Todo | — |
| **T-021** | **The approval-REQUEST path across the wall** — the read half shipped, the request half exists nowhere; no new trust-boundary input while RED | — | Blocked | — |
| **T-022** | **The governed automation dispatch** — firing one writes a desktop row that never crosses the wall; its `engine_receipt` is unobserved. After `T-021` | — | Blocked | — |
| **T-023** · **T-046** | **Two CI jobs called fixed on one green run** — windows trust-provisioning (inherited ACL) and the Windows engine job; one run proves nothing | — | Todo | `#182` |
| **T-030** | **Route 1 past the no-lease / no-secret whitelist** — `A-09`: routes 2/3 closed, Route 1 open **by design**; register at 19 leaves, not 8 | — | Todo | — |
| **T-034** | **Two palettes, one contrast gate** — `I-04`: `round(ratio, 2)` let 4.4995 print `4.50`; ◑ fixed on the raw ratio | — | Todo | — |
| **12 merged rows** | **Shipped, and none independently confirmed** — `T-073`·`#239`, `T-071`·`#231`, `T-070`·`#230`, `T-069`·`#227`, `T-068`·`#223`, `T-067`·`#222`, `T-066`·`#221`, `T-065`·`#220`, `T-064`·`#217`, `T-063`·`#214`, `T-059`·`#219`, `T-060`·`#219`. Verbatim in [`docs/archive/TASKS_ARCHIVE_2026-09.md`](docs/archive/TASKS_ARCHIVE_2026-09.md) ◑ | Bro | Review | merged |

Outside review starts at [`docs/EVIDENCE_INDEX.md`](docs/EVIDENCE_INDEX.md).

## What is not on this board

Waiting on the Owner, not rows: two one-line edits (`gitleaks.toml`, requiring the Windows tools
job) and `T-063`'s tag arm — [`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md).

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document.

`CURRENT_ACTIVE_TASK: floor-writer` · `CURRENT_ACTIVE_WAVE: production-half` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

# TASKS — the coordination board · կոորդինացիայի տախտակ

> **Open rows only.** Closed rows:
> [`docs/archive/TASKS_ARCHIVE_2026-08.md`](docs/archive/TASKS_ARCHIVE_2026-08.md).

<!-- BANNER -->
> **⏭️ CURRENT ACTIVE: PR #252 · branch `t085/artwork-geometry-gate`** (base `main`, tip `bb8a00a`, task T-085).
>
> no gate read the front page's pictures
>
> **Standing verdict: RED** -- the NINTH round, `apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

**Claim a row before you touch anything — never two on one.**

Status: `Todo` · `In-Progress` · `Review` · `Done` · `Blocked`. ◑ the Builder's own claim;
✅ independently confirmed. Never promote your own work.

| ID | Task | Claimed by | Status | Branch / PR |
|----|------|-----------|--------|-------------|
| **T-085** | **No gate read the front page's pictures** - `check_artwork_geometry.py`, eleven rules; it found a dark panel a step lighter than every other panel on its first run ◑ | Bro | Review | `#252` |
| **T-084** | **The page re-trued for four landings at once** — matrix 144→150, engine 2148→2152, the to-scale bar redrawn, and T-072 carried off the board ◑ | Bro | Review | `#251` |
| **T-083** | **A mutation that did not run looks exactly like a survivor** — five times in one day; the harness now refuses a verdict it cannot prove it applied ◑ | Bro | Review | `#250` |
| **T-082** | **The triage sent a test where it could not import what it tests** — only 4 of 12 runtime modules import without `cryptography` ◑ | Bro | Review | `#249` |
| **T-081** | **A key with everything right except audience, and a refusal that must carry no bytes** — NM-SCOPE-04, NM-TERM-04 ◑ | Bro | Review | `#248` |
| **T-080** | **Three bare sections got artwork, nothing was removed** — and a designer "Verified" a dark sheet it never shipped; nine mechanical checks on every sheet since ◑ | Bro | Review | `#247` |
| **T-079** | **Four predicates, four independent kills** — a spent nonce, a divergent challenge context, an accessor nobody may add, and a trust class nobody may infer ◑ | Bro | Review | `#246` |
| **T-078** | **Every TCB violation test poked one file** — the floor is now asserted over the WHOLE pinned set and all seven principals; plus a trigger a neighbour claimed and never checked ◑ | Bro | Review | `#245` |
| **T-077** | **The crash family is closed in §3** — NM-CRASH-12/13/14; the floor turns out to be defended twice, so one mutant each survives and both together kill ◑ | Bro | Review | `#244` |
| **T-076** | **A required gate failed 1 run in 40** — `pages.browser.spec.tsx` sampled the DOM once after `mount`; polling instead, 18-red proof ◑ | Bro | Review | `#243` |
| **T-020** | **The anti-rollback floor's writer is the party the floor constrains** — a distinct **Floor Writer**; completion REQUESTS an advance. **C3 and a 2nd Architect pass NOT done** | Bro | Review | `#219` |
| **T-058** | **The transport, then §3.3's BUILD half** — the tick dispatches armed bundles, egress decided against the grant's table. **Nothing resolves an `auth_ref` yet** ◑ | Bro | Todo | `#207` |
| **T-061** | **Checks correct by reading, defended by no test** — all six of `docs/VERIFICATION_QUEUE_1.md` CLOSED, mutation-proven | Bro | Review | `#219` |
| **T-062** | **The negative matrix's silent state** — **150 / 54 / 38** of 242 bound. §2 done but 3 shell rows (Linux+root); §3 has 23 left ◑ | Bro | In-Progress | `#233` |
| **T-056** | **Two fail-closed checks prevent nothing** — `control-invocation.json` holds each control to what its failure stops; `bro_deploy_preflight.py` has no non-test caller | Bro | Todo | `#208` |
| **T-057** | **56 fabricated audit rows say so, and the mark reaches the reader** — `repo::seed` writes `payload_json`, both read mappers carry it ◑ | Bro | Review | `#210` |
| **T-004** | **Engine deferred items O-1..O-5** (Phase 10) — all OPEN, blocked by deployment wiring and a second principal; O-1 the only HIGH | — | Blocked | — |
| **T-005** | **Option-2 feasibility (audited): engine as a submodule** + a worktree-check fix. Own PR, Owner approval | — | Todo | — |
| **T-021** | **The approval-REQUEST path across the wall** — the read half shipped, the request half exists nowhere; no new trust-boundary input while RED | — | Blocked | — |
| **T-022** | **The governed automation dispatch** — firing one writes a desktop row that never crosses the wall; its `engine_receipt` is unobserved. After `T-021` | — | Blocked | — |
| **T-023** · **T-046** | **Two CI jobs called fixed on one green run** — windows trust-provisioning (inherited ACL) and the Windows engine job; one run proves nothing | — | Todo | `#182` |
| **T-030** | **Route 1 past the no-lease / no-secret whitelist** — `A-09`: routes 2/3 closed, Route 1 open **by design**; register at 19 leaves, not 8 | — | Todo | — |
| **T-034** | **Two palettes, one contrast gate** — `I-04`: `round(ratio, 2)` let 4.4995 print `4.50`; ◑ fixed on the raw ratio | — | Todo | — |
| **15 merged rows** | **Shipped, and none independently confirmed** — `T-075`·`#242`, `T-074`·`#241`, `T-073`·`#239`, `T-072`·`#232`, `T-071`·`#231`, `T-070`·`#230`, `T-069`·`#227`, `T-068`·`#223`, `T-067`·`#222`, `T-066`·`#221`, `T-065`·`#220`, `T-064`·`#217`, `T-063`·`#214`, `T-059`·`#219`, `T-060`·`#219`. Verbatim in [`docs/archive/TASKS_ARCHIVE_2026-09.md`](docs/archive/TASKS_ARCHIVE_2026-09.md) ◑ | Bro | Review | merged |

Outside review starts at [`docs/EVIDENCE_INDEX.md`](docs/EVIDENCE_INDEX.md).

## What is not on this board

Waiting on the Owner, not rows: two one-line edits (`gitleaks.toml`, requiring the Windows tools
job) and `T-063`'s tag arm — [`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md).

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document.

`CURRENT_ACTIVE_TASK: floor-writer` · `CURRENT_ACTIVE_WAVE: production-half` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

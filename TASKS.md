# TASKS — the coordination board · կոորդինացիայի տախտակ

> **Open rows only.** Closed rows:
> [`docs/archive/TASKS_ARCHIVE_2026-08.md`](docs/archive/TASKS_ARCHIVE_2026-08.md).

<!-- BANNER -->
> **✅ SETTLED — `main` is at `3c03955`.** The only thing open is PR #323 on `t155/settled-at-3c03955`, the pull request that records it. Blocked on whom: `docs/OWNER_ACTION_REQUIRED.md`.
>
> **Next:** the uncapped second read of T-145 (verifiers running), then design §10 and the executor design.
>
> **Standing verdict: RED** -- the TENTH round, `apps/desktop/AUDIT/2026-09-19-tenth-audit-75fca65.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

**Claim a row before you touch anything — never two on one.**

Status: `Todo` · `In-Progress` · `Review` · `Done` · `Blocked`. ◑ the Builder's own claim;
✅ independently confirmed. Never promote your own work.

| ID | Task | Claimed by | Status | Branch / PR |
|----|------|-----------|--------|-------------|
| **T-154** | **A merge that touches engine security code needs a cited audit or a waiver the Owner wrote** — `check_merge_ready.py` reads `config/audit-required-paths.json` (the engine's own protected roots, tests excluded); 73 mutants, 73 named deaths ◑ | Bro | Review | `#322` |
| **T-153** | **The tightening list the Owner approved** — native-confirmed delete, a dead command denied, `ci/` `install/` `contracts/` protected, the HMAC verifier gone, the test catalog enforced, L5/L13 true. Owner waiver for the missing Architect audit: roadmap §G.2 ◑ | Bro | Review | `#321` |
| **T-150** | **A merge and a push are refused before they turn `main` or CI red** — `check_merge_ready.py`, `check_push_ready.py`, and a pre-tool shell arm in the hook; 85 mutants, 85 named deaths ◑ | Bro | Review | `#319` |
| **T-145** | **The whole repository, read file by file** — 932 findings in [`docs/WHOLE_REPO_READ_2026-10-01.md`](docs/WHOLE_REPO_READ_2026-10-01.md): waves 1 and 2 merged (405 + 275 fixed), 89 open (§9 and wave 1), 36 wait on the Owner (§8); second read (uncapped) running ◑ | Bro | In-Progress | `#317` |
| **T-131** | **Install-minted root** — A, C, D and B's accounts+entry merged; deployment open | Bro | In-Progress | — |
| **T-021d** | **PHASE 2 CLOSED, 11/11** - the page asks the engine in a section named apart from this app's own authority, and the roadmap gained the enumeration a moved checkbox needs ◑ | Bro | Review | `#257` |
| **T-021c** | **The desktop asks across the wall and cannot be told it decided** - the command, the parser, and the contract test phase 2 asked for; a reply claiming a decision is blocked ◑ | Bro | Review | `#256` |
| **T-021b** | **The engine records an ask and cannot decide it** - the first WRITE the sidecar serves, provisioned on its own; O-1..O-5 discharged, six mutants, six named deaths ◑ | Bro | Review | `#255` |
| **T-021a** | **The approval-request contract, audited before it lands** - the schema the Owner's five invariants fixed in advance; four mutants, four named deaths ◑ | Bro | Review | `#254` |
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
| **69 merged rows** | **Shipped, and none independently confirmed** — every id with its pull request is a row in [`docs/archive/TASKS_ARCHIVE_2026-09.md`](docs/archive/TASKS_ARCHIVE_2026-09.md) ◑ | Bro | Review | merged |

Outside review starts at [`docs/EVIDENCE_INDEX.md`](docs/EVIDENCE_INDEX.md).

## What is not on this board

Waiting on the Owner, not rows: TWO one-line edits (`gitleaks.toml`, and requiring the Windows
tools job in `config/required-checks.json`), `T-063`'s tag arm, and — new on 2026-09-20 — the outbound LICENCE terms for this public repository
(§2f) — [`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md).

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document.

`CURRENT_ACTIVE_TASK: floor-writer` · `CURRENT_ACTIVE_WAVE: production-half` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

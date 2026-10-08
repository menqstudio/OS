# TASKS — the coordination board · կոորդինացիայի տախտակ

> **Open rows only.** Closed rows:
> [`docs/archive/TASKS_ARCHIVE_2026-08.md`](docs/archive/TASKS_ARCHIVE_2026-08.md).

<!-- BANNER -->
> **✅ SETTLED as of `main` `55863ea`.** PR #361 on `cockpit/approval-honesty` records it and merges after: read the live head with `git log -1`. Blocked on whom: `docs/OWNER_ACTION_REQUIRED.md`.
>
> **Next:** Owner: commission the next independent audit.
>
> **Standing verdict: RED** -- the TENTH round, `apps/desktop/AUDIT/2026-09-19-tenth-audit-75fca65.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

**Claim a row before you touch anything — never two on one.**

Status: `Todo` · `In-Progress` · `Review` · `Done` · `Blocked`. ◑ the Builder's own claim;
✅ independently confirmed. Never promote your own work.

| ID | Task | Claimed by | Status | Branch / PR |
|----|------|-----------|--------|-------------|
| **T-145** | **The whole repository, read file by file** — three records, all findings OPEN unless struck: [first read](docs/WHOLE_REPO_READ_2026-10-01.md) 932 (682 fixed, 87 open, 36 wait on the Owner §8); [engine, tools, documents](docs/WHOLE_REPO_READ_2026-10-02.md) 1226; [the cockpit](docs/WHOLE_REPO_READ_2026-10-02_COCKPIT.md) 1370 (18 closed, 1 half, 1 partly refuted — each marked in the record), where the readers left 168 files unfinished ◑ | Bro | In-Progress | `#332` |
| **T-131** | **Install-minted root** — A, C, D and B's accounts+entry merged; deployment open | Bro | In-Progress | — |
| **T-021d** | **PHASE 2 CLOSED, 11/11** - the page asks the engine in a section named apart from this app's own authority, and the roadmap gained the enumeration a moved checkbox needs ◑ | Bro | Review | `#257` |
| **T-021c** | **The desktop asks across the wall and cannot be told it decided** - the command, the parser, and the contract test phase 2 asked for; a reply claiming a decision is blocked ◑ | Bro | Review | `#256` |
| **T-021b** | **The engine records an ask and cannot decide it** - the first WRITE the sidecar serves, provisioned on its own; O-1..O-5 discharged, six mutants, six named deaths ◑ | Bro | Review | `#255` |
| **T-021a** | **The approval-request contract, audited before it lands** - the schema the Owner's five invariants fixed in advance; four mutants, four named deaths ◑ | Bro | Review | `#254` |
| **T-020** | **The anti-rollback floor's writer is the party the floor constrains** — a distinct **Floor Writer**; completion REQUESTS an advance. **C3 and a 2nd Architect pass NOT done** | Bro | Review | `#219` |
| **T-058** | **The transport, then §3.3's BUILD half** — the tick dispatches armed bundles, egress decided against the grant's table. **Nothing resolves an `auth_ref` yet** ◑ | Bro | Todo | `#207` |
| **T-061** | **Checks correct by reading, defended by no test** — all six of `docs/VERIFICATION_QUEUE_1.md` CLOSED, mutation-proven | Bro | Review | `#219` |
| **T-062** | **The negative matrix's silent state** — **171 / 54 / 17** of 242 bound. Each reproduced, then mutation-proven or recorded blocked with its measurement; of the 17 left, triage finds most need security code or a second UID ◑ | Bro | In-Progress | `#339` |
| **T-056** | **Two fail-closed checks prevent nothing** — both declared (`#208`); neither can be made to block from here: `bro_deploy_preflight.py` gates a deployment and none exists to call it (`T-131`; its one caller is `provision/tests/python_verifier.rs`), and requiring `check_ai_surfaces`' job is a protection change | Bro | Blocked | `#208` |
| **T-057** | **56 fabricated audit rows say so, and the mark reaches the reader** — `repo::seed` writes `payload_json`, both read mappers carry it ◑ | Bro | Review | `#210` |
| **T-004** | **Engine deferred items O-1..O-5** (Phase 10) — all OPEN, blocked by deployment wiring and a second principal; O-1 the only HIGH | — | Blocked | — |
| **T-005** | **Option-2 feasibility (audited): engine as a submodule** + a worktree-check fix. Own PR, Owner approval | — | Todo | — |
| **T-022** | **The governed automation dispatch** — firing one writes a desktop row that never crosses the wall; its `engine_receipt` is unobserved. `T-021` landed; what blocks it now is the shut production gate | — | Blocked | — |
| **T-023** · **T-046** | **Two Windows CI jobs, cause never characterised** — trust-provisioning (inherited ACL) and the engine job: green on six `main` runs in a row to 2026-10-08, which counts runs and explains nothing | — | Todo | `#182` |
| **T-030** | **Route 1 past the no-lease / no-secret whitelist** — `A-09`: routes 2/3 closed, Route 1 open **by design**; register at 19 leaves, not 8 | — | Todo | — |
| **88 merged rows** | **Shipped, and none independently confirmed** — every id with its pull request is a row in [`docs/archive/TASKS_ARCHIVE_2026-09.md`](docs/archive/TASKS_ARCHIVE_2026-09.md) ◑ | Bro | Review | merged |

Outside review starts at [`docs/EVIDENCE_INDEX.md`](docs/EVIDENCE_INDEX.md).

## What is not on this board

Waiting on the Owner, not rows: commissioning the next independent audit (93 PRs unaudited), what the drafted 0.1.0 release becomes, requiring the Windows
tools job (file and live protection together), `T-063`'s tag arm, and — new on 2026-09-20 — the outbound LICENCE terms for this public repository
(§2f) — [`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md).

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document.

`CURRENT_ACTIVE_TASK: floor-writer` · `CURRENT_ACTIVE_WAVE: production-half` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

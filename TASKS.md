# TASKS — the coordination board · կոորդինացիայի տախտակ

> **Open rows only.** This file was 2758 lines, 92% of it also in `NEXT_CHAT.md`. Closed:
> [`docs/archive/TASKS_ARCHIVE_2026-08.md`](docs/archive/TASKS_ARCHIVE_2026-08.md). The ceiling is
> in `config/canon-budget.json`; over it the wall takes only a shrinking edit.

<!-- BANNER -->
> **⏭️ CURRENT ACTIVE: PR #212 · branch `feat/negative-matrix-declared`** (base `main`, tip `6782787`, task T-062). Also open, and not this PR's work: PR #112 on `design/floor-writer-service`, PR #207 on `feat/credential-store`, PR #210 on `feat/audit-rows-name-their-source`, PR #214 on `feat/version-parity-gate`.
>
> 12 negative-matrix rows out of unreviewed: 3 implemented (mutation-proven), 9 blocked on a measured cause.
>
> **Standing verdict: RED** -- the NINTH round, `apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

**Claim a row before you touch anything — never two on one row.**

Status: `Todo` · `In-Progress` · `Review` · `Done` · `Blocked`. ◑ is the Builder's own unverified
claim; ✅ means an independent audit confirmed it. Never promote your own work.

| ID | Task | Claimed by | Status | Branch / PR |
|----|------|-----------|--------|-------------|
| **T-059** | **`main_ci` is stale by construction.** Recording a reading of `main` needs a merge, and the merge moves `main`: the gate passes inside the run that merges it and fails on the next read, so its verdict depends on WHEN it runs. Fix: accept a reading of any recent `main` and name which head | — | Todo | — |
| **T-058** | **§4's credential store, then the transport; and §3.3's BUILD half.** The produced agent runs: the tick dispatches armed bundles, egress is decided against the grant's table, `model`/`call` still refuse. Open: §4, being rewritten as an `auth_ref` REFERENCE store (#207) — migration 0022 forbids this process holding a secret at all; then the transport; then the netns jail for the population holding `Bash`. ◑ Builder-claimed | Bro | In-Progress | `feat/egress-authorizer-slice` |
| **T-061** | **Five checks in the Queue-1 PRs are correct by reading and defended by no test** — `docs/VERIFICATION_QUEUE_1.md` V-1..V-5, from a second sweep off a fresh clone; V-5, `both_read_surfaces_carry_the_mark`, cannot fail. Fix after #207/#210 land | — | Todo | — |
| **T-062** | **189 negative-matrix rows are still `unreviewed`** — nobody has looked, the silent state. 12 moved 2026-08-31: 3 to `implemented` (mutation-proven), 9 ACL rows to `blocked` on a measured cause. Priority domains: TIME 12, ACL 6, REPLAY 7, CONC 5, REG 5, EVID 3 | — | Todo | — |
| **T-056** | **Two fail-closed checks prevent nothing** — `config/control-invocation.json` derives 56 controls from the filesystem and holds each to what its failure stops. `bro_deploy_preflight.py` has zero non-test callers: a runbook mention is a suggestion. `check_ai_surfaces.py` runs under a context NOT in the required 33, and making one required is branch protection, the Owner's act | Bro | Todo | `#208` |
| **T-057** | **56 fabricated audit rows are indistinguishable from real ones.** `repo::seed` writes them by raw SQL; no `source` column. **Closure: a reviewer reading `audit_events` can tell fabricated from real WITHOUT reading `repo.rs`.** A column nothing surfaces does not close it. PR #210 | — | Todo | — |
| **T-046** | **The Windows engine job must run clean across several PRs** before the ledger's concurrency flake is called fixed — one green run does not prove an intermittent | — | Todo | merged `#182` |
| **T-004** | **Engine deferred security items O-1..O-5** (Phase 10). All five OPEN; none needs an Owner-minted artifact — deployment wiring and a second principal block them. O-1 is the only HIGH. `docs/PHASE_10_PRODUCTION_ITEMS.md` | — | Blocked | — |
| **T-005** | **Option-2 feasibility (audited): engine as a submodule**, plus a worktree-check fix (`git rev-parse --show-toplevel`). Security-adjacent: own branch, own PR, Owner approval. Until then 10 engine tests skip-guard themselves | — | Todo | — |
| **T-021** | **The approval-REQUEST path across the wall.** Phase 2 shipped the read half; the request half exists on neither side. Sequenced behind the standing audit: no new input to the trust boundary while the verdict is RED | — | Blocked | — |
| **T-022** | **The governed automation dispatch.** Firing an automation writes a row to the desktop store; it does not cross the wall, so its `engine_receipt` evidence is unobserved. Sequencing as `T-021` | — | Blocked | — |
| **T-023** | **CI reliability on a custody assertion.** *Trust provisioning + audit signer (windows-latest)* fails intermittently on an inherited runner ACL. Open until it runs clean across several PRs | — | Todo | — |
| **T-030** | **Route 1 past the no-lease / no-secret whitelist** (`A-09`, ninth audit). Routes 2 and 3 closed, mutation-confirmed. Route 1 open **by design** — a credential is what a remote system accepts, not what its text looks like. Register COMPUTED: **19 leaves, not 8** | — | Todo | — |
| **T-034** | **Two palettes, one contrast gate** (`I-04`, ninth audit): the gate decided on `round(ratio, 2)`, so two of its own pairs sat below AA at 4.4995 and printed `4.50`. ◑ Builder-fixed on the raw ratio. **Awaiting independent confirmation** | — | Todo | — |

Outside review starts at [`docs/EVIDENCE_INDEX.md`](docs/EVIDENCE_INDEX.md), whose
first section is what this repository does **not** establish.

## What is not on this board

Nothing on the security-remediation track is open, and nothing is waiting on the Owner —
[`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md) is the page of record. What
would change the position is the next independent audit round: everything merged since the
ninth round's head is unconfirmed.

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document. *(That requirement is why one document came to live in three files: three places obliged to carry the same text, and nothing obliging any of them to stay short.)*

`CURRENT_ACTIVE_TASK: egress-authorizer` · `CURRENT_ACTIVE_WAVE: production-half` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

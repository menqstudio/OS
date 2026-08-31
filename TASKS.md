# TASKS — the coordination board · կոորդինացիայի տախտակ

> **Open rows only.** This file was 2758 lines, 92% of it also in `NEXT_CHAT.md`. Closed:
> [`docs/archive/TASKS_ARCHIVE_2026-08.md`](docs/archive/TASKS_ARCHIVE_2026-08.md). The ceiling is
> in `config/canon-budget.json`; over it the wall takes only a shrinking edit.

<!-- BANNER -->
> **⏭️ CURRENT ACTIVE: PR #211 · branch `verify/queue-1-reverification`** (base `main`, tip `d42cb65`, task T-061). Also open, and not this PR's work: PR #112 on `design/floor-writer-service`, PR #207 on `feat/credential-store`, PR #208 on `feat/control-invocation`, PR #209 on `fix/prior-art-latest-declaration`, PR #210 on `feat/audit-rows-name-their-source`.
>
> A second measurement of Queue 1 from a fresh clone: 22 checks proven by my own mutations, 4 defended by nothing, and one assertion in PR #210 that cannot fail.
>
> **Standing verdict: RED** -- the NINTH round, `apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

**Claim a row before you touch anything — never two on one row.**

Status: `Todo` · `In-Progress` · `Review` · `Done` · `Blocked`. ◑ is the Builder's own unverified
claim; ✅ means an independent audit confirmed it. Never promote your own work.

| ID | Task | Claimed by | Status | Branch / PR |
|----|------|-----------|--------|-------------|
| **T-059** | **`main_ci` is stale by construction.** Recording a reading of `main` needs a merge, and the merge moves `main` — the gate passes inside the run that merges it and fails on the next read, so its verdict depends on WHEN it runs, not on the code. Fix: accept a reading of any recent `main` and name which head it is of | — | Todo | — |
| **T-058** | **§4's credential store, then the transport; and §3.3's BUILD half.** The produced agent runs: the tick dispatches armed bundles, egress is decided against the grant's table, `model`/`call` still refuse. §4's binding store is PR #207 and carries a flag: it adds the only secret-valued column in the schema, which 0022 forbids. Then the transport; then the netns jail for the population holding `Bash` (perimeter surgery) | Bro | In-Progress | `feat/egress-authorizer-slice` |
| **T-061** | **Five checks in the Queue-1 PRs are correct by reading and defended by no test** — `docs/VERIFICATION_QUEUE_1.md` V-1..V-5, found by a second sweep from a fresh clone: `is_bound`'s slot predicate, `for_egress`'s credential-slot refusal, `security::map_event`'s `source`, `Home.tsx`'s seeded count, and `both_read_surfaces_carry_the_mark`, whose last assertion cannot fail. Fix after #207/#210 land | — | Todo | — |
| **T-056** | **Every fail-closed check must name what its failure PREVENTS** — merge, session, deploy, release or nothing — in a registry, not a docstring. A check whose consequence is `nothing` is RED: a runbook mention is a suggestion. `bro_deploy_preflight` is the worked example. The population is DERIVED from the filesystem, so the gate cannot omit itself. PR #208 | — | Todo | — |
| **T-057** | **56 fabricated audit rows are indistinguishable from real ones.** `repo::seed` writes them by raw SQL; no `source` column. **Closure: a reviewer reading `audit_events` can tell fabricated from real WITHOUT reading `repo.rs`.** A column nothing surfaces does not close it. PR #210 attempts it; see `T-061` | — | Todo | — |
| **T-046** | **The Windows engine job must run clean across several PRs** before the ledger's concurrency flake is called fixed — one green run does not prove an intermittent. Open on the EVIDENCE, not the code | — | Todo | merged `#182` |
| **T-004** | **Engine deferred security items O-1..O-5** (roadmap Phase 10). All five OPEN; none needs an Owner-minted artifact — what blocks them is deployment wiring and a second principal. O-1 is the only HIGH. Inventory: `docs/PHASE_10_PRODUCTION_ITEMS.md` | — | Blocked | — |
| **T-005** | **Option-2 feasibility (audited): engine as a submodule**, plus a worktree-check fix (`git rev-parse --show-toplevel`). Security-adjacent: own branch, own PR, Owner approval. Until then 10 engine tests skip-guard themselves | — | Todo | — |
| **T-021** | **The approval-REQUEST path across the wall.** Phase 2 shipped the read half; the request half exists on neither side. Sequenced behind the standing audit — a new input to the trust boundary is not added while the verdict is RED | — | Blocked | — |
| **T-022** | **The governed automation dispatch.** Firing an automation writes a row to the desktop store; it does not cross the wall, so its `engine_receipt` evidence is permanently unobserved. Same sequencing as `T-021` | — | Blocked | — |
| **T-023** | **CI reliability on a custody assertion.** *Trust provisioning + audit signer (windows-latest)* fails intermittently on an inherited runner ACL. ◑ Builder-claimed closed; open until it runs clean across several PRs — reruns were once treated as evidence | — | Todo | — |
| **T-030** | **Route 1 past the no-lease / no-secret whitelist** (`A-09`, ninth audit). Routes 2 and 3 closed, mutation-confirmed. Route 1 open **by design** — a credential is what a remote system accepts, not what its text looks like. Register COMPUTED: **19 leaves, not 8** | — | Todo | — |
| **T-034** | **Two palettes, one contrast gate** (`I-04`, ninth audit): the gate decided on `round(ratio, 2)`, so two of its own pairs sat below AA at 4.4995 and printed `4.50`. ◑ Builder-fixed on the raw ratio. **Awaiting independent confirmation** | — | Todo | — |

## What is not on this board

Nothing on the security-remediation track is open, and nothing is waiting on the Owner —
[`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md) is the page of record. What
would change the position is the next independent audit round: everything merged since the
ninth round's head is unconfirmed.

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document. *(That requirement is why one document came to live in three files: three places obliged to carry the same text, and nothing obliging any of them to stay short.)*

`CURRENT_ACTIVE_TASK: egress-authorizer` · `CURRENT_ACTIVE_WAVE: production-half` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

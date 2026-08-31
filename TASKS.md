# TASKS — the coordination board · կոորդինացիայի տախտակ

> **Open rows only.** Closed rows:
> [`docs/archive/TASKS_ARCHIVE_2026-08.md`](docs/archive/TASKS_ARCHIVE_2026-08.md).

<!-- BANNER -->
> **⏭️ CURRENT ACTIVE: PR #219 · branch `feat/floor-writer-service`** (base `main`, tip `87bfe73`, task **T-020**). No other pull request is open.
>
> Five states kept apart: #112's DESIGN **merged** · Architect design audit **done** · five rulings **issued** · implementation **in progress, NOT approved** · production trust claim **NOT granted**.
>
> **Standing verdict: RED** -- the NINTH round, `apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

**Claim a row before you touch anything — never two on one.**

Status: `Todo` · `In-Progress` · `Review` · `Done` · `Blocked`. ◑ the Builder's own claim;
✅ independently confirmed. Never promote your own work.

| ID | Task | Claimed by | Status | Branch / PR |
|----|------|-----------|--------|-------------|
| **T-020** | **The anti-rollback floor's writer is the party the floor exists to constrain.** The per-task floor moves to protected custody, mutable only through a distinct **Floor Writer** principal: completion REQUESTS an advance, never mutates, and stays separate from the per-install ceiling. `#112` merged; Architect **BLOCKED** `#219` (B1–B7/C1–C7). B6/C4/C6 corrected and measured (provisioning, 4 UIDs / 23 checks, crash injection); C1–C3, C7 and a second Architect pass NOT | Bro | Review | `#219` |
| **T-064** | **The shut governed gate now names WHICH requirement a machine fails.** `broker/src/preflight.rs` reports **27** requirements met / not met / not measurable, with who provisions each; here **1 / 25 / 1** | Bro | Review | merged `#217` |
| **T-063** | **The app version is stated 5x in 4 files and nothing compared them.** `check_version_parity.py` refuses drift and names the file. **Open: the git-tag arm**, which needs a release policy the Owner has not stated | Bro | Todo | merged `#214` |
| **T-059** | **`main_ci` is stale by construction.** Recording a reading of `main` needs a merge, and the merge moves `main`: it passes inside the run that merges it and fails on the next read. Fix: accept any recent `main`, named | — | Todo | — |
| **T-058** | **The transport, then §3.3's BUILD half.** The produced agent runs: the tick dispatches armed bundles, egress is decided against the grant's table, `model`/`call` still refuse. §4 landed as an `auth_ref` REFERENCE store — this process holds no secret (0022). **Nothing engine-side resolves an `auth_ref` yet**, so transport-first would be unreachable code. ◑ | Bro | Todo | merged `#207` |
| **T-060** | **A PR that outlives its own `Last updated` line reddens `main` on merge.** The gate compares the claimed date with the newest commit touching the file, and a squash makes that the merge date. `T-059`'s family | — | Todo | — |
| **T-061** | **Checks correct by reading and defended by no test** — `docs/VERIFICATION_QUEUE_1.md`. V-1/V-3/V-5 closed, mutation-proven; **V-2, V-4, V-6 open** | — | Todo | `#210` |
| **T-062** | **189 negative-matrix rows are still `unreviewed`** — nobody has looked, the silent state. Counts and the 12 moved on 2026-08-31 are in `config/negative-matrix.json` | — | Todo | — |
| **T-056** | **Two fail-closed checks prevent nothing** — `config/control-invocation.json` holds each control to what its failure stops. `bro_deploy_preflight.py` has zero non-test callers: a runbook mention is a suggestion. `check_ai_surfaces.py` runs under a context NOT in the required set, and making one required is the Owner's act | Bro | Todo | merged `#208` |
| **T-057** | **56 fabricated audit rows say so, and the mark reaches the reader.** `repo::seed` writes `payload_json = {"source":"seed"}`; a query separates them and both read mappers carry it out. ◑ — a test asserts the closure | Bro | Review | merged `#210` |
| **T-004** | **Engine deferred items O-1..O-5** (Phase 10). All five OPEN; deployment wiring and a second principal block them, not an Owner artifact. O-1 is the only HIGH. `docs/PHASE_10_PRODUCTION_ITEMS.md` | — | Blocked | — |
| **T-005** | **Option-2 feasibility (audited): engine as a submodule**, plus a worktree-check fix (`git rev-parse --show-toplevel`). Own branch, own PR, Owner approval. 10 engine tests skip-guard themselves | — | Todo | — |
| **T-021** | **The approval-REQUEST path across the wall.** Phase 2 shipped the read half; the request half exists on neither side. Behind the standing audit: no new trust-boundary input while RED | — | Blocked | — |
| **T-022** | **The governed automation dispatch.** Firing one writes a desktop row that never crosses the wall, so its `engine_receipt` evidence is unobserved. Sequencing as `T-021` | — | Blocked | — |
| **T-023** · **T-046** | **Two CI jobs called fixed on one green run** — *Trust provisioning + audit signer (windows-latest)* on an inherited runner ACL, the Windows engine job on the ledger's concurrency. Open on the EVIDENCE: one green run does not prove an intermittent | — | Todo | merged `#182` |
| **T-030** | **Route 1 past the no-lease / no-secret whitelist** — `A-09`, ninth audit. Routes 2 and 3 closed, mutation-confirmed; Route 1 open **by design**, and the register is COMPUTED at **19 leaves, not 8** | — | Todo | — |
| **T-034** | **Two palettes, one contrast gate** — `I-04`, ninth audit: it decided on `round(ratio, 2)`, so 4.4995 printed `4.50`. ◑ Builder-fixed on the raw ratio, **awaiting independent confirmation** | — | Todo | — |

Outside review starts at [`docs/EVIDENCE_INDEX.md`](docs/EVIDENCE_INDEX.md); its first
section is what this repository does **not** establish.

## What is not on this board

Three things wait on the Owner and are not rows: `T-059`'s fix, `T-063`'s tag arm, and
whether `parse_audit_candidate` should say how many markers it found.
[`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md) is the page of record.

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document.

`CURRENT_ACTIVE_TASK: floor-writer` · `CURRENT_ACTIVE_WAVE: production-half` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

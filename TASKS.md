# TASKS — the coordination board · կոորդինացիայի տախտակ

> **Open rows only.** Closed rows:
> [`docs/archive/TASKS_ARCHIVE_2026-08.md`](docs/archive/TASKS_ARCHIVE_2026-08.md).

<!-- BANNER -->
> **⏭️ CURRENT ACTIVE: PR #112 · branch `design/floor-writer-service`** (base `main`, tip `363c51c`, task T-020). Also open, and not this PR's work: PR #217 on `feat/provisioning-preflight`.
>
> The floor-writer design is re-verified against this head and NOT superseded: PRODUCTION_HALF_DESIGN is the output half, this is the containment half. Still a PROPOSAL awaiting the Architect.
>
> **Standing verdict: RED** -- the NINTH round, `apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

**Claim a row before you touch anything — never two on one.**

Status: `Todo` · `In-Progress` · `Review` · `Done` · `Blocked`. ◑ the Builder's own claim;
✅ independently confirmed. Never promote your own work.

| ID | Task | Claimed by | Status | Branch / PR |
|----|------|-----------|--------|-------------|
| **T-063** | **The app version is stated 5x in 4 files and nothing compared them.** `check_version_parity.py` refuses drift and names the file; it landed as a SECOND `T-060` and was renumbered. **Open: the git-tag arm** — it needs a release policy the Owner has not stated | Bro | Todo | merged `#214` |
| **T-059** | **`main_ci` is stale by construction.** Recording a reading of `main` needs a merge, and the merge moves `main`: the gate passes inside the run that merges it and fails on the next read. Fix: accept a reading of any recent `main` and name which head | — | Todo | — |
| **T-058** | **The transport, then §3.3's BUILD half.** The produced agent runs: the tick dispatches armed bundles, egress is decided against the grant's table, `model`/`call` still refuse. §4 landed on `#207` as an `auth_ref` REFERENCE store — this process holds no secret, per migration 0022. Next the transport, then the netns jail for the population holding `Bash`. ◑ Builder-claimed | Bro | In-Progress | `#207` |
| **T-060** | **A PR that outlives its own `Last updated` line reddens `main` on merge.** The gate compares `PROJECT_STATE.md`'s claimed date with the newest commit touching it, and a squash makes that the merge date. `T-059`'s family: a verdict that depends on WHEN it runs | — | Todo | — |
| **T-061** | **Five Queue-1 checks are correct by reading and defended by no test** — `docs/VERIFICATION_QUEUE_1.md`, from a second sweep off a fresh clone. **V-3/V-5 closed on `#210`, V-1 on `#207`**, each mutation-proven. V-2, V-4, V-6 open | — | Todo | `#210` |
| **T-062** | **189 negative-matrix rows are still `unreviewed`** — nobody has looked, the silent state. 12 moved 2026-08-31: 3 to `implemented` (mutation-proven), 9 ACL rows to `blocked` on a measured cause. The domain counts are in `config/negative-matrix.json` | — | Todo | — |
| **T-056** | **Two fail-closed checks prevent nothing** — `config/control-invocation.json` derives 56 controls from the filesystem, each held to what its failure stops. `bro_deploy_preflight.py` has zero non-test callers: a runbook mention is a suggestion. `check_ai_surfaces.py` runs under a context NOT in the required 33, and making one required is the Owner's act | Bro | Todo | `#208` |
| **T-057** | **56 fabricated audit rows say so now, and the mark reaches the reader.** `repo::seed` writes `payload_json = {"source":"seed"}`; a query alone separates them, and `activity::list` + `security::summary` both carry it to the Home sparkline. ◑ Builder-claimed — a test asserts the closure, not this row | Bro | Review | `#210` |
| **T-046** | **The Windows engine job must run clean across several PRs** before the ledger's concurrency flake is called fixed | — | Todo | merged `#182` |
| **T-004** | **Engine deferred items O-1..O-5** (Phase 10). All five OPEN; none needs an Owner-minted artifact — deployment wiring and a second principal block them. O-1 is the only HIGH. `docs/PHASE_10_PRODUCTION_ITEMS.md` | — | Blocked | — |
| **T-005** | **Option-2 feasibility (audited): engine as a submodule**, plus a worktree-check fix (`git rev-parse --show-toplevel`). Own branch, own PR, Owner approval. Until then 10 engine tests skip-guard themselves | — | Todo | — |
| **T-021** | **The approval-REQUEST path across the wall.** Phase 2 shipped the read half; the request half exists on neither side. Sequenced behind the standing audit: no new input to the trust boundary while the verdict is RED | — | Blocked | — |
| **T-022** | **The governed automation dispatch.** Firing an automation writes a row to the desktop store; it does not cross the wall, so its `engine_receipt` evidence is unobserved. Sequencing as `T-021` | — | Blocked | — |
| **T-023** | **CI reliability on a custody assertion.** *Trust provisioning + audit signer (windows-latest)* fails intermittently on an inherited runner ACL. Open until it runs clean | — | Todo | — |
| **T-030** | **Route 1 past the no-lease / no-secret whitelist** (`A-09`, ninth audit). Routes 2 and 3 closed, mutation-confirmed. Route 1 open **by design**: a credential is what a remote system accepts, not what its text looks like. Register COMPUTED: **19 leaves, not 8** | — | Todo | — |
| **T-034** | **Two palettes, one contrast gate** (`I-04`, ninth audit): it decided on `round(ratio, 2)`, so pairs at 4.4995 printed `4.50` and passed AA. ◑ Builder-fixed on the raw ratio. **Awaiting independent confirmation** | — | Todo | — |

Outside review starts at [`docs/EVIDENCE_INDEX.md`](docs/EVIDENCE_INDEX.md), whose first
section is what this repository does **not** establish.

## What is not on this board

Nothing on the security-remediation track is open and nothing waits on the Owner —
[`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md) is the page of record.
Everything merged since the ninth round's head is unconfirmed.

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`; `tools/check_coordination.py` requires them of each coordination document, which is why one sentence lives in three files.

`CURRENT_ACTIVE_TASK: egress-authorizer` · `CURRENT_ACTIVE_WAVE: production-half` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

# TASKS — the coordination board · կոորդինացիայի տախտակ

> **Open rows only.** Closed rows:
> [`docs/archive/TASKS_ARCHIVE_2026-08.md`](docs/archive/TASKS_ARCHIVE_2026-08.md).

<!-- BANNER -->
> **⏭️ CURRENT ACTIVE: PR #225 · branch `t062/triage-2026-09-19`** (base `main`, tip `a261406`, task T-062).
>
> T-062: 182 unreviewed negative-matrix rows read against the tree; 33 blocked by name, 79 already covered, 59 implementable, 149 left. docs/NEGATIVE_MATRIX_TRIAGE_2026-09-19.md.
>
> **Standing verdict: RED** -- the NINTH round, `apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

**Claim a row before you touch anything — never two on one.**

Status: `Todo` · `In-Progress` · `Review` · `Done` · `Blocked`. ◑ the Builder's own claim;
✅ independently confirmed. Never promote your own work.

| ID | Task | Claimed by | Status | Branch / PR |
|----|------|-----------|--------|-------------|
| **T-068** | **The frontend suite oversubscribed the machine** — vitest's default (CPUs−1) spent half its time in `environment`; `maxWorkers: 4` halves it for +15% wall, 9 runs. T-040's flake not reproduced, not claimed fixed ◑ | Bro | Review | merged `#223` |
| **T-067** | **`_rest_open_prs` asked about `menqstudio/OS` by name** (H-05, one file over); built from `_repo_slug()` now, no slug ⇒ no read. Mutant RED ◑ | Bro | Review | merged `#222` |
| **T-066** | **Two tools lied on 2026-09-19, untested** — UTF-8 git reads; `what`/`current`/Active line move with the carrier; measured `main_ci`. 9 mutants RED ◑ | Bro | Review | merged `#221` |
| **T-065** | **Scheduled supply-chain gate red since 2026-09-07 on unnamed advisories** — `browserslist`, `rustls` lifted; `T-055` executed by the Owner; `actions: read` on Repo-state ◑ | Bro | Review | merged `#220` |
| **T-020** | **The anti-rollback floor's writer is the party the floor exists to constrain.** A distinct **Floor Writer** principal: completion REQUESTS an advance, never mutates. `#112`, `#219` merged (B6/C1/C2/C4/C6/C7 measured); C3 and a second Architect pass NOT done — NOT approved | Bro | Review | merged `#219` |
| **T-064** | **The shut governed gate names WHICH requirement a machine fails** — `broker/src/preflight.rs`: 27 requirements, met / not met / not measurable, who provisions each | Bro | Review | merged `#217` |
| **T-063** | **The app version is stated 5x in 4 files and nothing compared them.** `check_version_parity.py` refuses drift and names the file. **Open: the git-tag arm** — a release policy the Owner has not stated | Bro | Todo | merged `#214` |
| **T-059** | **`main_ci` was stale by construction** — an OLDER reading now passes while every run since was `success`; one stepping over a red `main` is refused | Bro | Review | merged `#219` |
| **T-058** | **The transport, then §3.3's BUILD half.** The produced agent runs: the tick dispatches armed bundles, egress is decided against the grant's table, `model`/`call` still refuse; §4 is an `auth_ref` REFERENCE store (0022). **Nothing resolves an `auth_ref` yet.** ◑ | Bro | Todo | merged `#207` |
| **T-060** | **A PR outliving its `Last updated` line reddened `main` on merge** — a squash re-dates the commit (both dates, 0 of 796 differ); the gate checks whether that commit MOVED the line | Bro | Review | merged `#219` |
| **T-061** | **Checks correct by reading, defended by no test** — `docs/VERIFICATION_QUEUE_1.md`. All six CLOSED, mutation-proven | Bro | Review | merged `#219` |
| **T-062** | **The negative matrix's silent state** — 182 rows read by 12 readers + 12 skeptics: 33 `blocked` by name, 79 already covered, 59 implementable; 149 left. `docs/NEGATIVE_MATRIX_TRIAGE_2026-09-19.md` ◑ | Bro | In-Progress | `#225` |
| **T-056** | **Two fail-closed checks prevent nothing** — `control-invocation.json` holds each control to what its failure stops; `bro_deploy_preflight.py` has zero non-test callers; `check_ai_surfaces.py` runs under a non-required context — the Owner's act | Bro | Todo | merged `#208` |
| **T-057** | **56 fabricated audit rows say so, and the mark reaches the reader.** `repo::seed` writes `payload_json = {"source":"seed"}`, both read mappers carry it. ◑ | Bro | Review | merged `#210` |
| **T-004** | **Engine deferred items O-1..O-5** (Phase 10). All five OPEN, blocked by deployment wiring and a second principal; O-1 the only HIGH. `docs/PHASE_10_PRODUCTION_ITEMS.md` | — | Blocked | — |
| **T-005** | **Option-2 feasibility (audited): engine as a submodule** + a worktree-check fix. Own branch, own PR, Owner approval | — | Todo | — |
| **T-021** | **The approval-REQUEST path across the wall.** the read half shipped, the request half exists nowhere; no new trust-boundary input while RED | — | Blocked | — |
| **T-022** | **The governed automation dispatch.** Firing one writes a desktop row that never crosses the wall; its `engine_receipt` evidence is unobserved. After `T-021` | — | Blocked | — |
| **T-023** · **T-046** | **Two CI jobs called fixed on one green run** — windows-latest trust-provisioning (inherited ACL), the Windows engine job (ledger concurrency); one green run proves nothing | — | Todo | merged `#182` |
| **T-030** | **Route 1 past the no-lease / no-secret whitelist** — `A-09`, ninth audit. Routes 2, 3 closed; Route 1 open **by design**; register COMPUTED at **19 leaves, not 8** | — | Todo | — |
| **T-034** | **Two palettes, one contrast gate** — `I-04`: `round(ratio, 2)` let 4.4995 print `4.50`. ◑ fixed on the raw ratio, awaiting confirmation | — | Todo | — |

Outside review starts at [`docs/EVIDENCE_INDEX.md`](docs/EVIDENCE_INDEX.md).

## What is not on this board

Waiting on the Owner, not rows: branch protection on `main` (OFF on a private Free-plan repo — Pro or
public), `T-063`'s tag arm, `parse_audit_candidate`'s marker count —
[`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md) carries the first.

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document.

`CURRENT_ACTIVE_TASK: floor-writer` · `CURRENT_ACTIVE_WAVE: production-half` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

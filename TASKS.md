# TASKS — the coordination board · կոորդինացիայի տախտակ

> **Open rows only.** This file was 2758 lines with an essay under most rows, 92% of it
> also present in `NEXT_CHAT.md`. Closed rows and the full narrative are in
> [`docs/archive/TASKS_ARCHIVE_2026-08.md`](docs/archive/TASKS_ARCHIVE_2026-08.md).
> `tools/check_canon_budget.py` holds this file to 20 KB.

<!-- BANNER -->
> **⏭️ CURRENT ACTIVE: PR #188 · branch `t054/readme-measured`** (base `main`, tip `fe26a78`, task T-054). Also open, and not this PR's work: PR #112 on `design/floor-writer-service`.
>
> The README's counts are re-measured and five are corrected; the superseded measurements move to docs/README_CLAIM_HISTORY.md rather than being deleted.
>
> **Standing verdict: RED** -- the NINTH round, `apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

**Claim a row before you touch anything, and never two agents on one row.**

Status vocabulary: `Todo` · `In-Progress` · `Review` · `Done` · `Blocked`.
A mark of ◑ means the Builder's own unverified claim; ✅ means an independent audit
confirmed it. Never promote your own work.

| ID | Task | Claimed by | Status | Branch / PR |
|----|------|-----------|--------|-------------|
| **T-055** | **The first produced artifact — one agent, built by the factory, not by hand.** It must EXIST as a thing, not a row carrying `verb: argument`. All five, or not done: a customer sentence reaches Bro and Bro confirms it; specialists produce an ARTIFACT with a defined shape on disk and in schema; **that artifact carries its own grant — which capabilities, which paths, which domains — written by the RUNTIME, not a prompt**; `run_due()` fires it on schedule and it does ONE real thing; a receipt says what it touched, including the mode it ran under. Linux only; the one real thing may be as small as reading a local file and writing a summary. Do not open the governed gate; do not extend containment. **Point 3 decides it:** a grant back in a prompt fails the slice however well the other four work. If one of the five cannot be met honestly, stop and say which | — | Todo | — |
| **T-046** | **The audit ledger's concurrency test let the runner decide the verdict** — 24 threads raced one `O_EXCL` lock against the PRODUCTION 10 s bound, so a slow Windows runner turned `main` red on a tree byte-identical to one that had just passed. Bound raised in the TEST only; merged as PR #182. Open on the evidence, not the code: **it stays open until several pull requests run the Windows engine job clean**, which is `T-023`'s lesson | — | Todo | merged `#182` |
| **T-004** | **Engine deferred security items O-1..O-5** (roadmap Phase 10). All five OPEN; none needs an Owner-minted artifact. What blocks them is deployment wiring and a second principal. O-1 is the only HIGH and the Owner chose the fix over accepting the risk — closure is the VERIFICATION on a packaged build, not the assertion that the install directory is unwritable. Inventory: `docs/PHASE_10_PRODUCTION_ITEMS.md` | — | Blocked | — |
| **T-005** | **Option-2 feasibility (audited): engine as a submodule plus a targeted fix to the worktree check** (`git rev-parse --show-toplevel` instead of parsing `git worktree list`). Touches security-adjacent code, so it needs its own branch, its own PR and Owner approval; it must not land inside a coordination merge. Until then 10 monorepo-coupled engine tests skip-guard themselves | — | Todo | — |
| **T-021** | **The approval-REQUEST path across the wall.** Phase 2 shipped the read half end to end; the request half exists on neither side. Sequenced behind the standing audit: a new input to the engine's trust boundary is not added while the independent verdict is RED | — | Blocked | — |
| **T-022** | **The governed automation dispatch.** Firing an automation writes a row to the desktop store; it does not cross the wall, so its `engine_receipt` evidence is permanently unobserved. Same sequencing as `T-021` | — | Blocked | — |
| **T-023** | **CI reliability on a custody assertion.** *Trust provisioning + audit signer (windows-latest)* fails intermittently on an inherited runner ACL. ◑ Builder-claimed closed; **stays open until the job runs clean across several pull requests** — one green run does not prove an intermittent failure fixed, and this row exists because reruns were once treated as evidence | — | Todo | — |
| **T-030** | **Route 1 past the no-lease / no-secret whitelist** (`A-09`, reopened by the ninth audit). Routes 2 and 3 are closed and mutation-confirmed. Route 1 is open **by design**: a credential is defined by what a remote system accepts, not by its text, so the honest answer is the enumerated surface rather than a heuristic. The register is COMPUTED from the real validators now — **19 leaves, not 8** — but the route is not closed | — | Todo | — |
| **T-034** | **Two palettes, one contrast gate.** Reopened by the ninth audit (`I-04`): the gate decided on `round(ratio, 2)`, so two of its own pairs sat below AA at 4.4995 and 4.4996 and printed `4.50`. ◑ Builder-fixed 2026-08-27 — the comparison is on the raw ratio and both colours were re-solved against the composite as a fixed point. **Awaiting independent confirmation**, like everything since `5cf9b8c` | — | Todo | — |

## What is not on this board

`main` is settled and nothing on the security-remediation track is open. The production
gate is shut and only the Owner opens it, after an independent audit —
[`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md) is the page of record and
as of 2026-08-29 nothing there needs the Owner.

The next independent audit round is what would change the position: 20 pull requests, 107
files and 19688 inserted lines have merged since the ninth round's head and none of it is
independently confirmed.

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document. *(That requirement is why one document came to live in three files: three places obliged to carry the same text, and nothing obliging any of them to stay short.)*

`CURRENT_ACTIVE_TASK: T-054` · `CURRENT_ACTIVE_WAVE: canon` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

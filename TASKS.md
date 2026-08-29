# TASKS — the coordination board · կոորդինացիայի տախտակ

> **Open rows only.** This file was 2758 lines with an essay under most rows, 92% of it
> also present in `NEXT_CHAT.md`. Closed rows and the full narrative are in
> [`docs/archive/TASKS_ARCHIVE_2026-08.md`](docs/archive/TASKS_ARCHIVE_2026-08.md).
> `tools/check_canon_budget.py` holds this file to 20 KB.

**Active branch** `gate/canon-budget` · **task** `T-045` · `main` settled at `b190a16`
(PR #179) · open and deliberately unmerged: PR #112 (`design/floor-writer-service`).

**Claim a row before you touch anything, and never two agents on one row.**

Status vocabulary: `Todo` · `In-Progress` · `Review` · `Done` · `Blocked`.
A mark of ◑ means the Builder's own unverified claim; ✅ means an independent audit
confirmed it. Never promote your own work.

| ID | Task | Claimed by | Status | Branch / PR |
|----|------|-----------|--------|-------------|
| **T-045** | **The canon has to stay readable, and the handoff has to be checkable.** Every gate in `tools/` could only be satisfied by ADDING, and `coordination_stop_guard.py` went further and blocked a session from ending unless it wrote into `PROJECT_STATE.md`/`TASKS.md`/the roadmap — so the read manifest grew to 1917 KB (~386k tokens) with `NEXT_CHAT.md` and `PROJECT_STATE.md` carrying 3037 identical lines. `check_canon_budget.py` and `check_handoff_ready.py` are the counterweight, plus the PreToolUse refusal that accepts only shrinking edits to an over-budget canonical file. Its own gates then went red in CI on `1a5616d` for reasons nothing local could see — `check_handoff_ready.py` judged a `pull_request` merge commit as an ordinary checkout and said "nothing of it is on GitHub", and the `purpose` cut deleted the audit pointer `check_audit_reports.py` reads and the O-1..O-5 severities `check_residual_items.py` reads. All four fixed and mutation-verified. Remaining: the roadmap, `current_state.json` and the audit ledger are still over their ceilings | 🔨 Claude | In-Progress | `gate/canon-budget` |
| **T-004** | **Engine deferred security items O-1..O-5** (roadmap Phase 10). All five OPEN; none needs an Owner-minted artifact. What blocks them is deployment wiring and a second principal. O-1 is the only HIGH and the Owner chose the fix over accepting the risk — closure is the VERIFICATION on a packaged build, not the assertion that the install directory is unwritable. Inventory: `docs/PHASE_10_PRODUCTION_ITEMS.md` | — | Blocked | — |
| **T-005** | **Option-2 feasibility (audited): engine as a submodule plus a targeted fix to the worktree check** (`git rev-parse --show-toplevel` instead of parsing `git worktree list`). Touches security-adjacent code, so it needs its own branch, its own PR and Owner approval; it must not land inside a coordination merge. Until then 10 monorepo-coupled engine tests skip-guard themselves | — | Todo | — |
| **T-021** | **The approval-REQUEST path across the wall.** Phase 2 shipped the read half end to end; the request half exists on neither side. Sequenced behind the standing audit: a new input to the engine's trust boundary is not added while the independent verdict is RED | — | Blocked | — |
| **T-022** | **The governed automation dispatch.** Firing an automation writes a row to the desktop store; it does not cross the wall, so its `engine_receipt` evidence is permanently unobserved. Same sequencing as `T-021` | — | Blocked | — |
| **T-023** | **CI reliability on a custody assertion.** *Trust provisioning + audit signer (windows-latest)* fails intermittently on an inherited runner ACL. ◑ Builder-claimed closed; **stays open until the job runs clean across several pull requests** — one green run does not prove an intermittent failure fixed, and this row exists because reruns were once treated as evidence | — | Todo | — |
| **T-030** | **Route 1 past the no-lease / no-secret whitelist** (`A-09`, reopened by the ninth audit). Routes 2 and 3 are closed and mutation-confirmed. Route 1 is open **by design**: a credential is defined by what a remote system accepts, not by its text, so the honest answer is the enumerated surface rather than a heuristic. The register is COMPUTED from the real validators now — the honest count is **19 leaves, not 8** — but the route is not closed and is not claimed to be | — | Todo | — |
| **T-034** | **Two palettes, one contrast gate.** Reopened by the ninth audit (`I-04`): the gate decided on `round(ratio, 2)`, so two of its own pairs sat below AA at 4.4995 and 4.4996 and printed `4.50`. ◑ Builder-fixed 2026-08-27 — the comparison is on the raw ratio and both colours were re-solved against the composite as a fixed point. **Awaiting independent confirmation**, like everything since `5cf9b8c` | — | Todo | — |

## What is not on this board

`main` is settled and nothing on the security-remediation track is open. The production
gate is shut and only the Owner opens it, after an independent audit —
[`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md) is the page of record and
as of 2026-08-29 nothing there needs the Owner.

The next independent audit round is what would change the position: 17 pull requests, 66
files and 6496 inserted lines have merged since the ninth round's head and none of it is
independently confirmed.

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document. *(That requirement is why one document came to live in three files: three places obliged to carry the same text, and nothing obliging any of them to stay short.)*

`CURRENT_ACTIVE_TASK: T-045` · `CURRENT_ACTIVE_WAVE: canon` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

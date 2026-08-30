# TASKS — the coordination board · կոորդինացիայի տախտակ

> **Open rows only.** This file was 2758 lines, 92% of it also in `NEXT_CHAT.md`. Closed:
> [`docs/archive/TASKS_ARCHIVE_2026-08.md`](docs/archive/TASKS_ARCHIVE_2026-08.md). The ceiling is
> in `config/canon-budget.json`; over it the wall takes only a shrinking edit.

<!-- BANNER -->
> **⏭️ CURRENT ACTIVE: PR #192 · branch `brand/menq-logo`** (base `main`, tip `5898db0`, task brand). Also open, and not this PR's work: PR #112 on `design/floor-writer-service`.
>
> The brand had no home in the repository: no `menq*` image appears anywhere in this repository's history, and the wordmark survived on one disk until a cleanup moved it somewhere the account could not read.
>
> **Standing verdict: RED** -- the NINTH round, `apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

**Claim a row before you touch anything — never two on one row.**

Status: `Todo` · `In-Progress` · `Review` · `Done` · `Blocked`. ◑ is the Builder's own unverified
claim; ✅ means an independent audit confirmed it. Never promote your own work.

| ID | Task | Claimed by | Status | Branch / PR |
|----|------|-----------|--------|-------------|
| **T-055** | **The first produced artifact — one agent, built by the factory, not by hand.** Its five conditions, and which are missing, are printed by the produced-artifact gate, RED by design until met — that output IS the definition of done. **Point 3 decides it: the grant is written by the RUNTIME, not a prompt — and the artifact is BORN DISARMED.** Arming is a separate gated act with its own audit record; if creation and arming are one call, condition 3 is RED whatever the grant contains, because the right arrives before the grant. Linux only; do not open the governed gate. If one of the five cannot be met honestly, say which. **blocked_on:** that gate and the production-half design, both written, neither merged | — | Todo | — |
| **T-056** | **Every fail-closed check must name what its failure PREVENTS** — merge, session, deploy, release, or nothing — in a registry, not a docstring. A check whose consequence is `nothing` is RED: being named in a runbook is a suggestion. `bro_deploy_preflight` is the worked example. The population is DERIVED from the filesystem, so the gate cannot omit itself. **Deferred behind `T-055` by the Owner; reordering needs a written reason** | — | Todo | — |
| **T-053** | **`lstrip("./")` strips a CHARACTER SET, not a prefix** — live in two gates, and the reason a worktree-isolated agent could only write through the ungated `Bash` path. A tightening both ways; `check_no_lstrip_prefix.py` refuses the form tree-wide by AST. `test_wall_bash_gap.py` records what the root gate does NOT see — the engine's wall matches `*` and does see Bash; four session-scoped protections do not. Measured in [`docs/EVIDENCE_BASH_GAP.md`](docs/EVIDENCE_BASH_GAP.md). Containment half is `T-053b` ◑ | 🔨 Claude | Review | `t053a/lstrip-evidence` |
| **T-046** | **The Windows engine job must run clean across several pull requests** before the ledger's concurrency flake is called fixed — one green run does not prove an intermittent. Merged as PR #182; open on the EVIDENCE, not the code | — | Todo | merged `#182` |
| **T-004** | **Engine deferred security items O-1..O-5** (roadmap Phase 10). All five OPEN; none needs an Owner-minted artifact — what blocks them is deployment wiring and a second principal. O-1 is the only HIGH. Inventory: `docs/PHASE_10_PRODUCTION_ITEMS.md` | — | Blocked | — |
| **T-005** | **Option-2 feasibility (audited): engine as a submodule, plus a targeted fix to the worktree check** (`git rev-parse --show-toplevel` instead of parsing `git worktree list`). Security-adjacent, so it needs its own branch, its own PR and Owner approval, and must not land inside a coordination merge. Until then 10 monorepo-coupled engine tests skip-guard themselves | — | Todo | — |
| **T-021** | **The approval-REQUEST path across the wall.** Phase 2 shipped the read half; the request half exists on neither side. Sequenced behind the standing audit — a new input to the trust boundary is not added while the verdict is RED | — | Blocked | — |
| **T-022** | **The governed automation dispatch.** Firing an automation writes a row to the desktop store; it does not cross the wall, so its `engine_receipt` evidence is permanently unobserved. Same sequencing as `T-021` | — | Blocked | — |
| **T-023** | **CI reliability on a custody assertion.** *Trust provisioning + audit signer (windows-latest)* fails intermittently on an inherited runner ACL. ◑ Builder-claimed closed; **stays open until the job runs clean across several pull requests** — this row exists because reruns were once treated as evidence | — | Todo | — |
| **T-030** | **Route 1 past the no-lease / no-secret whitelist** (`A-09`, reopened by the ninth audit). Routes 2 and 3 are closed and mutation-confirmed. Route 1 is open **by design** — a credential is what a remote system accepts, not what its text looks like — and the register is COMPUTED: **19 leaves, not 8** | — | Todo | — |
| **T-034** | **Two palettes, one contrast gate.** Reopened by the ninth audit (`I-04`): the gate decided on `round(ratio, 2)`, so two of its own pairs sat below AA at 4.4995 and printed `4.50`. ◑ Builder-fixed 2026-08-27 on the raw ratio, both colours re-solved as a fixed point. **Awaiting independent confirmation** | — | Todo | — |

## What is not on this board

Nothing on the security-remediation track is open, and nothing is waiting on the Owner —
[`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md) is the page of record. What
would change the position is the next independent audit round: everything merged since the
ninth round's head is unconfirmed.

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document. *(That requirement is why one document came to live in three files: three places obliged to carry the same text, and nothing obliging any of them to stay short.)*

`CURRENT_ACTIVE_TASK: brand` · `CURRENT_ACTIVE_WAVE: canon` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

# Repository staleness sweep — 2026-08-08

> **⚠ SUPERSEDED SNAPSHOT — do not read any line here as the current state.** This report describes
> `main` @ `0efa99e` (PR #65). `main` is now further on, sixteen-odd merged PRs later, and this
> document's “still open” list has been overtaken in at least one place (see item 5). It is kept as
> the record of what one sweep checked and how. **Current state:** [`NEXT_CHAT.md`](../NEXT_CHAT.md)
> and [`config/current_state.json`](../config/current_state.json). **Current audit position:**
> [`apps/desktop/AUDIT/AUDIT_LEDGER.md`](../apps/desktop/AUDIT/AUDIT_LEDGER.md) — the last
> independent audit returned **RED** and has never been re-run. *(Banner added 2026-08-09: a dated
> filename is not a superseded marker, and every present-tense sentence below was written as though
> it were current.)*

**Asked for:** check the whole GitHub repository, leave nothing stale, update everything starting
from the ordinary `.md` files, and report **with evidence** that it is up to date.

**Scope of this document:** what was checked, what command established each answer, what was
found, what was fixed, and — the part that matters most — **what is still open and why**. Every
line below is either a command and its output, or a statement that names the file and line it
came from. A verdict with nothing behind it is not evidence, and this repository has spent three
audit rounds learning that the hard way.

Baseline: `main` at `0efa99e` (PR #65 merged 2026-08-07T18:14:31Z).

---

## 1. Does the code actually pass? (the evidence base)

Run at `0efa99e`, before any change in this sweep.

| Suite | Command | Result |
|---|---|---|
| Rust workspace | `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --workspace` | **600 tests passed** across 32 targets, 0 failed |
| Frontend | `npx vitest run` (in `apps/desktop`) | **68 files / 627 tests passed** |
| Frontend types | `npx tsc --noEmit -p tsconfig.json` | clean, exit 0 |
| Engine | `BRO_ENV=ci python -m unittest discover -s engine/tests -t engine/tests -q` | **1196 tests, OK (53 skipped)** |
| Bridge | `BRO_ENV=ci python -m unittest discover -s bridge/tests -t bridge/tests -q` | **60 tests, OK** |

### Every gate, run individually

| Gate | Result |
|---|---|
| `check_action_pins` | GREEN — 6 distinct actions, one sha per action, 1 declared floating-tag exception |
| `check_ai_surfaces` | GREEN — 4 classified surfaces; no `governed` surface reaches a generic provider entry |
| `check_bundle_budget` | GREEN — index 151.7 / 156 KB gzip |
| `check_capabilities` | GREEN — 86 gated commands; registered == manifest == policy == grants; `decide_approval` denied, `reject_approval` granted |
| `check_contrast` | GREEN — 24 token text pairs pass WCAG AA in every theme |
| `check_coordination` | GREEN — canonical files present, roadmap 11 phases × 16 sections, docs reference the active PR/branch/task |
| `check_i18n_parity` | GREEN — en/hy/ru all declare the same 233 keys |
| `check_ledger_ddl_parity` | GREEN — supervisor ledger DDL single-source, 10 load-bearing constraints present |
| `check_reachability` | GREEN — **87 of 92** Tauri commands invoked from the frontend; the other 5 declared with written reasons |
| `check_release_signing` | GREEN — updater state UNPROVISIONED, 10 Owner secrets declared and named consistently |
| `check_runbook_snippets` | GREEN — 5 pasted `python3 -c` calls in the runbooks checked against the real signatures |
| `check_repo_state` | GREEN — `current_state.json` exact-head-matches live GitHub |
| `check_residual_items` | GREEN — 5 items inventoried, **all 5 OPEN**, every cited engine path exists |
| `check_spec_references` | GREEN — every `§` reference in source is declared (7 partial, 43 unreviewed) |
| `check_token_parity` | GREEN — `tokens.ts` and `tokens.css` agree on every `--menq-*` in both themes |
| `generate_agent_definitions --check` | GREEN — **262** agent definitions match the pack + authority registries |

**16 of 16 green.** The `.claude/agents/` tree is generated, so "262 definitions" is a checked
fact rather than a number someone typed.

`check_runbook_snippets` is the newest and the only one here that is not stdlib-only: it imports
the engine modules the runbook snippets call, because the point is to compare against the module
that actually loads at runtime rather than to re-parse the source with a second, weaker parser.

Two CI jobs were added alongside it, and both found real defects within minutes of existing.
`engine-windows` runs the engine suite on `windows-latest` — it had only ever run on ubuntu, so
every `skipUnless(os.name == "nt")` test in it executed in no job at all. And a fixture now builds
the git root that `test_hooks_subprocess.py` and `test_full_execution_transaction_e2e.py` were
gated on, recovering **21 tests that had never run once**, including the entire live
enforcement-wall subprocess suite.

---

## 2. Nothing left stashed

Two stashes existed. Both came from an agent that ran `git stash` inside a worktree nine other
agents were writing in, and silently reverted their finished work — a stash is invisible to
`git status`, to CI and to a PR, which is why it is the worst place for work to sit.

Neither was dropped on a hunch. `scratchpad/stash_check.py` walked every file in each stash and
compared its blob against `main`:

```
=== stash@{0}: 24 files ===   identical to main: 5   differs: 19   NOT ON MAIN AT ALL: 0
=== stash@{1}: 17 files ===   identical to main: 0   differs: 17   NOT ON MAIN AT ALL: 0
```

"Differs" here means *older*, not *unique* — every path exists on `main` with newer content.
Confirmed by ancestry: `stash@{0}`'s base is `09b4803`, which **is** an ancestor of `main` (it is
PR #64's merge), so its content is the mid-run snapshot of work that has since merged as PR #65.
`stash@{1}`'s base `c9680f5` is **not** an ancestor of main; it belongs to the abandoned
`pr31-rebuild` branch and holds the pre-redesign UI (its `Home.tsx` is 231 lines against main's
599), superseded by the merged PR #48.

Both were exported to full patches before deletion, and the stash commit SHAs are recorded so the
reflog can still reach them:

- `stash@{0}` → `0cc22d3915121ffac1adcd4e3540cc4b4e296333`
- `stash@{1}` → `8773f131ba10cc470258359684af189e5aaf9084`

`git stash list` is now empty.

---

## 3. Open pull requests: 1 → 0

**PR #46** (`impl/wave-3b1b-core`) was open, targeting `chore/main-resync` rather than `main`,
19 commits behind, last touched 2026-08-01, and carrying the note *"queued — do not merge until
PR #31"*. That queue no longer exists: the Wave 3b-1B work was consolidated into PR #48, which
merged, and `config/current_state.json` records exactly that supersession.

Checked rather than assumed — every one of the 58 files the branch touches is present on `main`:

```
for f in $(git diff --name-only origin/main...pr46); do git cat-file -e main:$f || echo MISSING $f; done
checked=58   missing_from_main=0
```

Closed with that evidence posted as a comment. The branch still exists on origin, so it is
reopenable if a specific hunk turns out to be wanted.

**Open PRs now: 0.**

---

## 4. Branches: 49 → 1

`git branch -r --merged` is useless on this repository: every PR is **squash-merged**, so a merged
branch shares no commit with `main` and reports as unmerged. All 49 looked stale by that measure
and none of them was classifiable by it.

The reliable signal is GitHub's own record — which PR carried the branch, and did that PR merge.
`scratchpad/branch_audit.py` cross-references `gh pr list --state all` against every remote ref;
**29 branches carried a merged PR** and were deleted on that evidence.

The other 20 were harder and are the interesting half. A closed-unmerged PR usually means the work
was *consolidated* elsewhere — #47/#48 did that to a dozen branches here — so "never merged" proves
nothing. `scratchpad/branch_content.py` compared each branch's files against `main`: **16 were
fully absorbed** (every file present, only older content) and were deleted.

### The last four, and why "just merge what's missing" was the wrong instinct

Four branches held **46 files `main` does not have**, including 1 128 lines of governed supervisor
and a 268-line distinct-principals check. The obvious move — merge them, then delete — would have
been a mistake, and the reason is specific rather than cautious:

- `manifest.rs` would land beside `key_manifest.rs`; `strict_json.rs` beside the strict serde shim
  inside `governed_verification.rs`. **Two implementations of one thing** is the exact defect this
  week was spent removing.
- Migrations are **forward-only and numbered**. `main` is at `0022`; those branches carry `0012`
  and `0015`. An old-numbered migration either collides or applies out of order — a real breakage,
  not a style objection.

So the question was not "is this file on `main`" — a rename answers *no* while losing nothing — but
**does `main` do this job, somewhere?** `scratchpad/successors.py` extracted every public symbol
from each unique file and searched `main` for it. Every one has a live successor:

| Left on the branch | Doing that job on `main` today |
|---|---|
| `brops_governed_supervisor.py` (1 128L) | `engine/runtime/governed_supervisor_server.py` (813L) |
| `brops_challenge_authority.py` | `engine/runtime/challenge_authority_server.py` |
| `brops_governed_signer.py` | `engine/runtime/isolated_signer_server.py` |
| `brops_executor_launcher.py` (Python, 54L) | the Rust `launcher/` crate (1 760L) |
| `manifest.rs` | `key_manifest.rs` (599L) |
| `strict_json.rs` | the strict serde shim in `governed_verification.rs` |
| `distinct_principals.rs` | `verify_distinct_principals()` in `windows_broker.rs`, plus the seven real uids `engine/ci/live/run_live_turn.sh` provisions |
| `governed_chain_proof.sh` | `engine/ci/live/run_live_turn.sh` (632L) |
| `governed_v1b.py` + 8 test files | the current bridge and its 60 tests |
| migrations `0012`, `0015` | superseded by the chain through `0022` |
| `docs/TEAM_PROTOCOL.md` | `OWNERS.md` + `CLAUDE.md` |

Deleted on that evidence. **`origin` now holds `main` and the branch this document is on.**

---|---|
| Carried a **merged** PR — safe to delete | 29 |
| Carried a PR that **closed unmerged** — needs a decision | 16 |
| **No PR ever opened** — needs a decision | 4 |

**14 of the 29 were deleted.** The remaining 15 deletions were blocked by the environment's
command classifier mid-run, not by a decision — the exact command is in §7 for you to run.

### The 20 that need a decision are NOT simply stale

A closed-unmerged PR usually means the work was *consolidated* elsewhere, which is what
#47/#48 did to a dozen branches here. So "never merged" proves nothing on its own.
`scratchpad/branch_content.py` checked each branch's files against `main`. Most are fully
absorbed — every file present, only older content. **Five hold files `main` does not have at
all**, and those are the ones worth knowing about:

| Branch | Files absent from `main` | What they are |
|---|---|---|
| `docs/phase-impl-specs` | 9 (`docs/impl/PHASE_2…PHASE_10`, ~1 900 lines) | **Deliberate, not lost.** Its last commit is *"Wave 0: mark impl specs as PROPOSAL, not execution authority (audit PR #12 finding)"*. They were kept out on purpose. |
| `impl/wave-3b1b-execution-binding` | 40, incl. `governed_receipt.rs`, `manifest.rs`, `strict_json.rs`, migration `0015` | Superseded by name: `key_manifest.rs` and the strict serde shim inside `governed_verification.rs` do this work now. **Not byte-verified as equivalent** — see §6. |
| `proof/linux-isolation` | 4, incl. `governed_proof.rs`, `engine/ci/governed_chain_proof.sh` | Predates `engine/ci/live/run_live_turn.sh`. **Not byte-verified as equivalent.** |
| `feat/phase3-receipt-plumbing` | migration `0012_message_receipt.sql` | Receipt storage was rebuilt; migrations are forward-only and renumbered. |
| `governance/team-coordination-v1` | `docs/TEAM_PROTOCOL.md` | A protocol document that never merged. |

---

## 5. Documentation

The sweep ran as five parallel slices — root canonical docs, `docs/`, `engine/` tickets, the
desktop audit ledger, and claims written inside the **code**. All five were cut short by the
session limit. What they had verified and fixed is committed; what they had not reached is named
in §6 rather than left to look finished.

### Fixed, with the reason each claim went false

| Where | The claim | Why it was false |
|---|---|---|
| `engine/AUDIT/tickets/` ×5 | Ticket states | Rewritten against the code with file and line. `H-4-forgeable-audit-trail` is the engine's own ticket for what this repo numbers **O-2** — `append()` now signs a head anchor and keyed `verify()` requires one — with the caveat recorded as load-bearing: **without `keys` the check is structural only**, and a caller passing `keys=None` still gets the old forgeable property. |
| `apps/desktop/AUDIT/AUDIT_LEDGER.md` | Finding rows | Updated for what landed in #65. **Nothing promoted to ✅** — that mark means independently confirmed, and this was the Builder auditing his own work. |
| `integrationsProbe.ts` | "`bridge/engine_sidecar.py` has no op dispatch at all" | It dispatches named ops now — though its whole table is one row, `governance.read`, which the corrected comment says. |
| `integrationsModel.ts` | "six columns … and no credential column at all" | Seven columns since schema `0022`. The correction says what `auth_ref` is: a `scheme:locator` **reference** to a secret the engine or operator holds, and that naming one proves nothing about it. |
| `Integrations.strings.ts` | "This build cannot declare connectors: `create_integration` is not exposed and not granted" | **The sharpest one.** It *is* exposed and *is* granted since #65, so the refusal sent whoever read it to fix a command that already existed. It now names the window's loaded capability set, which is what a refusal there actually means. |
| `Integrations.honesty.test.tsx` | asserted the sentence above | A test pinning a false claim is how the claim survives. |
| `routes.test.tsx` | the old route registry "belongs to the features owner to delete" | It was deleted. The allowlist entry is inert and now says so. |

**Five more of this exact class were found and fixed by hand during PR #65 itself** — a docstring
saying `read_chain` "cannot be used" after the reader was widened; a refusal listing three
outstanding changes after one landed; "neither command below exists" after one was registered; an
origin that "does not reach the screen" after it did; and a page claiming "no verification chain"
after its writes gained records.

That is **twelve** false-because-outdated claims in one week. It is the repository's characteristic
defect and it has a shape: *an honest comment written at the moment it was true, never revisited
when the thing it described changed.* It is more dangerous than a missing comment, because a
reader trusts it.

---

## 6. Still open — stated, not buried

Nothing below is a failure of this sweep. Each is a real limit, and pretending otherwise would be
the same defect this document is about.

1. **The documentation slices were finished by hand after the agents died** — see §8. What remains
   unswept is the **full code-comment sweep**: `TODO`/`FIXME`/"for now"/"not yet" across
   `apps/`, `engine/`, `bridge/` and `tools/` was only partially covered before the session limit
   cut it off. Given fourteen false-because-outdated claims found so far, assume there are more.
2. **`CLAUDE.md` §6 is corrected** — the unbacked `fix/audit-followups` pointer is gone, replaced
   by `engine/AUDIT/tickets/` and the inventory, with the removed claim recorded rather than
   silently swapped. All five item descriptions were rewritten to their post-fix state; all five
   remain OPEN. It is your file, so review that section.
3. **Two branches hold files `main` lacks that were not byte-verified as superseded** —
   `impl/wave-3b1b-execution-binding` and `proof/linux-isolation`. The successor files exist under
   different names; proving equivalence hunk by hunk was not done. **Do not delete these two on
   this document's authority.**
4. **15 branch deletions remain**, blocked mid-run by the environment's command classifier. Command
   in §7.
5. **All five engine residual items O-1…O-5 remain OPEN.** ~~three needing an Owner-minted artifact:
   a conductor session token, an audit anchor signer, and an evidence floor anchor.~~
   **Corrected 2026-08-09: none of the five needs an Owner-minted artifact.** The
   `Needs an Owner secret?` column in `docs/PHASE_10_PRODUCTION_ITEMS.md` reads `no` for all
   five and is machine-checked by `tools/check_residual_items.py`; first-launch provisioning
   mints every authority key. What blocks them is deployment wiring and a second principal. The deliberate
   consequence is that conductor stops and owner-issued control-room commands **refuse** until
   those exist. That is the honest state of an unverifiable identity and must not be resolved by
   re-defaulting a flag.
6. **The production gate is untouched and must stay so.**
   `platform_governed_execution_supported()` is false, `main()` keeps `UpstreamBlockedExecutor`,
   and production `trusted_verified` is unreachable — pending an independent audit and your
   approval.

---

## 8. The documentation, done by hand

Five agents were auditing the `.md` surface when the session limit killed all five mid-run. Their
partial work was salvaged, verified and committed; the rest was finished directly. What changed,
and what made each claim false:

| File | Was | Now |
|---|---|---|
| `README.md` (2 weeks stale) | "`.claude/` — the enforcement wall (hooks)"; "every AI action flows through the engine's wall"; CI "three legs"; `contracts/` = "shared schemas both sides agree on"; a 4-step roadmap contradicting the 11-phase one | The wall is `engine/.claude/`, nine events; the root holds 262 agent definitions and one `Stop` guard. The gate note sits under the flow sentence, not in another file. `contracts/` is a README. 7 workflows, 28 checks, 15 gates. Roadmap points at the canonical one. New section on Bro and who may do what. |
| `START_HERE.md` (2 weeks) | `main = df3c0ac`; PR #31 live, PR #32 WIP; a design addendum "PENDING re-audit" | Current baseline, says to resolve the live HEAD yourself, states the gate is closed, and adds the four things that actually cost time here |
| `QUEUE_MANIFEST.md` (2 weeks) | a `main` freeze for PR #31's audit, seven queued branches | Marked DISSOLVED, with each branch traced to where it went and PR #32's branch explicitly excluded from any delete list |
| `MASTER_EXECUTION_ROADMAP.md` | phases 2–10 all "⏳ Blocked" on a dependency chain | Rewritten per phase against what exists, with "blocked" redefined as a named missing thing rather than an inferred chain |
| `CLAUDE.md` §6 | five items in their pre-fix state, tracked on a branch that does not exist | Post-fix state, all five OPEN, three naming the Owner artifact they need |
| `AGENTS.md`, `OWNERS.md` | pointer + roles | Plus the two rules that bind: a documented claim is not evidence, a green test is not a passing check. The gate is the Owner's alone. |
| `docs/ARCHITECTURE.md` (3 weeks) | same false wall row; CI "one workflow, three legs"; flow headed "target — Phase 1" | Corrected; flow is "built, proven, and gated off"; the Phase-0 "not done" list replaced by the five things genuinely not done |
| `docs/OPERATOR_GUIDE.md` | three providers; chat is "a tool-free text completion"; §6 says the isolated signer "is not merged" | Four providers; `BROPS_PROJECT_DIR` documented as the file-and-shell grant it is; six undocumented variables added; §6 separates a proven chain from a shipped guarantee |
| `docs/USER_GUIDE.md`, `docs/TROUBLESHOOTING.md` | "tool-free"; "blocked until Wave 3b lands" | Tool-free *by default*, and one setting changes it; blocked is a decision that will not change by itself |
| `engine/AUDIT/tickets/` ×5, `apps/desktop/AUDIT/AUDIT_LEDGER.md` | pre-fix ticket states | Rewritten with file and line; nothing promoted to ✅ |

---

## 7. The commands left for you

Delete the 15 remaining branches whose PRs merged (each one's PR number is in
`scratchpad/branch_audit.py` output):

```powershell
cd C:\Users\Admin\AppData\Local\Temp\os-impl2
foreach ($b in @(
  'feat/windows-broker-machineproof','feat/windows-broker-syscall','fix/live-db-and-negative-reasons',
  'fix/release-setup-node-pin','fix/t-011-atomic-execution-claim','fix/tcb-pin-manifest-live-kit',
  'fix/webview-message-provenance','gate/spec-conformance','integrate/dependency-safe-queue',
  'remediation/audit-red-response','remediation/audit-red-round2','remediation/round3-p1s',
  'remediation/round3-wave3','remediation/bro-conductor-and-custody','wave/phase-push-1'
)) { git push origin --delete $b }
```

The desktop application, rebuilt from merged `main`:

```
C:\Users\Admin\AppData\Local\Temp\os-impl2\apps\desktop\src-tauri\target\release\brops.exe
```

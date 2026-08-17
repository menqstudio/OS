# Dependency-safe queue manifest — OS v1

> **DISSOLVED 2026-07-27. Kept as the record of what the queue was and where each branch went.**
>
> This file described a freeze that no longer exists. `main` was held still so that PR #31's
> exact-head Architect design re-audit would stay valid, and independent work was parked here
> rather than merged. **PR #31 merged on 2026-07-27T22:19:39Z**, and PR #47 —
> *"integrate: dependency-safe quality/CI gates + UI refreshes + post-#31-merge state sync"* —
> merged 28 minutes later, absorbing the queue. Nothing is queued today.
>
> Current state lives in [`NEXT_CHAT.md`](./NEXT_CHAT.md) and
> [`config/current_state.json`](./config/current_state.json). **Open pull requests: 1** — #82 on
> `settle/after-81`, the self-carrier that records the settle. *(This said “Open pull requests: 0”
> until 2026-08-09, and it was a count nothing checked. It is a snapshot in a DISSOLVED file: resolve
> it from GitHub or from `config/current_state.json.current_workflow_pr`, never from this line.)*

---

## Where each queued branch went

Traced rather than assumed. "Absorbed" means every file the branch touched is present on `main`
today; where a branch still holds something `main` does not have, that is said instead of glossed.

| Branch | Then | Now |
|---|---|---|
| `ci/ai-surface-inventory-gate` | ✅ verified, queued | **Absorbed via PR #47.** No PR was ever opened for the branch itself. The gate ships as `tools/check_ai_surfaces.py` and is GREEN. |
| `ci/supply-chain-gate` | ✅ verified, queued | **Absorbed.** Its own PR #35 was closed unmerged; the work landed through #47. `.github/workflows/supply-chain.yml` now carries eleven jobs, four added since. |
| `ui/design-system` | ✅ verified, queued | **Absorbed.** PR #36 closed unmerged; tokens and the contrast gate landed via #47. `check_contrast` and `check_token_parity` are GREEN. |
| `ui/modal-a11y` | ⏸ HELD — full `ui.tsx` replace | **Gone from origin.** The a11y work landed as `ui/shell-a11y` (PR #44, also closed unmerged) and through #47; the a11y gate runs on every PR. The "held for manual merge" note is what a careful hold looks like when it works. |
| `docs/windows-broker-design` | ✅ verified, queued | **Fully absorbed** — one file, byte-identical to `main`. The branch still exists on origin and can be deleted. |
| `docs/pr32-rebase-map` | ✅ queued | **Absorbed.** PR #37 closed unmerged. |
| `backup/pr31-pre-rebase-6ebeca8` | 🔒 backup ref | **Still on origin.** PR #31 merged, so the thing it insured against did not happen. Deletable at the Owner's discretion. |

PR #32 (`impl/wave-3b1b-execution-binding`) was **closed unmerged**. Its branch still holds 40
files `main` does not have — `governed_receipt.rs`, `manifest.rs`, `strict_json.rs`, migration
`0015` and others. The successors exist under different names (`key_manifest.rs`, the strict serde
shim inside `governed_verification.rs`), but **equivalence was never verified hunk by hunk**, so
that branch is not on any delete list.

---

## What replaced the queue

The freeze existed because a moving `main` invalidated an exact-head audit. Two mechanisms now do
that job continuously, so no freeze is needed:

- **`config/current_state.json` + `tools/check_repo_state.py`** — the state file records the exact
  candidate head, and CI verifies it against **live GitHub** on every run. A stale claim fails the
  build instead of silently outliving its audit.
- **The `AUDIT_CANDIDATE_HEAD` marker** in a PR body, kept in lockstep with every push. An audit is
  anchored to a commit rather than to a promise that nobody moved anything.

## The admission rule was right, and outlived the queue

> A branch is admitted only after it builds, its tests pass, and an independent adversarial review
> returns CLEAN.

That rule is now the merge rule — held by convention, not by enforcement: **31 checks run on every
PR** (15 of them repository gates under `tools/`), and **none of them is a *required* check**,
because `main` carries branch protection: **33 required status checks**, `enforce_admins`, `strict`, linear history, no force pushes, no deletions (enabled 2026-08-17 by Owner decision after the seventh audit's `G-01`; widened from 12 to 33 on 2026-08-18 after the eighth audit's `H-01`). Exactly two pull-request jobs are excluded, each for a measured reason: `AI-surface inventory gate` (a `paths:` filter means it does not report on unrelated PRs, and GitHub treats a skipped required context as pending) and `Trust provisioning (windows-latest)` (`T-023`, three recorded occurrences). *(Until 2026-08-17 this sentence said `main` had none, and it was true when written — that is the seventh audit's `G-01`, and the eighth audit's `H-04` is that seven documents went on saying it afterwards.)* Enabling protection
is the Owner's, not the Builder's. For security work there is also
the discipline that every added check is **deleted once to confirm its test goes red**. In the last
wave about ninety checks were verified that way, and four came back *green*, meaning four tests
were testing nothing. That is exactly the failure the admission rule was written against.

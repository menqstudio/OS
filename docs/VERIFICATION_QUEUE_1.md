# Verification of Queue 1 — a second measurement, from a fresh clone

Queue 1 opened four pull requests and wrote
[`docs/OVERNIGHT_QUEUE_2026-08-31.md`](OVERNIGHT_QUEUE_2026-08-31.md). Everything in
it was one agent's claim. This pass measures it again and **finds four things that
report did not**, three of them in its own work.

Nothing here is fixed. Fixing inside a verification pass destroys the verification.

## Method

A **fresh `git clone`** of `menqstudio/OS` into a directory outside the working tree
— not a worktree, not the tree Queue 1 built in. Confirmed genuinely fresh: the
branch commit a squash erased earlier tonight does not resolve there
(`git cat-file -e b9f12dd` → not found), which is the exact way a local object store
makes a dead reference look alive.

One deviation, stated because it is a shared-state risk: `CARGO_TARGET_DIR` was
pointed at one directory outside the clone and reused across the four checkouts.
`/tmp` here is a **7.8 GB tmpfs and it filled** — one cargo target alone was 6.7 GB.
Cargo fingerprints by content, so a shared target is not the stale-artefact hazard a
shared *git object store* is; it is recorded so a reader can weigh it. The one place
a stale artefact **did** appear is called out below, and was re-produced.

## Suites, per PR, in the fresh clone

| | #207 | #208 | #209 | #210 |
|---|---|---|---|---|
| `cargo test --workspace` | **1104 passed, 0 failed** | 1088 passed, 0 failed | not run (tools-only) | **1092 passed, 0 failed** |
| engine `unittest discover -s tests` | 2039 OK, 10 skipped | 2039 OK, 10 skipped | — | 2039 OK, 10 skipped |
| bridge `unittest discover -s bridge/tests` | **210 OK** | 210 OK | — | 210 OK |
| `tsc --noEmit` | exit 0 | — | — | exit 0 |
| `vitest run` | 80 files / **758 tests** | — | — | 80 files / **761 tests** |
| gate self-tests | — | **197 OK, 1 skipped** | 14 OK | — |

Every `tools/check_*.py` was run on #207 and #210. All GREEN except:
`check_canonical_sync`, `check_prior_art`, `check_read_receipt` print usage without
arguments (CLAUDE.md §5); `check_handoff_ready` is RED because the local branch
`pr-NNN` has no upstream — an artefact of fetching a PR into a local branch, not a
defect; `check_bundle_budget` was RED until `npm run build`, after which it is
**GREEN — 1 entry within gzip budget (index 133.7/156 KB), 23 routes, 257.0 KB gzip
total**.

## Numbers that disagreed with Queue 1

**One, and it is a measurement difference rather than a contradiction.** Queue 1
reported **194** gate self-tests; this pass counts **197, with 1 skipped**. Both are
right for their moment: Queue 1's number was taken before three parser tests were
added to `test_check_control_invocation` in the same PR. Populations counted: Queue 1
counted the eight modules in the CI list at that commit; this pass counted the same
eight modules plus `test_check_control_invocation` at its final commit.

The skip is named rather than left as a number: `test_roadmap_split`, skipped with
the reason *"5512d82 is no longer reachable; the fixture is the record"*. It is
pre-existing and not Queue 1's.

Every other number Queue 1 stated reproduced exactly: 1104, 1092, 2039/10, 758→761.

## Mutation sweeps — mine, not the report's

Each mutation below is a **different edit** from the one Queue 1 describes, was
grep-confirmed on disk, was confirmed to compile (or parse) before any test ran, and
was restored afterwards. A mutation that does not compile proves nothing and is
labelled so.

### PROVEN — I broke it and a named test went red

**#207** (5): `Secret`'s `Debug` does not reach the value · the approval entity is
scoped to the slot · the Call arm detects a missing binding · an absent binding
changes the refusal · `credential_state` distinguishes absent from present.

**#208** (10): the population is globbed and not taken from the registry · an entry
whose file is gone is refused · `blocks: merge` is checked against the REQUIRED set
and not merely against CI · `blocks: nothing` may not understate · a fail-closed
check blocking nothing needs `unenforced_reason` + `tracked_by` · `tracked_by` must
resolve · a short reason is a placeholder · `blocks: nothing` needs a `why` · an
unread workflow is a READING failure and not a verdict · every path in
`contracts/index.json` resolves.

**#209** (1): `declaration_for` returns the LATEST — mutated by adding `break` to the
loop rather than reverting the function, caught by
`test_the_LATEST_declaration_is_read_even_if_two_somehow_exist`.

**#210** (6): the seed writes the marker · `activity::map` carries it · `source_of`
reads the key it is given · `source_of` tolerates a malformed payload · the summary
names the seeded count · it says it in every language.

**22 checks proven by my own mutation.**

### NOT PROVEN — the code reads correct and no test defends it

These are the finding. Each survived a mutation with **every test still green**.

1. **`credentials::is_bound` does not require the SLOT to match.** Removing the
   `slot_id` predicate leaves the suite green. Queue 1's sweep varied the *digest*,
   and `a_binding_does_not_reach_a_different_build` catches that — **no test varies
   the slot**. As written the code is correct; nothing would notice if it stopped
   being. Consequence if it regressed: a value bound to slot `a` would satisfy a
   step requiring slot `b` on the same bundle.
2. **`Grant::for_egress`'s credential-slot validation is untested.** Deleting the
   duplicate/empty-name refusal leaves the suite green. Queue 1 never swept it.
3. **`security::map_event` may drop the mark entirely and nothing notices.** Setting
   its `source` to `None` — the second of two identical mapper bodies — leaves every
   test green. **PROVEN by mutation.**
4. **`Home.tsx` may stop counting seeded rows and nothing notices.** Replacing
   `rows.filter(e => e.source === 'seed').length` with `0` type-checks and leaves the
   frontend suite green. `activitySummary` is tested; the wiring that feeds it is not.

### A check that cannot fail

`repo.rs::both_read_surfaces_carry_the_mark` (PR #210) is named for two surfaces and
asserts one. It computes `security::summary(&conn)`, discards it (`let _ = &summary`),
and then asserts `rows.iter().any(|e| e.source.is_some())` — re-checking the
`activity::list` rows it already asserted eight lines above. **No state of the world
makes that last assertion red if the earlier one passed**, and finding 3 above is the
proof: the security surface can drop the mark with the test still green.

## The produced artifact, end to end

Verified on **both** #207 and #210, in the fresh clone:

- `git ls-files | grep -icE 'produced-artifact|runs.jsonl|receipts.jsonl'` → **1**,
  and that one is `config/produced-artifact-contract.json`, the contract. **The store
  is not committed.**
- Before producing: `check_produced_artifact` **RED** — *"the store is declared and
  nothing has produced it"*.
- `cargo run -p brops-core --bin produce_agent_artifact` — which the source shows
  goes `register` (disarmed) → `approvals::approve_confirmed` → `set_active` →
  `automations::run_due`, with **no `claim_and_run` call** outside a comment.
- After producing: **GREEN on all five**, `invoked_by` = `run_due`, receipt carrying
  `enforcement_regime` = `enforce`.

**One stale-artefact trap caught here.** On the #210 checkout the gate was GREEN
before I produced anything — because the store written during the #207 checkout
survives a `git checkout` (it lives under `target/`, which is untracked). Deleting it
returned the gate to RED, and re-producing on #210's own code returned it to GREEN.
Queue 1's claim is confirmed, but a reader repeating this must delete the store first
or they will measure the previous checkout.

## Defects recorded, not fixed

| # | where | what |
|---|---|---|
| V-1 | `credentials::is_bound` (#207) | **CLOSED on #207.** Every other test varied the digest, so `AND slot_id = ?2` could have been dropped and stayed green. `is_bound_answers_about_the_slot_it_was_asked_about` now reddens on exactly that mutation |
| V-2 | `Grant::for_egress` (#207) | the credential-slot refusal is untested. STILL OPEN: it lives in `agent_bundle.rs`, which §4's rewrite did not touch |
| V-3 | `security::map_event` (#210) | **CLOSED on #210.** It could drop the `source` mark with nothing noticing; V-5's repaired assertion now reddens on exactly that mutation |
| V-4 | `Home.tsx` (#210) | the seeded count can become `0`; nothing notices |
| V-5 | `repo.rs::both_read_surfaces_carry_the_mark` (#210) | **CLOSED on #210.** It asserted one surface, was named for two, and closed on a restatement of an earlier assertion. It now asserts `security::summary`'s own rows |
| V-6 | `produce_agent_artifact.rs` module doc, lines 4-5 | still says the binary *"claims that run, executes it"*; since the dispatch change `run_due` does, and the binary does not call `claim_and_run` |

V-1 through V-5 meant **PR #210's headline claim — "the mark reaches the reader" — was
half proven**: it reached `activity::list`, and whether it reached `security::summary` or
the Home sparkline was asserted by nothing.

**Half of that is closed, and the closure was proven both ways.** With
`security::map_event` mutated to `source: None` — grep-confirmed at `repo.rs:3951`, and it
compiled, so the mutation is a real one — the OLD assertion printed `ok` and the NEW one
printed `FAILED ... security::summary must carry the mark too`. The same mutation, two
verdicts: that is the difference between a test and a restatement. `cargo test --workspace`
on this branch afterwards: 1092 passed, 0 failed.

**V-4 stays open**: the Home sparkline's seeded count is still asserted by nothing, so
"the mark reaches the reader" is proven as far as `security::summary` and no further.

## What this pass did not do

- It did not run the Windows-only jobs, which have no runner here.
- It did not verify PR #207's flagged conflict with migration 0022 by any new
  measurement; that flag stands on Queue 1's own reading and my re-reading of the
  same two files, and it is a decision for the Owner either way.
- It did not re-measure Task E. The frontend intermittent did not occur in any run
  of this pass; that is one more absence, not evidence.

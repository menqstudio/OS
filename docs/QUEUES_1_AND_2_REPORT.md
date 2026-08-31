# Queues 1 and 2 — one report

Eleven tasks, seven pull requests, **nothing merged**. `main` is `d42cb65` throughout.
All seven PRs are 36 of 36 checks passing.

The two lists that matter are **[Proven](#proven-by-my-own-mutation)** and
**[Claimed](#claimed-and-not-independently-confirmed)**. Everything else is context.

## Per task

| | task | outcome |
|---|---|---|
| **A** | §4, the credential store | **DONE — #207**, then REWRITTEN as a reference store on the Owner's decision: see [the conflict](#the-one-thing-to-decide-before-merging-anything) |
| **B** | the transport seam | **BLOCKED — on a decision, not on work** |
| **C** | T-056, controls name what they prevent | **DONE — #208** |
| **D** | `check_prior_art` re-declaration | **DONE — #209**; the reported defect is not real |
| **E** | the frontend intermittent | **MEASURED, cause not found**; no PR, by instruction |
| **F** | T-057, the fabricated audit rows | **DONE — #210** |
| **G** | re-verification of Queue 1 | **DONE — #211**; it found four things Queue 1 did not |
| **H** | finish what Queue 1 left blocked | **NOTHING TO TAKE.** B is the only blocked item and a decision blocks it |
| **I** | negative matrix | **DONE — #212**; 12 rows moved, 3 mutation-proven |
| **J** | the evidence index | **DONE — #213** |
| **K** | this report | on #213's branch |

## The one thing to decide before merging anything — DECIDED 2026-08-31

**PR #207 introduces the only secret-valued column in the schema, and migration 0022
already forbids exactly that.** `grep -rniE "secret|password|token" core/schema/`
returns `credential_bindings.secret` — mine — and nothing else holding a value. 0022:

> nothing in this table, this process, or this repository may ever hold the secret. The
> desktop is deliberately on the untrusted side of the boundary; a credential that got
> here would be a credential leaked.

Every constraint of Task A was met **as written**, including "state where the bytes
rest". Stating it was the wrong remedy for a repository that had already decided the
desktop holds none. **Recommended:** store an `auth_ref`-shaped reference, reuse
`normalize_auth_ref`, and delete `Secret` / `resolve_secret` from `core`. Cost: most of
#207's storage half is rewritten. **I did not make that change** — the task specified a
value store, and it was the Owner's call.

**The Owner made it on 2026-08-31, and withdrew his own constraint:** *"Ես ենթադրեցի,
որ պահեստ պիտի լինի, ու հարցը միայն թե որտեղ։ Phase 9-ը արդեն որոշել ա, որ desktop-ը
գաղտնիք չի պահում ընդհանրապես։"* The rewrite is on #207: `credential_bindings.auth_ref`
carrying 0022's CHECK, `bind` refusing through the same `normalize_auth_ref`, and no
`Secret` type at all. Every other constraint — digest keying, born unbound, the gate,
the ungated unbind, three call outcomes — is unchanged. Four mutations prove the new
checks; the sweep is in that PR's commit message.

That also unblocks **Task B**: "the transport receives a slot id, never bytes" is now
coherent, because there are no bytes on this side to receive.

## Proven by my own mutation

Each was broken by me, grep-confirmed on disk, confirmed to compile or parse, watched
go red by a **named** test, and restored.

**#207 — 5.** `Secret`'s `Debug` does not reach the value · the approval entity is
scoped to the slot · the Call arm detects a missing binding · an absent binding changes
the refusal · `credential_state` distinguishes absent from present.

**#208 — 10.** The population is globbed and not taken from the registry · an entry
whose file is gone is refused · `blocks: merge` is checked against the REQUIRED set, not
merely against CI · `blocks: nothing` may not understate · a fail-closed check blocking
nothing needs `unenforced_reason` + `tracked_by` · `tracked_by` must resolve · a short
reason is a placeholder · `blocks: nothing` needs a `why` · an unread workflow is a
READING failure and not a verdict · every path in `contracts/index.json` resolves.

**#209 — 1.** `declaration_for` returns the latest.

**#210 — 6.** The seed writes the marker · `activity::map` carries it · `source_of`
reads the key it is given · `source_of` tolerates a malformed payload · the summary
names the seeded count · it says it in every language.

**#212 — 3.** NM-TIME-16 (the lower equality of the step-8a gate) · NM-CONC-05 (a ledger
op inside a caller's transaction is refused) · NM-CONC-06 (the terminal write happens
exactly once — both the idempotent and the divergent limb).

**Queue 1's own sweeps, re-run in Queue 2 and reproduced:** 11 on the egress Call arm,
9 on the lease's `allowed_egress`, 6 on the dispatch, 6 on the ancestry gate, 8 on the
control registry. Those are **Queue 1's** numbers, confirmed by re-running, not by
re-deriving each mutation.

**Total proven by a mutation I wrote myself in Queue 2: 25.**

## Claimed, and not independently confirmed

**Four checks are correct by reading and defended by nothing.** Each survived a mutation
with every test green. Recorded as `T-061`; not fixed, because fixing inside a
verification pass destroys the verification.

1. `credentials::is_bound` does not require the SLOT to match. Queue 1's sweep varied the
   digest and was caught; **no test varies the slot**.
2. `Grant::for_egress`'s credential-slot refusal was never swept at all.
3. `security::map_event` can drop the `source` mark entirely — **proven by mutation**.
4. `Home.tsx` can stop counting seeded rows and the frontend suite stays green.

**And one assertion that cannot fail**, in PR #210:
`both_read_surfaces_carry_the_mark` computes `security::summary`, discards it, then
re-asserts the rows it checked eight lines above. **PR #210's headline — "the mark
reaches the reader" — is therefore half proven.** It reaches `activity::list`. Whether
it reaches `security::summary` or the Home sparkline is asserted by nothing.

**Also claimed and not confirmed:** everything in Queue 1's report that Queue 2 did not
re-measure — the Windows-only CI jobs (no runner here), and #207's conflict with 0022,
which rests on reading two files twice rather than on any new measurement.

## Numbers I was given that turned out different

**One, and it is a measurement difference rather than an error.** Queue 1 reported
**194** gate self-tests; Queue 2 counted **197, with 1 skipped**. Queue 1 counted the
eight modules in the CI list at that commit; Queue 2 counted the same eight **plus**
`test_check_control_invocation` at its final commit, after three parser tests were added
in the same PR. Both are right for what each counted. The skip is named:
`test_roadmap_split`, *"5512d82 is no longer reachable; the fixture is the record"* —
pre-existing.

**Everything else reproduced exactly:** cargo 1104 (#207) and 1092 (#210), engine
2039 OK / 10 skipped, vitest 758 → 761, `tsc` exit 0, and the negative matrix's
242 / 29 / 12 / 201 with the per-domain breakdown matching row for row.

**One number I was given that was right and I doubted:** Task D said
`declaration_for` returns the first record so a re-declaration is never read. Measured:
`declare()` de-duplicates per target, so a target never has two records and the remedy
IS reachable. The *symptom* recorded in my own memory was real; the cause was not.
Corrected in the memory file and in #209.

## Defects found and not opened

| | where | what |
|---|---|---|
| T-061 | four checks across #207 and #210 | correct by reading, defended by no test — listed above |
| T-060 | `check_coordination` | a PR that outlives its own `Last updated` line turns `main` RED on merge |
| T-059 | `check_repo_state` | `main_ci` is stale by construction between merges |
| T-056 | `bro_deploy_preflight`, `check_ai_surfaces` | fail-closed and blocking nothing; both now declared |
| T-062 | the negative matrix | 189 rows still `unreviewed` |
| — | `produce_agent_artifact.rs` doc, lines 4–5 | still says the binary *"claims that run, executes it"*; `run_due` does, and the binary does not call `claim_and_run` |
| — | `contracts/index.json` | three dead `rust_mirror` paths — **fixed** in #208, and the execution lease's is `null` because no Rust file mirrors it |

## What I am unsure of

* Whether §4 should become a reference store or the 0022 boundary should be amended.
  Both are defensible. I recommend the first and did neither.
* The Task E local rate of **0 failures in 50 runs** is on a tree that changed under the
  loop — branches were switched mid-run. I would not quote it as a per-commit figure.
  The live CI capture (`findByRole('dialog')` at **5040 ms**, exactly the
  `asyncUtilTimeout` ceiling) is the stronger evidence, and the cause is **not found**:
  CPU contention is ruled out with a 24× margin, memory pressure and runner
  worker-scheduling are not ruled out and were not measured.
* Whether the 189 rows left `unreviewed` in the matrix contain anything urgent. I did
  not look at them; that is what `unreviewed` means.
* This verification pass is a **second measurement, not a second party.** It is mine.

# Overnight queue, 2026-08-31 — what was done, and what was not

One session, six queued tasks, **nothing merged**. Four pull requests are open and
green; two tasks did not produce one. Every number below was measured in this
session; where a number is a repeat of somebody else's, it says so.

`main` was `d42cb65` throughout, read at the start of each task with
`gh run list --branch main` — seven workflows of seven `success`, `.conclusion`
read rather than inferred, because a cancelled run is not a failure.

## The six

| | task | outcome |
|---|---|---|
| **A** | §4, the credential store | **DONE — PR #207**, and see the flag below |
| **B** | the transport seam | **BLOCKED** — the answer is in the flag below |
| **C** | T-056, controls name what they prevent | **DONE — PR #208** |
| **D** | `check_prior_art.py` re-declaration | **DONE — PR #209**, and the reported defect is not real |
| **E** | the frontend intermittent | **MEASURED — cause not found**, no PR, by instruction |
| **F** | T-057, the fabricated audit rows | **DONE — PR #210** |

All four PRs: **36 of 36 checks pass.** PR #210 needed **one** re-run of the
frontend job — counted here rather than absorbed, and it is the same intermittent
Task E was sent to measure.

---

## The flag that outranks everything else here

**PR #207 introduces the only secret-valued column in the schema, and migration
0022 already forbids exactly that.** Found while starting Task B, on my own work.

`grep -rniE "secret|password|token" core/schema/` returns
`credential_bindings.secret` — mine, from this PR — and nothing else that holds a
value. Migration 0022 states the rule as a boundary:

> **nothing in this table, this process, or this repository may ever hold the
> secret. The desktop is deliberately on the untrusted side of the boundary; a
> credential that got here would be a credential leaked.**

`repo::integrations::normalize_auth_ref` says it a second time in code: *"If it
is unclear whether a value is a reference or a secret, it is a secret, and it is
refused."*

Every one of Task A's five constraints is met **as written** — including "state
where the bytes rest", which is stated in the migration, the module docstring and
`spec-conformance` as `§4: partial`. But *stating it* was the wrong remedy for
this repository: Phase 9 already decided the desktop never holds a credential, so
there is no honest place here for bytes to rest.

**Recommended fix, by name:** `credential_bindings` stores a **reference**, not a
value — rename the column `auth_ref`, reuse `normalize_auth_ref` and the 0022
CHECK so the same refusal applies, and delete `Secret` and `resolve_secret` from
`core` so nothing in the desktop can produce a credential value at all. The
digest keying, born-unbound, the gate, the ungated unbind and the three call
outcomes all survive; only what the slot resolves TO changes.
**Cost:** most of #207's storage half is rewritten, and §4 stays `partial` for a
smaller reason — the engine-side resolution does not exist.

I did not make that change: the task specified a value store, and a decision the
Owner has not given is not mine to guess.

---

## Task B — BLOCKED, and the same finding is why

The constraint was *"the transport receives a SLOT ID, never bytes. If it can see
the secret, the design is wrong — stop and report."*

That constraint is **coherent precisely because of 0022**: the value lives on the
engine/operator side, and a slot resolves to a reference they resolve. With a
value store in the desktop, the transport would have to see bytes — the design
would be wrong for the reason the task anticipated. Building the seam on top of
#207 as it stands would have baked that in.

Nothing was built. `core`'s dependency list is unchanged.

---

## Task E — measured, cause not found

**Local: 50 full-suite runs, 0 failures.** Mean wall 49.5 s; 80 files, 758→761
tests as branches changed.

**Method flaw, stated rather than buried:** the loop ran across branch switches,
so it is not 50 runs of one tree. It measures the suite's stability under
repeated local execution, not one commit's.

**A live capture is the stronger evidence.** The intermittent failed on PR #210's
CI during this session:

```
× GRANT is reachable by the §D `g` key ... 5040ms
TestingLibraryElementError: Unable to find role="dialog"
```

**5040 ms is the `asyncUtilTimeout: 5_000` ceiling `setup.ts` set for T-040.** So
this is a LATENCY failure — `findByRole` waiting out its budget — and not the
T-038 shared-`brops.lang` signature, whose fix (clearing storage per test) is in
place and held.

**Latency of that exact test, measured three ways:**

| condition | duration |
|---|---|
| file alone, idle machine | 50, 50, 52 ms |
| file alone, 2× CPU oversubscription (8 spinners on 4 cores) | 133, 169, 205 ms |
| **full 80-file suite**, 2× oversubscription | 175, 205, 210 ms — 80/80 pass |
| CI, inside the full suite | **5040 ms, gave up** |

**Ruled out:** shared browser state (T-038's cause, fixed and holding); local
repetition (50/50); CPU contention alone at 2× oversubscription, which leaves a
24× margin under the ceiling.

**Not ruled out, and I have not measured any of these:** memory pressure or swap
on the runner; vitest worker-pool scheduling on a 2-core hosted runner against my
4; a specific interleaving the 50 local runs did not hit.

**Cause not found.** I did not raise the ceiling: `setup.ts` argues, correctly,
that a generous ceiling hides a real slowdown, and choosing between "the ceiling
is wrong" and "the latency is wrong" is a decision, not a measurement.

---

## Defects found and not opened, per R8

1. **§4 versus migration 0022** — above. **DECIDED by the Owner on 2026-08-31:** rewrite §4 as an
   `auth_ref` reference store. Done on PR #207; `Secret` and `resolve_secret` are gone from `core`.
2. **`tools/check_ai_surfaces.py` calls itself fail-closed and blocks no merge** —
   its context is not among the 33 required. Declared in
   `config/control-invocation.json` with a written reason; making a context
   required is branch protection, the Owner's act. `T-056`.
3. **`engine/tools/bro_deploy_preflight.py`** — zero non-test callers, named 3×
   in `engine/docs/OPERATOR_RUNBOOK.md`. Same declaration. `T-056`.
4. **`tools/check_produced_artifact.py`** — the T-055 five-conditions gate runs
   under a context nobody requires, so its failure blocks nothing. Declared.
5. **No Rust file mirrors the execution lease.** `contracts/index.json` claimed
   one at a path that never existed; set to `null` with the reason, in PR #208.
6. **`T-060` (new row): a PR that outlives its own `Last updated` line turns
   `main` red on merge.** The coordination gate compares the claimed date with
   the committer date of the newest commit touching `PROJECT_STATE.md`, and a
   squash merge makes that the MERGE date. PR #207 would have done it tonight;
   the date is bumped there. It is the same family as `T-059`: a gate whose
   verdict depends on WHEN it runs rather than on the code.
7. **`T-059` remains open and is why `check_repo_state` is red between merges.**

## Things I am not sure of

- Whether the Owner wants §4 reworked to a reference store or wants the value
  store kept with the 0022 boundary amended. Both are defensible; I recommend the
  first and did neither.
- Whether `activity::source_of` returning `None` for an unreadable payload is
  right if a second writer of that key ever appears. It is safe today because
  `seed` is the only writer; the comment says where that stops being true.
- The Task E local rate is `0/50` on a tree that changed under it. I would not
  quote it as a per-commit figure.

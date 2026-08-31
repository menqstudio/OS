# NINTH independent audit — `main` @ `5cf9b8c`

**Auditor:** Architect session, role-only. I did not write any of the code judged here, and the only
files I have written in this tree are this report and the coordination documents the
Continuous-Documentation Law requires in the same commit.

**Date:** 2026-08-19 · **Verdict: RED** · **No P0.**

---

## 1. The pin, proved before anything was read

`main` has moved mid-audit before — the fourth round records how it was caught — so the pin is
proved rather than asserted, on a clean worktree, before the first file was opened:

```
$ git rev-parse HEAD
5cf9b8cba9860807bb7e15ec3dec2e6a91f3dea8

$ git rev-parse 5cf9b8cba9860807bb7e15ec3dec2e6a91f3dea8^{tree}
9580b86deffb7be00cac18716f18ae33bc318a3a

$ git status --porcelain
(empty)

$ git write-tree
9580b86deffb7be00cac18716f18ae33bc318a3a

$ git log -1 --format='%H %T %ci %s'
5cf9b8cba9860807bb7e15ec3dec2e6a91f3dea8 9580b86deffb7be00cac18716f18ae33bc318a3a
2026-08-19 18:33:08 +0400 Settle at main d0bddc4 — block A is closed (#162)
```

Head, `^{tree}` and `write-tree` all agree, and both trees equal the pinned
`9580b86deffb7be00cac18716f18ae33bc318a3a`. Every read, run and mutation below ran against that
tree.

**Mutations were applied to the shipping source and restored byte-exact.** Every mutated file was
digested before mutation and re-digested after restore, and `git write-tree` was re-run at each
restore point and re-produced `9580b86…` — the last check appears at the end of §6. No mutation was
committed.

---

## 2. P0 — the production gate

**No P0. All three refusals are closed at this head.** Read at the source, not taken from the
ledger:

| Refusal | Where | State at `5cf9b8c` |
|---|---|---|
| `governed_verification_unconfigured()` | `apps/desktop/src-tauri/src/commands.rs:1305-1308` | **Closed.** The body is `Some(GOVERNED_VERIFICATION_UNCONFIGURED)` with **no branch**. Fires before the model is called. |
| `connect_broker()` | `apps/desktop/src-tauri/src/governed_turn.rs:230-253` | **Closed off Linux.** `#[cfg(not(target_os = "linux"))] { Err(BrokerAccessError::UnsupportedPlatform) }` at `:251`. |
| `build_governed_executor` | `apps/desktop/src-tauri/broker/src/main.rs:256-280` | **Closed.** `BROPS_BROKER_CONFIG` unset or empty ⇒ `fail_closed()` ⇒ `UpstreamBlockedExecutor`. |

Two further checks, because the third refusal is conditional and the condition is the whole claim:

* **Nothing in the tree sets `$BROPS_BROKER_CONFIG`.** A repo-wide search for
  `set_var("BROPS_BROKER_CONFIG` / `export BROPS_BROKER_CONFIG` / `BROPS_BROKER_CONFIG=` over
  `*.rs *.sh *.ps1 *.yml *.py *.json *.toml` returns **zero** matches. Every occurrence is a reader
  or a comment. `tauri.conf.json` declares no `externalBin` and no `resources`.
* **`AnswerProvenance::Governed` is constructed nowhere in production.** It appears once as a
  construction, at `commands.rs:2990`, inside `#[cfg(test)] mod tests` — which opens at `:2724` and
  runs to the file's only column-0 closing brace at `:3230` (the file is 3230 lines). The two
  production construction sites are `DevelopmentUntrusted` (`:2283`) and `Ungoverned` (`:2328`).

The gate is shut and nothing this cycle moved it.

### 2.1 Second pass — the questions the three-refusal check does not ask

The three refusals are the documented gate, and checking them is not the same as checking that the
gate has no way around it. Challenged on the P0 verdict, I re-attacked it along four vectors the
first pass did not cover. **The verdict is unchanged and the evidence is now four locks deep.**

**(a) Does every governed surface actually reach a refusal?** The pre-flight's own doc comment says
*"the three governed surfaces"* while `NEXT_CHAT.md` §1 and `CLAUDE.md` §3 both say **four** AI
surfaces. Four command definitions exist — `stream_reply` (`:1638`), `stream_run_step` (`:1794`),
`stream_ask` (`:2129`), `reply_in_conversation` (`:2346`) — and there are only **three**
production call sites of `governed_unconfigured_block` (`:1532`, `:2007`, `:2214`), the last of
them *above* `reply_in_conversation`. That is the shape a hole has.

It is not one. `:1532` sits inside `run_governed_conversation_turn` (`:1490`), and **both**
`stream_reply` (`:1670`) and `reply_in_conversation` (`:2372`) call it. Four surfaces, three
pre-flights, no uncovered surface. `tools/check_ai_surfaces.py` independently reports *"4 classified
surfaces; every provider-invoking command is accounted for … no 'governed' surface reaches a generic
provider entry."*

**(b) Is `NoTrustedManifest` what production actually wires?** Yes, at every verify site:
`commands.rs:1578`, `:2053`, `:2273` and `ai.rs:4611`. There is no second authority in the shipped
paths.

**(c) Two shipped `#[tauri::command]`s run the real in-process crypto chain.** This is the vector
the first pass missed entirely. `governed_trust_selftest` (`governed_selftest.rs:156`) and
`demonstration_verified_reply` (`commands.rs:2681`) both call
`brops_win_live::proof::in_process_turn_produce`, and `governed_selftest.rs:162` surfaces
`production_verified: outcome.production_verified` to the webview — **passed through from the chain,
not hardcoded false.** So the honesty of the whole thing rests on what that chain resolves to.

It resolves to demonstration custody **by type**. `proof.rs:256-261` builds the anchor as
`provenance: RootProvenance::Demonstration`, hardcoded, with the root's private seed five lines above
it in the same source file — and the comment says why that is the point: *"its private half is the
seed two lines above, in this source file … which is why this proof can never render `Production`
however completely the chain runs."* `verify_manifest_anchored` carries that provenance into the
token, `resolve_trust_state` splits on it, and `is_production_verified()` is
`matches!(self, TrustState::Production { .. })`. `proof.rs:499-500` asserts `!production_verified`,
and the comment records that the assertion *"used to be the opposite way round."* I ran it:
`cargo test -p brops-win-live --lib proof::` → **7 passed**.

**(d) Can anything shipped mint the provenance that would open it?** `RootProvenance::External` is
the only value that yields `TrustState::Production`. Every construction of it in the tree is either
`#[cfg(test)]` (`production_trust.rs`, `key_manifest.rs`) or a `RootProvenance::parse` of a
**deployment config** inside a live-kit binary (`win_live_turn.rs`, `live_turn.rs`, `ladder_turn.rs`,
`win_provision.rs`). **No shipped desktop code path constructs it.** Production trust is unreachable
by the type system, not only by an unset environment variable.

**One thing worth stating rather than leaving implied.** On a Windows build,
`governed_trust_selftest` does return the literal string `"trusted_verified"` to the webview when
`outcome.bound` is true (`governed_selftest.rs:161`), beside `production_verified: false` and
`demonstration_custody: true`. That is the documented demonstration badge, not a production claim,
and the honesty machinery around it is real and tested — `TrustSelftest.tsx:86` renders the custody
flag, and `Conversations.test.tsx:34` pins *"maps demonstration_custody to the demo badge — never the
production green."* It is not a P0. It is recorded because it is the one place in the shipped app
where the production vocabulary appears on a surface a person can reach, and a future edit that drops
the custody flag beside it would turn a labelled demonstration into an unlabelled one.

---

## 3. Promotion table — the nine Builder claims

Nine claims landed in PRs #153–#162, every one marked ◑. **Six earn ✅. Two are REOPENED. One is
not promoted.**

Where a row says **read**, I read the code and did not re-take the measurement. A mark that says
read is worth more than one that pretends.

| Claim | Verdict | The measurement I performed |
|---|---|---|
| **A-09** — smuggle routes 2 and 3 closed; route 1 replaced by a declared eight-leaf free-text register | ❌ **REOPENED** | Routes 2 and 3 **are** closed and I could not reopen them: reverting the widened `key` family turns 2 tests red, reverting `flatten` to string-only turns 3 red. **Route 1's replacement does not hold.** Three measurements in §4.1: a 64-hex credential rides in a leaf the register calls *shape-constrained*; the decode window is escaped by one out-of-range byte; and **deleting three of the eight register entries leaves all 10 tests green.** |
| **T-037** — REST second road has 14 tests; slug resolved-or-refused; the `][` branch was broken, not inert | ✅ | `RestSecondRoad` carries exactly **14** `def test_`; the module totals **88**, and CI's own invocation (`python -m unittest test_check_repo_state`, `ci.yml:826`) runs all 88. Slug refusal mutation-verified: making `_repo_slug()` fall back to `_REPO_FALLBACK` instead of returning `None` turns **7** tests red. The `][` claim re-derived directly: `'[{"number":1}][{"number":2}]'.replace("][", "],[")` → `json.loads` raises `JSONDecodeError: Extra data`, so the branch written to defend that shape turned it into a refusal; `_json_documents` reads it correctly and **raises** on a partial document. New finding `I-05` attached — see §4.2. |
| **T-039** — both candidate causes eliminated by measurement; refusal instrumented, no retry added | ✅ | `cargo test -p brops-win-live --lib` → **108 passed**. Instrumentation mutation-verified: replacing the diagnostic `format!` with a bare `{e}` turns `an_unreadable_counter_refuses_AND_says_enough_to_diagnose_it` red — and the mutant's output is the original ambiguous `Access is denied. (os error 5)`, which is the state the ticket exists to leave behind. No retry: `read_hint` (`head_sequence.rs:56-59`) returns `Ok(0)` only for `NotFound` and refuses every other error; the only loop in the file is the `create_new` slot walk. **The elimination half is read, not re-measured** — I did not re-run the 200/40 local runs, the ~27 000-read rename race, or the `share_mode(0)` probe, and the CI failure does not reproduce on this box. |
| **T-034** — a live WCAG AA defect fixed; contrast gate 28 → 56 pairs | ❌ **REOPENED** | The gate widening is real and exact: 14 → **28** pair entries × 2 themes = **56** checks, GREEN. Re-derived independently with my own WCAG implementation and then with the gate's own `contrast_ratio()`: dark worst = **4.62** (claim: 4.62), and all five pre-fix numbers reproduce to 2dp (accent 4.34, info 3.83, success 3.85, warning 3.83, danger 3.81). **But two of the fourteen added pairs are below AA and pass only on a rounding rule** — see §4.3. |
| **T-035** — the proposed theme axis is vacuous and was deliberately not shipped | ✅ | Not shipped, measured: `pages.browser.spec.tsx:425` is `const STATES: State[] = ['pending','settled','unreachable']` — three states, no theme dimension. Vacuity confirmed structurally: `grep -c data-theme theme/aios.css` → **1**, and that single block (`:root[data-theme="light"]`, `:70`) declares **nothing but custom properties and `color-scheme`**, so no rule can match differently between themes. The five opacity tokens it names (`--aurora-op --mesh-op --grid-op --scan-op --grain-op`) are all inside it. |
| **T-036** — default-state fixtures, vocabulary compile-enforced; populated deliberately not in STATES | ✅ | Compile-enforcement mutation-verified: restoring the exact wrong vocabulary the ticket describes (`lvl('L2')`, `approvalState('granted')`) produces **two `tsc` errors** — `TS2345 '"L2"' is not assignable to 'ApprovalLevel'` and `'"granted"' … 'ApprovalStatus'`. The four vocabulary claims check out against `domain/enums.ts`: `ApprovalLevel` is `A0\|A1\|A2\|A3`, `Priority` has no `medium`, `ApprovalStatus` no `granted`, `TaskStatus` no `in_progress`. `populated` is absent from `STATES`. The tier finding re-measured: `.v-approvals .tier-A3` exists (`aios.css:996`, `:1260`) and **no `.tier-A0`/`.tier-A1`/`.tier-A2` rule exists anywhere**, against markup that applies `` `tier-${a.level}` `` — three of four levels genuinely render untreated. Browser suite **323 passed**. New finding `I-11` attached. |
| **T-023** — the refusal names the ACE; the cause is an INHERITED ACE; fixed in the harness | ◑ **NOT PROMOTED** | I agree with the brief: this rests on one green run of an intermittent job and must not be promoted. What I could check, I checked **by reading**: the ACE dump is real (`bro_custody.py:762` `inherited = bool(header.AceFlags & 0x10)`, `:768` emits `INHERITED` / `APPLIED DIRECTLY`), and the `ci.yml` harness fix is real (`:495-513` — `/inheritance:r` + `/grant:r` by SID, `$env:USERNAME` deliberately ungranted, and a re-read that throws if `Authenticated Users` or `Everyone` survive). What I **cannot** check: the cause and the fix both live on the GitHub runner's `_temp` ACL, which no local box reproduces, and the job is in `deliberately_excluded`, so CI will not gate it either. The Builder's own row says it stays open until the job runs clean across several PRs. It stays ◑. New finding `I-08` attached. |
| **T-033** — 1 185 unreachable rules deleted, 33% → 8%, bundle 345 → 218 kB | ✅ | Every headline re-derived. `python tools/count_dead_classes.py` → **“136 of 1799 … (8%)”**, exact. `aios.css` selector blocks against `be525bf^`: **3 194 → 2 009**, delta **1 185**, exact. Bundle: the `dist/` on this box predated the deletion, so I **rebuilt** — `npm run build` (which is `tsc --noEmit && vite build`) exits 0 and emits `index-CIV_2Ktx.css` at **218 518 bytes = 218.52 kB**, exact. One number is off, in the understating direction: the deleted source measures **157 115 bytes (157.1 kB / 153.4 KiB)**, not the “147 KB” claimed. New finding `I-12` attached. |
| **T-038** — the load-flake is localStorage leaking between files, not slowness | ✅ | **Cause reproduced deterministically.** Replacing the clear in `test/setup.ts` with a seed of `brops.lang='hy'` reproduces the reported signature exactly: `Approvals.test.tsx:101` fails on `getByText(/native confirmation the app window cannot forge/i)` while line 100's `findByRole('dialog')` resolves — plus `DENY routes through the real fail-safe reject command` at `:155`, the second test the ticket names. (I observe **three** failures, not two; the account undercounts by one, in the understating direction.) **And the brief's question is answered by measurement, not argument:** running the full suite with the `beforeEach` deleted fails **exactly one** test in 739 — the one written to pin it. Nothing else in the suite depends on storage being clean, so the fix hides no previously meaningful assertion. `LS.get` runs in a `useState` lazy initialiser (`app/store.tsx:96-97`), i.e. at mount, so the clear genuinely reaches it. Baseline: **739 passed / 79 files**. |

**Score: 6 ✅ · 2 REOPENED · 1 held at ◑.**

---

## 4. New findings

### `I-01` (P2) — A-09's register calls a credential carrier "shape-constrained"

`agentsDispatch.boundary.test.ts:157-171` states the property the fix rests on: *"these — and only
these — are places a credential could ride."* That sentence is false.

`SHAPE_CONSTRAINED` classifies nine leaves by `isContractId`, whose pattern is
`^[a-z0-9][a-z0-9._-]{1,127}$` — **128 characters of lowercase alphanumeric with separators**, which
is a perfectly good credential alphabet. `buildAssignment` puts caller input through `slug()`
(`agentsDispatch.ts:189-191`), which lowercases and joins with `-`; a lowercase hex secret survives
that unchanged.

Driven through the real `buildAssignment` / `attemptDispatch` with the file's own helpers:

```
taskId = 'a3f1c9d47b2e8054f6a1b9c3d7e250184c6b9f2a3d5e7081b4c6a9f2d3e50718'

flatten(sent) contains the secret verbatim          → true
register reports undeclared leaves                  → []        (nothing)
FORBIDDEN sweep offenders                           → []        (silent)
```

Route 4, through a leaf the register declares safe. The same applies to `contract_draft.pack_id`,
`agent_id`, `core_skills`, `additional_skills`, `reference_skills`,
`verification.verifier_agent_id` and `pack_role_reference`.

This is not the undecidability route 1 correctly declines to solve. Route 1's honest statement is
"we cannot tell a token from a sentence in free text." This is different: the register **asserts a
bound it does not have**, because it treats "matches a permissive id pattern" as "cannot carry a
credential."

### `I-02` (P2) — three of the eight register entries are never exercised, and deleting them is green

The register test drives one fixture, `BASE`. `leafPaths` drops `null` (`:122`) and an empty array
contributes no leaf, and `BASE` sets `verifierRole: null`, `verifierAgentSlug: null`,
`verificationCommands: []` and no `rollbackCommands`. So:

```
EXERCISED (5): contract_draft.title, .objective, .assignee_role, .done_criteria, .rollback.strategy
NEVER PRESENT (3): contract_draft.verification.verifier_role,
                   contract_draft.verification.commands,
                   contract_draft.rollback.commands
```

The test asserts *every present leaf is declared*; it never asserts *every declared leaf is
present*. **Mutation: deleting all three unexercised entries leaves the file at 10 passed / 10.**
Deleting `rollback.strategy`, which the fixture does populate, turns 2 red. So the "declared
eight-leaf register" is a declared five-leaf register with three entries nothing checks, and the
promise that "a ninth field turns the suite red" holds only for a ninth field that `BASE` happens to
populate.

### `I-03` (P3) — the decode window is escaped by a single out-of-range byte

`decodeCharCodes` (`:94-102`) returns `null` unless **every** element is in `0x20`–`0x7e`. Appending
one byte outside it defeats the whole decode:

```
bytes = [...'lease-7f2a91'.charCodes, 0x0a]
flatten contains 'lease-7f2a91'   → false
FORBIDDEN offenders               → []
```

The fix closes the auditor's literal proof-of-concept and nothing adjacent — a newline, a tab, or
any byte ≥ 0x7f walks past it. Worth stating because the brief asked whether `0x20`–`0x7e` is the
right window: it is the right window for the one example that was published.

### `I-04` (P2) — `check_contrast.py` decides an accessibility verdict on a rounded number, and two shipped pairs are below AA

`tools/check_contrast.py:158-162`:

```python
# Round to 2dp for stable reporting; compare on the rounded
# value so a printed 4.50 is never reported as a failure.
ratio=round(ratio, 2),
threshold=threshold,
passed=round(ratio, 2) >= threshold,
```

Using the gate's **own** `contrast_ratio()` on the light palette against the `selected` tint:

| pair | raw ratio | `>= 4.5` raw | rounded | gate verdict |
|---|---|---|---|---|
| `accent-on-selected` | 4.509728927475 | ✔ | 4.51 | pass |
| **`info-on-selected`** | **4.499621964567** | ✘ | 4.50 | **pass** |
| `success-on-selected` | 4.543362936489 | ✔ | 4.54 | pass |
| `warning-on-selected` | 4.516447132623 | ✔ | 4.52 | pass |
| **`danger-on-selected`** | **4.499490555793** | ✘ | 4.50 | **pass** |

**Mutation, one character of intent:** change `passed=round(ratio, 2) >= threshold` to
`passed=ratio >= threshold` and the gate goes RED on exactly those two:

```
RED: 2 text pair(s) below WCAG AA:
  XX danger-on-selected  light #c6314a on #e7ebff  4.50:1  (need 4.5 · normal)
  XX info-on-selected    light #246bc0 on #e7ebff  4.50:1  (need 4.5 · normal)
```

Both are pairs **T-034 itself added**, on the `selected` composite **T-034 itself recomputed**, in
two of the five colours **T-034 itself re-tuned**. The re-tune aimed at the floor and landed
0.0004 and 0.0005 under it, and the tolerance introduced for tidy reporting is what turns that into
GREEN. The report even prints `4.50:1 (need 4.5)`, which reads as passing — which is why nobody saw
it.

This is why T-034 is REOPENED rather than promoted with a caveat: the claim under attack is
literally *"a live WCAG AA defect fixed"*, and a live WCAG AA defect is what remains.

### `I-05` (P3) — `unittest.main()` sits four lines above the class it is supposed to run

`tools/test_check_repo_state.py`:

```
:510   if __name__ == "__main__":
:511       unittest.main()
:514   class RestSecondRoad(unittest.TestCase):
```

Run the file the obvious way and `unittest.main()` executes — and exits — before `RestSecondRoad`
is defined:

```
$ python tools/test_check_repo_state.py       →  Ran 74 tests ... OK
$ python -m unittest test_check_repo_state    →  Ran 88 tests ... OK      (CI's form, ci.yml:826)
```

**CI runs all 88, so T-037's 14 tests are genuinely wired and the claim stands.** But the file's own
entry point silently runs 74 of 88 and prints `OK` — and the 14 it drops are exactly the ones added
because that code had no coverage at all. A developer checking T-037's work the direct way is told
it passes without running any of it.

### `I-06` (P2) — the machine mirror's prose is three PR generations stale and contradicts its own field

`config/current_state.json` is called, in five canonical documents, the file that *cannot quietly
drift* because `tools/check_repo_state.py` verifies it against live GitHub. Two of its fields have
drifted anyway:

* `purpose`: *"STATE: settled. main is at settled_at_main_head **(b3010f6)**"* — while
  `settled_at_main_head` in the same file is `d0bddc42c984e37407b0f6990c2051e8daee65c5`. The
  parenthetical contradicts the field it cites, in the same sentence.
* `sync.live_main_resolution`: *"live main is b3010f6 (PR #81 merged, 2026-08-09) … the only open
  pull request is the self-carrier **#82**"* — the carrier is #162, and `sync.verification` in the
  same object says so.

`check_repo_state.py` is GREEN because it reads `settled_at_main_head` and `prs[]` and compares
those to GitHub. It does not read `purpose` or `live_main_resolution`. So the drift-proof file has
free-text fields that drift, in the file every reader is told to trust over the prose documents.

### `I-07` (P3) — the roadmap status board disagrees with its own checkboxes on exactly the two phases that matter

Counted from `MASTER_EXECUTION_ROADMAP.md` at this head:

| Phase | Board cell | All checkboxes (DoD + Task) | DoD only (the gate's view) |
|---|---|---|---|
| 3 | 11/11 | **11/11** ✔ | 5/5 |
| 4 | 12/12 | **12/12** ✔ | 5/5 |
| 5 | 11/11 | **11/11** ✔ | 5/5 |
| 6 | 10/10 | **10/10** ✔ | 5/5 |
| 7 | 8/8 | **8/8** ✔ | 4/4 |
| **8** | **8/10** | **7/9** ✘ | 3/5 |
| **9** | **8/9** | **7/9** ✘ | 4/5 |

Phases 3–7 establish the board's convention: it counts all checkboxes in the phase. Phases 8 and 9
are the only two where the board disagrees with that convention — and they are two of the five
phases the Builder says are blocked.

Whole-roadmap totals: **92/115** by checkbox, **44/56** by Definition-of-Done. The claimed
**94/117** is neither, and the string `94/117` appears **nowhere in the tree and nowhere in
`git log --all -S`**. `tools/check_roadmap_order.py` is GREEN because it compares *completeness as a
boolean* (`dod_state` vs `board_state`), never the printed fractions — so no gate has ever read
those two numbers.

### `I-08` (P3) — `required-checks.json` names the wrong pull requests for T-023

`config/required-checks.json` → `deliberately_excluded` → the trust-provisioning job:
*"observed on PR #125, #132 and **#148**"*. Both other sources say otherwise:
`ci.yml:474` says *"#125, #132, #155 and #157"* and `TASKS.md`'s T-023 row records #125, #132, then
*"THIRD OCCURRENCE … on PR #155"* and *"FOURTH OCCURRENCE … on PR #157"*. `#148` is in none of them.

This is the file `H-04` created so that a protection claim would be *checkable*. The context list is
machine-compared; the exclusion **reasons** are not, so a wrong occurrence history sits inside the
artifact built to stop exactly that.

### `I-09` (P3) — the ledger routes the eighth round's §E finding to the wrong ticket

`AUDIT_LEDGER.md:139` files *"The browser suite measures 16.1% of the styled design system"* as
`◑ Open — T-039`. That finding is `T-036` (`TASKS.md:2650`, which carries the same sentence
verbatim). `T-039` is the Windows `head_sequence` flake and has nothing to do with it. A reader
following the index of record from the eighth audit's §E lands on an unrelated ticket.

### `I-10` (P3) — the gate counts in the onboarding documents are stale again

`START_HERE.md`: *"19 `check_*.py` files exist; 18 are wired into workflows."* Measured at this head:
**22 files exist; 19 are wired.** `docs/ARCHITECTURE.md`'s CI cell says **18** gates. Both were
corrected on 2026-08-14 and have drifted by three since. Minor, but this is the paragraph that
teaches a new session what a full gate run should look like, and it is the second consecutive round
in which it is wrong.

### `I-11` (P3) — T-036's vocabulary enforcement stops where the entity type says `string`

The typed accessors bind only fields that have a real union in `domain/enums.ts`. Fixture values
whose entity field is declared `string` route through no accessor and are bare literals:
`status: 'accepted'` (`pages.browser.spec.tsx:203`), `status: 'open'` (`:245`), and the
`kind:` values at `:195`, `:216`.

```ts
export interface Decision {
  ...
  status: string;      // domain/entities.ts
}
```

`0002_decisions.sql:6` is `status TEXT NOT NULL DEFAULT 'proposed'` with no CHECK. So for these
fields there is no enum, no constraint and no accessor — the exact shape that let `Approval.level:
string` admit `'L2'` and produce sixteen wrong values in the first draft. The claim "the canonical
vocabulary is compile-enforced" is true of the enumerated fields and not of these.

### `I-12` (P3) — `check_bundle_budget.py` certifies whatever is in `dist/`, however old

The `dist/` present on this box was built at 16:38; T-033's deletion committed at 18:04. The gate
read the stale artifact and reported GREEN:

```
before rebuild:  GREEN: ... (index 151.6/156 KB)
after  rebuild:  GREEN: ... (index 133.0/156 KB)
```

Same gate, same tree, an 18.6 KB difference decided entirely by when someone last ran `vite build`.
`dist/` is git-ignored, so this is not tree state — but the gate has no freshness check and cannot
tell a bundle that corresponds to the source from one that does not. T-033's own verification line
cites `check_bundle_budget` GREEN as evidence for a bundle-size claim, which is the reading this
gate cannot support on its own.

---

## 5. The percentages — the claim that no box is closable by a Builder change

The Builder asserts Phases 1, 2, 8, 9 and 10 are blocked by the production gate (§0.1's seven
distinct OS service principals, the root-owned setuid launcher, an audited Windows broker) and by
deployment, not by any Builder change, and that the total is unchanged at 94/117.

**The blocking argument holds for 21 of the 23 open boxes.** I read
`WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md` §0.1 (`:287-311`), §0.W (`:313-355`) and §2.6 (`:533-577`)
and they say what is claimed: §0.1 requires all five primitives including
`verify_distinct_principals()` over the seven UIDs; §0.W keeps the gate false on Windows until a
separately-audited broker exists; §2.6 makes the seven-principal separation the linchpin. The
Phase 1/2/8/9 boxes are the approval-**request** path and governed automation dispatch (`T-021`,
`T-022`), which need an engine schema behind that gate. That is honest.

**Two boxes are not blocked by any of it, and that is the finding:**

* `Phase 10 L1738` — *"`contracts/` finalized as the single source; duplicates deleted; versioned"*
* `Phase 10 L1747` — *"`contracts/` final dedupe (lease/approval/task-contract/mode-grant) + versioning"*

`contracts/` at this head is a **single 3 012-byte `README.md` and nothing else**, while
`engine/schemas/` holds 21 schemas and `engine/contracts/` holds 3. `docs/ARCHITECTURE.md` states
the position itself: *"`contracts/` is still a placeholder — a README describing intent, no
extracted schemas … Principle 2 says the engine is authoritative, and today that is true by
convention rather than by a shared file."*

Extracting those schemas needs no service principal, no setuid launcher, no Windows broker and no
deployment. It is a Builder change that has not been made. Calling it "blocked by the production
gate" is the category the brief asked me to look for: a Builder declining work under a blocker that
does not apply to it.

Two further observations on the arithmetic rather than the blocking:

* **The total is not 94/117.** It is 92/115 by checkbox and 44/56 by Definition-of-Done (`I-07`).
* **`Phase 1 L782` can never be ticked by construction** — *"Update `PROJECT_STATE.md` + this
  roadmap when each slice lands. **Standing — never permanently ticked**"* — yet it sits in the
  denominator. A denominator containing a box that is definitionally unclosable makes the
  percentage unable to reach 100 for a reason unrelated to the work.

---

## 6. The 56 classes left unfixed — honest, or work declined?

`T-036`'s 24 and `T-033`'s 32 are recorded as design decisions. **I judge that honest for the 32 and
partly evasive for the 24**, and the difference is whether a decision is actually required.

* **T-033's 32 live-but-unreachable classes** — `accent cap cited cleared editing …` — genuinely
  need a design call per class: give the class a rule, or drop the unreachable requirement from the
  selector trapping it. The row says so, names all 32, and says `unstyledClasses` cannot see them
  and why. Deciding thirty-two of those from a test log would be inventing a design. Honest.
* **T-036's 24** are not all the same. Most are unbuilt surfaces. But `tier-A1` and `tier-A2` are
  not a design question: `.tier-A3` **already exists** at `aios.css:996` and `:1260`, so the design
  is settled and three of four approval levels are simply missing it. That is a Builder change of
  two selectors, and it is being carried under a heading that says a decision is owed. The row is
  candid about the measurement — it says *"`.tier-A3` IS styled, so three of the four approval
  levels get no tier treatment"* — and then files the whole set behind one blanket reason.

Neither is a fabrication, and both are stated in the file rather than hidden, which is why this is a
§6 note and not a numbered finding. But "the 24 are a design decision" is doing work for at least
two classes where the design already decided.

**Tree state at the end of the run**, after every mutation was restored:

```
$ git status --porcelain
(empty)
$ git write-tree
9580b86deffb7be00cac18716f18ae33bc318a3a
```

Byte-exact restore digests were re-verified per file:
`agentsDispatch.boundary.test.ts` `1fc9d574…`, `check_repo_state.py` `96e7b8e0…`,
`test/setup.ts` `61c8c371…`, `pages.browser.spec.tsx` `daccaa28…`,
`head_sequence.rs` `86e21c12…`, `check_contrast.py` `18388244…`.

---

## 7. What ran

| Suite / gate | Result |
|---|---|
| Frontend unit (`npm test`) | **739 passed / 79 files** |
| Browser (`vitest.browser.config.ts`) | **323 passed / 4 files** |
| `tsc --noEmit` + `vite build` | clean, exit 0 |
| `cargo test -p brops-win-live --lib` | **108 passed** |
| `python -m unittest test_check_repo_state` | **88 passed** |
| `tools/check_*.py` (22 files) | **19 GREEN**, 3 print usage (`check_canonical_sync`, `check_prior_art`, `check_read_receipt` — they take arguments) |

**CI GREEN is not audit GREEN, and none of the above is why this verdict is RED.**

---

## §E — what nothing in the repository can see

**1. The two sub-AA pairs cannot be caught by anything currently in the tree.** `I-04` is invisible
to `check_contrast` by construction (it is the rounding), and the browser suite's three detectors —
`invisibleContent`, `clobberedMotion`, `unstyledClasses` — measure opacity, animation names and
selector coverage. **Not one of them measures colour.** `T-034` says so about `aios.css` and the
same hole covers `--menq-*`: the only contrast measurement in this repository is the static gate,
and the static gate is the thing that is wrong. The 95 `aios.css` light-theme violations `T-034`
records are in the same blind spot, and they are recorded as a number in a task row rather than as
a check.

**2. The `selected` composite is modelled over one base surface, and the app paints more than one.**
`contrast-pairs.json` flattens `rgba(56,86,254,0.12)` over `surface` only. Composited over `bg`
instead, the light theme loses five foregrounds at once:

| fg | over `surface`/`elevated` (`#e7ebff`, modelled) | over `bg` (`#dee3f9`, not modelled) |
|---|---|---|
| accent | 4.51 | **4.19** |
| info | 4.50 | **4.18** |
| success | 4.54 | **4.22** |
| warning | 4.52 | **4.19** |
| danger | 4.50 | **4.18** |

and in dark, `selected` over `elevated` (`#2c3350`) drops accent to **4.19** and danger to **4.40**.
Whether any page actually paints a selection tint over `bg` or `elevated` is a question no artifact
in this repository answers — the composite is a hand-computed hex in a manifest, and nothing binds
it to a rendered element. I did not drive a browser to find out; that is the measurement this leaves
open, and it is the same shape as the defect T-034 just closed one level down.

**3. Whether T-023's fix works is unknowable from any tree at any head.** The inherited ACE comes
from the GitHub runner's `_temp`, no local box reproduces it, and the job is in
`deliberately_excluded` so no required check will ever gate it. The repository cannot distinguish
"fixed" from "has not recurred yet," and it will not be able to until someone counts clean runs
across several pull requests. That is not a defect in the fix; it is a property of the evidence, and
it is why the row must stay ◑ no matter how good the patch looks.

**4. The eight-leaf register's real weakness is a fixture, and no gate reads fixtures for coverage.**
`I-02` is invisible because the only thing that could catch it is a test asserting that every
declared entry is exercised — the inverse assertion — and nothing in this repository writes that
shape. The same blind spot produced `G-07` (a gate pointed at 2 surfaces out of 24) and
`ENTRANCE_CLASSES` (2 classes out of 14). This is the third instance of one pattern: **a
declaration that is checked in one direction only.**

**5. Nobody has audited the audit brief.** Two of the attack targets I was handed were misfiled —
the `0x20`–`0x7e` decode window is A-09's, not T-036's, and the ledger sends the browser-suite
finding to T-039 (`I-09`). Both errors are small and both point the same way: the cross-references
between the ledger, the task board and the round briefs are hand-maintained, there are now nine
rounds of them, and `check_audit_reports.py` verifies that cited *reports exist* — not that cited
*findings match the tickets they name*.

---

**Verdict: RED.** No P0; the gate is shut and was not moved. Six of nine claims earn ✅. `A-09` and
`T-034` are REOPENED, and `T-034` is reopened on a live WCAG AA defect that the gate built to catch
it reports as GREEN. `T-023` stays ◑ on evidence that no head can settle.

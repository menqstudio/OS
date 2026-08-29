# BroPS Audit Ledger · desktop + engine

> **Why this file exists (audit D-06/D-07):** the security tickets under `apps/desktop/AUDIT/tickets/`
> and `engine/AUDIT/tickets/` carried **no status/resolution field**, so a fixed finding and a forgotten
> one looked identical, and the desktop tickets were referenced from **nowhere** outside their own folder
> (orphaned). This ledger is the single index of record: it links both ticket sets, points at the current
> authoritative assessment, and records the status the Builder can evidence. It does **not** invent a
> status it cannot back — anything not individually re-verified is marked so, with the independent audit
> as the live source of truth for current-code behaviour.

**Authoritative current assessment:** [`2026-08-19-ninth-audit-5cf9b8c.md`](./2026-08-19-ninth-audit-5cf9b8c.md)
— the **NINTH** independent audit, of `main` @ `5cf9b8c` (tree `9580b86d`, pin proven). **Verdict:
RED, and no P0** — all three production-gate refusals read at that head and verified closed for the
fourth round running, with `AnswerProvenance::Governed` confirmed constructed only inside
`#[cfg(test)]` and nothing in the tree setting `$BROPS_BROKER_CONFIG`.

> ## THE NINTH ROUND: SIX ✅, TWO REOPENED, ONE HELD
>
> Nine Builder claims landed in PRs #153–#162, every one ◑. **Six earned ✅, two are REOPENED, and
> `T-023` is held at ◑ on evidence no head can settle.**
>
> **The two that did not survive are both cases of a fix that measured itself against the wrong
> thing.** `T-034` re-tuned five colours to clear WCAG AA and two of them landed at **4.4996** and
> **4.4995** — below the floor — passing only because `check_contrast.py` compares
> `round(ratio, 2) >= threshold`. Removing that rounding turns the gate RED on exactly those two
> pairs, both of which `T-034` itself added. `A-09` replaced an undecidable sweep with a *declared
> eight-leaf free-text register*, and the register classifies nine `isContractId` leaves as
> "shape-constrained" while that pattern admits 128 characters of `[a-z0-9._-]`: a 64-hex credential
> rides straight through with the register reporting nothing and the sweep silent. Three of the
> eight declared entries are also never exercised by the fixture — **deleting all three leaves the
> suite green.**
>
> **`T-023` is not promoted, and that is the honest answer rather than a harsh one.** The ACE dump
> and the `icacls` harness fix are both real and both read correctly. But the defect lives on the
> GitHub runner's inherited `_temp` ACL, no local box reproduces it, and the job is in
> `deliberately_excluded` so no required check will ever gate it. One green run of an intermittent
> job is what this row exists to refuse.
>
> **Where the ninth round read rather than measured, its rows say so** — `T-039`'s
> cause-elimination half and all of `T-023`.

**Prior assessment:** [`2026-08-18-eighth-audit-9ae2fd2.md`](./2026-08-18-eighth-audit-9ae2fd2.md)
— the **EIGHTH** independent audit, of `main` @ `9ae2fd2` (tree `30b3c966`, pin proven). **Verdict:
RED, and no P0** — all three production-gate refusals read at that head and verified closed for the
third round running.

> ## THIS FILE'S FIRST ✅ SINCE THE FOURTH ROUND
>
> The eighth round's primary output was not new findings. It was a **promotion table**: 29 marks
> carried by the sixth and seventh rounds, every one of them ◑ — *the Builder's claim, written by
> the session that wrote the fix* — attacked one at a time.
>
> **27 earned ✅. Two are REOPENED.** Every ✅ below rests on a measurement the auditor performed:
> mutations re-run independently, Chromium probes re-taken, gates driven live. Where they read
> rather than measured — `G-13` — the row says so and is marked as read.
>
> That matters because of what this ledger has cost twice: both earlier RED verdicts came from rows
> marked ✅ by the session that wrote the fix. Seven rounds have now punished that arrangement. These
> are the first marks in three rounds that did not come from the Builder.
>
> **The two that did not survive are the honest half of the number.** `A-06` — the audit report that
> is never filed — recurred *with the gate for it already in the tree and green*. `A-09` — the
> credential routes past the no-lease whitelist — was never touched: the DoD rows were corrected and
> the boundary made executable, but the routes stayed open, and calling that "fixed" was the
> overclaim the auditor caught.
>
> **The seventh round's report did not exist when the eighth ran.** It has been reconstructed from
> the only surviving record — two commit messages — and is filed as
> [`2026-08-17-seventh-audit-491f923.md`](./2026-08-17-seventh-audit-491f923.md), labelled as a
> reconstruction on its first page. The confirmation of its findings is the eighth round's table
> below, not that file.

> **`A-06` — read this before trusting any ✅ below.** The **FIFTH** round's report was never written
> to this directory. Until 2026-08-17 this line named the FOURTH audit as authoritative while
> `docs/OWNER_ACTION_REQUIRED.md` carried the fifth's verdict, its 11 findings and 15 promotions — so
> every `(…, fifth audit)` citation now embedded in the source pointed at a document nobody could
> open. **The sixth round's report is filed** (above), and the brief that produces these reports has
> been corrected so the next one is written to a file rather than left in a reply.
>
> The fifth round's text is **not recoverable** and is not reconstructed here. Its 15 promotions are
> therefore **not** carried into this file as ✅ — a promotion whose evidence cannot be opened is a
> claim, which is what ◑ means. Where the sixth round independently re-attacked a fifth-round fix and
> could not break it, that is recorded below on the sixth round's own authority.

**Prior assessment:** [`2026-08-15-zero-trust-reaudit-0a9a1af.md`](./2026-08-15-zero-trust-reaudit-0a9a1af.md)
— the **FOURTH** independent audit, a re-audit of the third round's five fixes against a **pinned
snapshot** of `main` @ `0a9a1af`. **Verdict: still RED — but now for one platform rather than one
mechanism.** Four of the five fixes could not be reopened; `B-01` found the fifth fixed on Linux
only while this ledger claimed both platforms. Its findings are in the
[RE-AUDIT table](#findings-of-the-re-audit-2026-08-15-snapshot-of-main--0a9a1af--status) below.

**Prior assessment:** [`2026-08-14-zero-trust-audit-e0dd969.md`](./2026-08-14-zero-trust-audit-e0dd969.md)
— the **THIRD** independent audit, of `main` @ `e0dd969`, commissioned by the Owner and run
**auditor-role-only, READ-ONLY on the tree**. **Verdict: RED — for materially fewer reasons than
2026-08-06.**

| | |
|---|---|
| New findings | **5** — `A-01`…`A-05` (P2 1 · P3 4) |
| ◑ claims attacked | 14 |
| ◑ claims it could **not** refute → recommended ✅ | **9** |
| ◑/⚠️ rows found **STALE** (open here, closed in the code) | 4 |
| Rows found **false** at this head | 2 |
| Previous round's **P0** | **closed on both platforms; could not be reopened** |
| The gate's three refusals | **confirmed closed** at this head |

**The promotions in §3 of that report are not applied in this file yet.** Doing so is the next
Builder task and it must copy the auditor's own row list, not a summary of it.

**Prior assessment:** [`2026-08-06-remediation-audit.md`](./2026-08-06-remediation-audit.md)
— the Owner's SECOND independent audit, of `main` @ `219c763` AFTER the remediation. **Verdict: RED.**
4 of 18 blockers CONFIRMED CLOSED, 2 STILL OPEN, 12 PARTIALLY CLOSED, 45 surviving findings
(1 P0 · 5 P1 · 13 P2 · 26 P3).

> **The new headline finding, because it is the one that moves.** **A-01 (P2, both platforms):** the
> anti-rollback floor is scoped by `install_id`, and the broker chooses it. The defect the ledger
> records as closed (R-07/R-10, floor moved off `task_id`) moved **up one level** rather than closing:
> `install-B / task-FRESH / head 3` bootstraps the same rolled-back head that `install-A` refuses.
> `governed_supervisor_ledger.py:762-765` states the rule it breaks — *"A defence whose scope the
> attacker chooses is not a defence."* `supervisor_id` is config-pinned
> (`governed_acceptance.py:405`); `install_id` is not.

> **That audit's target is not the current tree.** It assessed `main` @ `219c763`. Nine PRs have
> merged since (`2debb71`, `e81f50c`, `bfd55da`, `327519c`, `153a32f`, `8ac57c9`, `c139bde`,
> `09b4803`, `0efa99e`), so some of its findings have been fixed and some of this ledger's rows
> describe code that no longer exists. A Builder staleness sweep at `main` @ `0efa99e` is recorded
> in [Staleness sweep](#staleness-sweep-2026-08-07--main--0efa99e-builder-unverified) below. It
> re-checks rows against the code; it is **not** an audit and marks nothing ✅. **No independent
> audit has been run on `0efa99e`, so the RED verdict above stands until one is.**

> **Read this before any row below.** Every ✅ in the tables that follow was written by the session
> that wrote the fix, and the second audit found several of them overclaimed. The clearest case is
> **F-02**: it was marked CLOSED on the strength of the Linux remediation while the Windows twin
> (`win-live/src/execution.rs:132`) still carried the four `evidence_*` deployment constants — and
> Windows is the only platform on which a `production_verified=true` has ever been shown to the
> Owner. (That particular defect has since been addressed on both platforms; the example stands
> because the *rule* it produced is what this file is for.) A row here is the Builder's claim; the
> remediation audit is the assessment of that claim. Where the two disagree, the audit is the truth
> and the row is the defect.

**Prior assessment:** [`2026-08-06-independent-audit.md`](./2026-08-06-independent-audit.md) — the
25-agent zero-trust audit that produced the 12 soundness-blockers the remediation addressed.

## How to read the status column

Three rounds of audit have now found a row's ✅ overclaimed. So the column no longer says ✅ for
anything an independent audit has not re-checked:

* ✅ — an independent audit confirmed it closed.
* ◑ — the Builder believes it closed and can point at code and tests, and **nobody else has
  looked**. Treat exactly as an unverified claim; that is what the last two rounds punished.
* 🔴 / ⚠️ — open.

The distinction is not bureaucratic. Both RED verdicts came from rows marked ✅ by the session
that wrote the fix, and in the worst case (F-02) the ✅ was written while the defect was still
live on the only platform where the Owner had ever been shown a `production_verified=true`.

## Promotions decided by the NINTH independent audit (2026-08-19, `main` @ `5cf9b8c`)

Full text: [`2026-08-19-ninth-audit-5cf9b8c.md`](./2026-08-19-ninth-audit-5cf9b8c.md). **These ✅ are
the auditor's, not the Builder's** — each rests on a measurement the auditor performed against the
pinned tree, with every mutation restored byte-exact.

| Claim | Mark | What the auditor did |
|---|---|---|
| `T-037` | ✅ | `RestSecondRoad` = **14** tests, module = **88**, and CI's `python -m unittest test_check_repo_state` (`ci.yml:826`) runs all 88. Slug refusal mutated to guess `_REPO_FALLBACK` → **7 red**. The `][` claim re-derived: `.replace("][", "],[")` makes `json.loads` raise `Extra data`, so the branch turned the shape it defended into a refusal. See `I-05`. |
| `T-039` | ✅ | 108 win-live tests. Instrumentation stripped to a bare `{e}` → `an_unreadable_counter_refuses_AND_says_enough_to_diagnose_it` **red**, and the mutant prints the original ambiguous `Access is denied. (os error 5)`. No retry: `read_hint` returns `Ok(0)` only for `NotFound`. **The cause-elimination half is read, not re-measured** — the auditor says so and declines to count it. |
| `T-035` | ✅ | Not shipped: `STATES` is `['pending','settled','unreachable']`, no theme axis. Vacuity measured structurally: `aios.css` has **one** `[data-theme]` selector, declaring only custom properties and `color-scheme`, so no rule matches differently between themes. |
| `T-036` | ✅ | Compile-enforcement mutated: restoring `lvl('L2')` / `approvalState('granted')` → **two `TS2345` errors**. All four vocabulary claims verified against `domain/enums.ts`. Tier finding re-measured: `.tier-A3` exists at `aios.css:996`/`:1260` and **no `.tier-A0`/`A1`/`A2` rule exists**. 323 browser tests. See `I-11`. |
| `T-033` | ✅ | Every headline re-derived exactly: `count_dead_classes.py` → **136 of 1799 (8%)**; `aios.css` **3 194 → 2 009** blocks (Δ **1 185**); rebuilt bundle **218 518 B = 218.52 kB**. One number off in the understating direction: deleted source is **157.1 kB**, not "147 KB". See `I-12`. |
| `T-038` | ✅ | Cause reproduced deterministically — seeding `brops.lang='hy'` fails `Approvals.test.tsx:101` with `:100` passing, plus the second test the row names. **The "does it hide anything?" question answered by measurement:** deleting the `beforeEach` fails **exactly 1 of 739**, the test written to pin it. Baseline 739/79. |
| `A-09` | ❌ **REOPENED** | Routes 2 and 3 confirmed closed (mutants: 2 red, 3 red). **Route 1's replacement does not hold.** A 64-hex credential in `taskId` reaches the wire through `contract_draft.task_id`, which the register calls *shape-constrained* — `isContractId` admits 128 chars of `[a-z0-9._-]`. Register reports `[]`, sweep silent. And **deleting three of the eight declared entries leaves all 10 tests green**, because the single fixture never populates them. `I-01`, `I-02`, `I-03`. &nbsp; **◑ Builder remediation 2026-08-29 — all three, and the register is computed now.** `I-01`: `CREDENTIAL_PROBES` is run through each leaf's REAL validator and the credential-capable set is **asserted equal to the computed one** — **19 leaves, not 8**. The audit's own attack is a test: a 64-hex `taskId` reaches the wire through `contract_draft.task_id`, every leaf still validates, the sweep is silent. `I-02`: the true count of unreachable entries was **seven**, not three; a `FULL` fixture populates every optional field and the inverse assertion — *a declared entry no fixture reaches* — is what was missing. `I-03`: the decode returns printable runs plus the separator-stripped concatenation, in **all three** copies of the sweep. Seven mutants, each verified red and restored. **Route 1 is still not closed and still not claimed to be** — what changed is that the size of its surface is now derived from the validators instead of asserted in a sentence. **This mark stays ◑:** it is the Builder's own claim about the Builder's own fix, which is the exact shape the previous two rounds reopened. |
| `T-034` | ❌ **REOPENED** | Gate widening real and exact (14 → 28 entries = 56 checks; dark worst **4.62**; all five pre-fix numbers reproduce to 2dp). **But `info-on-selected` = 4.499621964567 and `danger-on-selected` = 4.499490555793 — below AA** — and pass only because the gate compares `round(ratio, 2)`. Changing it to `ratio >= threshold` turns the gate **RED on exactly those two**, both pairs `T-034` added. `I-04`. &nbsp; **◑ Builder remediation 2026-08-27, PR #165 (`I-04`).** The comparison moved to the raw ratio and the two colours were re-solved against the composite as a fixed point. Measured both ways: GREEN at 56 pairs with the fix; restore the old colours and the same gate goes RED naming both at 4.4995 and 4.4996 — the audit's own numbers, which is what says the comparison change closed it and not the colours alone. |
| `T-023` | ◑ **held** | Not promoted, by the auditor's own recommendation. The ACE dump (`bro_custody.py:762`, `:768`) and the `icacls` harness fix (`ci.yml:495-513`) are real **and were read, not run**. The defect exists only on the GitHub runner's inherited `_temp` ACL and the job is in `deliberately_excluded`, so the repository cannot distinguish "fixed" from "has not recurred yet". `I-08`. |

### New findings of the NINTH round

| # | P | Finding | Status |
|---|---|---|---|
| `I-01` | P2 | **A-09's register calls a credential carrier "shape-constrained."** Nine leaves are bound by `isContractId` = `^[a-z0-9][a-z0-9._-]{1,127}$`; `slug()` lowercases caller input, so a 64-hex secret in `taskId` survives verbatim into `contract_draft.task_id` with the register silent. The file's *"these — and only these — are places a credential could ride"* is false. | ◑ **Builder-claimed fixed 2026-08-29** — the register is COMPUTED now, not asserted: four credential probes are run through each leaf's REAL validator and a leaf that admits one must be declared. The honest count is **19**, not 8 — 8 with no validator, 11 bound by `isContractId`/`isRepoPath`/`isWorkPath`, which take a 64-hex secret and a JWT whole. The audit's own attack is a test: a 64-hex `taskId` reaches the wire, every leaf still validates, the sweep is silent. Mutant: tighten `task_id`'s validator ⇒ computed set loses it ⇒ **2 red** |
| `I-02` | P2 | **Three of the eight register entries are never exercised, and deleting them is green.** `BASE` leaves `verifierRole`/`verifierAgentSlug` null and `verificationCommands`/`rollbackCommands` empty; `leafPaths` drops nulls and empty arrays. The test asserts *every present leaf is declared*, never the inverse. | ◑ **Builder-claimed fixed 2026-08-29** — the true count was **seven**, not three: four shape-constrained entries (`inputs`, `additional_skills`, `reference_skills`, `verification.verifier_agent_id`) were unreachable for the same reason. A `FULL` fixture populates every optional field, `the register has no unreachable entries` asserts the inverse direction, and `both fixtures really do dispatch` pins the failure that made it possible — a fixture `validateAssignment` refuses exercises nothing. Mutants: delete a free-text entry ⇒ **2 red**; delete a shape entry ⇒ **2 red**; put `FULL` back on the `reader` tier ⇒ **3 red** |
| `I-03` | P3 | **A-09's decode window is escaped by one out-of-range byte.** Appending `0x0a` to the character-code array defeats `decodeCharCodes` entirely; the sweep goes silent again. The fix closes the published proof-of-concept and nothing adjacent. | ◑ **Builder-claimed fixed 2026-08-29** — the decode returns printable RUNS plus the printable bytes with separators removed, so neither a trailing `0x0a` nor one interleaved between every character hides the text. Fixed in **all three** copies of the sweep. Still not a wildcard: an array with no printable byte decodes to nothing, and the negative control is unchanged. Mutant in each copy: restore the all-or-nothing form ⇒ red |
| `I-04` | P2 | **`check_contrast.py` decides an accessibility verdict on a rounded number**, and two shipped light-theme pairs sit below WCAG AA because of it. `passed=round(ratio, 2) >= threshold` (`:162`). The report prints `4.50:1 (need 4.5)`, which reads as passing. | ◑ **Builder-claimed fixed 2026-08-27 in PR #165** — `passed` is decided on the raw ratio; `danger` `#c6314a`→`#c5314a`, `info` `#246bc0`→`#246bbf`. Gate re-run at this head: **GREEN, 56 pairs**. *(This row still read 🔴 OPEN on 2026-08-29, two days after the fix merged: PR #165 touched eight files and this ledger was not one of them. The ledger is the index a reader checks before believing a ✅, so a ledger that lags the code is the failure mode it exists to catch — recorded rather than quietly corrected.)* |
| `I-05` | P3 | **`unittest.main()` sits four lines above the class it should run.** `tools/test_check_repo_state.py:510` precedes `class RestSecondRoad` at `:514`, so `python tools/test_check_repo_state.py` runs **74 of 88** and prints `OK`. CI's `-m unittest` form runs all 88, so T-037's tests are genuinely wired — but the file's own entry point silently drops exactly the 14 added because that code had no coverage. | ◑ **Builder-claimed fixed 2026-08-29** — `unittest.main()` is the last statement in the file and `FileEntryPoint` keeps it there: the entry point must follow every `class` at column 0, there must be exactly one, and both loaders must collect the same count. Measured: **91 tests from both entry points** (was 74 direct / 88 via `-m unittest`). Mutant: move it back above `RestSecondRoad` ⇒ direct run collects **74** and prints `OK`, exactly as the audit measured, and the `-m unittest` form CI uses goes **red** |
| `I-06` | P2 | **The machine mirror's prose drifted.** `config/current_state.json.purpose` says *"main is at settled_at_main_head (b3010f6)"* while that field is `d0bddc4`, and `sync.live_main_resolution` still names PR #82 as the open carrier (it is #162). `check_repo_state.py` is GREEN because it reads `settled_at_main_head` and `prs[]` and never these fields. | ◑ **Builder-claimed fixed 2026-08-29** — `purpose` and `sync.live_main_resolution` restate the live head and the open carrier instead of `b3010f6`/PR #82 |
| `I-07` | P2 | **The roadmap status board disagrees with its own checkboxes on Phases 8 and 9 only** — board 8/10 and 8/9 against 7/9 and 7/9. Phases 3–7 match exactly, establishing the convention. Totals are **92/115** by checkbox and **44/56** by DoD; the claimed **94/117** appears nowhere in the tree or in `git log --all -S`. `check_roadmap_order.py` compares completeness as a boolean and never reads the printed fractions. | ◑ **Builder-claimed fixed 2026-08-29** — Phase 8 and Phase 9 board rows corrected to **7/9** and **7/9** (the superseded fractions kept in a parenthetical). And the gate no longer compares only a boolean: `fraction_problems` counts every checkbox in a phase section and compares it with the FIRST fraction the row prints. Whole-roadmap total re-measured: **92/115** by checkbox, **44/56** by DoD. Mutant: put `8/10` back ⇒ **RED naming Phase 8** |
| `I-08` | P3 | **`required-checks.json` names the wrong PRs for T-023** — *"#125, #132 and #148"* against `ci.yml`'s and `TASKS.md`'s #125/#132/#155/#157. The context list is machine-compared; the exclusion *reasons* are not, so a wrong history sits inside the artifact `H-04` built to make claims checkable. | ◑ **Builder-claimed fixed 2026-08-29** — the reason names #125, #132, #155 and #157, the same four `ci.yml:473` and `TASKS.md` name, and says why the wrong list mattered: #157 is the occurrence whose ACE dump identified the cause |
| `I-09` | P3 | **This ledger routes the eighth round's §E browser-suite finding to `T-039`** (`:139`). It is `T-036`. `T-039` is the Windows `head_sequence` flake. | ◑ **Builder-claimed fixed 2026-08-29** — the §E row routes to `T-036` and records that it pointed at `T-039`, the Windows `head_sequence` flake, until now |
| `I-10` | P3 | **The gate counts in the onboarding docs are stale again.** `START_HERE.md` says 19 files / 18 wired and `ARCHITECTURE.md` says 18; measured at this head: **22 files, 19 wired**. Second consecutive round in which this paragraph is wrong. | ◑ **Builder-claimed fixed 2026-08-29** — re-measured at this head: **23** `check_*.py` files, **22** invoked by path in `.github/workflows/`, one unwired (`check_prior_art.py`, session-side by design). Corrected in `START_HERE.md` (both halves — the Armenian one still said **15**) and `docs/ARCHITECTURE.md` (both halves). The measuring command is written into the paragraph, because this is the second consecutive round the number was wrong |
| `I-11` | P3 | **T-036's vocabulary enforcement stops where the entity type says `string`.** `Decision.status` is `string`, `0002_decisions.sql` has no CHECK, and the fixture's `status: 'accepted'` / `'open'` / the `kind:` values route through no accessor — the exact shape that admitted `'L2'`. | ◑ **Builder-claimed fixed 2026-08-29** — `DECISION_STATUS_FAMILY` declares the seven statuses this repository knows a source for, the classifier moved to `Decisions.status.ts` (the router types a page module as `Record<string, ComponentType>`, so it could not stay), and the browser fixture routes through `decisionState(v: DecisionStatus)`. `Decision.status` is deliberately NOT narrowed and no CHECK is added — the value is read from a ledger this app does not own — and the test says so. Mutant: `decisionState('granted')` ⇒ **TS2345** |
| `I-12` | P3 | **`check_bundle_budget.py` has no freshness check.** It reported GREEN at 151.6 KB against a `dist/` built before T-033's deletion, and GREEN at 133.0 KB after a rebuild of the same tree. T-033 cites this gate as evidence for a bundle-size claim. | ◑ **Builder-claimed fixed 2026-08-29** — the gate refuses to grade a build older than the tree: any bundled source newer than the manifest is RED, naming the file, and the size verdict is not printed beside it. Test files and `.md` are excluded (a gate that reds on a touched test gets switched off). Five tests; mutant: disable the freshness check ⇒ **3 red** |
| `I-13` | P2 | **Two Phase-10 boxes are closable by a Builder change**, against the claim that every open box is blocked by the production gate or deployment: `contracts/` finalisation (roadmap `L1738`, `L1747`). `contracts/` is a lone 3 012-byte README while `engine/schemas/` holds 21 schemas; `ARCHITECTURE.md` says so itself. No service principal, launcher, broker or deployment is involved. | ◑ **Builder-claimed fixed 2026-08-29, except the relocation** — `contracts/` holds the five cross-half schemas as the **source**, `contracts/index.json` carries each one's version as a JSON Pointer into its own `const`, and `tools/check_contracts_single_source.py` (17 tests, wired into CI) fails on drift between source and vendored copy, on an unclassified new engine schema, on a version bumped in one place, and on any `*.schema.json` outside the four declared homes. What is left is the file move, and the reason is written down rather than filed under a blocker it does not have: the engine resolves schema paths relative to its **own root** and `engine/` is a subtree of `menqstudio/Bro`. **The audit is right that no production gate, service principal, launcher, broker or deployment is involved** |


## Still open in the earlier rounds

Carried forward from [`AUDIT_LEDGER_ARCHIVE.md`](./AUDIT_LEDGER_ARCHIVE.md), which holds rounds 1–8 and the Builder sweeps in full. A row moved out of sight is a row that stops being answered, so the open ones stay here.

| # | Finding |
|---|---|
| `G-05` | A fifth fail-open door, pinned by a test named `_is_noop`. |
| `A-06` | The fifth audit's report was never filed; this ledger named the fourth as authoritative while the OWNER page carried the fifth's 15 promotions. |
| `A-09` | Three routes get a credential past the no-lease / no-secret whitelists; the tests prove frame shape and word-absence, not credential-absence. |

---

**Rounds 1–8 and the Builder sweeps:** [`AUDIT_LEDGER_ARCHIVE.md`](./AUDIT_LEDGER_ARCHIVE.md).

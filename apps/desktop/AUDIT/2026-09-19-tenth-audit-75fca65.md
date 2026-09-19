# Tenth round — independent verification of the ninth round, at `main` @ `75fca65`

**Date** 2026-09-19 · **Head** `75fca65` · **Auditor role** delegated to Claude by the Owner, as
recorded for the sixth round onward · **Scope** the ninth round's thirteen findings
(`2026-08-19-ninth-audit-5cf9b8c.md`), the three carried forward from rounds 1–8, and anything the
verification turned up on the way.

## Method, and what makes it independent

Every ninth-round row carries a `◑` — the Builder's own claim, with its own mutants named beside it.
Re-running those mutants would confirm the Builder's arithmetic, not the finding. So each row here was
attacked **differently from the way its own fix describes**, and where a row is a statement about file
content it was read at this head rather than trusted.

Three rules, applied throughout:

1. **A mutation that did not run looks exactly like a survivor.** Every mutation below was proved
   applied — the anchor occurs exactly once, the bytes changed, the replacement is present and the
   anchor gone — before any verdict was believed. That discipline exists because five "survivors" in
   one day turned out to be mutations that never ran (`T-083`).
2. **Mutate production, not the test.** Mutating a test to check that the test works is circular. Where
   a Builder claim is "this test asserts X", the probe changes the code X is about.
3. **A green suite is not a passing check.** A verdict is only recorded where a **named** test died
   **by assertion**, or where a command printed the number in question.

## The ninth round's thirteen

| # | P | Ninth-round finding | Tenth-round verdict | Evidence, at `75fca65` |
|---|---|---|---|---|
| `I-01` | P2 | the credential register called a carrier "shape-constrained" | ✅ **CONFIRMED** | The fix computes the register from each leaf's real validator. The register is computed over `CALLER_CONTROLLED`, a hand-written list, so the attack was: add one caller-controlled leaf to the wire frame (`operator_hint`, carrying `contract_draft.task_id`) and see whether a hand-maintained population lets it through. **5 tests red by name**, including `every leaf is either shape-constrained or a DECLARED free-text field` and `what IS established: the frame is exactly its declared fields`. 19 green when restored. |
| `I-02` | P2 | three register entries were never exercised, and deleting them was green | ✅ **CONFIRMED** | Probed by dropping `reference_skills` out of the **production** frame builder rather than by touching the fixture: **10 of 19 red**, including `I-02 mutant: deleting a declared entry is no longer green` and `both fixtures really do dispatch`. The inverse direction fires. |
| `I-03` | P3 | one out-of-range byte escaped the decode window | ✅ **CONFIRMED, for its stated scope** | The published escape (`0x0a` appended, and interleaved between every character) is encoded in `agentsDispatch.nolease.test.ts:213-215` and the suites pass — 12 tests across the no-lease and no-secret sweeps. The fix claims the published proof-of-concept and nothing adjacent, and that is what it delivers: a printable separator would still hide a token from a substring search, which is `A-09` route 1 and is open **by declaration**, not by oversight. |
| `I-04` | P2 | an accessibility verdict decided on a rounded number | ✅ **CONFIRMED** | `round(` inside a `passed=` expression: **0 occurrences**. A raw `ratio >= threshold` comparison: **1**. |
| `I-05` | P3 | `unittest.main()` four lines above the class it should run | ✅ **CONFIRMED** | `unittest.main()` is at line **891 of 892**; no class is declared after it. |
| `I-06` | P2 | the machine mirror's prose drifted from the head it holds | ✅ **CONFIRMED** | No sha is quoted in `purpose` **at all** now, and `settled_at_main_head` is `bb8a00a…`, live `main` at the time of reading. The drift class was removed rather than corrected, which is stronger. |
| `I-07` | P2 | the roadmap status board disagreed with its own checkboxes on phases 8 and 9 | ✅ **CONFIRMED** | Checkboxes counted at this head: phase 8 = **7/9**, phase 9 = **7/9**, the corrected values. `tools/check_roadmap_order.py`: *"GREEN: roadmap phases 0..10 agree between Definition of Done and the status board; first open phase = 1"*. |
| `I-08` | P3 | `required-checks.json` named the wrong PRs for `T-023` | ✅ **CONFIRMED** | The exclusion reason names `#125`, `#132`, `#155`, `#157`. `#148` appears only inside the sentence that records the old error. |
| `I-09` | P3 | the ledger routed the eighth round's browser-suite finding to the wrong ticket | ✅ **CONFIRMED** | The §E row routes to `T-036`, and records that it pointed at `T-039`. |
| `I-10` | P3 | the gate counts in the onboarding docs are stale **again** | ❌ **REOPENED** | `START_HERE.md:129` (EN) and `:164` (HY) both read **23 files, 22 invoked**. Measured: **40** `tools/check_*.py`, **39** invoked by path across `.github/workflows/`. The exception named in the sentence is still exactly `check_prior_art.py`, so the structure was right and only the numbers rotted. **Third consecutive round** in which this cell is wrong. Corrected in the change that files this report. |
| `I-11` | P3 | vocabulary enforcement stopped where the entity type says `string` | ✅ **CONFIRMED** | Adding an invented member to `DECISION_STATUS_FAMILY` killed **2 named tests** — `every declared status classifies into the family the map claims` and `every declared status is RECOGNISED, not merely landing in the fallback`. `Decision.status` is still `string` and `0002_decisions.sql` still has no `CHECK`; both are **stated decisions** in the Builder's response ("the value is read from a ledger this app does not own"), not omissions, and the test says so. A finding drafted against them was withdrawn on reading it. |
| `I-12` | P3 | the bundle gate had no freshness check | ✅ **CONFIRMED** | `mtime`, `stale` and `freshness` all present in `tools/check_bundle_budget.py`; the gate reports `the build is stale` on this machine, which is the expected RED of the four. |
| `I-13` | P2 | two Phase-10 boxes were closable by a Builder change | ✅ **CONFIRMED, except the declared file move** | `contracts/` holds **5** cross-half schemas plus `index.json`. The relocation is still open with its reason written down (the engine resolves schema paths relative to its own root, and `engine/` is a subtree of another repository). |

**Twelve confirmed, one reopened.** The reopened one is a documentation count; no fix to a control, a
gate or a trust boundary was found to be overstated.

## Carried forward from rounds 1–8

| # | Verdict here | Why |
|---|---|---|
| `G-05` | **mis-listed** | The live ledger's *"Still open in the earlier rounds"* table says, in its own words, that it holds *"the open ones"*. `AUDIT_LEDGER_ARCHIVE.md:39` marks `G-05` ✅ with the attack that closed it — `""` → RED, `None` → RED, `OPEN` → GREEN, all four `A-11` doors re-attacked. It is closed, and this round removes it from the open table rather than leaving the ledger arguing with its own archive. Filed below as `J-04`. |
| `A-06` | **open, permanently** | The fifth round's report was never written and its text is unrecoverable. Structurally answered 2026-08-17; the scar does not close. |
| `A-09` | **open by declaration** | Routes 2 and 3 are closed (mutants: 2 red, 3 red). Route 1 is open **and says so**: a credential is defined by what a remote system accepts, so a free-text field can carry a token, and the answer shipped instead is an enumeration of every leaf that can — derived from the validators the product runs, and re-verified here under `I-01` and `I-02`. A heuristic that read as proof would be worse than the stated gap. |

## New this round

| # | P | Finding |
|---|---|---|
| `J-01` | P2 | **`docs/ARCHITECTURE.md`'s CI cell was stale in five places at once**, in both language halves: *"7 workflows"* against **8** files; *"33 checks run on every pull request"* against **37** reported on `#252`; *"**22** repository gates under `tools/`"* against **39** invoked; *"**23** files exist and **22** are invoked"* against **40 / 39**; and *"**33** of them are required"* against **34** in `config/required-checks.json`, with *"Exactly two pull-request jobs are excluded"* against **four** (plus a fifth that never reports on a pull request at all). The cell's own parenthetical said the check count *"is not re-measured here"* — honest, and also how it went four further rounds without being measured. Corrected in this change. |
| `J-02` | — | **Withdrawn before filing.** Drafted as *"`I-11`'s fix left the type and the column open"* on measuring `status: string` six times in `entities.ts` and no `CHECK` in `0002_decisions.sql`. Reading the Builder's response showed both are deliberate and reasoned. Recorded because a withdrawn finding is evidence the round read the answers rather than only the code. |
| `J-03` | P2 | **The roadmap was in no gate's read set.** `docs/roadmap/phase-*.md` is what `tools/check_roadmap_order.py` reads to decide which phase a session may work, and its **84** checked boxes across phases 1–9 are this repository's central claim about what is finished. It was in neither `config/canonical-read-manifest.json` (14 paths) nor `check_doc_claims.py`'s `ALSO_CHECKED`. Measured on arrival: pointing the gate at all eleven files reported **nothing** beyond the two known `config/toolchain.json` lines — every path, commit hash and ticket id the roadmap cites resolves. **That is the finding.** The referents were sound and nothing kept them sound, in the one document where a citation to a file nobody filed would read as a phase being done. Closed in this change: the eleven files are in `ALSO_CHECKED`, with a test that the set named equals the set on disk and a test that a dead path inside a phase file is caught. |
| `J-04` | P3 | **The ledger lists a closed finding as open.** `G-05` sits in *"Still open in the earlier rounds"* while `AUDIT_LEDGER_ARCHIVE.md` marks it ✅ with its attack. Corrected in this change. |

## Verdict

**RED**, and the reason is now three named items rather than thirteen unconfirmed claims:

- `A-06` — a report that cannot be recovered. Permanent.
- `A-09` route 1 — open **by declaration**, with the enumeration in place of a heuristic, re-verified
  here twice over.
- `I-10` / `J-01` / `J-04` — documentation counts and one mis-filed row, all corrected in the change
  that carries this report.

**What this round does not say.** It does not say the trust boundary is proven: no governed round trip
runs on a default deployment, `GOVERNED_TRUSTED_MANIFEST_PROVISIONED` is `false`, and phases 1, 2, 8 and
9 each hold Definition-of-Done rows that are open for stated reasons. What it does say is that nothing
in the ninth round's thirteen was found overstated except a count, and that no finding in this ledger
now forbids building the approval-**request** path (`T-021`). `TASKS.md` sequences `T-021` behind "the
standing audit"; the standing audit is this round, the sequencing note was the Builder's own, and the
Owner has since asked for the roadmap closed. So the block is lifted here, in writing, rather than
ignored.

**Also verified, because a checked box is not evidence either.** The 84 checked rows in phases 1–9 were
triaged by the evidence they cite: 39 cite no file and no test, and most of those are Task-checklist
rows that say *"see DoD row N"* — a delegation, not a claim. Every cited path resolves (`J-03`). One
apparent contradiction was chased and found not to be one: phase 1's Task row *"Slice 3 — the §4.10(f)
chunked output pull — done"* and its Definition-of-Done row *"Governed output delivery through the
wall"*, still open, describe the same code honestly — the hop exists in
`broker/src/ladder_executor.rs`, and the row is open because `build_governed_executor` serves
`UpstreamBlockedExecutor` without `$BROPS_BROKER_CONFIG`. **That is a wiring gap, not missing code**,
and it is the shortest path to closing phase 1.

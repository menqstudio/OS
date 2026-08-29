# Audit ledger archive — rounds 1 to 8, and the Builder sweeps

Moved out of `AUDIT_LEDGER.md` on 2026-08-29 (`T-045`). The ledger keeps the POSITION —
the standing verdict, how to read a mark, and the current round's rows. This file keeps
the per-round tables and the Builder sweeps behind it.

Nothing here is superseded: a row's history is how you tell a fix from a claim, and two
of this repository's own RED verdicts came from rows marked ✅ by the session that wrote
the fix. It is moved rather than shortened, and the ledger links it.

---

## Findings of the EIGHTH independent audit (2026-08-18, `main` @ `9ae2fd2`) — status

Full text: [`2026-08-18-eighth-audit-9ae2fd2.md`](./2026-08-18-eighth-audit-9ae2fd2.md).

| # | P | Finding | Status |
|---|---|---|---|
| `H-01` | P1 | **18 pull-request-running jobs sit outside branch protection with no reason recorded** — the whole of `supply-chain.yml`, including `gitleaks`, `Action pins (F-46)`, `cargo-audit`, `cargo-deny`, `pip-audit`, `npm audit` and `SBOM`. `enforce_admins: true` does nothing about jobs that are not required, *"which is where the supply chain lives."* | ◑ **Fixed 2026-08-18.** Required contexts 12 → **33**. Exactly two remain excluded, each for a measured reason: `AI-surface inventory gate` (a `paths:` filter means it does not report on unrelated PRs, and GitHub treats a skipped required context as pending) and `Trust provisioning (windows-latest)` (`T-023`, three recorded occurrences). Bundle-budget's old exclusion reason was **wrong** — it is RED locally only because `dist/` is absent; CI builds first — and it is now required. |
| `H-02` | P2 | **The seventh round produced no report, and the gate built to prevent that is GREEN by construction.** `A-06` verbatim, one round later. Eleven findings survived only as `(G-0n, seventh audit)` citations pointing at a document that did not exist. | ◑ **Fixed 2026-08-18.** The round is filed (reconstructed, labelled), the ledger carries its findings, and `check_audit_reports.py` now binds the **highest ordinal cited anywhere in the tree** to a filed report — so a round that leaves citations behind can no longer leave the report behind. |
| `H-03` | P2 | **The restored palette's active row is unreadable in the light theme.** `color: var(--brops-accent)` (aios cyan) on `var(--menq-color-selected)` (menq tint) — two palettes in one declaration, from the fix for the sixth round's own `A-01`. | ◑ **Fixed 2026-08-18, and the measurement corrected.** Recomputed against the real light-theme `--cyan` (`#0EA5E9`, not the fallback): **2.34:1**, not 1.81 — same verdict, AA wants 4.50, inactive rows are 18.58:1. **The audit's proposed remedy does not work either:** `--menq-color-accent` gives 4.34:1, still under the floor, which is why it was correctly marked UNVERIFIED. Selection is no longer signalled by text colour at all — the label sits at `--brops-text` (15.71:1 / 12.06:1) and the cursor is a left marker in the accent (4.34:1 / 4.62:1, above the 3:1 non-text floor) plus the tint and the weight. |
| `H-04` | P3 | **Seven canonical documents still say main has no branch protection** — `ARCHITECTURE.md` states the command, the output and a verification date. | ◑ **Fixed 2026-08-18.** All seven corrected, and the claim made **checkable**: `config/required-checks.json` commits the expected protection state and `check_repo_state.verify_branch_protection` compares it against live GitHub — a context required on GitHub and absent from the file is RED, and so is the reverse. Mutation-tested in four directions. Its first run caught a bug in itself: `gh api` decoded as cp1252 turned every `·` and `§` in a context name into mojibake. |
| `H-05` | P3 | The REST fallback hardcodes `menqstudio/OS`, and one line of its pagination is inert. The fail-closed contract holds; the repository slug does not survive a fork. | ◑ Open — `T-037` |
| `H-06` | P3 | **A load-flaky suite is required; a flaky suite was excluded for being flaky.** Two decisions taken the same day pointing opposite ways. | ◑ Open — `T-038` |
| §E | — | **The browser suite measures 16.1% of the styled design system** and reaches neither `default` (a page with data) nor `blocked` — the state every governed surface permanently ships in. Proven by mutation with a positive control. | ✅ Closed — `T-036` *(this row routed the finding to `T-039` until 2026-08-29 — ninth audit `I-09`. `T-039` is the Windows `head_sequence` flake and has nothing to do with the browser suite; a reader following the pointer landed on the wrong task in the wrong half of the product. `T-036` is the row that carries it, and the ninth round promoted `T-036` to ✅.)* |
| §E | — | **PR #149's REST fallback has no test of its own.** `grep -c "_rest_" tools/test_check_repo_state.py` → 0. The one piece of new code in the seventh round that no gate covers. | ◑ Open — `T-037` |

## Findings of the SEVENTH independent audit (2026-08-17, `main` @ `491f923`) — status

Full text: [`2026-08-17-seventh-audit-491f923.md`](./2026-08-17-seventh-audit-491f923.md) —
**reconstructed**, see `H-02`. The status column is the EIGHTH round's verdict, not the Builder's.

| # | P | Finding | Eighth round |
|---|---|---|---|
| `G-01` | P1 | **No required status checks on main.** Every "33 green checks" claim in this repository's history described advisory signal. | ✅ Protection read live: `enforce_admins`, `strict`, `linear`, 12 contexts all mapping to real jobs. *"The finding and the fix are real. The exclusion list is not"* → `H-01`. |
| `G-02` | P2 | `has_negative_test` required a `fn`, not a `#[test] fn`. | ✅ 3 mutations: attribute deleted → RED; test renamed → RED; intervening `#[should_panic]` → GREEN, so the tolerance clause is not a false positive. |
| `G-03` | P2 | The gate written to close `A-06` did not detect `A-06`. | ✅ 6 mutations, all correct. **Stronger than claimed** — it binds three documents, `current_state.json` included. |
| `G-04` | P2 | `animation_clobber` broke after the first matching group — order-dependent. | ✅ 4 orderings including both interleavings inside one file, all RED. |
| `G-05` | P2 | A fifth fail-open door, pinned by a test named `_is_noop`. | ✅ `""` → RED, `None` → RED, `OPEN` → GREEN (a real no-op). All four `A-11` doors re-attacked. |
| `G-06` | P2 | `--settled` left a merged carrier named on a deleted branch. | ✅ Run live against a merged #150: refuses, names the flags, and `git status` is clean — so *"Nothing has been written"* is true. |
| `G-07` | P2 | `unstyledClasses` was pointed at 2 surfaces out of 24. | ✅ 23 × 3 = 69 exactly. *"What those 69 pairs cannot reach is §E."* |
| `G-08` | P3 | The backward sweep was satisfied by the comment explaining its own fix. | ✅ Run line stripped, comment kept → RED with the exact message. |
| `G-09` | P3 | Three status pills below AA; the manifest called 10px/600 text "large". | ✅ Colours reverted → RED with exactly 3 pairs at 3.49, 3.46, 4.10. Zero `"size": "large"` remain. **Three files, not two.** |
| `G-10` | P3 | The contrast gate measures a palette the app does not paint with. | **Not promoted — became live.** Deferred to `T-034` as *"a structural gap, not a live defect"*, which was true when written and is not now: `H-03`. |
| `G-11` | P3 | `[data-theme]` inside `@media` evaded the responsive rule. | ✅ All four quadrants correct. `G-11(a)` — the theme block checked by nothing — remains `T-034`. |
| `G-12` | P3 | `classname_groups` read neither `class=` nor spread props. | ✅ The clobber applied through plain `class="…"` → RED. |
| `G-13` | P3 | The keyframe guard read a narrower surface than the check it protects. | ✅ **read, not mutated** — the auditor says so explicitly and declines to count it as re-run. |
| `G-14` | P3 | The ledger's P0 row cited a line that does not contain the refusal. | ✅ `grep -n` → 1305, matching the citation. |
| `G-15` | P3 | `785 of 2 639` could not be reproduced and no tool computed it. | ✅ `count_dead_classes.py` → 785 of 2356, reproducing numerator **and** corrected denominator. |

## Findings of the SIXTH independent audit (2026-08-17, `main` @ `b16e572`) — status

Full text: [`2026-08-17-sixth-audit-b16e572.md`](./2026-08-17-sixth-audit-b16e572.md). Status here is
the **Builder's** claim unless a later independent round says otherwise — that is what ◑ means, and
`A-06` exists because this file once said otherwise.

> **All fourteen are marked fixed as of 2026-08-17, and every one of them is ◑. Not one is ✅.**
> This ledger has twice carried a RED verdict that came from a row marked ✅ by the session that
> wrote the fix, and the sixth round's own §E named the arrangement while it was happening: *"It
> will be written, mutation-tested and marked ◑ by its own author, which is the arrangement six
> rounds have now punished."* The seventh round decides which of these survive.
>
> **Read the last banner before trusting the count.** `docs/OWNER_ACTION_REQUIRED.md` said *"All 11
> are fixed as of 2026-08-16"* about the fifth round and `A-08` found that false. What is different
> here is that each row names what was done and what was measured, so the claim is checkable rather
> than tallied — and **four rows record a defect found in the FIX, by the fixer, after the audit had
> closed**: the new browser suite missing four unstyled pill tones because it cannot reach the state
> they render in; `classname_groups` never having read a plain string `className` at all;
> `sync_active_pr --settled` emitting a `settled_at_main_head` its own gate refuses; and two tests
> that had encoded a fail-open as intent. None of those were in the report.

| # | P | Finding | Status |
|---|---|---|---|
| `A-01` | P1 | **The ⌘K palette has had no CSS since 2026-07-28.** Five classes deleted with `layout.css`'s palette section in `0c08dd8` (PR #47); the component kept rendering them. No overlay, no backdrop, no panel, no scroll container, no active-row highlight, and the page behind clickable while `aria-modal="true"`. | ✅ **Fixed 2026-08-17.** Section restored in `layout.css`. Measured, not asserted: `CommandPalette.browser.spec.tsx` fails 8 of 9 without it. &nbsp; **Eighth audit:** Re-ran the round-six Chromium probe against the real stylesheet graph. Every measurement inverted: scrim `position:fixed` `z-index:60` `rgba(0,0,0,.5)`, rect 764×429 = viewport, covers viewport **true** (was false); panel 620px with border; list `max-height:340px overflow-y:auto`; active row distinct **true**; `elementFromPoint` over the background control returns the scrim. |
| `A-02` | P2 | `validates()` requires a **substring**, not a check. Five mutations — including deleting `parse_evidence_event`'s discriminator comparison outright — leave the gate GREEN. | ✅ **Fixed 2026-08-17.** `validates()` scoped to the struct's own parser, comments and `#[cfg(test)]` stripped, and a `negative_test` required per mirror. All five audit mutations die: three at the gate, two at the test. &nbsp; **Eighth audit:** The decisive mutation re-run with rebuild proof: deleting `parse_evidence_event`'s comparison now turns the gate RED **and** fails a cargo test. In round six the same mutation left both green. 29 → 30 tests. |
| `A-03` | P2 | `animation_clobber` is evaded by the `animation-name` longhand **its own error message recommends**. | ✅ **Fixed 2026-08-17** (`T-026`). &nbsp; **Eighth audit:** `animation-name: sigbreathe` — the longhand the gate's own message used to recommend — RED. |
| `A-04` | P2 | `ENTRANCE_CLASSES` knows 2 entrance classes; 14 rules in the tree are invisible-until-animated. Three further blind spots measured. | ✅ **Fixed 2026-08-17** (`T-026`). &nbsp; **Eighth audit:** An entrance class that is neither `.reveal` nor `.rise` → RED. A clobber applied via `cx('a','b','reveal')` rather than a literal → RED. |
| `A-05` | P2 | `save_ask_to_knowledge` stamps `"governed research · …"` unconditionally, and the **only** path that can reach it on any install is the ungoverned one. | ✅ **Fixed 2026-08-17.** `AnswerProvenance` is a required parameter of `stash_pending_answer`; the save path writes it verbatim and asserts nothing. The renderer carries the fact rather than softening the words, and an unrecognised outcome reads as a warning. &nbsp; **Eighth audit:** Three-state enum carried from the producing site; `Governed` unreachable in production; the ungoverned path prints `UNGOVERNED research (no governed turn, no receipt)`. |
| `A-06` | P2 | The fifth audit's report was never filed; this ledger named the fourth as authoritative while the OWNER page carried the fifth's 15 promotions. | ❌ REOPENED **Structurally fixed 2026-08-17** for this round: report filed, this line repointed, brief corrected. **The fifth round's text remains unrecoverable** and its promotions are NOT carried here. &nbsp; **Eighth audit:** **The gate is strong and the defect recurred anyway.** No seventh-round report exists in any commit on any branch; the ledger still named the sixth authoritative. See `H-02` — and note the gate was GREEN throughout, correctly, because nothing announced a seventh. |
| `A-07` | P2 | `RoomReadout` reports a measured zero and a failed read as the same em dash (`:296`), and after any failed refresh states `0` for values that were never established (`:297-298`). | ✅ **Fixed 2026-08-17.** `established()` — a value counts only when this read finished, succeeded and produced data. Also closed the misattribution case the audit did not name: a room switch rendered the previous room's counts and round card. &nbsp; **Eighth audit:** One `figure(n)` for all three cells and callers that pass `null` on failure. A measured zero and a failed read are no longer the same glyph. |
| `A-08` | P2 | `OWNER_ACTION_REQUIRED.md:22` — *"All 11 are fixed"* is false; fifth-round `A-06` (six fallbacks on dead CSS) was never touched. | ✅ **Fixed 2026-08-17.** The five dead selectors deleted (130 lines). The banner was corrected the same day. `T-033` carries the measured remainder: 785 of 2 356 class tokens are dead. &nbsp; **Eighth audit:** The false sentence is gone and its correction is recorded in place. |
| `A-09` | P3 | Three routes get a credential past the no-lease / no-secret whitelists; the tests prove frame shape and word-absence, not credential-absence. | ❌ REOPENED **Fixed 2026-08-17.** Both DoD rows now claim what the tests establish, and `agentsDispatch.boundary.test.ts` makes the limit executable — the three smuggle routes are asserted to pass, on purpose. &nbsp; **Eighth audit:** **Untouched.** `FORBIDDEN` is byte-identical, `flatten` is still `typeof value === 'string'` only, and no test mentions a non-string leaf. All three smuggle routes remain open. The DoD rows were corrected and the boundary was made executable — the ROUTES were never closed, and that was a recorded decision, not an oversight. The auditor is right that the finding is not closed; `T-030` reopens with what would actually close it. &nbsp; **◑ Builder remediation 2026-08-18 — routes 2 and 3 closed, route 1 answered by enumeration.** `FORBIDDEN` is no longer byte-identical: the `key` clause carries an optional prefix/suffix family (`pubkey`/`apikey`/`keystore`/`sessionkey`/`keychain`/`keyring`/`keypair`/`key_id` match; `monkey`/`keyboard`/`keyword` do not). `flatten` visits number/boolean/bigint leaves and decodes an all-printable-ASCII `number[]`, so the auditor's own `[108,101,…]` case is swept as `"lease-7f2a91"`; a test names the non-string leaf in both directions, including a negative control that an ordinary numeric array gains no spurious text. Fixed in all three copies of the sweep. Route 1 is **not** closed and is not claimed to be: no grammar, no entropy detector — instead every leaf of the frame must now be shape-constrained against the module's own validators or listed in a **declared eight-leaf free-text register**, so the surface is counted rather than swept, and a ninth field turns the suite red. Three mutants verified by deletion. **This mark stays ◑:** the previous round's error was a Builder calling its own correction closed, and repeating that here would be the same mistake with a better patch under it. &nbsp; **NINTH AUDIT — REOPENED AGAIN, and the ◑ was the right call.** Routes 2 and 3 survive attack (both mutants re-run independently: 2 red, 3 red). Route 1's replacement does not. The register's own sentence — *"these — and only these — are places a credential could ride"* — is false: `isContractId` admits 128 characters of `[a-z0-9._-]` and `slug()` lowercases, so a 64-hex credential in `taskId` reaches the wire through `contract_draft.task_id` with the register reporting `[]` and the sweep silent (`I-01`). And the register is not the size it says: `BASE` never populates `verification.verifier_role`, `verification.commands` or `rollback.commands`, and **deleting all three declared entries leaves the file at 10 passed** (`I-02`). The decode window closes the published PoC only — one byte outside `0x20`–`0x7e` walks past it (`I-03`). |
| `A-10` | P3 | The C.1 gate still misses a non-spacing token overridden in a later `:root` — the docstring's own `--azure` example. | ✅ **Fixed 2026-08-17** (`T-026`). &nbsp; **Eighth audit:** All three round-six misses now caught: `--azure`, `--t-body`, `--r-pill` in a plain `@media :root` → RED, RED, RED; a legitimate `[data-theme]` colour override stays GREEN. |
| `A-11` | P3 | Two silent fail-open paths remain in `verify_settled_snapshot` beside the one that was fixed. | ✅ **Fixed 2026-08-17.** All three doors refuse with a reason, including one the audit did not name. Two tests that asserted the fail-open as intent were rewritten. &nbsp; **Eighth audit:** All four doors RED, plus the two residuals the round-six auditor left open: absent `mergeCommit` → RED, unresolvable `first_parent()` → RED. |
| `A-12` | P3 | `tools/test_renderer_broker_schemas.py` is named by no workflow; the round swept forward for new tests and not backward for orphaned ones. | ✅ **Fixed 2026-08-17.** Wired, and `check_reachability::unrun_test_modules` sweeps backward with no escape hatch. &nbsp; **Eighth audit:** Wired at `ci.yml:773`, and `G-08`'s backward sweep now prevents the regression — mutation-confirmed. |
| `A-13` | P3 | `AUDIT_LEDGER.md:134` — nested backticks terminate the code span; the row stating the P0 gate status renders garbled. | ✅ **Fixed 2026-08-17.** &nbsp; **Eighth audit:** Backtick parity in the P0 row is balanced. |
| `A-14` | P3 | `OWNER_ACTION_REQUIRED.md:638` — *"These are being worked"*; both surviving §3 items say they are not. `## 2d.` precedes `## 2c.` | ✅ **Fixed 2026-08-17.** The heading no longer claims the items are being worked — they are parked with a stated reason, which is a different and more honest thing to be — and `2c`/`2d` are in order. &nbsp; **Eighth audit:** The sentence was corrected and the correction recorded in place. |

## Findings of the THIRD independent audit (2026-08-14) — status

| Finding | Status |
|---|---|
| **`A-01` (P2, both platforms)** — the evidence-head anti-rollback floor is scoped by `install_id`, which the broker chooses | ◑ **Builder claims closed 2026-08-14; NOT independently re-checked.** `AuthorityConfig` now **requires** `install_id`, and the authority **refuses** a `create-pending` whose `install_id` is not this deployment's (`challenge_authority.py`, `challenge_authority_server.py`). **Validated, not substituted:** overwriting the caller's value would keep the floor honest and break the supervisor's independent `request_sha256` recompute — `governed_turn_open` already refuses when request and payload disagree (`:487-488`), so a silent substitution turns a misconfiguration into a failure three hops away. Production source is `cfg["resolved"]["install_id"]`, the same block the desktop (`ladder_desktop.py:108`) and the ladder's own gate (`run_ladder_turn.sh:905`) read, so the three cannot drift. **Mutation-verified:** with the check deleted `test_foreign_install_id_in_create_pending_is_refused` FAILS; restored, it passes. Engine suite **1997 OK / 43 skipped**. &nbsp; **⚠️ THIS ROW WAS AN OVERCLAIM AND THE RE-AUDIT CAUGHT IT (`B-01`).** It was titled *"(P2, both platforms)"* and marked closed with **no platform caveat**, while the fix existed only on Python/Linux — the Windows twin still took the caller's `install_id` off the wire at `servers.rs:174` and fed it to the floor's scope at `:1078-1085`. That is exactly the **F-02** failure this file's header cites as the reason it exists: *marking a finding CLOSED on one platform's evidence.* **Closed on Windows 2026-08-15 — see `B-01` below.** The mutation evidence above was also independently reproduced by the auditor (baseline 19 OK → mutant FAILED → restored 19 OK, restore digest matched the committed blob), so the claim held; the **scope** of the claim did not. |
| **`A-02`** — the run-evidence chain's hash link is written and never checked; `final_event_hash` decides `EvidenceFork` and is an unverified field | ◑ **Builder claims closed 2026-08-14; NOT independently re-checked. Both platforms.** Each consumer now walks the chain by the recorder's own rule — `event_hash = sha256(canonical(event))` over the **whole** event object, which contains that event's `previous_event_hash`, so altering any earlier event changes every digest after it. A break is refused, a first event claiming a predecessor is refused, and a `final_event_hash` that is not the last digest is refused. `governed_supervisor_ledger.py` (after the count checks) and `win-live/src/servers.rs` (after the payload digest). **Mutation-verified on both:** delete the Python block and 4 negatives FAIL; delete the Rust block and the new negative FAILS; restored, both pass. Each side carries a positive control, so the negatives cannot be satisfied by an arm that refuses everything. **Engine suite 2001 OK / 43 skipped; win-live 102 passed.** **It also caught the finding standing in a fixture:** `test_governed_output_read`'s `_complete` built a chain with `final_event_hash: "d" * 64` and an event carrying no `previous_event_hash` and no `sequence` — a chain no recorder would write, which passed because nothing verified the link. Corrected to a real one. |
| **`A-03`** — the ledger claims the self-owned-pin acknowledgement file is custody-checked; the module that would do it does not | ✅ **CLOSED — and this ✅ is the re-auditor's, earned 2026-08-15, not the Builder's (`B-03`).** The fixing session wrote the mark itself, which the legend at the top of this file forbids; the re-audit checked the row and **confirmed it substantively correct**, so the mark now has an independent basis. The violation is recorded rather than quietly repaired. **What was done, 2026-08-14 — the row is corrected, in this file.** Both halves of the `bro_signature.py:263` row are now stated as the code behaves: raw form CI-gated (true, and a good fix), file form a **disclosed, deliberately un-custodied posture declaration**. The circularity that justifies stopping there is recorded rather than dropped. **A documentation finding closes by correcting the document** — there is no code to re-verify, and the code was never the thing that was wrong. |
| **`A-04`** — a ledger row a later sweep proved false is still in the file, uncorrected | ✅ **CLOSED — and this ✅ is the re-auditor's, earned 2026-08-15, not the Builder's (`B-03`).** Same violation as `A-03`: the fixing session marked its own work confirmed. The re-audit checked it and found it correct. **What was done, 2026-08-14 — the false clause is struck, in this file.** *"Already declared with written reasons in `config/reachability-declarations.json`"* is struck through with the reason beside it: `windows_broker` appears **zero** times in that file. The module is recorded as **unreachable-AND-undeclared**, which is what it is. Whether to declare the symbol or leave it undeclared is a separate decision and is not made here. |
| **`A-05`** — Linux computes the payload digest with JCS, Windows with `serde_json::to_vec`, under one document asserting the two are byte-compatible | ◑ **Builder claims closed 2026-08-14; NOT independently re-checked.** `win-live/src/servers.rs` now digests the `output-captured` payload with `crypto::jcs(payload.as_object()?)` — the helper the same file already used for the record and receipt documents thirty lines away (`:949`, `:971`). Both **parsers**, the pair the audit named, now use one rule. `cargo check` clean; **101 win-live tests pass**. **Two things deliberately NOT done, stated rather than implied:** (1) the Windows **writer** (`execution.rs:161`) still emits `serde_json::to_vec`, under a comment arguing it is JCS-equivalent because serde's `Map` is a `BTreeMap` — true for these payloads, and changing the bytes that get chained and signed is not a side effect of fixing a parser. (2) **No test feeds a Linux-written chain to the Windows parser** — the enforcement the audit actually asked for. The existing tests feed the Windows writer to the Windows parser. Until such a test exists the byte-compatibility claim remains a Builder's assertion, and the doc comment now says exactly that. &nbsp; **◑ ITEM (2) IS NOW CLOSED — Builder's claim, 2026-08-15 (T-019), NOT independently re-checked.** `servers.rs::linux_written_chain_tests` builds the chain with the **Linux recorder's own** event shapes and its own encoder (`serde_json::to_vec`, never `crypto::jcs` — building the fixture with the parser's rule would have made the module a tautology) and feeds it to `derive_evidence`, requiring the derived head to equal the head the writer wrote. The fixture cannot drift: `the_model_matches_the_writer_it_claims_to_model` **reads `proof/src/bin/governed_recorder.rs`** and asserts every event type, payload key and the `serde_json::to_vec` rule still appear in it. **win-live 107 passed** (from 103). **6 mutants, 4 killed, 2 named survivors — and the survivors are the finding.** `M1`/`M2` put the parser back on `serde_json::to_vec` and **survive**, because with serde's `preserve_order` feature off a `Map` *is* a `BTreeMap`: the two calls are byte-identical for every input, so **the `A-05` fix changed the rule named in the code and not one byte on the wire**. That is worth stating plainly rather than leaving a reader to infer a behavioural fix. What the fix genuinely bought is now guarded: `M6` turns `preserve_order` on in `win-live/Cargo.toml` and kills `the_parsers_rule_is_canonical_rather_than_textual` — and **only** that test — because `crypto::jcs` sorts one level and hands the nested `payload` to serde untouched (its own doc comment says "a FLAT object"; an evidence event is not flat). `M3` (delete the `A-02` link check) and `M4` (delete the payload-digest check) are killed. `M4` **survived its first run**, masked by its neighbour — editing a payload after the fact breaks the link too, so the link check refused first — and was closed by a negative that only the payload check can catch: a recorder that chains correctly and lies about its own `payload_sha256`. Item (1) stands: the writers are still serde, deliberately. |

## Findings of the RE-AUDIT (2026-08-15, snapshot of `main` @ `0a9a1af`) — status

The Owner commissioned a re-audit of the third audit's five fixes. **Verdict: still RED — but now for
one platform rather than one mechanism.** Four of the five could not be reopened.

> **The auditor pinned a snapshot and proved it**, because `main` moved three times during the run
> (`e0dd969` → `0a9a1af` → `3b8acaf` → `f652d37`): `git rev-parse 0a9a1af^{tree}` and `git write-tree`
> in the export both gave `ca0b7de151ffc300b710ec80008575bd4bf46c2a`. Every read, test and attack ran
> against that tree. The commits after it touch only coordination docs.

| Finding | Status |
|---|---|
| **`B-01` (P2)** — `A-01` was fixed on Python/Linux only; the Windows twin still took the caller's `install_id` (`servers.rs:174`) and fed it to the floor's scope (`:1078-1085`), while the ledger row claimed "both platforms" | ◑ **Builder claims closed 2026-08-15; NOT independently re-checked.** `AuthorityConfig` (Windows) now carries `install_id` and `create_pending` refuses `install_id_mismatch`, sourced in production from `cfg.resolved.install_id` — the same deployment block the Linux authority reads, so the twins cannot drift on the value that scopes the floor. **Mutation-verified with a forced rebuild:** mutant → the new negative FAILS (102 passed / 1 failed); restored → **103 passed**. A positive control asserts the deployment's own id still passes. **The row it corrects is `A-01`'s, and the correction is the finding**: this is the F-02 pattern the header names. |
| **`B-02`** — the pin lives in the authority, not in the supervisor that owns the floor: one check, in a different service | 🔴 **OPEN, and deliberately still open after 2026-08-15 (T-019).** Recorded, not silently fixed. Moving or duplicating the check is a topology question — which principal is authoritative for the floor's scope — and it sits beside the **1b** decision (a floor-writer service that owns the marks directory would be the natural holder of the pin too). §I change-control, not a Builder edit. &nbsp; **T-019 looked at it and declined, with the reason written down rather than left as silence.** Both available Builder moves are wrong in the same way. *Move* the check into the supervisor and the authority stops refusing a foreign `install_id` at the door, so a misconfiguration that is caught today at `create-pending` would travel three hops before failing — and `governed_turn_open:487-488` already refuses when request and payload disagree, so the near check is load-bearing. *Duplicate* it and the deployment gains a second site that must agree with the first about which `install_id` is this install's, which is the "one contract, two implementations" shape this repository has now found **eight** times, in the one place where a disagreement silently widens an anti-rollback scope. Neither is an implementation detail: both change **which principal is authoritative** for the floor's scope, which is §I item 1 (architecture) and item 2 (trust boundary), and §I's own text makes bypassing it a stop condition. The Builder stops here. &nbsp; **CORRECTION, same day — the sentence that first stood here was wrong in the direction that matters.** It read *"what would settle it is the **1b** decision itself"*: future tense, as if a decision were pending. **1b was decided on 2026-08-14**, and the Owner's own reasoning already answers `B-02` — the floor-writer service *"is the natural place to pin `install_id` from trusted config as well — one principal, one trusted config, **both defects closed at the same boundary**"* (`docs/OWNER_ACTION_REQUIRED.md` §1b, reason 3, which names `A-01` and this row as two faces of one defect: *the floor is controlled by its own subject*). Writing "awaiting a decision" over a decision that has been taken is this file's own defect class, one tense away. **What is actually missing is §I step 2.** The decision ships with *"Owner approval (given, here) → Architect audit → implement. **No implementation lands on this decision alone.**"* — and the Architect had nothing to audit, because no design existed. [`docs/design/FLOOR_WRITER_SERVICE_DESIGN.md`](../../../docs/design/FLOOR_WRITER_SERVICE_DESIGN.md) is that proposal: §I step 1, which the roadmap's ownership matrix assigns to the Builder (🔨 proposal · 📐 mandatory audit · 🛑). It is a **proposal, not an implementation**, and `B-02` closes when it is Architect-GREEN and built — not before. |
| **`B-03`** — `A-03`/`A-04` were marked ✅ by the session that wrote the fix, violating this file's own legend | ✅ **Closed by the re-audit, not by the Builder.** The auditor checked both and **confirmed them substantively correct**, so ✅ is now earned — but it is the **auditor's** mark, and the rows say so. The Builder should have written ◑ and did not; that is recorded rather than quietly repaired. |

> **What the re-audit ran rather than believed.** It reproduced the Builder's `A-01` mutation claim
> end to end (baseline 19 OK → mutant FAILED → restored 19 OK, restore digest matching the committed
> blob — *"that was the biggest gap in my previous report"*), attacked `A-02` with **six** forged
> chains (tamper / reorder / truncate / `final_event_hash` substitution — **all refused**), and checked
> the risk the `A-05` fix itself created: the verifier is JCS while the writers are serde, so a
> divergence that used to be harmless would now refuse a genuine turn. On real events they agree and
> the live path is intact — **but that is still not protected by a test**, exactly as the `A-05` row
> already admits. It also re-checked the nine promotions in #100 for overclaim and found them clean,
> caveats carried, the two unresolved items correctly left unpromoted.
>
> **And it declined to call an artifact a defect.** The engine suite reported 2001 ran / 1 failure on
> the snapshot; the auditor checked the same test against the real tree on a byte-identical file,
> found it passing, and attributed the failure to its own `git init` export. The ledger's
> **2001 OK / 43 skipped** stands.

## Promotions from the THIRD independent audit (2026-08-14, `main` @ `e0dd969`)

**These are ✅ under this file's own legend** — an independent auditor looked, **tried to break them, and
failed**. Nine claims, reproduced as the auditor grouped them, with what was actually attacked. The full
text is [§3 of the report](./2026-08-14-zero-trust-audit-e0dd969.md). Fourteen `◑` claims were attacked;
these nine survived.

| # | Claim | ✅ what the auditor did |
|---|---|---|
| 1 | **The three production-gate refusals** | Read, not trusted: `governed_verification_unconfigured()` is `Some(...)` with **no branch** (`commands.rs:1305-1308`; this row cited `:1161-1164` — a doc comment about `AgentEvent` — until the seventh audit's `G-14`, the SECOND stale coordinate in this one sentence. The claim was true at both readings; only the line number rotted, which is what hand-maintained coordinates in an 833-line ledger do); `connect_broker` is `#[cfg(target_os = "linux")]`, every other host `UnsupportedPlatform` (`governed_turn.rs:230-253`; the `UnsupportedPlatform` return is at `:251` — this row cited `:225-232`, which does not contain it; corrected 2026-08-16 from the fifth audit's stale-row list, claim unchanged and re-confirmed); `build_governed_executor` returns `fail_closed()` unless `$BROPS_BROKER_CONFIG` is set and parses (`broker/src/main.rs:266-280`). **The gate is closed at this head.** |
| 2 | **F-01's second half — the `output_handle` sign-oracle** | **The previous round's P0.** Attacked the mechanism, not the wording, and **could not reopen it, on either platform.** Supervisor derives the head from the recorder's chain and refuses a completion whose `output_handle` the recorder did not capture (`governed_supervisor_ledger.py:624-685`, check at `:661-666`), on the only path to `COMPLETED`. Recorder no longer takes `--launcher/--executor/--store/--lease` from the broker's argv — root-owned policy at a compile-time path, argv disagreement refused. Windows twin refuses `evidence_mismatch`. Covered by a **real end-to-end negative**, not an assertion (`test_governed_chain_e2e.py:657-684`). |
| 3 | **`R-04` / F-08's OUTER equality** | *"a real gap"* — was asserted only by a deployment-time shell check. Now a runtime comparison: `verify_lease_matches_attested_request` refuses per-slot (`launcher/src/main.rs:491-505`), called before any drop or exec (`:592`), attested config read from a **compile-time** path so the broker cannot redirect it (`:586-591`). |
| 4 | **`R-03`'s store-input custody** | fds 3/4/5 are no longer "a regular file ≤ 8 MiB": each must be a regular inode owned by root/brops-admin with no group or other write bit (`launcher/src/main.rs:600-605`). |
| 5 | **The 45-skipped-test gap (§5.4) — 22 dead enforcement tests** | *"the cleanest fix in the wave."* `engine/tests/_engine_git_root.py:158-194` **manufactures** the precondition instead of skipping. Reproduced empirically: the previous audit measured **909 ran / 45 skipped**; this one measures **1995 ran / 43 skipped**, and the git-root skip is not among them. The two `skipUnless` lines a grep still finds are inside docstrings. |
| 6 | **The CI wiring claims** | Read from `ci.yml`, not from this ledger. `governed-crates` really tests all six production crates (`:68-70`); `engine-windows` really runs the engine suite on `windows-latest` (`:226-258`); the F-08 negative is real and wired — `run_live_turn.sh` tampers with a pinned store input and asserts the **cause** of the refusal (`:431-449`, `:465-482`), with two further negatives beside it. |
| 7 | **The DDL parity gate** | `check_ledger_ddl_parity.py` GREEN at this head, and the job is wired. |
| 8 | **The repository's own gates** | Ran all 19. Sixteen GREEN; three print usage (they take arguments); one RED for the documented reason (`check_bundle_budget` wants a Vite manifest). *"This matches `START_HERE.md`'s description exactly, including its correction of the older '15 gates, all green' sentence."* |
| 9 | **"The two F-01 regression tests assert only that an unknown attempt id is refused"** | The engine sweep declined to judge this. **They do not.** The module carries **16** tests — the substituted-reply negative, a no-chain-at-all negative, a smuggled-field negative, and an F-27 clock test pinning accept-at-T−2000 against complete-at-T. |

> **Two of the three "not verified deeply enough to claim either way" items stay unknown** and are NOT
> promoted: `build_tcb_pin_manifest.py` coverage-by-name, and `run_supervisor.py`'s §0.1 gate. The auditor
> drove neither. See §6 of the report for what this audit does **not** cover — chiefly that the **Linux
> live kit was not run** (Windows host), so every deployment-custody claim above is a **static read**.

---

## Round-2 remediation audit (2026-08-06) — RED, and what has been done about it

The SECOND audit of the remediation returned RED again. No new P0 was found, but the ground under
several "closed" verdicts was softer than it looked. Addressed here:

> **Marks in this table corrected 2026-08-07 (staleness sweep).** Every `✅ CLOSED` below was
> written by the session that wrote the fix, which is precisely what the status legend above says
> ✅ must NOT mean. They are demoted to ◑ — Builder's claim, nobody else has looked. Nothing about
> the code changed when the mark did; only the honesty of the mark.
>
> **Corrected 2026-08-09.** This paragraph claimed “the four rows that said ⚠️ OPEN … are now ◑
> with the code cited”. **Five** rows below say ⚠️ OPEN, and none of them was changed — the prose
> described an edit to the table that was never made, in the one file whose whole purpose is that a
> fixed finding and a forgotten one do not look identical. The table below is the record; where this
> prose and a row disagree, **the row wins and the prose is the defect.** The five ⚠️ rows are
> re-checks that a Builder staleness sweep believed had landed at `main` @ `0efa99e`; that sweep is
> a claim, so they stay ⚠️ until someone who did not write the fixes says otherwise. Evidence for
> every change is in the sweep table below.

| Finding | Status |
|---|---|
| **P1 — Windows signing seeds are plaintext until first read** | ◑ **Builder claims closed; NOT independently re-checked.** (Was marked ✅ by the fixing session; demoted 2026-08-07.) The named mechanism has since been replaced and strengthened: `win_provision::write_seed` no longer exists — every secret-bearing file is now created by `provision_custody::create_locked_file`, i.e. `CreateFileW` with a `SECURITY_ATTRIBUTES` already carrying the finished protected DACL, so the restrictive descriptor exists before the first byte does and `icacls` is gone from the seed path entirely (`win-live/src/provision_custody.rs:23-34`; call site `win_provision.rs:96`). `win_provision` additionally refuses a pre-existing deployment root it did not create (`check_root_custody`). This was the shortest path in the repository from an in-scope adversary to a forged `production_verified=true`: `attest.seed` + `signer.seed` are the two production keys `verify_and_accept` checks, and reading them skips the governed chain entirely rather than defeating it. `seedstore.rs`'s "the boundary is cryptographic, not just an ACL" claim is corrected — that is true AFTER the lazy seal, and the window before it was exactly the exposure. |
| **F-08's enforcement had zero tests** | ◑ **Builder's claim; NOT independently confirmed.** *(Was `✅ CLOSED`, written by the fixing session, in a table whose own header says every such mark was demoted on 2026-08-07. Three rows were missed; corrected 2026-08-09.)*  The four cited tests covered the lease parser and the fd→pin map; the digest-and-compare that IS F-08 had none, so deleting the check left every suite green. The decision is now a pure `verify_store_inputs` with 4 tests (per-slot mismatch, transposition, unreadable input), AND the live CI job runs a NEGATIVE case: it tampers with a pinned store input and requires the launcher to refuse. That is the test deleting the enforcement cannot pass. |
| **52 tests in the production crates run in no CI job** | ◑ **Builder's claim; NOT independently confirmed.** *(Same missed demotion; corrected 2026-08-09.)*  New `governed-crates` job tests launcher, executor, broker, live driver and both Windows crates. `brops-executor` was never compiled by CI at all. The Tauri host crate still is not built (webkit2gtk) — stated, not papered over. |
| Windows machine-proof script rejected by its own provisioner (exit 3) | ⚠️ OPEN |
| `bound` is a tautology (`CommittedMessage::new` hardcodes trust_state) | ✅ **WRONG ROW — corrected 2026-08-14 by the third independent audit** ([`2026-08-14-zero-trust-audit-e0dd969.md`](./2026-08-14-zero-trust-audit-e0dd969.md) §4). *"`trust_state` is a parameter (`core/src/governed_turn_ipc.rs:239-245`). The sweep recorded the correction and the row was never changed; it should be."* The finding was never true at this head. |
| `production_verified` never asks WHICH root anchor verified the manifest | ◑ **Builder claims closed; NOT independently re-checked.** `resolve_trust_state` now REQUIRES a `VerifiedManifestRoot` token, requires it to cover THIS manifest, and splits the verdict on `root.provenance()` (`core/src/production_trust.rs`). |
| **F-29 — the “bound-to-verifying-key” guard is a tautology** | ⚠️ **OPEN, and stated by the code itself.** Two rounds of fix left the comparison in `resolve_trust_state` unable to fail: every call site derives `envelope_verifying_key_hex` from `verifying_key_hex(...)` over bytes that the SAME `resolve_production_key` lookup produced. The check is KEPT as fail-closed defence in depth for a future call site that obtains its key another way; what is corrected is the claim. The property that holds today holds by CONSTRUCTION (one source, not two agreeing ones) — weaker than a check. `NEXT_CHAT.md` listed this CLOSED until 2026-08-09; it is a live keystone finding. |
| NULL DACL makes `FILE_FLAG_FIRST_PIPE_INSTANCE` inert | ✅ **CLOSED — independently confirmed 2026-08-14** ([third audit](./2026-08-14-zero-trust-audit-e0dd969.md) §4). *"`win-live/src/pipe.rs` builds a real DACL (`:62`, `:146-150`) and a test asserts the pipe must **not** have a NULL DACL (`:572`), with a note that a regression restores it (`:470`)."* Marked ⚠️ OPEN here while the code was closed. |
| A failed model call is replaced by a hardcoded constant the chain then signs | ◑ **Builder's claim; NOT independently confirmed.** *(Same missed demotion; corrected 2026-08-09.)*  The fallback itself is legitimate — the self-test exists to prove the CHAIN, with or without a model — but it was INVISIBLE: no `BROPS_SELFTEST_MODEL_CMD` (the default), a spawn failure, a non-zero exit or empty output all silently became a built-in constant that the chain bound and the UI showed beside `trusted_verified`. The receipt was honest about custody and the screen was misleading about what answered. `AnswerSource` now travels with the answer (model / no-model-configured / model-failed), the UI renders **NO MODEL RAN** and says which of the two reasons, and 3 tests cover all three cases. |
| Windows kit: no §2.5 floor, no anti-rollback floor | ✅ **BOTH HALVES EXIST — independently confirmed 2026-08-14** ([third audit](./2026-08-14-zero-trust-audit-e0dd969.md) §4). *"`win-live/src/tcb_floor.rs` is 834 lines; the anti-rollback floor runs through `brops_core::supervisor_ledger::evidence_floor_cas` with `head_sequence` from the durable counter in `win-live/src/head_sequence.rs`."* **Read with `A-01`/`A-02`** — those are defects **in** the floor, not its absence, and they are open. |

## Keystone soundness-blockers (independent audit 2026-08-06) — the gate depends on these

The gate cannot be flipped until every row here is ✅, a SEPARATE audit passes, and the Owner
approves. **Read that literally: ✅ in this file means an independent audit confirmed it, and no
independent audit has confirmed ANY row below.** Five rows carried ✅ written by the session that
wrote the fix until 2026-08-09 — the exact failure mode the legend above exists to prevent, in the
table the gate depends on. They are ◑. *(This sentence also named
`platform_governed_execution_supported()` as the gate; no function of that name exists in the tree —
it is the §0.1 spec symbol. The real refusals are named in `docs/OWNER_ACTION_REQUIRED.md`.)*
audit passes, and the Owner approves. See [`NEXT_CHAT.md`](../../../NEXT_CHAT.md) for the full text.

| Finding | Status | Note |
|---|---|---|
| **F-01** supervisor `attest-run` sign-oracle (🔴 P0) | ◑ **P0 addressed 2debb71; NOT re-audited** | §5 v2 durable-supervisor amendment: `attest-run {run_id, execution_attempt_id}` only; `build_run_attestation` has no `facts` parameter; evidence built from the supervisor's own durable terminal state over a CI-gated shared DDL (`tools/check_ledger_ddl_parity.py`). Fixed in **both** supervisors (Linux Python + the Windows proof-kit Rust twin). Proven end-to-end offline by `engine/tests/test_governed_chain_e2e.py` (real 3-key chain, ledger restarted mid-turn). A fabricated run gets `no_terminal_run_state`. **CI:** the Linux 7-service `run_live_turn.sh` is GREEN on this protocol and now runs on every CI event (`live-governed-turn`, run 31078055077 at `a64c8cc`): `production_verified=true bound=true` across six real uids, SO_PEERCRED and the setuid launcher. **Narrowed, not removed.** `output_handle` — the digest of the exact reply the desktop commits — is still reported by the executing chain (`COMPLETION_HANDLE_FIELDS`) and copied verbatim into the signed evidence; the isolated signer 're-derives' it from a content-addressed store, which is tautological. The supervisor still never observes the execution it attests. The recorder's own `output-captured` event already measures `output_sha256` — nothing compares the two. **Addressed (PR #56):** the supervisor reads the recorder's evidence chain from a directory the broker cannot write, derives the evidence head from it, and refuses a completion whose `output_handle` the chain did not record. The four `evidence_*` values are gone from the wire. **This closure has not been checked by anyone except its author** — the two prior rounds both found the previous closure overclaimed, so this row stays ◑ until an independent audit says otherwise. |
| **F-23** unsigned/decorative supervisor lease | ◑ closed with F-01; Builder's claim, NOT independently confirmed | `launch-gate` takes only `{execution_attempt_id}`; the caller no longer presents the lease it is judged against. |
| **F-09** acceptance CAS + evidence floor unwired | ◑ **partly** | Both halves now run: the acceptance CAS makes one signed challenge worth one attempt, and the anti-rollback/anti-fork floor runs on every `complete-run`. |
| **F-11** oversize error reply tears down the supervisor | ◑ supervisor leg closed; Builder's claim, NOT independently confirmed | Error text bounded; `_try_write` degrades instead of letting a `FrameError` escape `serve_forever`. The other proof-kit DoS legs (F-31/F-32/F-36) are still open. |
| **F-02 / F-18** static evidence facts | ◑ **addressed on both platforms; NOT re-audited** | Now per-run: `receipt_id` (supervisor-minted, `UNIQUE`), and `record_handle` / `lease_handle` / `execution_receipt_handle` — the supervisor BUILDS a governed-turn record + execution receipt from its own rows, addresses the exact persisted lease bytes, and publishes all three to the protected store; they left `produced` entirely, and the live kit's placeholder blobs are deleted. `containment_evidence_handle` is now written per run by the RECORDER (`--containment-out`: pinned image digests, lease digest, cgroup, the §2.7 fd contract, invoker uid/gid, launcher exit) and content-addressed by the broker; a missing report is a refusal. **Still open:** the four `evidence_*` counters — nothing measures a real recorder evidence chain, and they are now the ONLY static values left in the live kit's `facts` block. **Second half now closed:** the four evidence-head values (`final_event_hash`, `event_count`, `last_sequence`, `head_sequence`) were deployment constants in `provision_keys.py`, so every receipt of the deployment named the same evidence head and the supervisor's anti-rollback floor compared a constant against itself. The RECORDER now builds a hash-linked three-event chain of what it observed for the run (`lease-validated` → `execution-launched` → `output-captured`, each carrying `previous_event_hash`) and writes the head to `--evidence-out`; the broker PARSES that file and reports those values to `complete-run`. `head_sequence` comes from a recorder-owned durable counter (`recorder-state/`, 0700) so it grows across runs, which is what the floor needs to order anything. A missing or malformed chain REFUSES the turn — there is no config fallback left to fall back to. 3 new tests. **The Builder's ✅ was wrong.** The Linux recorder does measure a real chain, but `win-live/src/execution.rs:132` still sends the four `evidence_*` deployment constants, so the original defect is live on the platform where `production_verified=true` was actually demonstrated. Marking this CLOSED on one platform's evidence is exactly the overclaim this ledger exists to prevent. **Reclosed on BOTH platforms (2026-08-06, post-audit):** the Windows twin no longer sends the four `evidence_*` constants — `win-live` measures its own `brops.run-evidence-chain.v1` (byte-compatible with the Linux recorder's) and the Windows supervisor derives the head from it and refuses an `output_handle` the chain did not record. 3 new tests, and they run on the LINUX CI runner, which is what the kit's zero coverage cost us the first time. |
| **F-08** request↔output unbound | ◑ CLOSED (2026-08-06); Builder's claim, NOT independently confirmed | The three request inputs are now PINNED in the root-owned §4.3 lease (`system_sha256`/`history_sha256`/`generation_config_sha256`, each required — a lease that omits one does not parse) and the setuid launcher re-hashes the HELD fds 3/4/5 against those pins with `pread` from offset 0 (no path re-lookup, offset undisturbed) BEFORE the privilege drop and the exec. Overwriting `<recorder_store_dir>/system` after provisioning now refuses the launch instead of running prompt A under a receipt attesting prompt B. `run_live_turn.sh` derives the pins from the provisioned store bytes and asserts they equal the `resolved.*_sha256` the supervisor attests from, so launcher pin = executed bytes = attested digest. 4 new tests. |
| **F-10** §2.5 TCB integrity floor has no caller | ◑ **PARTIAL (remediation audit)** | The floor now has a real probe, real callers, and a real manifest to enforce. `brops-broker::tcb_probe::LinuxFsProbe` stats through `O_PATH|O_NOFOLLOW` and digests contents; the production broker AND the live driver run `verify_deployment_tcb` before they will serve a governed turn, refusing on an unconfigured, unreadable, malformed or violated manifest. `build_tcb_pin_manifest.py` emits the full `TCB_REQUIRED_ARTIFACTS` set for the live kit — every entry a real digest of a file that genuinely serves that role, built AFTER the lease/anchor/allowlist exist and BEFORE any service starts. The `*.ipc-policy` roles are now real: each server loads its own root-owned `brops.ipc-policy.v1` file instead of reading its peer-auth rule out of the shared config, and refuses to serve without it. 3 new tests + 4 refusal tests. Real on Linux; **absent entirely on Windows**, which has no §2.5 floor at all. |
| **F-07 / F-17 / F-28** self-certifying + world-writable custody | ◑ CLOSED (2026-08-06); Builder's claim, NOT independently confirmed | **F-17:** the root anchor moved out of the shared config into a root-owned TCB file that STATES its provenance; the driver checks that file under the §2.5 owner/mode floor, REFUSES a config still carrying an inline anchor, and will not report `production_verified=true` unless the provenance is `external`. The kit-generated default now prints `production_verified=false root_anchor=kit_generated` — the chain result is unchanged and honestly labelled. `provision_keys.py` accepts an external anchor plus the manifest IT signed (all four flags or none) and serves those bytes verbatim. **F-07/F-28:** the store/report/socket dirs are no longer `1777` — each is group-owned by exactly the principals that write it (`brops-store`: supervisor+broker, world-readable for the signer; `brops-report`: recorder+broker, no world access; `brops-ipc`: the socket binders), setgid so new files inherit the group. Integrity still does not depend on these modes, which is why they cost nothing to get right. 4 new tests. |
| **F-26 / F-27 / F-29** decorative binding checks | ◑ **F-26/F-27 closed; F-29 claim corrected, guard kept** | **F-26:** `verify_and_accept` now binds the signed `run_id`/`task_id`/`execution_attempt_id` to the run the broker authorized (its own resolution + the attempt id from the lease it obtained); three negative tests. **F-27:** `challenge_accepted_at_ms` is the supervisor's accept clock from the acceptance row, not the broker's completion clock — closed by F-01 and now asserted end-to-end (accept at T−2000, complete at T). **F-29:** the production verdict is compared against the key the CHAIN verified under (`verifying_key_hex` of the bytes handed to `verify_and_accept`), not a second manifest lookup of itself; the second lookup is retired to an early resolvability check. **The remediation audit finds F-29 still open** — the `verifying_key_hex` change did not make the guard load-bearing. See `2026-08-06-remediation-audit.md`. **F-29 corrected, not re-closed (2026-08-06):** the remediation audit (R-39) showed the guard is still incapable of failing — both operands come from the same `resolve_production_key` over the same manifest and key_id, and `hex32`/`verifying_key_hex` are an exact round trip. The check is KEPT as fail-closed defence in depth for a future call site that obtains its key another way, but it is no longer cited as what binds the trust verdict to the verifying key. That property holds by CONSTRUCTION: every call site derives the key it hands `verify_and_accept` from the same resolution. A guard that cannot fail is not evidence. |
| **F-31 / F-32 / F-36** proof-kit DoS | ◑ closed 2026-08-06; Builder's claim, NOT independently confirmed | **F-31:** every accepted broker connection is armed with a read/write deadline, so a silent renderer-uid peer can no longer hold the serial accept loop forever. **F-32/F-36:** the renderer→broker client sets read/write timeouts at connect and caps ingress with `take(MAX_REPLY_BYTES)` BEFORE buffering — the framing cap only ran in `decode_one`, i.e. after the bytes were already resident, so it bounded nothing on the direction the desktop reads. |
| **F-06 / F-13 / F-14** engine anti-rollback honesty | ◑ **R-06 addressed 2debb71; NOT re-audited** | **F-06:** `_pin_from_file` checked that group/other cannot write the anchor but never WHO owns it, so a file the reading account owned at 0644 passed while staying one write away from being any anchor that account liked (the Windows DACL branch had the same hole by construction — it skips owner and OWNER RIGHTS ACEs). Both platforms now refuse a self-owned pin: POSIX compares `st_uid` to `geteuid()`, Windows compares the owner SID to the process token's user SID. A deployment with no principal separation must say so explicitly via `BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged`, and the module's claim that the trust root cannot be swapped by environment variables alone is now stated with that condition attached. 1 new test; 903 engine tests green. **F-13/F-14:** the L-4 stale-head floor was read from the very head it polices (`load_head(...).head_sequence` fed back in as `min_head_sequence`, so `validate_chain` compared `x >= x`) and every production caller passed `None`, so it could not fail on any path. The high-water mark is now a DURABLE per-task record (`<store>/head-floor/<task>.floor.json`, or `BRO_EVIDENCE_HEAD_FLOOR` for a deployment that can put it under a principal the builder cannot write), advanced only after a chain verifies and only upward. A retained older-but-genuinely-signed head re-presented on a later call is now refused; a damaged mark refuses rather than reading as absent. 3 new tests. The remediation audit finds the durable mark does not close the rollback, and every F-06 test is skipped on Windows so the SID comparison is unverified. See the report. **F-13/F-14 re-addressed (2026-08-06, audit R-06):** the durable mark was defeated by the SAME capability the original attack needed — write access to the evidence store. `rm -rf head-floor/` made the floor silently stop existing, and `BRO_EVIDENCE_HEAD_FLOOR` was ungated. Now: an absent floor directory REFUSES instead of reading as 'no floor required' (bootstrapping is a deliberate act), a `_index.json` roster catches the removal of any single task's mark, the floor directory is held to the same self-owned-custody rule as the operator pin, and a recorded 0 is no longer coerced to 'no floor'. 3 new tests. **F-06 re-addressed (2026-08-08, PR #72):** the sentence above — *"Windows compares the owner SID to the process token's user SID"* — described a check that did nothing where it mattered. An administrator does not own the files they create; `BUILTIN\Administrators` does, so the comparison came back unequal and the refusal silently did not apply to the most privileged account on the box. It passed on a workstation and failed to fire on the CI runner. Windows now asks `AccessCheck` — the evaluation the kernel itself performs on open-for-write, against the whole descriptor and the whole token, including rights arriving through a group and the owner's implicit `WRITE_DAC` — plus a separate test for `SeTakeOwnershipPrivilege`/`SeRestorePrivilege`, which `AccessCheck` deliberately ignores. POSIX gained the two cases its `st_uid == geteuid()` proxy missed: running as root over someone else's file, and a writable containing directory (the file can be replaced whatever its own mode says). The ledger's other stale claim — *"every F-06 test is skipped on Windows so the SID comparison is unverified"* — is also closed: the `engine-windows` job runs the engine suite on `windows-latest`, which is how this was found at all. The report above stays as written; it was accurate when written. |

## Desktop tickets — from the 2026-07-19 BroPS audit (ticket files removed 2026-08-08)

> **Every ✅ in this table was written under the file's OLD, weaker legend (“Builder has code evidence”) and means ◑ under the legend at the top of this file: nobody independent has re-checked it. Read them as ◑. Re-marking them row by row is outstanding — inventing statuses for them would be the defect this file exists to catch.**

> The thirteen ticket files, the audit report and its README were deleted: every one was a
> **read-only proposed patch** against `menqstudio/BroPS` at a single commit, all of them landed,
> and the README's instructions ("hand a coding agent `tickets/H-1-…`") pointed at a workflow that
> no longer exists. **This table is the surviving record** — it already carried each ticket's
> status and evidence, which is why deleting the files loses nothing. Git history has the full
> text if a finding ever needs re-reading.

| Ticket | Status | Evidence / note |
|---|---|---|
| `H-1-migration-atomicity` | ✅ fixed | `core/src/db.rs` runs migrations under `BEGIN IMMEDIATE` (atomic); confirmed by the independent audit's D-06 check. |
| `M-1-approval-self-service` | ⚠️ by-design | Native OS confirmation is the real anti-self-approval barrier; the durable-principal self-approval guard is vacuous BY DESIGN (see independent audit **F-30**). Not a live hole. |
| `M-2-approval-matching` | ✅ fixed | `approvals::consume_for` — one grant unlocks exactly one completion. |
| `M-3-set-step-result-gate` | ✅ fixed | `set_step_result` removed (latent T-011 bypass); completion goes through the attempt-guarded path. |
| `M-4-run-step-prompt-injection` | ◑ mitigated | `sanitize_author` (control+colon strip, 64-cap) + bounded run fields; the colon turn-forgery PoC is defeated. Residual: a stricter agent-name allowlist (independent audit **F-40**) — tracked, deferred. |
| `M-5-write-transactions` | ✅ fixed | Renderer-driven writes are atomic (single-tx gate+write). |
| `M-6-advance-status` | ✅ fixed (2026-08-06) | `runs::advance` bound its completion to the single approval-checked step instead of every `status='active'` row (independent audit **F-12**; commit `5548ab4`). |
| `M-7-ci-permissions` | ◑ partial | CI jobs run least-privilege (`contents: read`); some supply-chain gaps remain open in the independent audit (**F-15/F-20/F-45/F-46** — F-46 fixed, F-15/F-45 fixed, F-20 owner-gated). |
| `M-8-app-command-capability` | ✅ fixed | T-010 capability wall + `check_capabilities.py` now captures every module prefix + `INTENTIONALLY_UNGATED`; regex-blindness (independent audit **F-03/F-05/F-43**) closed on this branch. |
| `L-1-availability-dos` | ◑ partial | Several fail-closed/bounded hardenings shipped; proof-kit DoS surfaces remain (independent audit **F-11/F-31/F-32/F-36**, keystone-class). |
| `L-2-info-disclosure-hardening` | ◑ not re-verified | See independent audit for current-code state. |
| `L-3-data-integrity` | ◑ not re-verified | See independent audit for current-code state. |
| `L-4-identity-audit-hygiene` | ◑ not re-verified | See independent audit for current-code state. |

## Engine tickets — `engine/AUDIT/tickets/` (registered in `engine/config/documentation-manifest.json`)

> **Every ✅ in this table was written under the file's OLD, weaker legend (“Builder has code evidence”) and means ◑ under the legend at the top of this file: nobody independent has re-checked it. Read them as ◑. Re-marking them row by row is outstanding — inventing statuses for them would be the defect this file exists to catch.**

| Ticket | Status | Note |
|---|---|---|
| `C-1-find-readonly-bypass` | ◑ see F-04 | `git -C`/`--git-dir`/`--work-tree` read-containment fixed 2026-08-06 (independent audit **F-04**, commit `5548ab4`); review the ticket's other cases against current `bro_security.py`. |
| `H-1-unsigned-workspace-binding` | ◑ not re-verified | — |
| `H-2-windows-emit-crash` | ✅ fixed | Windows emit hardened (fail-closed). |
| `H-3-windows-fail-open-wiring` | ✅ fixed | `bro_live_validate.py` proves 17/17 laws LIVE_PROVEN incl. the Windows leg (now run in root CI — independent audit **F-22**). |
| `H-4-forgeable-audit-trail` | ⚠️ OPEN (keystone-class) | Anti-rollback/audit-head remediation is partly unwired (independent audit **F-06/F-13/F-14/F-41/F-42**). |
| `H-5-registry-anti-rollback` | ⚠️ OPEN | Registry anti-rollback floor; see independent audit. |
| `H-6-protected-set-gaps` | ⚠️ OPEN (O-1) | **bytecode-shadow (O-1, HIGH):** *(Corrected 2026-08-09 — this cell said `assert_no_bytecode_shadow` “has no caller and the wall is not run with `-B`”. Both halves are false today and `CLAUDE.md` §6 has said so since: it has three real callers (`bro_control_plane.py:80`, `:271`, and `bro_protected.verify_control_plane_digest`) and every hook interpreter runs `-B`.)* What is actually open is the READ half, which cannot be closed from inside Python: `-B` stops bytecode being written; nothing stops CPython reading a `.pyc` planted before the process starts, which shadows the very module that would detect it. The compensating rule is that the engine refuses a control plane the running account can write — free from a packaged install, and needing verification on a packaged build rather than assertion (independent audit **D-09**). Fix is trust-critical + interacts with the CI `compileall` step — deferred to focused keystone-class work. |
| `LOW-findings` / `MEDIUM-findings` | ◑ mixed | Bundle files; see the independent audit + `BroCore_Audit_Report.md`. |

## Desktop-surface sweep (2026-08-10, `at-main-2`) — **Builder's claim, nobody else has looked**

Every mark in this section is **◑**. Nothing here has been independently audited, and the RED verdict
above still stands. The sweep covered the 29 LIVE findings from the consolidated index whose fix lands in
`apps/desktop/src/**`, `apps/desktop/src-tauri/src/**` or `apps/desktop/src-tauri/core/src/**`.

**Note on sources.** `2026-08-06-consolidated-index.md` is the only index of all three rounds. The round-2
and round-3 detail files **do not exist in the tree** — only round 1 survives, as
`2026-08-06-remediation-audit.md` — so R2/R3 titles are truncated at roughly 110 characters and were
verified against the code rather than against their own text.

### One row in this ledger is WRONG, not merely stale

R2 `core/src/governed_turn_ipc.rs:239` is listed **⚠️ OPEN** on the claim that `CommittedMessage::new`
hardcodes `trust_state`, making `bound` a tautology. It does not: `trust_state` is a **parameter**
(`governed_turn_ipc.rs:239-254`). The row describes code that no longer exists. Recorded here rather than
silently edited, because a ledger that quietly repairs itself is the failure this file exists to prevent.

### ◑ Already closed by later work — the ledger did not know (12)

| id / loc | claim | why it is closed |
|---|---|---|
| R3 `src/commands.rs:1064` | unescaped `"Name: text"` speaker protocol | `cde5279` — the turn format is `AUTHOR ": " JSON-STRING`, injective |
| R3 `src/commands.rs:1072` | roster names raw into every system prompt | `cde5279` — `validate_roster` rejects rather than truncates, plus a splice-side defence |
| R3 ×2 `src/ai.rs:1072` | coding-agent auto-approve / undocumented env var | `cde5279` — `BRO_PROTECTED_PATHS` + `TrustSurfaceGuard`, settling on `Drop` |
| R2 `core/src/repo.rs:660` | M-1 self-approval guard cannot fire | **F-30**, `dc4735a` |
| R2 `core/src/governed_turn_ipc.rs:239` | `bound` tautology | **the ledger row is wrong** — see above |
| R2 `core/src/governed_verification.rs:209` | replay defence only `InMemoryLedger` | `broker_turns::DurableAcceptanceLedger`, `BEGIN IMMEDIATE`, opened at `broker/src/main.rs:401` |
| R2 `core/src/production_trust.rs:49` | `production_verified` never asks which root anchor | `resolve_trust_state` requires a `VerifiedManifestRoot` and splits on `root_provenance()` |
| R2 `src/governed_selftest.rs:88` | failed model silently replaced by a constant | `AnswerSource` travels with the answer; 3 tests |
| R2 `src/features/Settings.tsx:361` | unconditional "fail-closed, verified-receipt-mandatory" | gated on `isGoverned && ready` |
| R2 `src/features/Onboarding.strings.ts:21` | onboarding promises lease+receipt for all model calls | `howBody` names the condition and says "That is NOT the default" |
| R2 `src/services/governedTurn.ts:121` | zero UI callers | `Bridge.tsx:181` calls it |
| R3 `src/features/Decisions.tsx:321` | empty record set reported `ok` + a green node | explicit `n == 0` branch |
| R3 repo badge join on a non-unique column | | aggregate projection, `COUNT(*)=0 ⇒ NULL`, weaker-wins, migration 0023 |
| R3 `src/governance.rs:248` | GREEN verdicts from an unauthenticated source | `authenticated: RECORDS_ARE_AUTHENTICATED` (false) + a UI tag |
| R3 `src/files.rs:200` | two distinguishable error strings → existence oracle | one `PATH_REFUSED` for every branch |

### ◑ Fixed in this sweep (4)

| finding | what it actually was |
|---|---|
| `core/src/supervisor_ledger.rs:358` | `accept_prepare`'s idempotency comparison called itself "deliberately exhaustive over the durable request binding" and hand-listed **16 of 24** bound columns. The five it never looked at were `challenge_accepted_at_ms` and all four `challenge_registry_*` — **including the anti-rollback `epoch`**. A retry re-presenting the same nonce under a **rolled-back registry epoch** was answered `Idempotent`, "the same turn". Replaced with a `#[derive(PartialEq)] struct DurableBinding`, so the field list *is* the comparison. **The Python twin `governed_supervisor_ledger._BOUND_FIELDS` omits exactly the same five and is NOT fixed** — it is another agent's file this round, so the Rust side is currently stricter than the Python side. |
| `src/governed_turn.rs:85` | no total deadline on the renderer→broker read. `SO_RCVTIMEO` restarts per byte, so 8256 bytes × 120 s could hold a synchronous Tauri command for roughly **11.5 days**. Now `EXCHANGE_BUDGET_MS`, with the loop and its arithmetic lifted **out of `mod linux`** — the previous bound lived where no non-Linux suite could reach it. Includes the guard that returns `None` rather than arming `Duration::ZERO`, which POSIX reads as *infinite*, at exactly the moment the bound matters most. |
| `core/src/repo.rs:1116` | the demonstration badge was a bare flag row. It is the **only green badge the shipped app can display**, and `demonstration_verified_reply` `remove_dir_all`s the chain's working directory before writing it, so every artifact was destroyed and `(message_id, recorded_at)` was the whole evidence. Migration **0024**: the row carries the SHA-256 of the exact bytes the chain bound, written in the same transaction as the message, recomputed on read. Pre-0024 rows are `NULL` and **lose the badge** — back-filling them from the body they sit beside would manufacture the evidence. |
| `src/features/Conversations.tsx:372` | Demo-verify made the thread render every session message twice: `s.reload()` refetched history while `extra` still held the streamed copies, so `[...history, ...extra]` duplicated each under colliding `key={m.id}`. Now `mergeThread`, preferring the persisted row because it carries the badge. |

### ◑ Deliberately NOT fixed, with reasons

* **`production_trust.rs:73` (F-29 tautology)** — real, and the code and this ledger already say so. There
  is exactly one key source, so no call site can make it fail; the property holds by construction.
  Deleting it removes a fail-closed guard for a future caller, and "fixing" it means inventing a second
  source. Left with the honest comment.
* **`windows_broker.rs:272` unreachable, and `governed_output_stream.rs` §4.10(f)** — wiring either makes
  a governed surface reachable, which is forbidden. ~~Already declared with written reasons in
  `config/reachability-declarations.json`.~~ **STRUCK 2026-08-14 — that clause was FALSE** (audit `A-04`).
  `windows_broker` appears **zero** times in `config/reachability-declarations.json`; its `rust_symbols`
  block holds exactly six entries — `pull_output`, `governed_pull_output`, `governed_turn_output_read`,
  `prepare_governed_turn_v1b`, `resolve_governed_generation_config_v1b`, `governed_turn_submit_prepared` —
  and names no symbol in `windows_broker.rs`. The Windows sweep below recorded this as false and chose to
  report rather than silently edit; the row it contradicts stayed, and **a reader hits the false one
  first.** By that config file's own vocabulary the module is *unreachable-AND-undeclared* — the state it
  calls the one nobody can diagnose. **`governed_output_stream.rs` is gone entirely** (deleted 2026-08-12,
  zero production callers), so only the `windows_broker` half of this row survives at all.
* **`governed_verification.rs:276`** — §7.1's mandatory freshness step really is absent;
  `verify_and_accept` is documented "no clock" and `FreshnessWindow` exists only on the v1
  `receipt_store` path. Fixing it changes the signature and the caller in `broker/src/chain_executor.rs`,
  outside this sweep's surface and adjacent to live work. **Recommended as the next item.**
  **Closed in the freshness round below (2026-08-10, same day, separate session) — ◑, Builder's claim.**
* **`supervisor_ledger.rs:779`** — `final_event_hash` validates case-insensitively and compares
  case-sensitively. True, but it fails **closed** (a re-cased retry reads as `EvidenceFork`, never as a
  bypass), and the Python twin behaves identically; fixing only the Rust side would create twin
  divergence on a CAS for an unreachable corner.
* **`0014_*.sql:57`** — the comment "cannot be turned into a storage-DoS vector" is false (per-row cap, no
  row cap). Editing an already-applied migration's bytes to correct a comment is not worth the
  migration-ledger risk. Reported, not changed.

### Mutation results

13 killed. **Two survived, and the reason is the point:** the first badge implementation had two guards —
`AND d.body_sha256 IS NOT NULL` in SQL and the digest comparison in Rust — and deleting **either one alone
changed nothing**, because each masked the other. The SQL guard could not change any outcome, so it was
deleted rather than shipped, leaving one decision point that can fail. Re-run after collapsing: no
survivors.

Numbers, each from a run performed for this sweep and re-run independently before the commit:
`brops --lib` **124**, `brops-core --lib` **314**, frontend **69 files / 638 tests**, `tsc --noEmit` clean,
`check_ai_surfaces` / `check_capabilities` / `check_reachability` GREEN. No gate was touched.

## §7.1 freshness round (2026-08-10, `at-main-2`) — **Builder's claim, nobody else has looked**

Every mark here is **◑**. It closes exactly one row of the sweep above — the one that sweep named as its
next item — and touches nothing else.

### What the finding was

`verify_and_accept` decided acceptance with **no bound on how old the receipt was**. Every check it made
is time-free: a signature that verified when it was minted verifies forever, and the identity/binding
equalities hold forever too. The acceptance ledger is a **replay** defence — it stops the same receipt
being accepted twice — and has no opinion at all about a receipt that has never been accepted and was
signed a year ago. §7.1's "Freshness" bullet is the missing property, and it was missing.

### ◑ Fixed

| where | what |
|---|---|
| `core/src/governed_verification.rs` | New `check_receipt_freshness`, called at step **4d** (after the attestation turn-binding, before the output digest and before the ledger claim, so a stale receipt burns neither 8 MiB of hashing nor the one-time nonce). It bounds **both** signed `_ms` fields — `challenge_accepted_at_ms` and `completed_at_ms` — inside the §1-LOCKED `FreshnessWindow{future_skew_ms: 60000, max_age_ms: 300000}` (the real `receipt_store` constant, reused not re-declared), inclusive on both ends per §1; enforces the §1 integer range `1 ≤ v ≤ 2^53-1` on both fields **and on the clock**; and enforces the §7 ordering `challenge_accepted_at_ms ≤ completed_at_ms`. New `Freshness` type: private fields, one public constructor `Freshness::at(now_ms)` that always installs the locked window, and a checker that refuses any window **wider** than it — there is no way to express "unbounded". |
| `broker/src/chain_executor.rs` | New `WallClock` seam + `SystemWallClock`; `GovernedChain::new` installs the real clock, `with_clock` is the test-only override. The clock is read **at acceptance**, not at turn start, because the receipt ages while the turn executes. An unreadable clock returns `None` and **Blocks** — it is never `unwrap_or(0)`, which would collapse the window to `[-300000, 60000]` and make every 1970-stamped receipt "fresh". |
| `win-live/src/proof.rs` (tests only) | The in-process proof tests pinned `1_900_000_000_000` — the year 2030 — as "a fixed, plausible wall clock". With a real acceptance clock that is a skewed receipt, and it Blocks. They now use the host's real clock, which is also what both **shipped** callers of `in_process_turn_produce` (`governed_trust_selftest`, the demonstration-chat command) pass. A new test asserts a run under a fabricated clock (±10 years) cannot commit in either direction. |

### The arithmetic, done rather than asserted

A cap larger than the largest legal input is a check that cannot fail, so:
`LEASE_DURATION_MS` = **210000** (§4.3 pins `lease_issued_at_ms == challenge_accepted_at_ms` and
`completed_at_ms ≤ lease_expires_at_ms`), challenge TTL ≤ **30000**, sum **240000 < 300000** — and
`300000 − 210000 = 90000 ms` of budget left for the broker's own post-completion work.
`the_locked_window_nests_the_whole_legitimate_lease_budget_with_real_slack` asserts all of it **and**
shows both edges on the real verifier: a turn at the worst legitimate age is accepted, one millisecond
past `max_age_ms` Blocks.

### Mutation results

**18 mutants, 17 killed, 1 survivor, named.** Every mutant was applied to the shipping source, the named
test watched to fail, then the file restored byte-exact and the restore verified by SHA-256.

Killed: removing the freshness call (8 tests); stale limit off by one; future limit off by one; window
bounds made exclusive at the edge; dropping the `now_ms` range check; dropping the §1 `_ms` range check;
dropping the ordering check; dropping the window-configuration guard; bounding only one of the two `_ms`
fields; widening the locked window to a year; narrowing it to 60 s; zeroing the future skew; feeding the
verifier the receipt's own timestamp as the clock; the shipped `GovernedChain::new` installing a fixed
far-future clock; computing both bounds over `completed_at_ms` only; moving freshness after the ledger
claim; and letting the win-live proof caller choose the acceptance clock.

**Survivor — `self.clock.now_ms().unwrap_or(0)` in place of `.ok_or(Block)?`.** It survives because it is
**behaviourally equivalent**: `now_ms == 0` is outside §1's `1 ≤ v` range, so the core refuses it anyway.
No black-box test can separate the two, since both produce the same `UpstreamBlocked`. It is
defence-in-depth overlap, not a hole — and it is left in the report rather than killed with a test written
only to kill it.

### Numbers, each from a run performed for this round

`brops-core --lib` **323** (314 before, +9), `brops-core` all targets **363** (323 + 4 + 9 + 10 + 17),
`brops --lib` **124** (unchanged), `brops-broker` **31 lib + 3 main** (27 + 3 before, +4),
`brops-win-live --lib` **83** (82 before, +1), frontend **69 files / 638 tests**,
`check_reachability.py` GREEN (exit 0), `check_spec_references.py` GREEN (exit 0).

Pre-existing and untouched: `brops-audit-signer --test anchor_end_to_end` has 2 failures on this box —
one is the declared-prerequisite panic for `windows-elevated-registration` (this session is not elevated)
and one is an engine-side anchor case. Neither crate depends on the changed code.

No gate was flipped: `governed_verification_unconfigured`, `UpstreamBlockedExecutor` and `connect_broker`
are byte-untouched (`apps/desktop/src-tauri/src/**` and `broker/src/main.rs` have no diff).

## Windows / provisioning-crate sweep (2026-08-10, `at-main-2`) — **Builder's claim, nobody else has looked**

Every mark in this section is **◑**. The RED verdict above still stands. This sweep covered the 39 LIVE
findings from the consolidated index whose fix lands in `win-live/**`, `win-broker/**`, `provision/**`,
`launcher/**`, `executor/**`, `audit-signer/**`, `proof/**`, `core/src/windows_broker.rs` or
`src/governed_selftest.rs` — the privileged Windows and provisioning surface, which the 2026-08-10
desktop sweep did not touch.

### ◑ Already closed by later work — the ledger did not know (21 of 39)

`R-02` + `R-16` (win-live evidence constants, and the containment handle) · `R-17` (executor image pin
was decorative; `execution.rs::executor_image_binding` now refuses an unmeasured or mismatched image
BEFORE the producer runs) · `R-18` (no §2.5 floor on Windows; `win-live/src/tcb_floor.rs` is ~830 lines
with four real callers that `exit(5)`) · `R-25` (evidence counters the invariant forbids) · `R2
execution.rs:115/118` (executor exited before `execution-started`; driver's own pid attested) · `R2
pipe.rs:56` (NULL DACL) · half of `R-44` (the pipe squat window) · `R2 proof.rs:293` + `R2
win_live_turn.rs:203` (`InMemoryLedger` / in-memory DB — both are `DurableAcceptanceLedger` over a real
file now) · `R3 servers.rs:744` (publish-before-decide) · `R3 win_provision.rs:74` (adopts a pre-existing
root) · `R-03` (launcher store-input TOCTOU) · `R2 launcher/main.rs:444` (F-08's decision had no test —
it has six) · `R2 launcher/main.rs:447` (drop-order constant → recorded `DropJournal`) · `R-21` (broker
names the recorder's counter dir) · `R2 isolation_proof.ps1:46` + `R2/R3 win_live_proof.ps1:30` (both
harnesses now compare, and `-RootKey` is operator-supplied) · `R3 spawn_as.rs:141` (password on argv →
`--password-stdin`) · `R2 governed_selftest.rs:88` (`AnswerSource`) · `R-45` (zero CI coverage —
`brops-win-live` now runs on both runners).

### ◑ Fixed in this sweep

| finding | what it actually was |
|---|---|
| **`R-42` / `R-24` — no evidence-head floor on Windows at all** | The supervisor's whole state was `accepted: Mutex<BTreeMap<String, Acceptance>>`, keyed by `execution_attempt_id`, so **nothing was ever compared across runs**: turn A at head 100 then turn B at head 1 were both attested and signed without objection, on the only platform the desktop ships on, while F-09's row said the floor runs "on every `complete-run`" with no platform qualifier. Two halves were missing, and fixing one without the other does nothing. **(a)** `head_sequence` — the one field that orders two runs — was `cfg.facts.evidence_head_sequence` in the live driver and the literal `3` in the in-process proof, i.e. a constant, so a floor would have compared a constant against itself. That is the F-02 defect, closed on the other four `evidence_*` values and left alive on the fifth, under a doc-comment that *stated* the deployment must advance it. It now comes from `win-live/src/head_sequence.rs`, a durable counter that claims each number with `create_new` (atomic) rather than read-then-write, refuses a damaged counter instead of reading it as absent, and cannot re-issue a number whose marker exists. **(b)** `complete_run` now runs `brops_core::supervisor_ledger::evidence_floor_cas` — the SAME durable CAS the Linux supervisor uses, over the same shared DDL — between the state-machine decision and the store publish: after, so a refused turn cannot burn a head sequence; before, so a rejected head never reaches the store the signer reads. `Supervisor::new` is fallible and there is no `Option` and no in-memory fallback. This also gives `core/src/supervisor_ledger.rs` the first non-`create_schema` caller R-24 recorded it as lacking. |
| **Both machine-proof harnesses could never PASS** (new; not in any audit round) | The round that gave `win_live_proof.ps1` and `isolation_proof.ps1` a real comparison also made their `RESULT: PASS` line unreachable. Each case function ended with `Write-Output "<transcript>"` and then the verdict object, and PowerShell puts both on the success stream — so `$results += Run-Case ...` appended a `[string]` AND a `[pscustomobject]` per case, `$results.Count` was 4 against `$expectedCases = 2`, and the arity guard fired on every run. Neither harness has ever emitted its GREEN line as written. The self-tests stayed green because they call the CASE function directly and never touch the collection. It fails in the safe direction, and it is still the same defect this repository keeps finding: a proof that cannot pass is a check that cannot fail with the sign flipped. The transcript now rides on the result object; the run decision is a pure `Resolve-ProofOutcome` the self-test drives with seven new vectors, including a results array with a leaked transcript in it. |
| **The isolated signer resolved the containment report and threw it away** (R2 `servers.rs:1037`) | `let _ = (policy_bundle_sha256, containment_evidence_sha256);` — with a comment claiming both were "bound via request/handles". Neither was. The containment report is the one chain document written BY the party the isolated signer exists to be a second opinion on, and it was the only one the signer merely counted. `containment_evidence_handle` is now a fourth `CHAIN_AGREEMENT` entry: it must carry `brops.containment-evidence.v1` and agree with the attested evidence on `run_id`, `execution_attempt_id` and `output_handle`. The policy bundle stays resolve-only and the comment now says so instead of implying a check. 3 new tests. |
| **Nine dead `Facts` fields + four placeholder store blobs** (the residue of F-02) | F-02 removed `receipt_id`, the three terminal-artifact handles and the four `evidence_*` values from the PROTOCOL, but left the config that used to supply them: `win_provision` still seeded four placeholder blobs into the protected store — documents that LOOK like a completed run's terminal artifacts — and still wrote their handles plus a fabricated `evidence_final_event_hash` and a constant `receipt_id` into `config.json`, where an operator reads them as the deployment's evidence head. **Nothing had read any of them since F-02.** The substance was removed and the appearance was kept. Both are gone; serde ignores unknown keys, so an older config still loads. |
| **`R-19` — the Windows verdict document asserts facts the code contradicts** | Still true, and re-checking found two more. (1) "the shipped desktop app … does not even link this kit" — `Cargo.toml` links `brops-win-live` on Windows and two shipped `#[tauri::command]`s call `proof::in_process_turn_produce`; what IS true is that they run under the compiled-in demonstration root and can never render `production_verified`. (2) "`attest-run` is bound **one-time**" — `attest_run` never consumes anything; two calls return byte-identical bytes. (3) "seeds not plaintext at rest" — `win_provision` writes 64 plaintext hex chars; what was fixed is the ACL race, not encryption. (4) the two anti-rollback rows say CONFIRMED-CLOSED for a signature `resolver.rs` and `tcb.rs` both describe in their own comments as a corruption check under a PUBLIC source constant. Corrected in place with the false sentences struck through rather than deleted. |

### ◑ Deliberately NOT fixed, with reasons

* **`R-43` / half of `R-44` — no read/write deadline on the Windows named pipes, and the frame is read
  BEFORE peer authentication; the client never authenticates the server.** Real and unchanged. Not fixed
  because the whole of `pipe.rs` is `#![cfg(windows)]` with no pure seam, so **no test on either CI runner
  could witness the fix**, and a deadline needs overlapped I/O + `CancelIoEx` — a rewrite of the transport
  adjacent to the live trust chain. Shipping an unwitnessable change to that file is how the last three
  rounds got their ✅s. The audit's own adversary is also narrowed since it was written: the pipe DACL is
  no longer NULL, so in the cross-account deployment only the provisioned broker SID can open it at all.
* **`R2 config.rs:140` — the DPAPI seal-on-first-use fails open and silently**, in three places, each
  returning `Ok(seed)` and leaving the seed plaintext. Worse than the audit knew: the service account is
  granted `FILE_GENERIC_READ` only (`provision_custody.rs`), so the reseal's `std::fs::write` into
  `keys/` **cannot succeed** and the seal is effectively dead code. Not fixed because the honest fix is a
  decision about custody posture, not a patch: either the provisioner seals at creation (changing what
  `win_provision` writes and what the §2.5 pin measures) or the claim is withdrawn. The claim IS
  withdrawn — in `WINDOWS_BROKER_AUDIT_VERDICT.md` — and the mechanism is left for a session that can
  test it elevated.
* **`R2 win_provision.rs:121` — `manifest_epoch` is the literal `2` and `floor.json` is rewritten
  unconditionally on every run**, so the manifest anti-rollback floor can refuse a same-epoch fork and
  nothing else, and re-provisioning resets it. Not fixed here because `floor.json` is also a §2.5 pinned
  artifact (`tcb_floor.rs`, `anti-rollback-floor`), so making the floor genuinely advance changes its
  digest and refuses all four bins until re-pinned — the two anti-rollback mechanisms are mutually
  exclusive as designed, and reconciling them is a design decision, not a sweep item. Recorded in the
  verdict document instead.
* **`R-40` / `R-41` — the driver's start-of-process clock is used as `completed_at_ms`**, so the
  in-process receipt has zero duration and the live named-pipe path now fails CLOSED (`complete-run`
  refuses `completed_before_execution_started`, because the supervisor's `execution-started` clock is
  strictly later). Real. Not fixed because the fix is a clock seam through `GovernedExecutionCore`, which
  is the same object the §7.1 freshness round wired a `WallClock` into days ago; two sessions injecting
  clocks into the same struct is how twin divergence starts. **Recommended as the next item**, and it is
  an availability bug on a path that cannot currently complete, not a trust hole.
* **`core/src/windows_broker.rs:272` — the entire Windows peer-authorization and image-integrity policy
  layer is unreachable.** Wiring it makes a governed surface reachable, which is forbidden. **But the
  sweep row above that says it is "already declared with written reasons in
  `config/reachability-declarations.json`" is FALSE** — that file has six `rust_symbols` entries (three when this row was written, three more the same day)
  (`pull_output`, `governed_pull_output`, `governed_turn_output_read`) and names no symbol in
  `windows_broker.rs`. By the file's own words the module is in the state it calls the dangerous one:
  "unreachable-AND-undeclared — the state in which nobody can tell which of those it is." Left for the
  owner of that config, reported rather than silently edited.
* **`R-20` / `R-23` (launcher: one lease does not authorize one execution; the second TCB owner is the
  hardcoded uid 500)** — both still true, both Linux-only setuid code, and R-23's constant carries a TODO
  to bind it from the root-owned `TcbPinManifest`, which is the actual fix and is a Linux-deployment
  change no test on this box can witness. Also noted: the launcher's *decisions* are tested on Windows,
  its `real_main` *call sites* are not — deleting `verify_store_input_bindings(&lease)?` from `real_main`
  leaves every suite green.
* **`R-28`** — `live_turn`'s `verify_tcb` still exits the process rather than gating a served turn, and
  the broker's floor call site still cannot pass on the kit's own layout. Unchanged, Linux-only,
  `live_turn.rs` has zero tests on any host.
* **`R2 servers.rs:576`** — `receipt_id` is `format!("R-{now_ms}-{counter}")`, predictable from an
  observed lease. The uniqueness half is closed (`DurableAcceptanceLedger`, `receipt_id TEXT PRIMARY
  KEY`); predictability alone is not exploitable without also defeating that ledger, and changing the id
  format is a wire-compatibility decision.
* **`R3 isolation_proof.ps1:20`** — the harness still reads seven service-account passwords in cleartext
  and hands them to `Register-ScheduledTask -Password`. Real. The audit's "a path its own harness wrote"
  clause is now wrong: nothing in the tree writes `accounts_creds.txt`; it is an operator-supplied
  precondition. Fixing it means replacing Task Scheduler with the hardened `spawn_as --password-stdin`
  path, which needs elevation and seven real service accounts to test.

### Mutation results

**20 mutants applied to the shipping source, 17 killed, 3 survivors named.** Every mutant was applied to
the real file, the named test watched to fail, the file restored byte-exact and the restore verified by
SHA-256. (13 Rust, 7 PowerShell. An earlier draft of this paragraph said 24/21 — the count included two
anchors that never applied and one that broke the build, i.e. mutants that were never actually run. It is
corrected here rather than left, because an inflated mutation score in this file is the same defect as an
inflated ✅.)

Killed: accepting a stale head; accepting a same-head fork; scoping the floor per-attempt instead of
per-install; an in-memory floor fallback when unconfigured; claiming a head sequence by hint arithmetic
instead of `create_new`; a malformed counter reading as absent; a negative counter accepted; the proof
reverting to a constant `head_sequence`; dropping the containment-evidence agreement entirely; dropping
`output_handle` from it; treating an absent agreement field as satisfied; and, on both harnesses, the
case-count check, the failed-case check and the stray-object check.

**The stray-object check survived its first mutation, and that is worth recording.** Deleting it changed
no exit code, because a leaked `[string]` has no `Pass` and therefore also trips the failed-case check —
two guards masking each other, the arrangement the desktop sweep had to collapse a fortnight ago. It was
not deleted, because its real contribution is the CAUSE: without it a leaked transcript is reported as two
mystery case failures with empty problem lists, which is exactly how this defect stayed invisible. So the
self-test now asserts the MESSAGE, not just the exit code, on six vectors — and the mutant dies.

**Survivor 1 — `MAX_PROBE: 4096 → 8192` in `head_sequence.rs`.** `the_probe_is_bounded_rather_than_
unbounded` derives its fixture from the constant, so it follows the mutation. Behaviourally equivalent
for the property that matters (the walk terminates and a free slot inside the window is still found);
the value is a DoS margin, not a boundary. Not killed with a test written only to kill it.

**Survivor 2 — re-introducing `Write-Output "<transcript>"` inside `Invoke-Turn` / `Run-Case`.** The
harness self-tests cannot reach those functions: they start three processes, register scheduled tasks
and need elevation. This is the "mutant that survives only because the code sits in a branch no test can
reach" class, stated rather than papered over. What changed is that the regression is now REPORTED by
name (`non-result object(s) reached the results array; a case function wrote to the success stream`)
instead of appearing as a misleading case count.

**Survivor 3 — scoping the floor's `task_id` per attempt.** It survives because the property it targets
is enforced inside `brops_core::supervisor_ledger::evidence_floor_cas`, which compares against the highest
head recorded anywhere on the INSTALL regardless of task, so the call site's `task_id` is only the
idempotency key. The call site's real contribution is passing the true `install_id` — mutating THAT
(`M4b`) kills four tests. Named rather than dropped, because "the mutant did not weaken anything" and "the
test is weak" look identical from the score alone.

*Not a mutant, but the same class, found while inventorying:* the launcher's `real_main` call sites
(`verify_store_input_bindings`, `verify_lease_matches_attested_request`) are inside
`#[cfg(target_os = "linux")] mod linux` and no test constructs that sequence — deleting either invocation
leaves every suite green on every host. The decisions are well covered; the wiring is not.

*Also worth recording:* the first version of `head_sequence.rs` used ONE staging filename for the
counter, and `concurrent_allocations_never_return_the_same_number` failed immediately — the engine's R-30
"unlocked load-compare-write over a shared temp filename" defect, reproduced by accident and caught by a
test written before it was noticed.

### Numbers, each from a run performed for this sweep

`brops-win-live --lib` **101** (83 before, +18) · `brops-win-broker` **3 + 5** · `brops-launcher` **32** ·
`brops-executor` **5** · `brops-core --lib` **376** (unchanged by this sweep; 343 at this session's start,
the difference is another session's work in `core/`) · `brops --lib` **127** (unchanged) ·
`win_live_proof.ps1 -SelfTest` **PASS, exit 0** (11 case vectors + **10** run vectors, 7 of them new) ·
`isolation_proof.ps1 -SelfTest` **PASS, exit 0** (9 case vectors + **10** run vectors, 7 new).

**Pre-existing failures on this box, NOT caused by this sweep and NOT silenced.**
`BROPS_TEST_MISSING_PREREQUISITES` was never set.
* `brops-provision --test anchor_custody`: **21 passed, 1 failed** —
  `a_symlink_inside_the_anchor_is_refused_rather_than_followed`, declared prerequisite
  `windows-symlink-creation` (this account holds no `SeCreateSymbolicLinkPrivilege`).
* `brops-audit-signer --test anchor_end_to_end`: **8 passed, 1 failed** —
  `registration_applies_the_plan_for_real_or_says_why_it_could_not`, declared prerequisite
  `windows-elevated-registration` (this session is a FilteredAdministrator).
* **New observation, reported not fixed:** that suite is **not safe to run concurrently with itself**. It
  contends on the machine-global anchor `C:\ProgramData\BroPS-o2-anchor\trust-anchor`, and while another
  session ran it in this shared tree the failure count drifted 1 → 2 → 3
  (`an_anchor_signed_by_any_key_the_app_holds_is_refused_by_the_real_verifier`,
  `rewriting_the_operator_pin_is_refused_by_the_operating_system_and_the_forgery_fails`). Both pass in
  isolation and the count returns to 1. A machine-global fixture in a parallel test binary is a flake
  generator; naming it here so a future red run is not mistaken for a regression.

No gate was touched. `commands.rs:1152 governed_verification_unconfigured`, `UpstreamBlockedExecutor` and
`connect_broker` are byte-untouched — nothing under `apps/desktop/src-tauri/src/` was modified at all.
The R-42 fix can only REFUSE more turns than before; it cannot make any surface reachable.

## Engine / bridge / tools sweep (2026-08-12, `at-main-2`) — **Builder's claim, nobody else has looked**

Every mark in this section is **◑**. The RED verdict above still stands. This sweep covered the
LIVE findings from the consolidated index whose fix lands in `engine/runtime/**`,
`engine/tools/**`, `engine/ci/**`, `engine/AUDIT/**`, `bridge/**` or `tools/**` — the ENGINE, which
neither the 2026-08-10 desktop sweep nor the Windows/provisioning sweep touched.
`engine/ci/live/run_live_turn.sh` and `apps/desktop/src-tauri/broker/**` were another session's
files this round and were not read for edits.

**33 in-surface findings inventoried. 17 were already closed and the ledger did not know. 5 were
live and are fixed. 8 are live and deliberately not fixed, with reasons. 3 were not re-verified
deeply enough to claim either way, and say so.**

### One row of the Desktop-surface sweep is now stale

That sweep's `supervisor_ledger.rs:358` row ends: *"The Python twin
`governed_supervisor_ledger._BOUND_FIELDS` omits exactly the same five and is NOT fixed."* It is
fixed, at `e4f73e2`. `_BOUND_FIELDS` is now derived —
`tuple(f.name for f in dataclass_fields(NewAcceptance) if f.name not in _IDENTITY_FIELDS +
_DIGEST_COMPARED_FIELDS)` — so the field list IS the comparison, the same property the Rust
`#[derive(PartialEq)] struct DurableBinding` gives, and the only two exclusions are named in
writing next to their reason. `challenge_accepted_at_ms` and all four `challenge_registry_*`,
including the anti-rollback `epoch`, are compared. Recorded here rather than silently edited.

### ◑ Already closed by later work — the ledger did not know (17)

| id / loc | claim | why it is closed today |
|---|---|---|
| **P0** R1 `governed_supervisor.py:848` | `complete-run` takes the reply digest raw off the wire; the supervisor never observes the execution | `build_run_attestation` has no `facts` parameter and takes an `AttestationState`; `evidence_from_state` sources all 25 fields from the durable row + pinned config; `governed_supervisor_ledger.derive_evidence_from_chain` REFUSES a completion whose `output_handle` is not the `output-captured` digest in the recorder's own chain (`2debb71`) |
| P1 R1 `bro_completion.py:255` | head-floor cleared by deleting its directory; `BRO_EVIDENCE_HEAD_FLOOR` ungated | `_load_floor_index` refuses a missing `_index.json`, with bootstrap instructions; the env path goes through `_external_dir` + `_refuse_self_owned_floor` |
| P3 R1 `bro_completion.py:226` | the floor is advanced from a SECOND independent read of the head file | advanced from `head.head_sequence` + the digest of the head `validate_chain` actually verified |
| **P1** R3 `isolated_signer.py:647` | §7 deep verification is three existence checks | `_verify_chain_handles` + `_CHAIN_AGREEMENT`: each document is parsed, its protocol tag checked, and every shared field REQUIRED and compared; a missing field is a refusal, not a vacuous pass |
| P3 R3 `isolated_signer.py:199` | §1.5 step 4 dropped; `REASON_POLICY_MISMATCH` raised nowhere | `_check_policy_authorization` binds `(policy_id, policy_version)` to the registered bundle handle; an unprovisioned allowlist REFUSES |
| P2 R3 + P3 R3 `isolated_signer_server.py:273` | no catch-all; a planted store blob kills the signer for all future turns | `except Exception` fail-closed backstop in `handle_connection`, a second one in `serve_forever`, detail to stderr and not to the peer |
| P2 R2 + P3 R2 `engine/tools/brops_isolation_prover.py:84` | attack 4 is decided by a protocol-name mismatch, so it proves the shape guard is not there | the attack now sends `brops.evidence-request.v1` — the supervisor's OWN protocol — with a positive control that must come back `run_binding_invalid`; delete the shape gate and the attack matches the control, so the row goes INCONCLUSIVE rather than quietly passing |
| P2 R1 `governed_supervisor_ledger.py:640` / `:645` | the anti-rollback floor is keyed on a `task_id` the broker chooses | `_evidence_floor_cas` compares against `_install_floor_ceiling` — the highest head recorded anywhere on the INSTALL, in any task bucket; `task_id` is only the idempotency key |
| P2 R1 `governed_supervisor_ledger.py:553` | the four evidence values reach the signer as the broker's self-report | `DERIVED_EVIDENCE_FIELDS` are derived by `derive_evidence_from_chain` and are not in `COMPLETION_FIELDS`, i.e. not on the wire at all |
| P2 R3 `governed_supervisor_ledger.py:575` | no upper time bound survives the pre-launch lease gate | `lease_launch_gate` refuses `lease_not_yet_valid`, `lease_expired` AND `insufficient_remaining_budget` (`MIN_LAUNCH_REMAINING_MS`), boundary-pinned against the Rust twin |
| P3 R3 `governed_supervisor.py:688` | §4.7 execution receipt is not implemented | `build_execution_receipt` builds `brops.execution-receipt.v1` from the acceptance + completion rows; its handle is in `DERIVED_HANDLE_FIELDS`, which a caller cannot supply |
| P3 R3 `challenge_authority_server.py:239` | `brops_protocol` has no deployed caller | imported by `brops_socket`, `governed_turn_open`, `governed_staging_upload`, `governed_output_read`, `governed_turn_result` |
| P3 R3 `brops_evidence_store.py:76` | §2.3 runtime store-ACL enforcement is unimplemented | `posix_forbidden_mode` is a pure rule with a real `nt` branch, and `harden_private_dir` is the single entry point |
| P2 R1 `bro_signature.py:263` | `BRO_OPERATOR_ROOT_PIN_SELF_OWNED` is an ungated ambient env var | **CORRECTED 2026-08-14 (audit `A-03`).** *First half, TRUE and a good fix:* the raw variable is honoured **only** under `BRO_ENV=ci`, refused loudly and by name otherwise (`bro_custody.py:151-165`) — the gate `R-14` asked for. *Second half, FALSE as written:* the `_FILE` form gets **no custody check of any kind**. `self_owned_acknowledged` reads the path and compares its content to `"acknowledged"` (`bro_custody.py:131-149`) — no owner check, no mode check, no `bro_custody` call on that path; **any file the process can read will do.** The module says so itself at `:73-81`: *"What the file form is NOT: a custody-checked artifact… It raises the cost from one `export` to an `export` plus a file the operator wrote… nothing more."* **The code is honest; this row was not.** Its reasoning for stopping there is sound and is kept: making the acknowledgement unforgeable means making it operator-signed, and verifying that signature needs the very pin whose custody rule the acknowledgement suppresses. **Accurate statement:** raw form CI-gated; file form is a **disclosed, deliberately un-custodied posture declaration**, with the circularity recorded. |
| R2 desktop-sweep handoff, `_BOUND_FIELDS` | the Python idempotency comparison omits five bound columns | derived from `NewAcceptance`; see above |

### ◑ Fixed in this sweep (5)

| finding | what it actually was |
|---|---|
| **R1 `governed_supervisor_server.py:626` — one 8 KiB frame kills the supervisor** | `handle_connection` caught `(FrameError, ServerError, SupervisorError, ValueError, UnicodeDecodeError)`. `json.loads` raises `RecursionError` — a `RuntimeError`, in none of them — on a body that nests ~3900 deep in 7800 bytes, comfortably inside the 8 KiB frame bound, so nothing earlier refused it. It escaped the handler, and `serve_forever` had **no `except` at all**, only `finally: conn.close()`. One frame from either authorized peer ended the process that issues every lease and produces every attestation. The isolated signer's front door already had exactly this backstop; the supervisor — the twin it is meant to match — did not. Both are present now, the peer is told only `internal supervisor fault`, and the detail goes to the operator's stderr rather than becoming an information channel. |
| **R1 `governed_supervisor_server.py:183` — no timeout of any kind on the front door** | `SocketPeerConn` never called `settimeout`, and the accept loop is serial, so a peer that connected and then sent nothing held every governed turn on the install for as long as it liked. Fixed with a **total** `CONNECTION_BUDGET_S` armed at accept and shared by both directions — a per-recv timeout is not a bound, because it restarts on every byte that arrives, which is the same defect the desktop sweep found in `governed_turn.rs`. The arithmetic is lifted OUT of `SocketPeerConn` into `recv_budget_s` / `recv_exactly_bounded`, because that class cannot be constructed off Linux (`read_peercred_uid` refuses) and a bound expressed only inside it would sit in a branch no runner here can reach. Exhaustion is `None`, never `0.0`: `settimeout(0)` is non-blocking, and the POSIX `SO_RCVTIMEO` it maps to reads 0 as *infinite*. |
| **R1 `bro_completion.py:271` — the head-floor advance is an unlocked load-compare-write** | Still true, and worse than "two concurrent turns race". The compare sat outside any lock and the write inside none, so which head was recorded was decided by whichever `os.replace` landed last rather than by which head was higher: turn A (head 5) and turn B (head 3) both read 0, both passed `head_sequence <= current`, and if B landed second the mark went **down** — "never lowers the mark" was true of the comparison and false of the operation. The `_index.json` roster is worse: one file that every task read-modify-writes through one shared staging name, so a concurrent enrolment silently loses the loser — and a task missing from the roster is, by `_load_head_floor`'s own rule, a task never seen, so deleting its mark afterwards reads as a first sighting and returns `(0, None)`. That is the R-06 rollback restored by timing alone, needing no attacker capability. The whole load-compare-write now runs under `_floor_write_lock`: an ADVISORY lock (`fcntl.flock` / `msvcrt.locking`), not an `O_EXCL` lock file, so a crash cannot leave the floor permanently unwritable; a platform with neither primitive REFUSES; and the unprovisioned-floor refusal is taken BEFORE the lock, so the lock cannot become the way an absent floor starts looking provisioned. |
| **R2 `bro_orchestration_runtime.py:380` — the claim-lock reentrancy check is PID equality** | `_guard_held_by_this_process` compared the pid in the lock file with `os.getpid()`. A lock file orphaned by a process that died inside the guard keeps that pid forever, and pids are recycled (default `pid_max` 32768). The unrelated later process handed that pid was told it already held the guard, so `_mutation_guard` yielded holding **nothing**, while any other process was free to break the stale lock and take it for real: two writers inside a guard whose only purpose is that there is one. It now compares the token this process minted at acquisition against the token on disk. *Both* `_claim_guard` implementations register — the V1 runtime **overrides** `_claim_guard` with its own near-copy, and registering in only the base one left every base method V1 delegates into trying to re-acquire a lock it already held. That regression was invisible to the unit tests and was caught by the full suite (1 failure + 5 errors across `test_control_room_api` and `test_reconciler`); a test for the override's wiring is now in the tree. |
| **R2 `isolated_signer.py:599` — `_check_run_binding` binds nothing** | Half-true, and now half-fixed honestly. The function contained `if not evidence["request_nonce"]: raise _Refuse(REASON_NONCE_MISMATCH)` under a comment that states the defect in its own words — *"already validated"*. `request_nonce` is in `EVIDENCE_STRING_FIELDS`, `_validate_evidence` has already required `_capped_str` (`0 < len`), and the single call site runs `validate_sign_request` first, unconditionally: **the branch could not be taken by any input**, inside the function the design calls the independent authorization gate (§1.5). Deleted rather than annotated — unlike the F-29 guard it has no future call site to defend, because it is a private method with one caller that validates first. A test now locks where the property actually lives: the shape gate, reason `malformed`. What was deliberately NOT built on top of it is below. |

### ◑ Deliberately NOT fixed, with reasons

* **`isolated_signer.py` still raises neither `run_binding_invalid` nor `nonce_mismatch`**, though
  both are in the ratified §4.2 vocabulary (`engine/contracts/brops-sign-result.v1.schema.json`) and
  `SECURITY_NEGATIVE_TEST_MATRIX` NM-XBIND-10 expects the first for an internally inconsistent
  `run_id`/`execution_attempt_id`/`lease_id`. The obvious repair — cross-compare the chain documents
  the signer already reads — **would be the same defect wearing a longer name**: the record, the
  execution receipt and the lease are all built by the same supervisor from the same acceptance and
  completion rows (`build_terminal_record` / `build_execution_receipt` / `_lease_payload`), so every
  field they share agrees BY CONSTRUCTION and a comparison of them could not fail either. Binding
  the run against a source the supervisor does not control needs the signer to hold one, which §5
  does not give it. A protocol change and an Owner/Architect decision, stated in the code.
* **`engine/ci/live/run_signer.py:83` — the isolated signer pins its supervisor-attestation
  verifying key from the shared deployment config** (`cfg["keys"]["supervisor_attest_pub_hex_value"]`),
  not from the root-signed manifest. Real and unchanged. Fixing it means resolving the key from the
  manifest under the §2.5 floor and refusing an inline one — a change whose only end-to-end witness
  is the Linux 7-service `run_live_turn.sh`, another session's file this round, which no runner on
  this box can execute. Shipping an unwitnessable change to the trust chain is how the last three
  rounds got their ✅s.
* **`run_signer.py:103` — the signer's identity allowlist and the supervisor's identity block are
  two reads of the same `config.json`.** Same reason: separating them is a provisioning-topology
  change verifiable only on the live kit.
* **`engine/ci/live/provision_keys.py:383` — the challenge-authority key is outside the root-signed
  manifest.** `build_manifest_bytes(signer_pub_hex, sup_pub_hex)` carries two keys and the challenge
  key is not one of them, so the key that authorizes an acceptance is not covered by the root
  signature. Real. Adding it changes the manifest bytes that the Rust `KeyManifest` /
  `manifest_resolver.rs` / `production_trust.rs` parse — cross-language, and **no `cargo` command
  could be run this session** (the box's memory was reserved for another agent's build), so the twin
  could not be compiled, let alone tested. Left rather than guessed at.
* **`provision_keys.py:245` — `anchor_provenance = "external"` is still a string the kit writes about
  itself.** Narrowed since the audit: the external branch requires the operator to supply
  `--manifest-in` / `--manifest-sig-in` / `--root-anchor-*` and serves those bytes verbatim, and the
  kit-generated default prints `production_verified=false root_anchor=kit_generated`. What remains is
  that nothing cryptographically distinguishes the two labels at the point of writing. Same live-kit
  witness problem.
* **`governed_supervisor.py:710` — §4.3's signed 25-field lease is a 5-field unsigned blob.**
  `_lease_payload` carries `lease_id`, `execution_attempt_id`, `lease_expires_at_ms` and the two
  executable digests, persisted and content-addressed rather than signed. A real
  design-conformance gap, and a protocol change touching the setuid launcher's pin checks on Linux.
  Not a sweep item.
* **`bro_completion.py:269` — the head-floor mark is advanced by the very process it polices.**
  Unchanged, deliberately: it is an open design contradiction (a floor this process can write fails
  custody; one it cannot write fails the advance), pinned as executable fact by
  `HeadFloorConfigurationContradictionTests`. The serialization lock added above needs the same write
  capability as the mark it protects, so it neither widens nor narrows the contradiction — noted in
  that class so its statement stays true.
* **The base `DurableOrchestrationRuntime._claim_guard` and the V1 override are near-duplicates that
  have already diverged**: the V1 copy retries `PermissionError` (a Windows delete-pending race on an
  `O_EXCL` open) and the base copy does not, so the base guard hard-fails where the override
  recovers. Found while fixing the reentrancy hole above; reported rather than merged, because
  collapsing two lock implementations changes the mutation path of every runtime method and wants
  its own round.

### Not re-verified deeply enough to claim either way (3)

`engine/ci/live/run_supervisor.py:130` (§0.1 platform capability gate has no implementation),
`engine/ci/live/build_tcb_pin_manifest.py:84` (the coverage floor is satisfied by logical NAME, not
causal role), and `engine/tests/test_governed_chain_e2e.py:487` (the two F-01 regression tests
assert only that an unknown attempt id is refused). All three are live-kit or long-file reads that
this sweep sampled rather than drove. Recorded as unknown rather than assigned a status — inventing
one is the defect this file exists to catch.

### Mutation results

**18 mutants applied to the shipping source, 16 killed, 2 survivors named.** Every mutant was
applied to the real file, the named test watched to fail, the file restored byte-exact and the
restore verified by SHA-256. The harness is crash-safe rather than `try/finally`-safe: pristine bytes
and their digests are written to disk before the first mutation, a sentinel is armed before it and
cleared only after the final restore verifies, the harness refuses to start while a sentinel exists,
and it has a `--restore` mode. Five files were touched and all five ended byte-identical.

Killed: deleting the `handle_connection` catch-all; deleting the `serve_forever` catch-all; arming
`settimeout(0)` at the exact moment the budget expires; a budget that never expires; a read loop
that ignores an exhausted budget; a timed-out `recv` escaping the loop; advancing the floor with no
lock; load-compare outside the lock with the write inside (**the original defect, reproduced
exactly**); a lock context manager that locks nothing; dropping the pre-lock provisioning check; a
roster rewrite that stops reading the roster; a shape gate that stops requiring a non-empty nonce;
deleting the one decision `_check_run_binding` still makes; restoring pid-equality reentrancy;
trusting the in-process ownership record without re-reading the lock; and the V1 `_claim_guard`
override not registering its token.

**Survivor 1 — re-adding the deleted `if not evidence["request_nonce"]` check.** It survives because
that is precisely the finding: the branch cannot be taken, so putting it back changes no outcome and
no test. Reported rather than killed, because a test that detected the presence of dead code would
be a test of the source text, not of behaviour.

**Survivor 2 — not clearing `_HELD_CLAIM_TOKENS` on release.** Behaviourally equivalent: the release
path unlinks the lock file, so `_lock_owner()` returns `None` and the `== held` comparison already
answers correctly whether or not the entry was popped. Unlike the pair the desktop sweep had to
collapse, the pop is not a second guard at all — it is cleanup that stops a long-lived process
accumulating misleading entries — so it is kept and named here rather than deleted, and no test was
written only to kill it.

### Numbers, each from a run performed for this sweep

engine `PYTHONDONTWRITEBYTECODE=1 BRO_ENV=ci python -B -m unittest discover -s tests -q`:
**1915 tests, OK (skipped=43)** — 1895/43 at this session's start, +20 new tests. **Converged:** two
consecutive full runs gave an identical 1915/43 (113.5 s and 106.5 s). The run between them is
recorded honestly too — **1914 tests, FAILED (failures=1, errors=5)** — the V1 `_claim_guard` wiring
regression described above, found by the full suite after the unit tests stayed green.
bridge `-s bridge/tests` **210, OK**. `tools/` self-tests **419, OK** (see the caveat below: a
later re-run is 419 with 1 failure, from the same in-flight file).
Gates, each exit 0 against this sweep's final tree: `check_spec_references`,
`check_reachability`, `check_coordination`, `check_ledger_ddl_parity`, `check_residual_items`.

**One caveat, stated rather than rounded off.** A later re-run of `check_spec_references` returns
exit 1, and it is not this sweep: its single complaint is
`engine/ci/live/ladder_evidence.py:105 cites §4.10(h)` — an **untracked** file another session
created in this shared tree while this sweep was running (`git status` shows five such `??` files
under `engine/ci/live/`, none of them touched or read here). This sweep's diff does not touch
`engine/ci/**` at all, and the thirteen lines it adds that cite a section name only §0.1, §1.5,
§2.3, §2.5, §4.2, §4.3, §4.7, §5 and §7, all of them declared. Naming it here so a future red run
is not mistaken for this sweep's regression — and so it is not mistaken for someone else's problem
either, if it is still red when that file lands. The same file takes the `tools/` suite from
**419 OK** to **419 with 1 failure**, `test_check_spec_references.SpecReferenceGateTests.`
`test_the_real_repository_passes_its_own_gate`, whose whole assertion is that the real tree passes
its own gate — i.e. one cause, two red lines, and neither of them in this sweep's files.

`BROPS_TEST_MISSING_PREREQUISITES` was never set. No suite was silenced and no prerequisite was
declared to quiet a failure.

**No gate was flipped.** `git status` shows ten modified files: nine under `engine/runtime/` and
`engine/tests/`, plus this ledger. (Five `??` untracked files under `engine/ci/live/` belong to
another session in this shared tree and were neither created nor edited here.)
`apps/desktop/src/**`, `apps/desktop/src-tauri/**`, `.github/`, `tools/`, `config/`, `bridge/`,
`NEXT_CHAT.md`, `PROJECT_STATE.md`, `TASKS.md`, `engine/ci/**` including
`engine/ci/live/run_live_turn.sh`, and
`apps/desktop/src-tauri/broker/**` have no diff at all, so `governed_verification_unconfigured`,
`UpstreamBlockedExecutor` and `connect_broker` are byte-untouched. Every change here can only REFUSE
more than before — a hostile frame becomes a refusal instead of a crash, a starved connection
becomes a framing refusal, a concurrent floor advance is serialized, and a claim guard is harder to
enter. None of them makes a governed surface reachable.

## Legend
**One legend, and it is the one under “How to read the status column” above:** ✅ = an independent
audit confirmed it · ◑ = the Builder's claim, nobody else has looked · 🔴 / ⚠️ = open · by-design =
intentional, not a hole.

*(Until 2026-08-09 this line read “✅ fixed (Builder has code evidence)” — a SECOND legend, in the
same file, giving ✅ the exact meaning the first legend says it must not have. The two ticket tables
immediately above were marked under this weaker meaning and have NOT been re-marked row by row: read
every ✅ in the **Desktop tickets** and **Engine tickets** tables as ◑ until someone re-checks them.
Re-marking them is outstanding work, and inventing statuses for them would be the defect this file
exists to catch.)*

> **Maintenance:** when a ticket is resolved, mark it here in the same commit and cite the fixing commit.
> New security tickets MUST be added to this ledger (desktop) or the manifest (engine) so nothing is orphaned.
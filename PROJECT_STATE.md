# PROJECT_STATE — live status · կենդանի վիճակ

> **⏭️ CURRENT ACTIVE: PR #84 · branch `at-main-2`** (base `main`, tip `6bd3027`, task T-017).
>
> PR #84 puts the canonical law at the repository ROOT. The receipt mechanism already existed and worked, but its root was engine/ and it was wired only at engine/.claude/settings.json, so a session opened at the repository root got one Stop guard and nothing else -- which is how three days of Phase 10 work happened against a roadmap nobody opened. Four rules bind now: a SHA-256 read receipt voided when any canonical file changes mid-session; roadmap order, with a later phase refused by name while an earlier one is open; a recorded prior-art search before any new file; and an update law demanding all four canonical documents move with any substantive change, with no environment bypass. This commit is the first thing that law refused. What it does not do is stated rather than implied: shell writes are not gated, CANONICAL_LAW=off disables it deliberately, the receipt is forgeable, and a session may edit the wall but not silently. Fifteen mutations, fifteen caught; 63 gate self-tests pass.
>
> **The last independent audit returned RED, and none has been run since.** The Owner's SECOND independent audit -- `apps/desktop/AUDIT/2026-08-06-remediation-audit.md`, of `main` @ `219c763` AFTER the first round's remediation -- confirmed 4 of 18 blockers closed and left 122 surviving findings (1 P0, 7 P1, 32 P2, 82 P3) across its three rounds. It has never been re-run, on that head or on any later one, so **RED is the standing verdict of record.** The index is `apps/desktop/AUDIT/AUDIT_LEDGER.md`.
>
> **The governed surfaces stay fail-closed.** `governed_verification_unconfigured()` returns Some(...) unconditionally before the model is invoked, `connect_broker()` refuses off Linux, and the broker serves `UpstreamBlockedExecutor` unless `$BROPS_BROKER_CONFIG` names a deployment config with a TCB-root-signed manifest -- which nothing in the shipped app sets. Earlier prose below is HISTORY.

### The ledger was the wrong floor, and running it said so (2026-08-10)

I decided to consolidate `bro_completion`'s configuration-impossible head floor onto the supervisor's
durable ledger, on the strength of a sentence in the code's own docstring: the ledger "already holds an
equivalent floor written by the supervisor uid rather than by the builder". The agent sent to implement it
**stopped, changed nothing, and disproved the premise by execution.** That was the right outcome and the
instruction asked for it explicitly.

**The two floors measure different numbers.** The ledger counter is per INSTALL and, since bb26822,
deliberately an install-wide ceiling; the completion floor is per TASK, and every task's first anchor is 1.
Two real signed heads from the repo's own fixture -- task-1 seq 1 and task-2 seq 1 -- are both ACCEPTED by
the filesystem floor and the second is REFUSED by the ledger with `EvidenceFork`. A negative control in the
ledger's own shape behaved correctly, so that is a real semantic mismatch and not a broken probe.
**Consolidating would have made the second task in any deployment permanently un-completable.**

**It is also unreachable, absent, and narrower.** No module on the completion path imports
`governed_supervisor_ledger`; the DB is opened only by `run_supervisor.py` as the supervisor account, and
its only door is `governed_supervisor_server` -- AF_UNIX + `SO_PEERCRED`, Linux-only, allowlisting the
broker uid alone. Opening that sqlite file directly from the builder would delete the second principal and
reproduce the contradiction in sqlite instead of JSON. On **Windows**, the platform the desktop ships on and
the host where the contradiction was proven, there is no ledger floor at all -- `win-live/src/servers.rs`
keeps supervisor state in a `Mutex<BTreeMap<..>>` and `complete_run` performs no cross-run head comparison
(open finding R-42). And the ledger table has no column for `evidence_head_sha256`, which drives the "same
sequence, different signed head" refusal, nor any equivalent of the `_index.json` roster,
`_require_establishable_mark`, or the owner-signed bootstrap.

**What changed as a result.** No code was consolidated. The docstrings on `_head_floor_dir` and on
`HeadFloorConfigurationContradictionTests` that recommended the ledger route now say, with the four
disproofs, not to take it -- correcting the source of the error rather than its symptom. The contradiction
itself is unchanged and is now a named Owner decision in `docs/OWNER_ACTION_REQUIRED.md` section 1b: a
floor-writer service or a setuid helper, because the builder is the writer and no third posture exists.

Measured, not asserted: the floor's only two call sites are `bro_completion.py:244` and `:287`, both inside
`validate_evidence_chain`, established by instrumenting the functions and running the whole suite through
the wrappers -- 35 distinct runtime stacks, 262/188/79 calls, no dynamic dispatch. Every production entry
point observed (`bro_hook.py:194`, `bro_orchestration_runtime.py:956`, `bro_release_v3.py:164,207`) runs in
the builder's own process. `tests.test_completion_head_binding`: 27 tests, OK, 2 skipped by name on Windows.


### Nine ticks were six facts, and one of them was false (2026-08-10)

Phase 1's Definition of Done and Task checklist carried nine `[x]` boxes. Checked against the code rather
than against the commit messages the boxes cite, they are **six** distinct facts -- the adapter and its ten
tests, the `bridge` CI job, and the badge plus provider control each appear twice -- and one of the six was
false.

**The false one: "One governed round-trip proven end-to-end -- done."** The box had already narrowed
"round-trip" to a *fail-closed* one ending in `Blocked`. It is false on those narrowed terms. The production
order at `commands.rs:1338-1428` is `issue_challenge` (:1370) -> `governed_unconfigured_block` (:1379) ->
**early return** (:1382) -> and only then, unreached, `ai::governed_turn` (:1385) and
`verify_and_record_receipt` (:1424). `governed_verification_unconfigured` (`commands.rs:1152`) returns
`Some(...)` with no condition, and the same shape guards the other two governed surfaces at `:1854` and
`:2061`. Nothing is sent, no receipt is produced, no signature is examined: `verify_and_record_receipt` and
`verify_and_record_held_answer` have **zero runtime-reachable production callers**. The 23 green
`receipt_store` tests exercise the seam in isolation, which is a different claim.

**The refusal is deliberate and stays.** The gate is the Owner's standing constraint. The row is open because
the roadmap was describing a round-trip the gate forbids -- not because the gate is wrong. A genuine
end-to-end governed turn does exist, `engine/ci/live/run_live_turn.sh` under the `live-governed-turn` job
(`ci.yml:72-119`), but it runs `broker_orchestrator::run_governed_turn` + `verify_and_accept` and never
touches the chat path or the bridge adapter. Citing it under this box would repeat the substitution the box
already made once, so it is named in the row and not counted.

**The other five, stated at their real width.** The `task-request` contract is validated at runtime
(`engine_adapter.py:120`); `bridge-result.schema.json` is loaded only by a test, so "contracts tested" was
covering a test-only contract. The `bridge` CI job is real (`ci.yml:574-586`, re-run: **60 tests, 0
failures**) -- it runs but is **not required**, since `main` has no branch protection. The adapter is built,
correct and re-verified at **10/10**, and its only caller is reachable only through the dead governed path.
The governed-provider transport is real and default-OFF, and all three callers of `ai::governed_turn` sit
behind the unconditional refusal. The UI badge and control ship and a user reaches them (19 vitest cases),
but the badge is driven by `MESSAGE_RECEIPT_PROJECTION`, whose `trusted_verified` state needs the round-trip
above -- so the only badge a user can produce is `demonstration_verified`, Windows-only, behind
`BROPS_SELFTEST_MODEL_CMD`. The UI/UX spec names four badge states; three tones ship, with no `pending` and
no `blocked`/`error`.

`tools/check_reachability.py` did not and structurally cannot catch this: it prints GREEN at 87/92 commands
and its own LIMITS say it cannot tell whether a user can reach a path past an earlier return. An
unconditional `Some(...)` is exactly that. Every finding here came from reading the call order by hand.


### The anti-rollback floor, the TCB pin and the self-owned acknowledgement (2026-08-10)

Four live findings on the evidence-floor / custody cluster. Two are closed, one is closed as far as it can
be closed here, and one is a design contradiction that is now pinned in code and tests instead of being
quietly worked around.

**The anti-rollback floor was bypassable by choosing a string, and the relay understated it.** The floor was
partitioned by `task_id`, which is attacker-chosen -- but `head_sequence` is minted by ONE per-install
counter (`proof/src/bin/governed_recorder.rs::next_head_sequence`), so a per-task partition could never have
been correct: it only ever created buckets to hide in. `_evidence_floor_cas` now decides the exact
`(install, task)` row first (so a byte-identical retry is not read as a rollback) and then applies an
**install-wide ceiling**. The Rust twin's test `floor_scopes_by_install_and_task` had **asserted the defect
as a feature** -- "a DIFFERENT task_id is an independent floor" -- a falsely-green test, now rewritten with
its old body quoted in the doc comment. The DDL is untouched; the parity gate is green at sha256
`44a57f15...`.

**The rev-30 section 2.5 content pin was self-referential, and is now partly anchored.** A
`run_supervisor.py` replaced with an attacker payload before the pin was taken produced a green build whose
pin was the tampered bytes. `build_tcb_pin_manifest.py` now requires `--source-dir` (wired as `$REPO_ROOT`
in `run_live_turn.sh`); artifacts copied verbatim from the repo take their digest from the source, an
installed copy that differs refuses the build, every entry records `digest_origin`, and a manifest with zero
independent digests is refused. One relay correction: `HashMismatch` *can* fire -- for a change between the
pin and the check. What cannot fire is integrity of **origin**. **4 of 21** artifacts gain one; the compiled
binaries and the provisioned lease/anchor/policy/config/sudoers still have no origin outside the deployment
host. Closing that needs release-signed binary digests or an operator signature over the manifest -- neither
was invented here. `win-live/src/bin/win_tcb_pin.rs:132` has the identical construction and is untouched.

**The head-floor is configuration-impossible, and no code pretends otherwise.** Run on this host in all
three postures: writable and self-owned -> custody refuses; a DENY ACE on WD/AD/DC -> the advance refuses
`[Errno 13]` *and* custody still refuses, because the process owns the directory and so holds `WRITE_DAC`;
acknowledged -> advances, with every custody rule in the runtime off. On Windows **no** posture passes both
rules. Rather than widen a rule, `HeadFloorConfigurationContradictionTests` asks both rules of a real
directory and states that any change claiming to resolve this must arrive there and name the posture that
now satisfies both; `_head_floor_dir` and `_advance_head_floor` carry warning blocks saying the docstring's
own escape route cannot be configured, because the builder is the writer. **The decision is the Owner's:**
move the write to a second principal, or consolidate onto the supervisor's durable ledger floor -- which
already holds an equivalent floor written by the supervisor uid, making this filesystem floor a weaker
duplicate.

**The acknowledgement was ungated while its siblings were not.** `BRO_OPERATOR_ROOT_PIN_SELF_OWNED` is now
honoured only under `BRO_ENV=ci` -- the identical gate already on `ENV_PIN` and `ENV_REGISTRY_MIN` -- and
outside CI it *raises a named refusal* rather than being silently ignored. A production form
`BRO_OPERATOR_ROOT_PIN_SELF_OWNED_FILE` was added, and `engine_trust::resolve` refuses **both** names, which
closes the hole the new form would otherwise have opened. `self_owned_acknowledged` now honours a
caller-passed mapping, closing the audit's exact asymmetry. Stated plainly: this raises the cost from one
`export` to an `export` plus a file and puts the posture on disk where an audit finds it; it does **not**
make the acknowledgement unforgeable by an environment-setting adversary. Doing that needs an operator-
*signed* acknowledgement, which is circular -- verifying the signature needs the very pin whose custody rule
the acknowledgement suppresses. Breaking that cycle is an Owner/Architect decision, and it is written in the
code rather than buried.

**22 tests turned red, and that was the finding.** Every one relied on the ungated ambient variable --
including `test_deploy_preflight.test_hardened_environment_passes`, the test the 2026-08-06 audit named for
asserting that a self-owned anchor is "hardened". Fixtures now *declare the posture the honoured way* (new
`engine/tests/_self_owned_ack.py`, file form -- a dev workstation is not CI and a fixture claiming to be
would pin the gate open), not re-enable the old path.

Suite: **1330 tests OK (43 skipped)**, up from 1307. `brops-core` 310, `brops` 110, `brops-broker` 27 pass.
19 new tests, 10 mutants killed, every mutated file restored and verified by SHA-256. Two pre-existing
environment failures are named and not claimed as passes: a symlink test needing
`SeCreateSymbolicLinkPrivilege`, and audit-signer cascade from a machine anchor sealed on this host before
this session.


### Phase 1 — two open questions answered in writing (2026-08-09)

Both were places where the code and the roadmap had been disagreeing long enough that a reader could
not tell which was wrong. Neither is closed by building the thing the roadmap asked for; both are
closed by ruling, and the ruling is written where the disagreement was.

**1. The governed toggle — the specification was AMENDED, not implemented.** Phase 1 asked for an
opt-in `Provider::GovernedEngine` toggle with `default / on / blocked`. What shipped was a read-only,
`disabled` row. The toggle is not honestly buildable today and the roadmap now says why:
`ai.rs::resolve_provider` resolves the provider from the **backend process environment**, and Phase 1's
own security gate is *"Desktop never holds lease/key/env"* — a webview-writable control would hand the
renderer the choice of whether its own turns are governed, **including the downgrade direction**.
Independently of that, it could not change an outcome: `governed_verification_unconfigured()` returns
`Some(...)` unconditionally, so turning it "on" swaps a working ungoverned chat for a uniformly
refusing one. The amended criterion is a read-only control that reports all three named states, and it
was **not already met** — the row reported two of the three (`blocked` lived only in a panel elsewhere
on the page) and, being `disabled`, was removed from the tab order, so the state it exists to report
was unreachable to a keyboard user. Now: `default`/`on`/`blocked` from the real `ai_status`,
`aria-disabled` instead of `disabled`, activation inert. Five mutations, five caught.

**2. Governed streaming (slice 3) — DESCOPED, not deferred.** A governed turn is buffered *by
construction*: the desktop's sole authority is the isolated signer's envelope, which binds
`output_bytes` + `output_sha256` over the **whole** output. There is no per-delta signature and no
contract that could produce one, so a streamed delta would be unverified content rendered before any
verdict exists — the inverse of "no verified signature ⇒ no result". `governed_turn.rs`, the roadmap
and the status board now say this in the same words.

`core/src/governed_output_stream.rs` is **not** that streaming, and mistaking it for that is what kept
the question open. It is the rev-30 §4.10(f) chunked **pull** of an already-completed output, it has
**zero production callers** (only `create_schema` is called, from four binaries), and its table
diverges from the design it cites — INSERT-ONCE with receipt/attempt/handle bindings in the design,
versus a mutable `state` column and a `broker_turn_id` here — so wiring a caller is a rewrite, not a
hookup. The Phase-1 DoD box stays **open** on that pull; the phase is not closed by this ruling.

**The reachability gate could not have caught it, and now can.** `tools/check_reachability.py` covered
Tauri commands, Python engine symbols and capability grants — the entire `src-tauri` Rust tree, which
is where the security core lives, was invisible to it. `rustc` warns about an uncalled *private* item
and says nothing about a `pub fn` in a library crate, which is exactly how a public, documented,
nine-unit-test ladder shipped with no callers and a clean build. A `rust_symbols` section now scans it,
requiring a caller to **name** the symbol (`module::name(`) because a bare-name scan would have counted
`ai.rs`'s own unrelated `resolve()` as a caller of `governed_output_stream::resolve` — a false green
produced by the gate that exists to prevent false greens. Ten mutations, ten caught (one survived
first: the test meant to defend the defining-file exclusion did not actually exercise it, and was
rewritten until it did). 67 gate self-tests, 415 tools tests, 632 frontend tests, all green.

**Left for the Owner, not silently absorbed:** the DoD box *"One governed round-trip proven
end-to-end — done"* reads over-ticked against this repository's own status board (`engine_sidecar.
_real_callables()` still raises unconditionally) and against the unchecked task-checklist line *"Slice 2
— prove one governed round-trip (adapter ↔ real supervisor)"*. It was not flipped here: Phase 1 stays
open either way, so nothing is unlocked by leaving it, and re-judging a merged claim is the Owner's
call rather than a side effect of this change.

### The canonical law is enforced at the repository root (2026-08-09)

The read receipt, the roadmap order and the update law are no longer prose. `.claude/hooks/canonical_law_gate.py`
runs at `SessionStart` and `PreToolUse`; `tools/check_read_receipt.py`, `tools/check_roadmap_order.py`,
`tools/check_prior_art.py` and `tools/check_canonical_sync.py` are the gates behind it.

**Why it was needed.** The receipt mechanism already existed and worked — in `engine/`. Its root was
`engine/`, its manifest was `engine/config/canonical-read-manifest.json`, and it was wired only at
`engine/.claude/settings.json`. A session opened at the repository root got a single `Stop` guard and
nothing else, so `CLAUDE.md`'s "the repository hook is the enforcement wall" was true one directory down
and false where anyone actually stood. Three days of work were done against a stale roadmap because of it.

**What binds now.** A session must record a SHA-256 receipt over every canonical file before it may edit;
a canonical file changing mid-session voids the receipt and the new text is handed over. It must declare
which roadmap phase it is working, and that must be the first phase whose Definition of Done is not fully
checked — declaring a later one is refused by name. Creating a new file requires a recorded prior-art
search. And a commit touching substantive files without moving `NEXT_CHAT.md`, `PROJECT_STATE.md`,
`TASKS.md` and `config/current_state.json` is refused, with no environment bypass — the bypasses on the
older Stop-hook are why the rule was broken.

**What it does not do, stated rather than implied.** Shell writes are not gated: `sed -i` and `>` bypass
the PreToolUse matcher, because classifying shell safely is unsound and the engine's own wall documents
that. `CANONICAL_LAW=off` disables it, deliberately, as the recovery path. The receipt is forgeable by the
agent it binds. And a session may edit the wall — what it cannot do is edit it *silently*, since the
change lands in a diff the update law and CI both govern.

**Phase completion is a checkbox, and the gate says so.** No machine-readable completion signal existed;
`current_state.json` carries wave and task tokens, not per-phase state. So a phase counts complete only
when its DoD checkboxes and its status-board row agree — a lie has to be told twice, in a diff, in a
commit the update law governs. That is a paper trail, not custody.

Fifteen mutations were run against the gates and all fifteen were caught. Proving the escape path found a
real bug: a *refused* phase declaration was still persisted, wedging the session on a phase it had never
been allowed to claim. Fixed and regression-tested.

It also found a live defect while widening `check_reachability.py` rather than duplicating it:
`tools/check_i18n_parity.py` ran in no workflow at all. The invariant was never unguarded —
`src/i18n/i18n.parity.test.ts` runs in `cockpit-frontend` — but the standalone gate was unreached, and
the Phase-4 board row claiming "enforced in CI" pointed at the wrong thing. Now wired into
`design-gates.yml`.


> **Canonical file. Read it at the start of every session, and update it in the SAME commit as any change.**
> **Canonical ֆայլ։ Կարդա ամեն session-ի սկզբում, ու թարմացրու նույն commit-ում ինչ փոփոխությունը։**

**Last updated · Վերջին թարմացում:** 2026-08-10 — **the Owner ruled rev-30 approved, and the record now names who decided.** config/current_state.json carried CURRENT_DESIGN_GATE: GREEN while the addendum own banner said DESIGN RED / PENDING re-audit, and §0 of that document says it wins over any file that disagrees — so a token had been asserting a verdict the normative source denied. Resolved by writing the Owner waiver into the banner and changing the token to OWNER_APPROVED_NOT_ARCHITECT_AUDITED in all four canonical files, because a reader who only sees a status line must not mistake an Owner waiver for an Architect audit. No Architect re-audit of rev-30 has taken place; an independent audit of the resulting code is still required and the standing independent verdict is RED. **The production gate stays SHUT.** · _Previous entry (2026-08-09):_ — **audit-position pass: the standing verdict is RED and every doorway now says so.** A second cold read found that the Owner's SECOND independent audit (`main` @ `219c763`, **RED**, 4/18 blockers closed, 122 surviving findings, 1 P0) appeared in **no** canonical file, and that `apps/desktop/AUDIT/AUDIT_LEDGER.md` was on no read list — while `NEXT_CHAT.md` opened with the FIRST audit's “all code facts CONFIRMED”. Structural fixes, not sentence fixes: the ledger is now in `config/canonical-read-manifest.json` and is step 7 of `START_HERE.md`; the RED verdict is generated into all three banners by `tools/sync_active_pr.py` (the same generator that used to stamp the false broker sentence), so it cannot be corrected in one file and missed in two; and the four FREE-TEXT fields of `config/current_state.json` — which nothing read, and which were all four wrong at once — are now checked against the structured fields in the same file by `check_coordination.py` (7 new tests, each verified by mutation). Also corrected: **F-29 is NOT closed** (the verifying-key guard cannot fail; the code said so and `NEXT_CHAT.md` said CLOSED — now a named item in `docs/OWNER_ACTION_REQUIRED.md`); the audit ledger is **not tamper-evident on a shipped install** (nothing sets the anchor custody vars, no installer ships the signer, so `append()` writes a plaintext head); `CLAUDE.md`'s phase table (both languages) showed Phases 2–9 blocked while migrations 0020–0022 ship; a superseded phase table was **deleted** from `MASTER_EXECUTION_ROADMAP.md`; `SCHEMA_VERSION` is 22 not 17; the engine suite is 1282/43 not 591/38; T-017 and T-003 are Done, not In-Progress; and the Armenian halves of the required-checks and Owner-artifact claims caught up with the English. **The production gate stays SHUT.** · _Previous entry (2026-08-09):_ **repository-truth pass: the prescribed reading order no longer leads to stale text.** This line is now a **checked** claim: `tools/check_coordination.py` compares the date against the newest commit that touched this file and turns RED when the file changed after the date it claims. It used to check only that the line was non-empty while printing *"PROJECT_STATE fresh"* — which is why it sat three days behind without anything noticing. This cycle: the CURRENT STATE block above is current and the 2026-08-06 snapshot below it is inside HISTORY markers; the `platform_governed_execution_supported()` correction reached the four documents it had skipped (`README.md`, `docs/ARCHITECTURE.md`, `OWNERS.md`, `MASTER_EXECUTION_ROADMAP.md`) plus `config/spec-conformance.json`; the false *"the broker hands out `UpstreamBlockedExecutor`"* was corrected in `tools/sync_active_pr.py` (the generator that stamped it into three canonical files) and everywhere it had been repeated — the broker is fail-closed **by default**, and the condition is what a reader needs; the *"28 required checks"* claim is gone (**31 checks run, zero are required** — `main` has no branch protection and no rulesets, which is the Owner's to enable); `docs/PHASE_10_PRODUCTION_ITEMS.md` and `docs/SECURITY_MODEL.md` now agree on which O-items need an Owner secret, and `tools/check_residual_items.py` checks the column that let them disagree; and `demonstration_verified_reply` — registered, exported, wired to a button, and unable to succeed on any input because it gated on `production_verified`, which is always false under the demonstration anchor — was fixed and given a test that runs on both CI platforms. **The production gate stays SHUT.** · _Previous entry (2026-08-06), kept because it is the state of record for the keystone:_ **keystone blocker F-01 (P0) CLOSED**: the supervisor's `attest-run` was a sign-arbitrary-facts oracle over a dead durable state machine; it is now driven by the supervisor's OWN durable acceptance/lease/completion ledger over a CI-gated shared DDL, and `build_run_attestation` has no `facts` parameter at all (§5 v2 amendment in [`docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md)). **F-23**, the evidence-floor half of **F-09**, and the supervisor leg of **F-11** close with it. **11 of the 12 soundness-blockers remain; `platform_governed_execution_supported()` stays false and `main()` keeps `UpstreamBlockedExecutor`.** Verified: engine 897 ✅ · Rust workspace ✅ (brops-core 240+2+14, broker 17, win-live 7, live-proof 3) · **the Linux 7-service live governed turn is GREEN on this protocol and now runs on every CI event** (`live-governed-turn`, run 31078055077 at `a64c8cc`: `production_verified=true bound=true` over six real uids, SO_PEERCRED and the setuid launcher — closing the audit's ci-tests gap that nothing reproduced it) · coordination/capabilities/ledger-DDL gates GREEN. GREEN there means the CHAIN runs, NOT that the kit's custody is production-grade (F-17/F-07/F-28 and the F-02 evidence counters stay open). Earlier the same day: Owner's 25-agent **INDEPENDENT AUDIT** of `main` checked + committed at [`apps/desktop/AUDIT/2026-08-06-independent-audit.md`](apps/desktop/AUDIT/2026-08-06-independent-audit.md); all code facts CONFIRMED — it PROVES the shipped gate must stay false and EXPANDS the keystone with **12 soundness-blockers** (see [`NEXT_CHAT.md`](NEXT_CHAT.md)); non-keystone confirmed findings fixed on PR #53 — F-04 git-read containment, F-12 advance-gate, F-16/F-19/F-20/F-46 CI gates). Earlier 2026-08-04: Phase 2 COMPLETE on `main`; Wave 3b consolidation **PR #48 MERGED**; active workflow **PR #53** Windows LIVE machine-proof; production custody graduated + in-app agent + cockpit UX; **GitHub Release `brops-desktop-v0.1.0`**; shipped desktop "Verified" **still fail-closed**.
<!-- CURRENT_STATE: the single authoritative present-tense truth. Tokens are validated against config/current_state.json.status_tokens by tools/check_coordination.py. Historical prose is inside HISTORY markers and is NOT current. -->
> **▶ CURRENT STATE — the one authoritative present-tense truth.** Tokens:
> `CURRENT_ACTIVE_TASK: T-017` · `CURRENT_ACTIVE_WAVE: 3b-1B` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`
>
> **Where things actually stand (2026-08-09).** `main` is at `b3010f6` (the anchor's
> `settled_at_main_head`) — a baseline at the time of writing; resolve the live HEAD yourself every
> session. PR #81 was the last to merge. **No implementation work is queued here.** What is blocked,
> and on whom, is [`docs/OWNER_ACTION_REQUIRED.md`](./docs/OWNER_ACTION_REQUIRED.md). Next up: the
> POSIX installer (mint the anchor as another uid), the SCM service implementation, then the
> independent audit.
>
> **The production gate is SHUT** (`CURRENT_PRODUCTION_VERIFIED: false`) and stays shut until an
> independent audit passes and the Owner approves: `governed_verification_unconfigured()` returns Some(...) unconditionally before the model is invoked, `connect_broker()` refuses off Linux, and the broker serves `UpstreamBlockedExecutor` unless `$BROPS_BROKER_CONFIG` names a deployment config with a TCB-root-signed manifest -- which nothing in the shipped app sets. No function named
> `platform_governed_execution_supported()` exists in the tree — that is the §0.1 spec symbol.
>
> **Two tokens above are PROVENANCE, not open work:** `CURRENT_DESIGN_PR: 48` / `CURRENT_IMPL_PR: 48`
> name the PR the Wave-3b design and implementation landed on. PR #48 merged; so did PR #53 and
> everything through PR #81.
>
> **⚠ The three paragraphs that follow are HISTORY (written 2026-08-06).** They were left in the
> present tense under a heading that said *authoritative*, so a reader following the prescribed order
> was told PR #53 was active and `main` was at `b91f2356`, three days after both stopped being true.
<!-- HISTORY_BEGIN -->
> **[HISTORY 2026-08-06]** Wave 3a slices 1–3 are **merged, zero-trust GREEN** — the verify-seam, receipt-plumbing, and the real fail-closed governed round-trip **all landed** (PR #28). Wave 3b-0 design **merged** (PR #30). **Phase 0 (repository-truth remediation) is DONE** (baseline `b6c6712`). **The whole Wave 3b workflow — the 3b-1A boundary code, the 3b-1B design addendum, the 3b-1B/3b-2/3b-3 implementation, the live-proof kit, and the 22-page cockpit — was consolidated as PR #48 (`feat/cockpit-pages`, base `chore/main-resync`, head `38d5d715…`, superseding the split PR #46 impl / #31 design / #32 impl) and is now MERGED into `main`** together with **Phase 2** (the AI-surface governance slices #49/#50/#51/#52) → `main` tip `b91f2356`. `CURRENT_DESIGN_PR`/`CURRENT_IMPL_PR: 48` records that provenance; `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` reflects that the external Architect CODE-audit was never run (the Owner merged on the three converged builder passes + the independent Windows-broker audit GREEN, and waived the external audit). The snapshot's **current_workflow_pr is now PR #53** (`feat/windows-broker-machineproof`, base `main`, head `462edc5`) — the additive Windows LIVE machine-proof, a self-carrier exact-head-anchored by its PR-body **`AUDIT_CANDIDATE_HEAD`** marker.
>
> **Design:** the 3b-1B design is **Architect DESIGN GREEN at rev-30** (relayed by the Owner). **Design-GREEN is NOT code-GREEN.** **Code-audit:** three independent adversarial security passes **converged** (10 → 6 → 1 P1, ALL fixed; trust-boundary / chain / manifest CLEAN) — this is the **BUILDER's** evidence; the external **Architect CODE-audit gate is still pending** (do NOT claim Architect code-GREEN). **Live proof:** the **full 7-service production governed turn ran GREEN on real Linux** — the first production `trusted_verified` proven live (real service accounts, setuid launcher → executor, ed25519 keys + root-signed manifest, `verify_and_accept`); 3b-2 + 3b-3 are implemented + wired in the live kit (`engine/ci/live/run_live_turn.sh`). **Shipped-app honesty:** the SHIPPED desktop app's production "Verified" is **STILL fail-closed** — `main()` keeps `UpstreamBlockedExecutor`; the live chain is not yet wired into the desktop runtime, so **no production `trusted_verified`** ships yet. The 22-page cockpit is built + wired to real backends; app functional. **Open:** the Architect CODE-audit, wiring the live chain into the desktop runtime, the remaining AI entry points, **Windows production isolation**, Phases 2–10. **Engine security remediation is still pending** — `engine/config/documentation-manifest.json` carries `deployment: blocked-pending-security-remediation`, and the enforcement wall carries an accepted **HIGH** open gap **O-1 (bytecode-shadow)** plus O-2..O-5 (`CLAUDE.md`); the independent audit's keystone soundness-blockers (F-01..) gate production `trusted_verified`. Ticket status of record: [`apps/desktop/AUDIT/AUDIT_LEDGER.md`](apps/desktop/AUDIT/AUDIT_LEDGER.md) + [`apps/desktop/AUDIT/2026-08-06-independent-audit.md`](apps/desktop/AUDIT/2026-08-06-independent-audit.md).
>
> **Next action:** PR #48 is merged; the active workflow is **PR #53** (additive Windows LIVE machine-proof). The remaining enablement is to **wire the live-proven trust chain into the shipped desktop runtime** (retire `UpstreamBlockedExecutor` in `main()`) to enable production `trusted_verified`, and for Windows land the remaining broker hardening + a **separate Architect audit of the Windows broker** before flipping `platform_governed_execution_supported()`. Do **not** expose "Verified" before that gate + Owner approval.
>
<!-- HISTORY_END -->
>
> Machine mirror: [`config/current_state.json`](./config/current_state.json).
<!-- CURRENT_STATE_END -->

---

## 🗄️ Historical / audit log — NOT current state (do not read as present-tense truth)
<!-- HISTORY_BEGIN -->
**[history] Wave 3a slice 2 (receipt storage & atomicity, T-015) — DONE, MERGED** (PR #26, approved HEAD `64c2372`, squash **merge commit `9b214e5`** on `main`; zero-trust GREEN after a YELLOW + two RED rounds; 7/7 CI). **Wave 3a is COMPLETE — slice 3 (transport wiring + receipt trust UI, T-016) DONE, MERGED** (PR #28, approved HEAD `dee6661`, squash **merge commit `8a580028`** on `main`; zero-trust GREEN after a YELLOW + two RED rounds; 7/7 CI). The desktop now CALLS the merged verifier on a real governed turn (one `PreparedGovernedTurn` single source; exact structured `system`+`history` are the bridge signing authority; key-authority resolved in-tx, no fake key; bridge=transport/desktop=authority with the `verified` bool removed; `issue_challenge`→`verify_and_record_receipt(&NoTrustedManifest)`→Blocked turn-level notice, no double-post; transport-fail closes the nonce with a bounded real reason; dev/blocked badges; JCS parity + e2e). Fail-closed strict 3a: every governed turn Blocks until **Wave 3b (T-017)** provisions a key. core 89 · host 42 · bridge 35 py · frontend 6 green; clippy-clean. Slice 2 shipped migration **0014** (`SCHEMA_VERSION`=14 — `receipt_verification_attempts` with `wire_*` + decoded evidence and DB-level accepted⇔message / blocked⇔no-message CHECK, durable one-time `receipt_challenges` nonce, accepted-only `receipt_ids_seen` uniqueness ledger) + `brops-core::receipt_store` (`verify_and_record_receipt` = one `BEGIN IMMEDIATE` verify→consume→persist; `issue_challenge`; `ReceiptOutcome` has **no `TrustedVerified` variant** — production⇒Blocked). Architect **YELLOW** then **RED×2** audit rounds RESOLVED: **R1** (challenge `request_sha256` NOT-NULL+hex compared in-tx; staged decoded evidence on bad-sig/bind-fail; nested-tx reject + explicit COMMIT-failure rollback); **R2** (`issue_challenge(conn, conversation_id, &IssuedRequest, now_ms)` derives nonce+hash from one source — no split-authority; `message_id` `ON DELETE RESTRICT` + full accepted⇔message CHECK so a conversation/message delete with governed evidence is **refused**, keeping output bytes re-hashable; the concurrency test is now a **real threaded race** with a `Barrier`; `rusqlite` `hooks` moved to dev-dependencies). **83 core tests** (14 slice-2 negative-matrix incl. the threaded race), clippy-clean, coordination + capabilities GREEN. Prior: **Wave 3a slice 1 (protocol core) — DONE, MERGED** (T-014, PR #24). Approved HEAD `c51031e`, squash **merge commit `6c920d0`** on `main`; **zero-trust GREEN** after three RED rounds (key-authority binding, `Wave3aTrustState` with no `TrustedVerified` variant, `IssuedRequest` request-hash recompute — all resolved audit history); final CI 7/7 GREEN; `brops-core` **69 tests**, clippy-clean. Slice 1 shipped the pure, I/O-free `brops-core::receipt` (RFC 8785 JCS, strict decode, verify-only `verify_strict`, type-state `parse→verify→bind→resolve_3a`, never a `sign()` oracle). **Wave 2 (T-010 + T-011) + Wave 1 (T-012) + Wave 2a (T-013) complete.**
<!-- HISTORY_END -->
> _(The authoritative present-tense state is the ▶ CURRENT STATE block at the top of this file.)_

---

## 📍 Where we are · Որտեղ ենք

- **Canonical execution source:** [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md) — status
  `v1.0 · Canonical Execution Authority` 🔒 **Locked** (Owner-approved 2026-07-21, basis HEAD `2e0157b`),
  **11 phases** fully expanded (16 sections each) with per-page UI specs from `brops-aios.html`, an
  Execution Ownership Matrix (§G), a Canonical Artifact Registry (§H), and Change Control (§I, now in
  force). A cold-start session takes the next unchecked task there. **Locked = product content
  change-controlled, not execution frozen** — building proceeds.
- **Coordination enforcement (T-007):** the Startup Law / docs-sync is now **enforced, not
  remembered** — a fail-closed **CI gate** (`tools/check_coordination.py`: roadmap 11×16, canonical
  files, TASKS statuses, PROJECT_STATE freshness) plus a fail-open **Stop-hook** (`.claude/`) that
  reminds when code changes without a coordination-doc sync.
- **Phase 0 — Foundation:** ✅ DONE (locked). OS monorepo assembled (`engine/` = Bro, `apps/desktop/` =
  BroPS, subtree history preserved), bilingual docs, unified CI.
- **Engine CI:** ✅ green — the 9 monorepo-coupled tests skip-guard themselves (option **C**);
  `Ran 1282 tests … OK (skipped=43)` — measured 2026-08-09 from this monorepo root on Windows.
  *(This said `591 passed, 38 skipped` until 2026-08-09, while `CLAUDE.md` §4 carried the measured
  figure. One file was updated and the other was not; that is the defect this repository keeps
  reproducing, so re-measure rather than copy either number.)*
- **Phase 1 — Bridge:** 🔨 in progress — `bridge/DESIGN.md` **APPROVED**; slice 1 (contract + adapter +
  tests + **bridge CI leg**) **merged to `main`** (PR #3, HEAD `41cf4ff`, 10/10 canonical — receipt-must-
  VERIFY invariant landed) **and** slice 2 **transport** — desktop Rust `Provider::GovernedEngine` in
  `ai.rs` (opt-in, default OFF) + governed sidecar wiring + chat receipt badge — **merged** (PR #8). *(The
  Settings governed toggle shipped in PR #8 was **removed in Wave 1** — replaced by a read-only provider
  status, PR #15.)* **DONE via Wave 3a slice 3 (T-016, PR #28 `8a580028`):** the verify-seam (adapter →
  injected verifier), receipt-plumbing into the turn, and one real fail-closed governed round-trip
  end-to-end all **landed** (`CURRENT_VERIFY_SEAM: complete`, `CURRENT_RECEIPT_PLUMBING: complete`,
  `CURRENT_GOVERNED_ROUNDTRIP: complete`). Governed **streaming** is intentionally **not** implemented
  (governed turns are buffered by security design, not a forgotten task). Still open: production
  `trusted_verified` (Wave 3b) and governing the remaining AI entry points.

## 👷 Who's working on what (NOW) · Ով ինչի վրա ա (ՀԻՄԱ)

| Agent | Task (see TASKS.md) | Branch | Status |
|---|---|---|---|
| 🔨 Claude | **Wave 3b (T-017) — isolated signer + execution→receipt binding + production trust chain** | **none — `main`.** `feat/windows-broker-machineproof` (PR #53) and `feat/cockpit-pages` (PR #48, folding in PR #31 / #32 / #46) are all **MERGED and deleted**; so is everything through PR #81. | ✅ **NOT ACTIVE.** Nobody is working on this row today: the Wave-3b implementation landed and `main` is settled at `b3010f6`. The gate stays shut — see the CURRENT STATE block at the top of this file and [`docs/OWNER_ACTION_REQUIRED.md`](./docs/OWNER_ACTION_REQUIRED.md). &nbsp; — _The rest of this cell is HISTORY, written 2026-08-06, when PR #53 was open:_ 🟡 **[HISTORY] the Wave 3b workflow was consolidated as PR #48 (base `chore/main-resync`, head `38d5d715…`, superseding the split PR #46 impl / PR #31 design / PR #32 impl) and is now MERGED into `main`; the active workflow is PR #53 (`feat/windows-broker-machineproof`, head `462edc5`). The 3b-1B design is Architect DESIGN GREEN at rev-30 (design-GREEN ≠ code-GREEN). Three independent adversarial security passes converged (10 → 6 → 1 P1, all fixed; trust-boundary/chain/manifest CLEAN) — that is the BUILDER's evidence; the external Architect CODE-audit gate is still PENDING (do NOT claim Architect code-GREEN). The full 7-service production governed turn ran GREEN on real Linux — the first production `trusted_verified` proven live (via `engine/ci/live/run_live_turn.sh`); 3b-2 (signed manifest/anti-rollback) + 3b-3 (production trust resolver) are implemented + wired in the live kit. BUT the SHIPPED desktop app's production "Verified" stays fail-closed (`main()` keeps `UpstreamBlockedExecutor`; the live chain is not yet wired into the desktop runtime), so no production `trusted_verified` ships yet. The 22-page cockpit is built + wired to real backends. **PR #48 (design+impl consolidation) is now MERGED into `main`** with the Phase-2 slices #49/#50/#51/#52 (tip `b91f2356`); the external Architect CODE-audit was waived by the Owner (three converged builder passes + the independent Windows-broker audit GREEN stand as the verdict). The **current_workflow_pr is now PR #53** (`feat/windows-broker-machineproof`, base `main`, head `462edc5`, CI green) — the additive Windows LIVE machine-proof, exact-head-anchored by its PR-body AUDIT_CANDIDATE_HEAD marker (nothing exempt). Next — wire the live chain into the shipped desktop runtime and land the remaining Windows broker hardening + a separate Architect audit before flipping the Windows gate. No shipped "Verified" until that gate + Owner approval. Machine mirror: [`config/current_state.json`](./config/current_state.json).** &nbsp; — <!-- HISTORY_BEGIN --> _History (accurate through the 3b-0 gate):_ Owner directive: custody boundary = trust boundary, Architect-gated design note before code. [`docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md`](./docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md) **rev 2** locks: dedicated OS **security principal** (not just `0700`) / receipt-key custody unreachable by the sidecar / an **authenticated run-evidence chain** (supervisor = trusted producer + only authenticated caller, `brops.run-attestation.v1`; recompute ≠ authenticity) / not-an-oracle IPC / auth checklist / context-aware `KeyResolutionQuery` + scope-bound key + in-tx anti-rollback / signed-manifest+pinned-root+anti-rollback / fail-closed / normative §4 schemas / threat model. **Architect design RED history:** rev 1 (`6a6882e`, 4 P0) → rev 2 (`9801489`, 2 P0 + 3 P1) → **rev 3** closes them: the supervisor **builds evidence from `{run_id, attempt_id}`** (no `attest(caller_evidence)` oracle anywhere; single topology — sidecar never touches the signer); a **content-addressed protected evidence store** binds containment/large inputs to real artifact bytes; **one fixed 256 KiB IPC frame** (large inputs = handles, no inline); resolver query sourced from the **trusted `Expected`** (not the unsigned receipt); manifest floor **+ exact bytes persisted atomically** with semantic-uniqueness rejects. **Architect design YELLOW on rev 3 (`fa1b8cb`, CI #96 green) — architecture approved, no new P0; rev 4 closes 5 contract redlines:** per-artifact canonical-bytes table pinned to merged formulas + all-formula parity (P1-1), nonce schema fixed to the merged UUIDv4 `id()` not `hex(32B)` (P1-2), durable forensic-attestation record in `sign-result` + containment via bridge result (P1-3), supervisor process/service/ACL/store/IPC reclassified **BUILD** + 4 same-user isolation tests (P1-4), protected-store atomic publish algorithm (P1-5). **Architect design YELLOW on rev 4 (`73ff0f7`) — architecture confirmed; rev 5 closes the final contract:** the desktop resolves the **supervisor-attestation key from the root-signed manifest snapshot** (not signer config) via an explicit `key_usage: receipt_signing | supervisor_attestation` discriminator with **total type separation** (two disjoint in-tx resolvers; a receipt key can never verify an attestation and vice-versa) + attestation-key negative matrix. **✅ Architect DESIGN GREEN on rev 5 (approved HEAD `def7711`, exact-head CI #98 success) — 3b-0 design gate PASSED (no open P0/P1).** 3b implementation may start **only after Owner approval**; the 3b-1 stop condition holds (`NoTrustedManifest` unchanged, no production "Verified"); first `trusted_verified` only after the full 3b-1→3b-2→3b-3 chain is exact-head zero-trust GREEN. **[End of 3b-0 history. Post-3b-0 reality is in the 🟡 CURRENT block at the top of this cell.]** **Wave 3a (slices 1+2+3) COMPLETE + merged** (`8a580028`). <!-- HISTORY_END --> |
| 📐 ChatGPT | — | — | — |
| 👑 Gev | reviews / approvals · roadmap **v1.0 🔒 Locked** (Owner-approved, basis HEAD `2e0157b`) | — | — |

## ⏭️ Next task · Հաջորդ task

Follow [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md). Immediate open items:

1. **Wave 3b — isolated signer + signed manifest + production "Verified" (T-017)** — fill the
   `ReceiptKeyAuthority` seam slice 3 left: a minimal isolated trusted signer with real key custody
   (private key unreachable by the sidecar), an operator-provisioned signed key manifest validated against
   a binary-pinned root anchor (per-key `trust_class`, validity window, epoch, revocation), and
   anti-rollback (durable highest epoch + hash). A production-class key renders **`trusted_verified`**
   ("Verified"). **Consolidated on `feat/cockpit-pages` (PR #48).** The 3b-1B design is **Architect DESIGN
   GREEN at rev-30** (design-GREEN ≠ code-GREEN). The 3b-1B/3b-2/3b-3 implementation is built and
   **proven live on Linux** (the first production `trusted_verified` ran end-to-end via
   `engine/ci/live/run_live_turn.sh`); three builder security passes converged (all P1 fixed). **But** the
   external Architect CODE-audit is still pending, and the SHIPPED desktop app stays fail-closed — the
   broker falls back to `UpstreamBlockedExecutor` because nothing sets `$BROPS_BROKER_CONFIG`, and the
   live chain is not wired into the desktop runtime.
   **Now MERGED into `main`** (with Phase-2 slices #49/#50/#51/#52); the external Architect CODE-audit was
   waived by the Owner (three converged builder passes + the independent Windows-broker audit GREEN stand
   as the verdict). **PR #53 is merged too, as is everything through PR #81 — no PR is open on this item.**
   **Next permitted action:** wire the live chain into the shipped desktop runtime (make
   `governed_verification_unconfigured()` a real provisioning probe and stop falling back to
   `UpstreamBlockedExecutor`), and for Windows land the remaining broker hardening + a
   separate Architect audit before the gate opens. No shipped "Verified" until that gate + Owner approval.
2. **Phase 2 (Governance Sidecar) — COMPLETE on `main`** (PR #50/#51/#52 merged): all four AI surfaces
   (`stream_reply` + `reply_in_conversation` + `stream_ask` + `stream_run_step`) route through
   `ai::governed_turn`; generic fallthrough dev-only + fail-closed. Remaining: wire the live chain into
   the shipped runtime so production `trusted_verified` can render (still fail-closed today).
3. **T-005 — Option-2 (AUDITED, Phase 10)** — engine submodule + worktree-check native fix. Separate
   branch/PR, Owner approval, must not destabilize.

## 🚧 Blockers · Խոչընդոտներ

- ~~A/B root-model decision~~ → **DECIDED: Option 1 (subtree + C)** for stability (Architect call). The 9 enforcement-path tests stay skip-deferred (C); no security code touched. Option 2 (submodule + Bro worktree-check fix) is a future audited task — **T-005**. Verified finding: a submodule alone does NOT fix it (`git worktree list` reports the git-dir). See `CLAUDE.md` §3.
- Bro deferred security items **O-1..O-5** (residual-exploitable) — do not rush, wall/owner-env coupled. The normative inventory, machine-checked by `tools/check_residual_items.py`, is [`docs/PHASE_10_PRODUCTION_ITEMS.md`](./docs/PHASE_10_PRODUCTION_ITEMS.md); the engine tracks them under its own IDs in `engine/AUDIT/tickets/`. *(This line used to say "tracked on Bro's `fix/audit-followups`". **That ref does not exist**, locally or on origin — corrected 2026-08-09.)*

## 🔁 Startup Law · Startup օրենք

Every session, before anything: **`git pull` → read `CLAUDE.md` → read `PROJECT_STATE.md` → claim your task in `TASKS.md`**. Only then start.
Ամեն session, ամեն բանից առաջ՝ **`git pull` → կարդա `CLAUDE.md` → կարդա `PROJECT_STATE.md` → claim քո task-ը `TASKS.md`-ում**։ Միայն հետո սկսի։

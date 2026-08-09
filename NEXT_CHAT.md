# NEXT_CHAT — definitive handoff · վերջնական handoff

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


> **New Claude or ChatGPT session:** this file + the canonical files it points to are
> everything you need. GitHub (`menqstudio/OS`) is the single source of truth — this
> chat's predecessors are gone; do not rely on any prior chat memory. Read this in
> full, then follow [`START_HERE.md`](./START_HERE.md).
>
> **▶ FIRST INDEPENDENT AUDIT (2026-08-06) — and it is NOT the current audit position; the banner at the top of this file is.** *(This block used to open “INDEPENDENT AUDIT COMPLETE … done and CHECKED”, and every word after it described round ONE. A SECOND independent audit then ran on the remediation and returned **RED** — 4 of 18 blockers closed, 122 surviving findings, 1 P0 — and said so in no canonical file. Two cold reads in a row read this sentence and concluded the audit had come back clean. “CHECKED” meant the Builder re-verified round one's FACTS; it never meant a clean verdict, and no verdict was ever green. Read `apps/desktop/AUDIT/AUDIT_LEDGER.md` before any ✅ below.)* The Owner ran a 25-agent read-only zero-trust audit of `origin/main` (`b91f235`); the Builder independently re-verified every P0/P1 + fanned 4 verification agents over the rest — **all code facts CONFIRMED, none refuted**. Full report committed at [`apps/desktop/AUDIT/2026-08-06-independent-audit.md`](./apps/desktop/AUDIT/2026-08-06-independent-audit.md) (47 security F-01..F-47 + 9 doc-drift D-01..D-09). **The audit is decisive for this keystone: it PROVES the shipped gate must stay false and it EXPANDS the keystone scope.** The keystone is NOT just "plumb the raw prompt" — the proof kit does not yet prove governed custody, and these **12 soundness-blockers MUST be closed before the production gate can EVER be flipped** *(this named `platform_governed_execution_supported()` until 2026-08-09; no function of that name exists in the tree — it is the §0.1 spec symbol, and the three real refusals are named in the banner at the top of this file)***:**
> - **F-01 (P0) — ✅ CLOSED 2026-08-06 (§5 v2).** *Was:* the supervisor `attest-run` was a sign-arbitrary-facts oracle — `build_run_attestation` held NO run state, shape-validated caller facts, stamped `decision="completed"` and signed; the durable state machine in `core/src/supervisor_ledger.rs` was **dead code** (only `create_schema` had a caller, re-verified by grep). *Now:* the supervisor owns a durable ledger over a SHARED DDL ([`engine/runtime/supervisor_ledger.sql`](./engine/runtime/supervisor_ledger.sql), byte-equality CI-gated against the Rust mirror by `tools/check_ledger_ddl_parity.py`). `accept-open` CASes an acceptance row (one signed challenge ⇒ exactly ONE attempt, replay returns the ORIGINAL lease); `launch-gate` takes only `{execution_attempt_id}` and judges the window the supervisor persisted (also closes **F-23**); new `execution-started` + write-once `complete-run` (which drives the evidence-head anti-rollback/anti-fork floor — the **F-09** floor half); `attest-run` takes only `{run_id, execution_attempt_id}` and `build_run_attestation` has **no `facts` parameter at all**, so the no-oracle rule is enforced by the type signature. The identities the isolated signer allowlists (`executor_id`/`builder_id`/`policy_*`) moved to supervisor provisioning; the broker now hands the signer the evidence **parsed from the exact attested bytes**. A fabricated run has no row ⇒ `no_terminal_run_state`. **Both** supervisor implementations were fixed — the Linux Python one (durable ledger) and the Windows machine-proof Rust twin in `win-live/src/servers.rs` (in-process state, proof-kit scope); fixing only one would have left the Windows proof still demonstrating the oracle. Normative contract: [`WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md` §5 v2](./docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md). **Proven by [`engine/tests/test_governed_chain_e2e.py`](./engine/tests/test_governed_chain_e2e.py)** — the whole chain offline (real authority → supervisor with a durable ledger **restarted mid-turn** → isolated signer, three distinct real Ed25519 keys), asserting the receipt signature, the attestation-digest binding, the output digest+length binding, the `request_sha256` recompute, and every F-01 negative. Verified: engine **895** ✅, Rust workspace ✅ (brops-core 240+2+14, broker 17, win-live 7, live-proof 3), all CI gates GREEN, no new clippy warnings. ✅ **The Linux 7-service live turn is GREEN on this protocol, and now runs on every CI event.** The `live-governed-turn` job (hosted ubuntu runner: six real uids, SO_PEERCRED, setuid launcher → contained executor, sudoers) printed a `RESULT:` line reporting `trusted_verified` under the production signer key id `brops-live-signer-1` at key epoch 2, with `production_verified=true bound=true`, at head `a64c8cc` (run 31078055077) — so the §5 v2 supervisor, its durable ledger, and the supervisor-published terminal artifacts all hold against the REAL OS trust boundary, not just an in-process harness. This also closes the audit's ci-tests gap that NOTHING reproduced the live e2e. Its first two runs found two real defects (a non-executable script, and the canonical `supervisor_ledger.sql` never staged into the kit — the supervisor correctly refused to start without its schema). ⚠️ **GREEN here means the CHAIN runs end to end; it does not mean the CUSTODY is production-grade** — custody is now labelled honestly rather than claimed (**F-17/F-07/F-28** closed 2026-08-06: the kit's run reports `production_verified=false root_anchor=kit_generated`), and its evidence counters are still constants (**F-02/F-18** open half). **Still open below.**
> - **Static/placeholder evidence (F-02, F-18):** `receipt_id` + record/lease/execution-receipt/containment/policy handles + `evidence_final_event_hash`/counts are deployment-static config constants (`chain_executor.rs:621` `fixed §4.9 evidence facts`; `provision_keys.py:86` hardcodes `"77"*32`). Nothing derives them from the run; `receipt_id` being constant also breaks the §7.1(d) replay key.
> - ~~**Unbound request↔output (F-08)**~~ — **CLOSED 2026-08-06.** The §4.3 lease now pins all three request digests and the launcher re-hashes the held fds 3/4/5 against them before it will exec; the live kit derives those pins from the provisioned store bytes and asserts they equal the digests the supervisor attests from.
> - **Unwired durable floors (F-09, F-10):** the acceptance CAS + evidence anti-rollback floor + the §2.5 TCB binary/config integrity floor (`tcb_integrity.rs:213`) have ZERO production callers — one signed challenge mints unlimited leases, and no binary integrity is measured before governed mode.
> - ~~**Self-certifying / world-writable custody (F-07, F-17, F-28)**~~ — **CLOSED 2026-08-06.** The root anchor is a root-owned TCB file carrying its own `provenance`; the driver enforces the §2.5 floor on it, refuses an inline config anchor, and reports `production_verified=true` only for an `external` anchor — so the kit's own run now prints `production_verified=false root_anchor=kit_generated` instead of claiming production. The store/report/socket directories are group-scoped to their real writers instead of `1777`.
> - **Decorative binding checks (F-23, F-26, F-27, F-29):** the supervisor lease is an unsigned wire object; final acceptance never binds the envelope `run_id/task_id/execution_attempt_id` to the obtained lease; `challenge_accepted_at_ms` is the broker's completion clock; the production "bound-to-verifying-key" guard (`production_trust.rs:54`) compares a value against itself. Each must be made load-bearing.
> Also: proof-kit robustness/DoS **F-11/F-31/F-32/F-36** (unbounded/un-timed reads, oversize-reply teardown) and engine anti-rollback honesty **F-06/F-13/F-14** are keystone-adjacent. **Do NOT flip the gate until every soundness-blocker above is closed, re-audited, and Owner-approved.** The Builder has already fixed the non-keystone confirmed findings on PR #53 (F-04 git-read containment, F-12 advance-gate, F-16/F-19/F-20/F-46 CI gates) — see the audit report's status.
>
> **▶ KEYSTONE PROGRESS (2026-08-06, this cycle): 1 of 12 soundness-blockers CLOSED.**
> **F-01 (P0) is closed** by the §5 v2 durable-supervisor amendment (details in the F-01 bullet above).
> Two adjacent findings fell out of the same change and are closed with it: **F-23** (the launch gate no
> longer judges a caller-supplied lease) and the evidence-floor half of **F-09** (the anti-rollback/anti-fork
> CAS now runs on every `complete-run`). **F-11**'s supervisor leg is also closed — the new exhaustive
> per-op shape checks quote offending field names, which would have been a fresh reply-amplification
> vector, so error text is bounded and `_try_write` degrades instead of letting a `FrameError` escape and
> kill the lease-issuing process. **F-02/F-18 is now PARTIAL**: `record_handle`/`lease_handle`/`execution_receipt_handle` left the
> broker's `produced` and are built + published by the supervisor per run (the live kit's placeholder
> blobs are deleted); the RECORDER now writes a per-run containment report the broker content-addresses (a missing
> report is a refusal), so the ONLY static values left are the four `evidence_*` counters — nothing
> measures a real recorder evidence chain. **Do not read F-02 as closed.**
> **F-26/F-27 are CLOSED** (2026-08-06): the final acceptance now binds the signed run/task/attempt
> to the run the broker authorized, and `challenge_accepted_at_ms` is the supervisor's accept clock
> (closed by F-01, now asserted e2e).
> **F-29 is NOT closed — corrected 2026-08-09.** This line said it was, on the strength of "the
> production verdict compares the key the CHAIN verified under instead of a second lookup of itself".
> The code disagrees, in its own words: `production_trust.rs` (the comment above the comparison in
> `resolve_trust_state`) records that two rounds of fix left the comparison **unable to fail** — every
> call site derives `envelope_verifying_key_hex` from `verifying_key_hex(...)` over the bytes that the
> SAME `resolve_production_key` lookup produced, so the second audit found the same tautology wearing
> one more indirection. The check is KEPT as fail-closed defence in depth for a future call site that
> obtains its key some other way; what is corrected is the CLAIM. The property that holds today holds
> by CONSTRUCTION (one source, not two agreeing ones), which is a weaker property than a check. The
> AUDIT_LEDGER was corrected when the code comment was written; this file was not, for three days.
> It is a live keystone finding and it is listed in [`docs/OWNER_ACTION_REQUIRED.md`](./docs/OWNER_ACTION_REQUIRED.md).
> **F-31/F-32/F-36 are CLOSED** (2026-08-06): the broker's serial accept loop arms a per-connection
> deadline, and the renderer→broker client both times out and caps ingress before buffering.
> **F-10 is PARTIAL** (2026-08-06): the §2.5 floor has a real `O_PATH|O_NOFOLLOW` probe and a real
> fail-closed caller in the production broker (`build_governed_executor` refuses to serve governed turns
> unless the pinned TCB set verifies). The live kit still does not provision the full 22-artifact pinned
> set, so the floor enforces on the production path but the proof kit cannot yet satisfy it.
> **REMAINING blockers** — **F-02/F-18** (the open half above); **F-10** — F-09's acceptance-CAS
> *lease-budget* framing is satisfied, and the §2.5 TCB floor now HAS a fail-closed production caller
> (see the F-10 PARTIAL bullet directly above; this line said "has no caller" three lines after the
> bullet that says it does — corrected 2026-08-09), but the live kit cannot yet satisfy it;
> **F-29** (the tautological verifying-key guard, corrected above — it was listed CLOSED here and is
> not); **F-06/F-13/F-14** (engine anti-rollback honesty). Take them ONE AT A TIME, same discipline.
> **The gate stays false.** And note the arithmetic: these are the FIRST audit's blockers. The
> SECOND audit's 122 findings are a separate, larger, un-remediated set — see the banner.
>
> **▶ NEXT KEYSTONE — production `trusted_verified` model-image slice (P0-2/P0-3), owner-approved to resume in a fresh focused session (2026-08-05).**
> Deep-dive finding: the session-0 governed chain (`win-live`) runs ENTIRELY over HASHES — `ResolvedTurn` (broker/src/chain_executor.rs), the driver `win_live_turn.rs`, and the executor carry only `system_sha256`/`history_sha256`/`generation_config_sha256`, NEVER the raw prompt; `win-live/src/bin/win_executor.rs` emits a constant and `executor/src/main.rs` `build_output` is a deterministic SHA-256 stand-in ('stand-in for the pinned model-inference step'). So wiring a REAL model is NOT a quick env-seam — the slice is a trust-chain extension: (1) carry raw system/history in the request envelope + verify `sha256(raw)==pinned hash` at the boundary; (2) plumb the raw prompt request → broker → resolved → execution → the contained executor's stdin; (3) `win_executor` reads the prompt and runs an env-gated LOCAL model command (owner chose the **generic contained model-command seam**; mirror the demo's `run_demonstration_model` / `BROPS_SELFTEST_MODEL_CMD`: `cmd /C <cmd>`, prompt on stdin → stdout=reply) and emits the reply for content-addressing. ALL fail-closed; the gate STAYS shut and the broker keeps falling back to `UpstreamBlockedExecutor` (nothing sets `$BROPS_BROKER_CONFIG`) — this is the win-live PROOF KIT, not the shipped runtime. *(This sentence named `platform_governed_execution_supported()` as the gate and stated the broker fallback unconditionally; corrected 2026-08-09 — no function of that name exists, and the fallback is conditional.)* This is trust-critical chain code: design→implement→verify, never rush. Even complete, exposing production Verified still needs the owner's pinned MODEL + the 3 servers running (authority/supervisor/signer) + an INDEPENDENT audit + owner approval. Context: the Linux broker is already a config-driven fail-closed drop-in (`BROPS_BROKER_CONFIG` + TCB-root-signed manifest); the broker + desktop broker-client are LINUX-ONLY (SO_PEERCRED); Windows session-0 cross-account containment IS proven (the 0xC0000142 was a debug-CRT DLL dep, resolved by release bins — win-live/proof/CROSS_ACCOUNT_PROOF.md).

> **Նոր session (Claude կամ ChatGPT):** այս ֆայլը + իր ցույց տված canonical ֆայլերը
> բավական են։ GitHub-ն ա միակ ճշմարտության աղբյուրը; հին chat-երին մի ապավինիր։

**Last updated:** 2026-08-09 — **audit-position pass.** The standing independent-audit verdict is **RED** (`apps/desktop/AUDIT/2026-08-06-remediation-audit.md`, `main` @ `219c763`: 4 of 18 blockers closed, 122 surviving findings, 1 P0) and it has never been re-run — it now leads the banner of all three state docs, and `apps/desktop/AUDIT/AUDIT_LEDGER.md` is on the canonical read manifest and in `START_HERE.md`. **F-29 is NOT closed** — §3's “F-26/F-27/F-29 are CLOSED” was wrong and the guard cannot fail; see `docs/OWNER_ACTION_REQUIRED.md` §1a. §4's schema (0022 / `SCHEMA_VERSION = 22`), §8's test counts and §10's “Wave 3b not implemented” are corrected. **11 of 12 first-audit soundness-blockers remain, the SECOND audit's 122 findings are a separate un-remediated set, and the gate stays false.** · §3's CURRENT STATE block is current and the 2026-08-06 snapshot that followed it is now inside HISTORY markers, because a reader following this file's own read order was landing on the older text. The keystone material below (▶ blocks, 2026-08-06) is unchanged and still the state of record: **11 of 12 soundness-blockers remain and the gate stays false.** · _Previous entry (2026-08-06):_ (**keystone blocker F-01 CLOSED** — the §5 v2 durable-supervisor amendment: `attest-run` is no longer a sign-arbitrary-facts oracle; F-23 + the F-09 evidence-floor half + the F-11 supervisor leg close with it; 11 blockers remain, gate stays false. Earlier same day: Owner's 25-agent INDEPENDENT AUDIT of `main` checked + committed at `apps/desktop/AUDIT/2026-08-06-independent-audit.md`; keystone scope EXPANDED with 12 soundness-blockers; non-keystone confirmed findings fixed on PR #53 — F-04/F-12/F-16/F-19/F-20/F-46) · earlier: 2026-08-04 (production custody + in-app agent + cockpit UX + Windows LIVE machine-proof, PR #53) · **Maintained by:** the implementer session, in the same commit as any state change.

---

## 1. Identity

- **Repository:** `menqstudio/OS` — a governed AI-operations desktop: a safe cockpit (`apps/desktop/`, Tauri) on a contained governance engine (`engine/`, Python). **Target invariant (being built toward, NOT yet fully true):** every production AI action follows the governed chain `lease → gate → sandbox → signed receipt`. **Today:** **Phase 2 is COMPLETE on `main`** — all four AI surfaces (`stream_reply` main seam + `reply_in_conversation` #50 + `stream_ask` #51 + `stream_run_step` #52) route through the governed chain (fail-closed under `NoTrustedManifest` — production "Verified" not yet available; generic fallthrough dev-only + fail-closed). The higher-phase surfaces (automations, group chat, integrations) are built + governed by construction in later phases.
- **Owner:** 👑 **Gev** (`menqstudio`, ohanyan.88@gmail.com). Armenian-speaking — reply in Armenian by default; English only for code/identifiers/commands.
- **Roles ([`OWNERS.md`](./OWNERS.md)):**
  - 🔨 **Claude** — Builder / Implementer. Writes code, tests, commits, opens PRs.
  - 📐 **ChatGPT** — Architect / **zero-trust auditor**. Reviews each security PR against the exact HEAD and returns GREEN / YELLOW / RED. **The audit is the gate.**
  - 👑 **Gev** — Owner / final approver & merger.

## 2. Single source of truth + mandatory startup

**GitHub is canonical. A textual claim ("I read it", "it's done") is not evidence — verify against the repo.**

Startup read order (from [`START_HERE.md`](./START_HERE.md), extended):

1. `git pull` and confirm HEAD.
2. **This file** (`NEXT_CHAT.md`) — exact current state.
3. [`CLAUDE.md`](./CLAUDE.md) — the brain: what OS is, how to work, environment gotchas, security discipline.
4. [`PROJECT_STATE.md`](./PROJECT_STATE.md) — live status (who's on what, blockers).
5. [`TASKS.md`](./TASKS.md) — the task board; **claim your task before touching anything**.
6. [`OWNERS.md`](./OWNERS.md) — roles.
7. [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) + [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md) — design + canonical execution plan.
8. For the current security work: [`docs/design/WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md`](./docs/design/WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md) and the machine-readable [`config/canonical-read-manifest.json`](./config/canonical-read-manifest.json).

## 3. Current work — exact pointers

> **CURRENT STATE (authoritative; machine-mirror: [`config/current_state.json`](./config/current_state.json)).**
> Tokens (validated against `config/current_state.json.status_tokens`): `CURRENT_ACTIVE_TASK: T-017` · `CURRENT_ACTIVE_WAVE: 3b-1B` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`
>
> **How to read those tokens — two of them are PROVENANCE, not open work.** `CURRENT_DESIGN_PR: 48`
> and `CURRENT_IMPL_PR: 48` record the pull request the Wave-3b design and implementation landed on.
> **PR #48 is merged. So is PR #53, and so is everything up to PR #81.** Neither number names
> anything you are waiting for. They are restated here verbatim only because
> `tools/check_coordination.py` requires every token in the anchor to appear in this region.
>
> **Where things actually stand (2026-08-09).** `main` is at `b3010f6` — the anchor's
> `settled_at_main_head`, and a baseline at the time of writing: **resolve the live HEAD yourself
> every session and never trust this line over `git log`.** PR #81 was the last to merge; the only
> open pull request is **#82** on `settle/after-81`, the self-carrier that records the settle and
> this correction. There is no queued implementation work; what is blocked, and on whom, is
> [`docs/OWNER_ACTION_REQUIRED.md`](./docs/OWNER_ACTION_REQUIRED.md) — read that page before any
> older prose in this file.
>
> **The production gate is SHUT** (`CURRENT_PRODUCTION_VERIFIED: false`) and stays shut until an
> **independent** audit passes and the Owner approves. **The governed surfaces stay fail-closed.** `governed_verification_unconfigured()` returns Some(...) unconditionally before the model is invoked, `connect_broker()` refuses off Linux, and the broker serves `UpstreamBlockedExecutor` unless `$BROPS_BROKER_CONFIG` names a deployment config with a TCB-root-signed manifest -- which nothing in the shipped app sets. Do not go looking for
> `platform_governed_execution_supported()`: no function of that name exists in the tree — it is the
> §0.1 spec symbol, which `config/spec-conformance.json` records as `partial` for that reason.
>
> **Next:** the POSIX installer (provisioning must mint the anchor as another uid), the SCM service
> implementation, then the independent audit.
>
> **⚠ EVERYTHING BELOW, TO THE END OF §3, IS HISTORY.** It was written in the present tense on
> 2026-08-06 and left standing under a heading that said *authoritative* — which is how a reader
> following this file's own prescribed order arrived three days and roughly thirty merged commits
> behind, believing PR #53 was open and `main` was at `b91f2356`. It is kept for provenance, inside
> HISTORY markers so the coordination gate stops scanning it for present-tense truth. Read it as
> "how we got here", never as "where we are".

<!-- HISTORY_BEGIN -->
> **[HISTORY 2026-08-06] Consolidation note (T-017 / Wave 3b):** the whole Wave 3b workflow — the 3b-1A boundary code, the 3b-1B design addendum, the 3b-1B/3b-2/3b-3 implementation, the live-proof kit, and the 22-page cockpit — was **consolidated on branch `feat/cockpit-pages`** as **PR #48** (base `chore/main-resync`, head `38d5d715…`, superseding the earlier split PR #46 impl / PR #31 design / PR #32 impl), and **PR #48 is now MERGED into `main`** (with the Phase-2 governance slices #49/#50/#51/#52) — `main` tip `b91f2356`. `CURRENT_DESIGN_PR`/`CURRENT_IMPL_PR: 48` records that provenance; `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` reflects that the external Architect CODE-audit was never run (the Owner merged on the three converged builder security passes + the independent Windows-broker audit GREEN, and waived the external audit). The snapshot's **current_workflow_pr is now PR #53** (`feat/windows-broker-machineproof`, base `main`, branch head `462edc5`) — the additive Windows LIVE machine-proof, a **self-carrier** exact-head-anchored by its PR-body **`AUDIT_CANDIDATE_HEAD`** marker (event head == live headRefOid == marker; nothing is exempt).
> - **Design: `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED`.** The 3b-1B design is **Architect DESIGN GREEN at `CURRENT_DESIGN_CANDIDATE: rev-30`** (relayed by the Owner) — this supersedes the stale rev-27 RED / rev-28 pending history below. **Design-GREEN is NOT code-GREEN.**
> - **Code audit: `CURRENT_CODE_AUDIT: ARCHITECT_PENDING`.** Three independent adversarial security passes **converged** — 10 → 6 → 1 P1, **ALL fixed**; trust-boundary / chain / manifest **CLEAN**. That is the **BUILDER's evidence**; the external **Architect CODE-audit gate is still pending** — do **NOT** claim Architect code-GREEN.
> - **Live proof: `CURRENT_LINUX_E2E: proven`.** The **FULL 7-service production governed turn ran GREEN on real Linux** — the **FIRST production `trusted_verified` proven live** (real service accounts, real setuid launcher → executor, real ed25519 keys + root-signed manifest, `verify_and_accept`). **3b-2** (signed manifest / anti-rollback) and **3b-3** (production trust resolver) are **implemented + wired in the live kit** (`engine/ci/live/run_live_turn.sh`).
> - **Shipped app honesty: `CURRENT_PRODUCTION_VERIFIED: false`.** The SHIPPED desktop app's production "Verified" is **STILL fail-closed** — `main()` keeps `UpstreamBlockedExecutor`; the live chain is proven in the live kit, **not yet wired into the desktop runtime**. The chain is proven live, but the shipped app cannot render production `trusted_verified` yet.
> - **Cockpit:** the 22-page cockpit is **built + wired to real backends; app functional.**
> - **Next permitted action:** PR #48 (design+impl consolidation) is merged; the active workflow is **PR #53** (the additive Windows LIVE machine-proof). The remaining enablement is to **wire the live-proven trust chain into the shipped desktop runtime** (retire `UpstreamBlockedExecutor` in `main()`) and, for Windows, land the remaining broker hardening + a **separate Architect audit of the Windows broker** before flipping `platform_governed_execution_supported()`. Do **NOT** expose production "Verified" before that gate + Owner approval.
>
> The narrative below is the accurate 3b-0 design-review history (rev 1→5); it ends at the 3b-0 gate.

**Wave 3a is COMPLETE — slices 1, 2 AND 3 are DONE and merged.** **Wave 3b DESIGN-FIRST history** — its **3b-0 design** was reviewed and **MERGED via PR #30** (merge commit `df3c0ac`); the design lived on `design/wave-3b-isolated-signer` ([`docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md`](./docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md)). **Architect design RED ×2 (rev 1 `6a6882e` = 4 P0; rev 2 `9801489` = 2 P0 + 3 P1); rev 3 closes them all.** rev 3 locks: the **supervisor builds evidence itself from `{run_id, execution_attempt_id}`** — no `attest(caller_evidence)` oracle anywhere and a single topology (the signer's only peer is the supervisor over direct ACL'd IPC; the sidecar never connects to the signer); a **content-addressed protected evidence store** so containment + large inputs bind to real artifact bytes, not a hashed reference; **one fixed 256 KiB IPC frame** with large inputs as handles (no inline); the resolver query sourced from the **trusted `Expected`/turn** (only `key_id` from the unsigned receipt); and the manifest floor **plus exact canonical bytes persisted atomically** with semantic-uniqueness rejects + signed-in `root_key_id`. **Architect design YELLOW on rev 3 (`fa1b8cb`, CI #96 green) — architecture approved (no new P0); rev 4 closes 5 contract redlines:** per-artifact canonical-bytes table pinned to the merged desktop formulas + all-formula parity (P1-1), the nonce schema fixed to the merged UUIDv4 `brops_core::id()` not `hex(32B)` (P1-2), a durable forensic-attestation record in `sign-result` + containment bytes via the bridge result (P1-3), the supervisor process split/service/ACL/store/IPC reclassified **BUILD** (only `bro_supervisor.py` logic is reused; the live path still spawns `engine_sidecar.py` with fail-closed placeholders) + 4 same-login-user isolation acceptance tests (P1-4), and the protected-store atomic publish algorithm (P1-5). **Architect design YELLOW on rev 4 (`73ff0f7`) — architecture confirmed; rev 5 closes the final signed-key-authority contract:** the desktop resolves the **supervisor-attestation key from the root-signed manifest snapshot** (not signer config, which the desktop can't trust) via an explicit `key_usage: receipt_signing | supervisor_attestation` discriminator, with **total type separation** — two disjoint in-tx resolvers so a receipt key can never verify an attestation and an attestation key can never render "Verified" — plus the attestation-key negative matrix. **✅ Architect DESIGN GREEN on rev 5 (approved HEAD `def7711`, exact-head CI #98 success) — the 3b-0 design gate is PASSED (no open P0/P1).** Per the Architect verdict, 3b implementation may begin **only after Owner approval**; the 3b-1 stop condition stays mandatory (`NoTrustedManifest` unchanged, no production "Verified" exposed), and the first `trusted_verified` is allowed only after the full 3b-1→3b-2→3b-3 chain is exact-head zero-trust GREEN. **[SUPERSEDED — see the CURRENT STATE block above: PR #30 is MERGED (`df3c0ac`); 3b-1 is underway as PR #31 (3b-1A Code GREEN + 3b-1B rev-26 design candidate PENDING re-audit — the RED verdicts above were on the EARLIER 3b-0 revs 1–2, not rev-26) with WIP implementation in PR #32.]** (Owner directive: the private-key custody boundary IS the trust boundary — no rushing the engine perimeter.) Slice 3 (T-016, PR #28, approved HEAD `dee6661`, squash **merge commit `8a580028`**) wired the desktop to CALL the merged verifier on a real governed turn (fail-closed strict 3a: every governed turn Blocks until Wave 3b provisions a trusted key), through the `ReceiptKeyAuthority` seam, a single `PreparedGovernedTurn` source, exact structured `system`+`history` as the bridge signing authority, buffered `governed_turn`, a turn-level Blocked notice with no double-post, dev/blocked badges, JCS cross-language parity, and bounded transport-failure evidence. Zero-trust GREEN after a YELLOW + two RED rounds; final CI 7/7 GREEN.
> _(The authoritative present-tense state is the CURRENT STATE block at the top of §3. Everything from that block's ⚠ line to the end of this section is history.)_

| | |
|---|---|
| **Active PR / branch / task** *(as of 2026-08-06 — SUPERSEDED; PR #53 merged, as did #54–#81)* | **PR #53** (`feat/windows-broker-machineproof`, base `main`, branch head `462edc5`, CI green) — the additive Windows LIVE governed-turn machine-proof for **task T-017**. Self-carrier; exact-head anchored by its PR-body `AUDIT_CANDIDATE_HEAD` marker. (PR #48, the Wave 3b design+impl consolidation, is now MERGED into `main`.) |
| **Next task** | **Wire the live-proven trust chain into the shipped desktop runtime** (retire `UpstreamBlockedExecutor` in `main()`) to enable production `trusted_verified`, and for Windows land the remaining broker hardening + a **separate Architect audit of the Windows broker** before flipping `platform_governed_execution_supported()`. The 3b-1B design is `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` at `CURRENT_DESIGN_CANDIDATE: rev-30`; `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` (external audit waived by the Owner — three converged builder passes + the independent Windows-broker audit GREEN stand as the verdict). Do **not** expose production "Verified" before the runtime wiring + Owner approval. |
| **Proven live** | The **full 7-service production governed turn ran GREEN on real Linux** — the first production `trusted_verified` proven live (`CURRENT_LINUX_E2E: proven`, via `engine/ci/live/run_live_turn.sh`). 3b-2 (signed manifest / anti-rollback) + 3b-3 (production trust resolver) are implemented + wired in the live kit. The **shipped desktop app stays fail-closed** (`CURRENT_PRODUCTION_VERIFIED: false`) until the live chain is wired into the desktop runtime. |
| **Merged baseline** | Prior merged history (durable): **PR #30** — Wave 3b-0 isolated-signer DESIGN GREEN (`df3c0ac`); Phase 0 repository-truth remediation merged (`b6c6712`); **T-016 / slice 3 — PR #28** (`8a580028`) wired the desktop verifier into a real governed turn; **Wave 3b consolidation — PR #48 MERGED** (design+impl+live-proof+cockpit, superseding the split PR #46 impl / #31 design / #32 impl) plus the **Phase-2 governance slices #49/#50/#51/#52 MERGED** → `main` tip `b91f2356`. See `config/current_state.json`. |

> **Wave 3a is COMPLETE** — slices 1, 2, 3 all GREEN + merged (`git log main` → `6c920d0`, `9b214e5`, `8a580028`).
> The desktop issues a nonce challenge, runs the governed turn buffered, and verifies the signed receipt.
> **Current reality (do NOT flatten to "not implemented" OR to "done"):** the 3b-1B design is
> `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` at `rev-30`; the 3b-1B/3b-2/3b-3 implementation is **consolidated on
> `feat/cockpit-pages` (PR #48)** and the full chain is **proven live on Linux** (`CURRENT_LINUX_E2E:
> proven`) — the first production `trusted_verified` ran end-to-end. **But** the external Architect
> CODE-audit is still pending (`CURRENT_CODE_AUDIT: ARCHITECT_PENDING`), and the **shipped desktop app's
> production "Verified" remains fail-closed** (`CURRENT_PRODUCTION_VERIFIED: false` — `main()` keeps
> `UpstreamBlockedExecutor`; the live chain is not yet wired into the desktop runtime). The 22-page
> cockpit is built + wired to real backends.
<!-- HISTORY_END -->

## 4. Merged baseline (Done — verify via `git log main`)

- **Wave 1 — provider fail-closed** (audit P0-1), T-012, PR #15 (`15384cb`): `resolve()→Result`, no silent governed→ungoverned fallback; ungoverned only via `BROPS_ALLOW_UNGOVERNED=1`.
- **Wave 2a — webview message provenance** (audit P1-6), T-013, PR #16 (`d85dcba`): `WEBVIEW_MESSAGE_ROLES` restricted to `["user"]`; server-held answer via one-time `result_id`.
- **T-010 — Tauri capability boundary**, PR #19 (`7d537c3`): deny-by-default capability manifest over all 65 commands; the 4 L2 hard-delete commands DENIED; CI invariant `tools/check_capabilities.py`. Zero-trust GREEN.
- **T-011 — durable approval + native confirmation**, PR #20/#21 (merge `7638a64`): migrations 0012 (approval provenance) + 0013 (execution claim). Restart-safe self-approval by durable `origin_principal`; native-only approval authority; nonce compare-and-consume; canonical `RunExecutionScope` digest; atomic pre-dispatch execution claim; crash-recovery reconciliation; strict attempt ownership; enforced single-instance file lock. Zero-trust GREEN through multiple rounds.
- **Wave 3 Receipt Protocol v1 — design rev 4**, PR #23 (`35a6ab5`): Architect + Owner **GREEN**, merged. The design is the spec Wave 3a/3b implement.
- **Wave 3a slice 1 — receipt protocol core** (T-014), PR #24 (approved HEAD `c51031e`, **merge commit `6c920d0`**): `brops-core::receipt` — the pure verifier core (§5). Zero-trust GREEN after three RED rounds (§6).
- **Wave 3a slice 2 — receipt storage & atomicity** (T-015), PR #26 (approved HEAD `64c2372`, **merge commit `9b214e5`**): migration **0014** + `brops-core::receipt_store` — the durable, atomic `verify→consume→persist` layer on the slice-1 core (`issue_challenge`, one-time nonce, `receipt_id` uniqueness, freshness/skew, `ON DELETE RESTRICT` evidence, tri-state outcome with no "Verified"). Zero-trust GREEN after a YELLOW + two RED rounds (see the T-015 row in `TASKS.md`).
- **Wave 3a slice 3 — transport wiring + receipt trust UI** (T-016), PR #28 (approved HEAD `dee6661`, **merge commit `8a580028`**): the desktop CALLS the merged verifier on a real governed turn — `ai::PreparedGovernedTurn` single source, structured `system`+`history` bridge authority, `commands.rs` `issue_challenge`→`verify_and_record_receipt(&NoTrustedManifest)`→`StreamEvent::Blocked` notice (no double-post), `receipt_store::{record_pre_verification_block, bounded_reason}`, `Message.receipt` projection + dev/blocked badges, JCS cross-language parity + e2e. Fail-closed strict 3a. Zero-trust GREEN after a YELLOW + two RED rounds (see the T-016 row in `TASKS.md`). **Wave 3a complete.**
- **Phase 2 (Governance Sidecar) COMPLETE on `main`** — **PR #50** (`reply_in_conversation`), **PR #51** (`stream_ask`, held-answer core + migration **0016**), **PR #52** (`stream_run_step`) all MERGED: every AI surface routes through `ai::governed_turn`, generic fallthrough dev-only + fail-closed. **Wave 3b consolidation — PR #48 MERGED** (design+impl+live-proof+cockpit). **Windows §0.W broker — PR #49 MERGED** (real winapi named-pipe peer-SID auth + Windows CI proof).
- **Schema:** migrations run through **0022** (`0018_demonstration_verified`, `0019_approval_escalated_status`, `0020_automation_runs`, `0021_store_write_records`, `0022_integration_auth_ref`), `SCHEMA_VERSION = 22` (`core/src/db.rs:29`). *(This line said “through 0017 … SCHEMA_VERSION = 17” until 2026-08-09 — five migrations behind, in the section a reader consults to learn what shipped.)* Test suites (`brops-core`, host `brops`, bridge py, frontend + axe specs) are green in CI; the counts that used to be quoted here were PR #53's and PR #53 merged on 2026-08-06, so run them rather than read them (`CLAUDE.md` §4 carries the commands and the last measured figures). This cycle also shipped group-chat participants/attribution/routing and strengthened all 42 `engine/skills` to v1.1.0.

## 5. What IS implemented — slice 1 (PR #24) + slice 2 (PR #26)

**Slice 1 — `brops-core::receipt`** — the **pure, I/O-free protocol core** (design §2, §2.3, and the pure subset of §3, §6):

- RFC 8785 (JCS) canonicalization for the receipt + canonical **request** envelope (§2, §2.2).
- Wire format + strict decode (§2.3): base64url → exact bytes (**64 KiB cap**), UTF-8, **duplicate-key** + **unknown-field** + **non-string-value** rejection, fixed field set/types, lowercase-64-hex hashes, numeric timestamps, `decision` domain, and **`JCS(parsed) == decoded bytes`** (parser-differential defense).
- **Verify-only** Ed25519 (`verify_strict`) over the decoded bytes, via a **type-state chain**: `parse_strict → Parsed` (exposes only `key_id`) → resolve the manifest key → `verify(&ResolvedManifestKey, sig)` (enforces `parsed.key_id == resolved_key.key_id`) → `Verified` (carries the signed `trust_class`) → `bind(&Expected, output)` → `BoundReceipt` → `resolve_3a()`. `ResolvedManifestKey` has **private fields + no public constructor** (only an in-crate validated resolver mints one).
- The pure §3 binding subset: protocol, `decision == completed`, identity/policy/config **expected-value** matches, allowed executor/builder, output-bytes re-hash (§2.1). The request half is a single `IssuedRequest` from which `bind` **recomputes** `request_sha256` (never a separate supplied hash), so hash and per-field bindings can't diverge.
- Trust-state gate (§6): `resolve_3a()` returns a **`Wave3aTrustState { DevelopmentUntrusted, Blocked }`** — a type with **no `TrustedVerified` variant**, so Wave 3a code cannot name a "Verified" state anywhere; `production ⇒ Blocked`.
- **Verify-only in production**: the Ed25519 *signing* half is compiled solely under `#[cfg(test)]` — the desktop core is never a `sign(arbitrary_bytes)` oracle (design §1).

**Slice 2 — `brops-core::receipt_store`** — the durable, atomic storage layer (design §3 stateful subset + §4), merged in PR #26:

- **Migration 0014** (`SCHEMA_VERSION` 14): `receipt_challenges` (durable one-time nonce; `request_sha256` NOT-NULL+hex, compared in-tx to `expected.request.request_sha256()`), `receipt_verification_attempts` (capped raw `wire_*` + decoded envelope/signature + tri-state `outcome`; `message_id` real FK **`ON DELETE RESTRICT`** with the full accepted⇔message / blocked⇔no-message CHECK), `receipt_ids_seen` (accepted-only uniqueness ledger).
- **`verify_and_record_receipt`** — one `BEGIN IMMEDIATE` **verify → consume → persist**: consume the desktop nonce, run the slice-1 pipeline, apply the stateful gates (`receipt_id` unseen, two-timestamp freshness/skew), then persist. A **blocked verdict commits its evidence**; only a real SQLite failure returns `Err` (with an explicit rollback); a **nested (non-owning) transaction is rejected**. `issue_challenge(conn, conversation_id, &IssuedRequest, now_ms)` derives nonce+hash from one source.
- **`ReceiptOutcome`** has **no `TrustedVerified` variant** (production ⇒ `Blocked`); deleting a conversation/message with governed evidence is **refused** so the output stays re-verifiable. Verified by a **real two-thread `Barrier` race** (one accept + one block, both evidence rows).
- **83 core tests** total (slice 1 + slice 2 negative-matrix), clippy-clean.

## 6. Zero-trust audit history — RESOLVED (slices 1 + 2 are GREEN + merged)

Three RED rounds were closed and independently re-audited; the final HEAD `c51031e` got
**zero-trust GREEN** and merged (`6c920d0`). These are **resolved history, not current blockers.**

**Round 1 — RED on `a873501` (4 blockers), addressed in `aa4dc01`:**
1. **`key_id` not cryptographically bound to the passed key** → introduced `ResolvedManifestKey { key_id, public_key, trust_class }`; `verify` requires `parsed.key_id == resolved_key.key_id` before the signature (`KeyIdMismatch`); `Verified` carries that entry's `trust_class`; raw-key convenience is `#[cfg(test)]`-only.
2. **Trust state not bound to a verified+bound receipt** (standalone `resolve_trust_state(class, production_allowed)`) → removed it; trust state reachable only via `BoundReceipt::resolve_3a()`.
3. **`requested_at` not bound to the desktop request timestamp** → exact-equality binding added.
4. **`Parsed` derived `Debug` leaked private fields** → redacted manual `Debug` on `Parsed`/`Verified`/`BoundReceipt`.

**Round 2 — RED on `aa4dc01` (3 blockers), addressed in `f5b6ffe`:**
1. **`ResolvedManifestKey` was forgeable** — public fields let any caller pair an arbitrary `public_key`/`trust_class` with a chosen `key_id`. → *Addressed:* fields are now **private with no public constructor**; only an in-crate validated signed-manifest resolver (Wave 3b) can mint one; tests use the same-crate private fields.
2. **`TrustState::TrustedVerified` was directly constructible in shipping 3a code.** → *Addressed:* replaced `TrustState` with **`Wave3aTrustState { DevelopmentUntrusted, Blocked }`** — no `TrustedVerified` variant exists in 3a, so no code path can name a "Verified" state. The production state is a separate Wave 3b type.
3. **`request_sha256` was a separate caller-supplied value** — a wiring bug could pair request A's hash with request B's components. → *Addressed:* introduced an `IssuedRequest` (the 7 request-envelope fields); `Expected` embeds it and drops `request_sha256`; `bind` **recomputes** the canonical hash via `IssuedRequest::request_sha256()` and compares the receipt's signed value to it.

**Tests:** added the request-hash-recompute negative case; the mismatch matrix mutates every `IssuedRequest` component + policy/config field; trust-state tests use `Wave3aTrustState`. **69 core tests**, clippy-clean. **Final re-audit of `c51031e`: zero-trust GREEN → merged (`6c920d0`).**

## 7. Wave 3a slice 2 (receipt storage & atomicity) — DONE, merged (the followed plan)

> **Status: DONE and merged** — PR #26, squash **merge commit `9b214e5`** on `main`, zero-trust GREEN.
> The steps below are the design §3 (stateful items) + §4 plan the implementation followed; they are
> retained as the spec/record. The next task is **slice 3** (transport + UI), see §3.

1. **Claim it:** cut `feat/wave-3a-receipt-storage` from `main`; add a T-015 row in `TASKS.md` (In-Progress).
2. **First concrete step — migration 0014** (`SCHEMA_VERSION` 13 → 14) in `apps/desktop/src-tauri/core/schema/0014_receipt_verification.sql`:
   - `receipt_verification_attempts` (exact canonical envelope bytes + signature + `key_id` + tri-state `outcome` {`trusted_verified`|`development_untrusted`|`blocked`} + `verification_error` + `verified_at` + link to the resulting message for accepted outcomes),
   - a durable **one-time nonce** table (issued → consumed) for the desktop challenge,
   - a **`receipt_id` global-uniqueness** constraint.
3. Then the **atomic verify → consume → persist** transaction (one DB tx): verify (via `brops-core::receipt`) → resolve `Wave3aTrustState` → consume the nonce → insert the attempt row → if accepted, insert the agent message (badge from outcome); a `blocked` attempt records evidence + error and never becomes a `messages` row.
4. Then wall-clock **freshness/skew** on `requested_at`/`completed_at`, and the `receipt_id`-unseen durable check.
5. Full negative-test matrix at the storage layer (replayed nonce, duplicate `receipt_id`, blocked-never-persists, crash-atomicity), then live-sync docs + open the PR for zero-trust audit. **Transport wiring + receipt UI are slice 3; the isolated signer + manifest + production "Verified" are Wave 3b** (§10).

## 8. Verify commands (Windows box)

```bash
# Rust data core (⚠ run cargo from PowerShell, NOT the Bash tool — see CLAUDE.md §5)
cargo test -p brops-core --manifest-path apps/desktop/src-tauri/core/Cargo.toml   # 297 #[test] fns in core/src (was "83 tests" here until 2026-08-09 — a slice-2 figure)
cargo clippy -p brops-core --all-targets                                          # clippy-clean

# Coordination-docs gate (fails closed on stale coordination)
python tools/check_coordination.py

# Capability invariant (T-010)
python tools/check_capabilities.py

# Engine (Python) — MUST set BRO_ENV=ci
cd engine && BRO_ENV=ci python -m unittest discover -s tests   # 1282 tests, 43 skips (measured 2026-08-09)
```

CI (`.github/workflows/ci.yml`) triggers on `push → main` and on `pull_request`. A feature-branch push **without a PR runs no CI**. **CI GREEN is not audit GREEN.**

## 9. Merge gate & prohibited shortcuts

- **A security PR merges only after the Architect's zero-trust GREEN on the exact candidate HEAD, then Owner approval.** No self-merge of a security PR before that GREEN.
- No direct work on `main`; every task = branch + PR (PR template).
- Never fabricate a commit SHA, test result, verdict, or file state. Do not write `Done`/`GREEN`/`approved`/`merge-ready` unless it is a verified fact in the repo.
- Do **not** present slice-1-deferred items (below) as implemented.
- Do not touch the engine's wall/leases/gates/signatures/control-plane casually — it is an audited security perimeter (CLAUDE.md §6). Engine work is tracked in `engine/AUDIT/tickets/` and, for the five residual items, in [`docs/PHASE_10_PRODUCTION_ITEMS.md`](./docs/PHASE_10_PRODUCTION_ITEMS.md). **There is no separate engine handoff any more:** `engine/NEXT_CHAT.md` was removed on 2026-08-08 because it was a frozen 2026-07-19 handoff for the standalone repository that told whoever read it "do not touch BroPS" — the other half of this one. This file is the single handoff for both halves.

## 10. Deferred — NOT yet implemented (do not claim as done)

**Wave 3a is complete** — slices 1 + 2 + 3 merged (durable nonce issue/consume, `receipt_id` uniqueness,
wall-clock freshness/skew, migration 0014, atomic verify→consume→persist, `receipt_verification_attempts`,
**and** the desktop transport wiring + structured bridge contract + receipt trust UI + JCS parity + e2e —
all **done**, §5).

> **⚠ Corrected 2026-08-09. Wave 3b is NOT deferred — it is implemented and merged.** This section listed it under “NOT yet implemented (do not claim as done)” six sections after §3 and §4 of this same file said the 3b-1B/3b-2/3b-3 implementation was consolidated on PR #48, merged, and proven live on Linux. The bullet below is retained as the SPEC of what Wave 3b had to build, not as a statement that it is missing. What genuinely remains is not the code: it is that production `trusted_verified` stays **unreachable in the shipped app** (the three refusals in the banner), the **RED** standing audit verdict, and the keystone soundness-blockers in §3. Do not read “built” as “trusted”.

- **Wave 3b (spec, now built)** — the isolated trusted signer (real key custody, not a `sign(arbitrary_bytes)` oracle) +
  operator-provisioned signed key manifest + binary-pinned root anchor; manifest **loading + signature
  verification**; key validity window / epoch / revocation; manifest **anti-rollback**. It fills the
  `ReceiptKeyAuthority` seam (today `NoTrustedManifest` ⇒ Blocked); only 3b enables production
  **`trusted_verified`** ("Verified").

Beyond Wave 3: Wave 4 (supervisor hardening, engine P0-4), Wave 5 (trusted sidecar, P0-3), production CI/release (P0-6), then the product roadmap phases (`MASTER_EXECUTION_ROADMAP.md`).

## 11. Handoff rule (keep this file true)

Every approved decision made in a Claude/ChatGPT chat must be written into the canonical repo docs **in the same commit** as the change it authorizes — `NEXT_CHAT.md`, `PROJECT_STATE.md`, `TASKS.md`, and any design/security doc it touches. A new chat must be able to continue correctly from GitHub alone. The chat is never the record.

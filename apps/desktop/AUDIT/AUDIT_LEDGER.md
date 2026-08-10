# BroPS Audit Ledger · desktop + engine

> **Why this file exists (audit D-06/D-07):** the security tickets under `apps/desktop/AUDIT/tickets/`
> and `engine/AUDIT/tickets/` carried **no status/resolution field**, so a fixed finding and a forgotten
> one looked identical, and the desktop tickets were referenced from **nowhere** outside their own folder
> (orphaned). This ledger is the single index of record: it links both ticket sets, points at the current
> authoritative assessment, and records the status the Builder can evidence. It does **not** invent a
> status it cannot back — anything not individually re-verified is marked so, with the independent audit
> as the live source of truth for current-code behaviour.

**Authoritative current assessment:** [`2026-08-06-remediation-audit.md`](./2026-08-06-remediation-audit.md)
— the Owner's SECOND independent audit, of `main` @ `219c763` AFTER the remediation. **Verdict: RED.**
4 of 18 blockers CONFIRMED CLOSED, 2 STILL OPEN, 12 PARTIALLY CLOSED, 45 surviving findings (1 P0).

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
| `bound` is a tautology (`CommittedMessage::new` hardcodes trust_state) | ⚠️ OPEN |
| `production_verified` never asks WHICH root anchor verified the manifest | ◑ **Builder claims closed; NOT independently re-checked.** `resolve_trust_state` now REQUIRES a `VerifiedManifestRoot` token, requires it to cover THIS manifest, and splits the verdict on `root.provenance()` (`core/src/production_trust.rs`). |
| **F-29 — the “bound-to-verifying-key” guard is a tautology** | ⚠️ **OPEN, and stated by the code itself.** Two rounds of fix left the comparison in `resolve_trust_state` unable to fail: every call site derives `envelope_verifying_key_hex` from `verifying_key_hex(...)` over bytes that the SAME `resolve_production_key` lookup produced. The check is KEPT as fail-closed defence in depth for a future call site that obtains its key another way; what is corrected is the claim. The property that holds today holds by CONSTRUCTION (one source, not two agreeing ones) — weaker than a check. `NEXT_CHAT.md` listed this CLOSED until 2026-08-09; it is a live keystone finding. |
| NULL DACL makes `FILE_FLAG_FIRST_PIPE_INSTANCE` inert | ⚠️ OPEN |
| A failed model call is replaced by a hardcoded constant the chain then signs | ◑ **Builder's claim; NOT independently confirmed.** *(Same missed demotion; corrected 2026-08-09.)*  The fallback itself is legitimate — the self-test exists to prove the CHAIN, with or without a model — but it was INVISIBLE: no `BROPS_SELFTEST_MODEL_CMD` (the default), a spawn failure, a non-zero exit or empty output all silently became a built-in constant that the chain bound and the UI showed beside `trusted_verified`. The receipt was honest about custody and the screen was misleading about what answered. `AnswerSource` now travels with the answer (model / no-model-configured / model-failed), the UI renders **NO MODEL RAN** and says which of the two reasons, and 3 tests cover all three cases. |
| Windows kit: no §2.5 floor, no anti-rollback floor | ⚠️ OPEN |

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
  a governed surface reachable, which is forbidden. Already declared with written reasons in
  `config/reachability-declarations.json`.
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

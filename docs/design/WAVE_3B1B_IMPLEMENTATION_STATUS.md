# Wave 3b-1B — implementation status (WIP branch `impl/wave-3b1b-execution-binding`)

> **STATUS: WORK IN PROGRESS — implementation checkpoint, NOT a release candidate, NOT for merge.**
> The five required rev-26 mechanisms are being implemented **in place** (they are NOT deferrable
> Tier-2 follow-ups). Built on the ChatGPT partial (`OS_PARTIAL_HANDOFF_2026-07-26`, sha256
> `b043ae3b…`) applied onto the exact rev-26 base `6ebeca88627640eef8effe576b3d388417cb4949`. The five
> rev-26 canonical docs are **unchanged**; this file is an additive design→code status map. Normative
> source: [`WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](./WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md).

## Required-mechanism status (must all be GREEN under enforcing tests before this is an RC)

| # | Mechanism | Status |
|---|---|---|
| §8 | dual-key authority separation (evidence-recorder vs governed-turn-recorder; supervisor+signer) | **IMPLEMENTED** — the two authorities live in **different OS principals/processes**: the governed supervisor holds ONLY the governed-turn-recorder key; the evidence-recorder key is held by the separate `brops-recorder` runner (own AF_UNIX socket, own keydir). Separation is structural (distinct principals), not a same-process runtime check; the signer verifies each artifact against its authority's `TrustedKey`. Machine-proven by `isolation_proof.sh`; recorder-core + verification tests GREEN |
| §5 | durable acceptance ledger + outbox + idempotency + restart/crash recovery | **IMPLEMENTED** — `governed_turn_acceptance` outbox (9-state CHECK + 3 UNIQUE CAS); `execute()` split into ACCEPTED_PREPARED (lease bytes persisted before signing) → LEASE_READY → gate→EXPIRED/EXECUTION_STARTING → EXECUTING → COMPLETED; deterministic post-accept refusals → durable BLOCKED + idempotent replay; `recover()` (post-launch→RECOVERY_REQUIRED, stale LEASE_READY→EXPIRED). In-process ledger tests GREEN; full accept→COMPLETED E2E on Linux CI |
| §7 | durable evidence-head anti-rollback floor + A–E CAS/fork/replay matrix + real evidence chain | **IMPLEMENTED** — signer-owned `governed_evidence_head_floor` (keyed install_id+task_id) with the full A–E matrix in one BEGIN IMMEDIATE tx, committed BEFORE the envelope: rollback→`stale_evidence`, fork→`evidence_fork`, unchanged re-anchor advances the high-water, byte-identical re-sign idempotent, valid prefix-extend via `validate_chain_detailed`; the supervisor now persists a **real `bro_evidence` chain** (event + signed head, evidence-recorder authority, `{payload,signature}` format) in the recorder namespace; the signer **loads + validates it via `validate_chain_detailed`** with a `TrustedKey` built from the evidence-recorder pubkey and **derives** `event_count`/`last_sequence`/`final_event_hash`/`head_sequence` from the validated chain (the asserted record/attestation fields must equal it, else `evidence_fork`) — no envelope is minted from asserted head fields alone. **Scope (honest):** the floor is a per-`(install_id, task_id)` evidence-integrity high-water — it stops rollback/fork/replay of the head *within a task's own event chain*; cross-turn replay of a stale-but-internally-valid record from a different turn is stopped by the §7.1 request nonce + freshness window and the §5 durable acceptance ledger, NOT by the floor (each governed turn is its own task_id chain, so keying the floor across turns would be wrong). A–E floor tests + real-chain verification tests (tamper/untrusted-key/missing-head) GREEN; full E2E on Linux CI |
| §2.3 | `2750` store custody (`S_IWGRP` refusal) + additive isolation test/proof write-denial | **IMPLEMENTED** — `_harden_dir` now creates at `2750` and refuses `S_IWGRP` (group-write) as well as world; `test_brops_isolation` additively asserts `2750` allowed / group-writable (`2770`/`0770`) refused / created-at-`2750`; `isolation_proof.sh` provisions the store at `2750` (was `2770`) and adds a machine write-denial proof (signer group member + login user cannot create/rename in the store; `stat`==`2750` guard). **Two-namespace custody CLOSED:** the governed store is a `NamespacedEvidenceStore` (`store/sup/` supervisor-written + `store/rec/` recorder-written — output/containment/execution-receipt/evidence go to `rec/`, everything else to `sup/`; read resolves from whichever namespace holds the handle); `isolation_proof.sh` proves the **complete** principal × operation × namespace matrix with real `brops-recorder`/supervisor/signer/login principals (create/overwrite/rename/unlink/chmod/symlink/list/read). Linux isolation job GREEN |
| §4.10(g) | exact frontend `governed_turn_execute` command + 4-inventory wiring | **IMPLEMENTED** — the dedicated `#[tauri::command] governed_turn_execute(conversation_id, agent)` is wired into all four capability inventories (lib.rs `generate_handler!` + build.rs COMMANDS + command-policy.json + capabilities/default.json), capability gate GREEN at **67** (was 66); system/history/config/run_id/task_id are all backend-resolved (never cross the webview); `resolve_governed_generation_config_v1b()` is the single generation-config source (5 frozen literals + 4 `BROPS_GOVERNED_*` host overrides, `engine_id` immutable). Refinements remaining: freezing `stream_reply`'s governed branch entirely into the new command + private `PreparedGovernedTurnV1B` fields (audit MINOR, single-process/immutable so fails closed) |

Then: full normative test matrix, one real end-to-end proof, exact-head CI + Linux isolation GREEN, and a fresh zero-trust audit.

## Fresh zero-trust audit → remediation

A fresh 2-track independent zero-trust audit (adversarial, try-to-refute) ran over all five
mechanisms. Both tracks confirmed the **safety cores sound** — no double-spend, no auto-relaunch
past `EXECUTION_STARTING`, idempotent replay never re-executes, no cross-authority forgery, no
gating bypass, pinned hash correct, `_harden_dir` refusals genuine. Findings were normative /
completeness / defense-in-depth (all fail-closed, no wrong-accept). **Remediated in place:**

- **§4.10(g) override contract (BLOCKER):** `resolve_governed_generation_config_v1b` now returns
  `Result` and strict-decode validates each `BROPS_GOVERNED_*` override (format+range); `prepare`
  no longer hard-pins the hash, so a format-valid override flows through and is refused DOWNSTREAM
  as `model_profile_unknown` (was: every override aborted at prepare with "hash drift").
- **§7 signer lease-time invariants:** now also enforces `lease_issued == challenge_accepted`,
  exact `LEASE_DURATION_MS`, and `lease_issued ≤ started ≤ finished ≤ completed ≤ lease_expires`.
- **§8 authority separation is now STRUCTURAL, not a runtime guard:** the evidence-recorder key is
  held by a **separate process/principal** (the `brops-recorder` runner over its own AF_UNIX socket) —
  the governed supervisor no longer holds it or takes it as a constructor arg, so there is no longer a
  same-process "distinctness" check to make; the two authorities cannot be one key because they live
  in different principals with different keydirs, machine-proven by `isolation_proof.sh`.
- **§8 containment binding:** the signer binds `containment_evidence_handle` to the
  gov-turn-recorder-signed record's `containment_evidence_sha256`.
- **§5 crash-resume:** `recover()` now deterministically re-signs an `ACCEPTED_PREPARED` lease from
  the persisted `lease_payload_bytes` → `LEASE_READY` (the documented determinism).
- **MINORs:** `final_event_hash` 64-**hex** check; floor `DatabaseError` fails closed to refused;
  store docstring corrected to the 2750 model. New tests for each. 

## §0–§9 gaps — BOTH CLOSED

Both previously-tracked infrastructure gaps are now implemented in this branch and CI-proven:

1. ~~**§7 real evidence chain**~~ — **CLOSED**: the supervisor persists a real `bro_evidence` event +
   signed head (evidence-recorder authority) in the recorder namespace; the signer loads + validates it
   via `validate_chain_detailed` and derives the head scalars from the validated chain, refusing if the
   asserted fields disagree — no envelope from asserted head fields alone. Real-chain verification tests
   + the A–E floor tests GREEN; full E2E on Linux CI.
2. ~~**§2.3 two-namespace store custody**~~ — **CLOSED**: the governed store is a two-namespace
   `NamespacedEvidenceStore` (`store/sup/` supervisor-written, `store/rec/` recorder-written). Writes to
   `store/rec/` are NOT done by the supervisor — they are delegated over an AF_UNIX socket to the
   dedicated **`brops-recorder` runner** (`brops_governed_recorder.py` / `brops_recorder_service.py`),
   a separate process/principal that alone holds the evidence-recorder key and alone writes `rec/`; a
   compromised supervisor can neither write `rec/` (OS ACLs) nor mint recorder-signed evidence (no key).
   The Linux isolation job proves the complete principal × operation × namespace matrix with real
   `brops-recorder`, supervisor, signer, and login principals (create/overwrite/rename/unlink/chmod/
   symlink-attack/list/read — signer exhaustively denied every write in BOTH namespaces), with a
   `stat==2750`/`640` mode-regression guard. In-process recorder-core tests exercise the runner on
   Windows; the full supervisor→recorder→signer AF_UNIX E2E runs on Linux CI.

## Trust boundary + known limitations (honest — do NOT overclaim)

An independent zero-trust audit (compromised-supervisor threat model) confirmed the custody wall and
signature isolation are sound, and surfaced two limitations that this document states plainly so the
receipt is never read as proving more than it does:

- **The recorder is a NOTARY, not an execution monitor.** `record_governed_turn` signs the output
  bytes the supervisor hands it and records fixed containment/exit facts (`contained=True`,
  `exit_code=0`); it does NOT independently launch the executor, measure a cgroup/process group, or
  otherwise prove that a contained execution actually occurred. In rev-26 the **supervisor remains the
  trusted containment monitor** — the two-principal split defends *evidence-recorder key custody and
  chain integrity* (a compromised supervisor cannot forge recorder signatures or write `rec/`), NOT
  the proposition "a contained execution happened". A fully-compromised supervisor, for a turn the
  desktop legitimately challenged, could substitute output bytes and obtain a genuine
  recorder-signed receipt over them (the challenge pins `system`/`history`/`generation_config`, but
  not the not-yet-existing output). **Executor-authenticated output** (the executor signing its own
  output so substitution is detectable) is a FUTURE item and is explicitly NOT claimed done here.
  What IS enforced: the receipt, the signed evidence event, and the output are now cryptographically
  bound to one task — the signer refuses unless `execution_receipt.task_id == record.task_id`, the
  event's `task_id` matches, and the event's `payload_hash` equals the output the signer itself
  hashes — so the recorder's three co-produced artifacts cannot be recombined with foreign parts.
- **The §7 A–E floor is exercised only at single-event scope today.** The recorder currently mints a
  one-event chain per turn (`head_sequence=1`), so only bootstrap + branch B (same-sequence) fire;
  branches C/D (multi-event advance / prefix-extension) and `min_head_sequence` are retained for a
  future multi-event chain design and are NOT reached by current minting. Because of branch B, a
  `task_id` MUST be unique per governed turn (a reused `task_id` with different content is refused as
  `evidence_fork`). Cross-turn replay is therefore stopped by the freshness window + `receipt_id` /
  `execution_attempt_id` uniqueness + the §5 durable acceptance ledger, NOT by the floor. This is
  faithful to per-turn scope; the floor machinery is real and unit-tested (incl. a concurrency test
  proving `BEGIN IMMEDIATE` serialization) but its multi-event branches are dormant until a
  multi-event chain design lands.

## Provenance

Reconstructed from the ChatGPT partial (`OS_PARTIAL_HANDOFF_2026-07-26`, sha256 `b043ae3b…`) applied
with `git apply --3way` onto the exact rev-26 base `6ebeca8`; the five rev-26 canonical docs are
byte-for-byte preserved. Scope is **3b-1B trust-chain only** — NOT 3b-2/3b-3/Phase 0–10 (held by the
repo ordering law until 3b-1 is merged). Each mechanism above is its own exact-head-CI-8/8 commit.

## STOP gates (unchanged, in force)

`NoTrustedManifest` unchanged and fail-closed · no production "Verified" without the complete real
chain · 3b-2/3b-3 not started · **not merged** · rev-26 not Architect-GREEN · frozen Wave-3a / 3b-1A
protocols + fixtures byte-for-byte preserved.

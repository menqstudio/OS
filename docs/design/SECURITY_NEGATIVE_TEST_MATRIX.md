# Wave 3b-1B — Security Negative Test Matrix · TEST PLAN (design-only, dependency-safe)

> **Status: DESIGN / PLAN ONLY.** No product code, no test code, and no architecture change
> ships under this document. It is the **executable-later** enumeration of the full 3b-1B
> negative matrix the Architect required (addendum §9 + the per-section "Negative tests"
> blocks), each row mapped to a **stable Test ID**, the **fault injected**, and the **exact
> fail-closed outcome**. It adds **zero** dependencies and **does not alter** the disputed
> 3b-1B security architecture or PR #31's audit candidate — it only names what the
> already-designed controls must prove once 3b-1B reaches Architect design-GREEN and
> implementation begins.
>
> **Single normative source.** Every contract referenced here lives in
> [`WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](./WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md)
> (rev 28). Where this plan and the addendum disagree, **the addendum wins**; this file
> re-inlines no schema. Section refs below (`§N`) are addendum sections.

---

## 0. How to read this plan

### 0.1 Row shape

Each test is one row:

| Field | Meaning |
|---|---|
| **Test ID** | stable `NM-<DOMAIN>-<n>` identifier; never renumbered once assigned |
| **Under test** | the boundary/component the fault targets |
| **Fault injected** | the single adversarial mutation (one fault per test — no compound tests) |
| **Expected fail-closed outcome** | the exact refusal: a `GOVERNED_REFUSAL_REASONS` literal, an internal `governed_internal_refusal:{stage}:{reason}`, an acceptance-ledger terminal state, a desktop Block, or a start-time refusal — and the invariant that MUST hold (no lease / no receipt / no render / no relaunch / no message row) |
| **§ ref** | governing addendum section |

### 0.2 Outcome vocabulary (the only accepted verdicts)

A test **passes** iff the system reaches its stated fail-closed outcome **and nothing renders
`trusted_verified`**. The five outcome classes:

1. **Governed verdict refusal** — the isolated signer / supervisor returns
   `brops.governed-sign-result.v1{status:"refused", reason:<literal>}` where `<literal>` ∈ the
   closed **`GOVERNED_REFUSAL_REASONS`** (§4.5): `attestation_invalid, not_completed,
   run_binding_invalid, nonce_mismatch, handle_missing, hash_mismatch, policy_mismatch,
   containment_missing, identity_denied, timestamp_invalid, oversize, malformed,
   challenge_replay, acceptance_conflict, lease_not_ready, output_oversize, output_timeout,
   evidence_fork, stale_evidence, lease_expired, challenge_invalidated, retry_conflict,
   stream_unknown, stream_expired, stream_binding_mismatch, seq_out_of_range,
   model_profile_unknown, tcb_integrity_violation, platform_unsupported`. Relayed verbatim to
   the desktop ⇒ one durable `blocked` attempt (`governed_verdict_refused:{reason}`).
2. **Internal (pre-row) refusal** — a supervisor/authority sub-protocol reason from the
   **disjoint** namespace (§4.10(h)): `peer_denied, noncanonical, sig_invalid, no_staging_row,
   session_corrupt, handle_not_challenge, seq_mismatch, digest_mismatch, quota_*, field_invalid,
   pending_expired, key_unavailable, challenge_expired, no_inputs_ready` — carried to the desktop
   as one `bridge.governed-turn-diagnostic.v1` ⇒ one durable Block
   `governed_internal_refusal:{stage}:{upstream_reason}`. **No acceptance row is created.**
3. **Acceptance-ledger terminal state** (§5, `governed_turn_acceptance.state`): `BLOCKED`
   (post-accept deterministic refusal), `EXPIRED` (pre-launch lease-expiry gate),
   `RECOVERY_REQUIRED` (ambiguous post-`EXECUTION_STARTING` crash — never auto-relaunch),
   `FAILED` (completed operational failure).
4. **Desktop Block** — `record_pre_verification_block` (one `BEGIN IMMEDIATE` tx: consume the
   one-time `request_nonce`, write a durable `blocked` evidence attempt, **no message row, no
   signed receipt**), surfaced as `StreamEvent::Blocked{reason}`; or `NonceState::Replay` on a
   re-asked nonce; or a `receipt_ids_seen` uniqueness reject.
5. **Start-time / platform refusal** — `platform_governed_execution_supported()` /
   `verify_distinct_principals()` / `verify_tcb_integrity()` returns false at supervisor start ⇒
   **no governed real-mode, no lease is ever issued**, desktop renders dev/blocked.

### 0.3 Universal invariant (asserted on every row unless stated)

> **STOP holds throughout:** `NoTrustedManifest`-equivalent — **no production `trusted_verified`
> renders** on any negative row. A negative that produced a rendered "Verified" is an automatic
> **fail**, regardless of any other assertion.

### 0.4 Harness placement (executable-later; no code now)

When 3b-1B is implemented, these IDs bind to test files by domain — planned, not created here:

- Python engine (isolated signer, supervisor, authority, store, evidence floor):
  `engine/tests/test_governed_turn_negative_matrix.py` (+ per-domain modules named below).
- Linux isolation / principal / ACL / IPC-peer / launcher proofs (run **as each OS principal**,
  not only the login user): `engine/ci/isolation_proof.sh` extension +
  `engine/tests/test_governed_store_acl.py` gated behind the `§0.1` platform predicate.
- Rust desktop acceptance (envelope/attestation/echo/nonce/receipt_id/freshness/output-hash):
  `apps/desktop/src-tauri/**` unit tests (vitest for the TS surface; Rust `#[test]` for
  `receipt.rs`/`ai.rs`/`commands.rs`), matching the merged style.
- Cross-language parity fixtures: one fixture per §4.0a/§3 artifact formula asserting identical
  `sha256` Python↔Rust.

Each row's outcome is a **machine-checkable assertion** (a specific reason literal, a DB state, a
denied syscall, a non-render) — never "looks rejected".

---

## 1. Replay, nonce, receipt-id, and challenge-replay (`NM-REPLAY-*`)

Two independent replay ledgers both hold (§5 "Relationship to the desktop nonce"): the desktop
`request_nonce`/`receipt_id` consume (final receipt) and the supervisor acceptance ledger
(execution). Neither substitutes for the other.

| Test ID | Under test | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-REPLAY-01 | Desktop nonce consume | Replay a full turn whose `request_nonce` was already consumed (`receipt_challenges.consumed_at != NULL`) | `NonceState::Replay` ⇒ desktop **Block**; no render | §6.1(14), §7.1 |
| NM-REPLAY-02 | `receipt_id` global uniqueness | Second turn presenting a `receipt_id` already in `receipt_ids_seen` | PK insert fails on ACCEPT ⇒ **Block**; no second persist | §7.1 |
| NM-REPLAY-03 | Supervisor exec replay (same nonce, same challenge) | Re-submit an already-`COMPLETED` `(install_id, request_nonce)` | Idempotent re-serve of the **same** verified terminal record only; **zero second execution** | §5(11), §5 neg-tests |
| NM-REPLAY-04 | Ledger `challenge_replay` | Reuse a `request_nonce` already ACCEPTED for a **different** `challenge_handle` | Acceptance CAS ⇒ `refused` **`challenge_replay`** | §4.5, §5 |
| NM-REPLAY-05 | Same-nonce / different-challenge | New signed challenge reusing an accepted nonce | `UNIQUE(install_id,request_nonce)` conflict ⇒ **refused** (`acceptance_conflict`/`challenge_replay`) | §5 |
| NM-REPLAY-06 | Same-challenge / different-nonce | Resubmit identical `challenge_handle` with a different nonce | `UNIQUE(challenge_handle)` conflict ⇒ **refused** | §5 |
| NM-REPLAY-07 | Conflicting retry facts | Retry with different `run_id`/`task_id`/`workspace_id` on a stored row | Conflict ⇒ **`retry_conflict`**; no new attempt | §4.5, §5 |
| NM-REPLAY-08 | `execution_attempt_id` uniqueness | Force two attempts to reserve one attempt id | `UNIQUE(execution_attempt_id)` ⇒ exactly one attempt; loser gets idempotent result | §5 |
| NM-REPLAY-09 | Authority pending single-use | Replay `brops.governed-challenge-issue.v1` for an already-`ISSUED` pending row | Pending is one-time-consumed (`PENDING→ISSUED`) ⇒ internal refusal (`field_invalid`/`pending_expired`), no second signature | §2.1 |
| NM-REPLAY-10 | Replayed output chunk | Replay a previously-served `brops.governed-turn-output-read.v1` chunk with mutated bytes | Reassembled `SHA256 != envelope.output_sha256` ⇒ desktop **Block** | §7.1, §4.10(f) |

---

## 2. Time model — expiry, skew, boundaries, unit confusion (`NM-TIME-*`)

All governed-turn times are integer epoch-**ms** (§1); the reused `bro_evidence` seconds field is
**never** compared to any ms window. Boundaries inclusive: `lo_ms ≤ t ≤ hi_ms`.

| Test ID | Under test | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-TIME-01 | Unit confusion | A `_ms` field carrying a ~10-digit seconds value | Range/consistency reject ⇒ `malformed`/`timestamp_invalid` | §1 |
| NM-TIME-02 | Overflow / negative / zero | `_ms` = `0`, negative, or `> 2^53-1` | Strict-decode reject ⇒ `malformed` | §1 |
| NM-TIME-03 | Challenge window (acceptance) | `challenge_accepted_at_ms > challenge_expires_at_ms` | Acceptance predicate fails ⇒ **`timestamp_invalid`** (acceptance-time window expiry) | §5, §4.5 |
| NM-TIME-04 | Challenge window lower | `challenge_accepted_at_ms < challenge_issued_at_ms` | Predicate fails ⇒ `timestamp_invalid` | §5, §7 |
| NM-TIME-05 | `requested_at` ordering | `requested_at_ms > challenge_accepted_at_ms` | Predicate fails ⇒ `timestamp_invalid` | §5, §7 |
| NM-TIME-06 | Inclusive boundary (accept) | `challenge_accepted_at_ms == challenge_expires_at_ms` (exact hi) | **Accepts** (inclusive) — positive-control boundary; any refusal here is a bug | §1 |
| NM-TIME-07 | Lease-expiry gate — expired | On launch, `now_ms > lease_expires_at_ms` | `LEASE_READY → EXPIRED`; **no launch**; `lease_expired` | §5(8a), §4.5 |
| NM-TIME-08 | Lease-gate remaining-budget boundary (block) | `lease_expires_at_ms − now_ms == 179999` (< MIN_LAUNCH_REMAINING_MS 180000) | **EXPIRED**, no launch | §5(8a) |
| NM-TIME-09 | Lease-gate remaining-budget boundary (proceed) | `lease_expires_at_ms − now_ms == 180000` (exact threshold) | **Proceeds** (positive-control boundary) | §5(8a) |
| NM-TIME-10 | Lease-gate exact-expiry boundary | `now_ms == lease_expires_at_ms` (passes (i), must fail (ii) budget) | **EXPIRED** (fails remaining-budget) | §5 neg-tests |
| NM-TIME-11 | Lease-gate `+1` | `now_ms == lease_expires_at_ms + 1` | **EXPIRED** | §5 neg-tests |
| NM-TIME-12 | Wall-clock NTP step (pre-launch) | NTP step forward between `LEASE_READY` persist and the gate | Gate re-reads stepped wall clock ⇒ **EXPIRED** if expired; monotonic in-exec timeout must not smuggle it past | §5 neg-tests |
| NM-TIME-13 | Complete time-chain in-window (verify) | `completed_at_ms > lease_expires_at_ms` with `finished` in-window | Signer §7 lease-time invariant ⇒ **`lease_expired`**; no envelope | §7, §4.5 |
| NM-TIME-14 | Time-chain ordering | `started_at_ms`/`finished_at_ms`/`completed_at_ms` out of order (`completed < finished`) | §7 chain inequality ⇒ refuse | §7 |
| NM-TIME-15 | Lease duration equality | `lease_expires_at_ms − lease_issued_at_ms != LEASE_DURATION_MS (210000)` | §7 duration mismatch ⇒ refuse | §7, §4.3 |
| NM-TIME-16 | `lease_issued_at_ms` equality | `lease_issued_at_ms != challenge_accepted_at_ms` | §7 equality fails ⇒ refuse | §7 |
| NM-TIME-17 | Desktop freshness skew | Receipt `_ms` outside `FreshnessWindow{future_skew_ms:60000, max_age_ms:300000}` | Desktop freshness reject ⇒ **Block** | §7.1, §1 |
| NM-TIME-18 | Wall-clock NTP step (in-exec) | NTP step during execution stamps `completed_at_ms` past `lease_expires_at_ms` | Signer §7 refuse **`lease_expired`** | §7 |
| NM-TIME-19 | Evidence seconds leak | Attempt to compare `bro_evidence` `issued_at_epoch` (seconds) to an ms window | Design forbids the comparison; test asserts seconds field never enters ms logic | §1 |

---

## 3. Registry / manifest — rollback, same-epoch different hash, revoked / wrong-usage key (`NM-REG-*`, `NM-MAN-*`)

Two roots/registries, separate from receipt keys: the **challenge-key registry** (supervisor
side, §4.2) and the desktop **isolated-signer manifest** (§7.1, key_usage-typed). Anti-rollback
is on `(epoch, hash)` transactionally.

| Test ID | Under test | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-REG-01 | Registry rollback (epoch) | Present a registry with `registry_epoch < highest_registry_epoch` | Floor reject ⇒ refuse; supervisor won't bind it | §7 registry anti-rollback |
| NM-REG-02 | Same-epoch / different-hash | `registry_epoch == floor` but `registry_hash` differs | Refuse (divergent-content at same epoch) | §7 |
| NM-REG-03 | Divergent handle at floor | `challenge_registry_handle` not matching the floor's stored handle | Refuse | §7 |
| NM-REG-04 | Unknown root | `root_key_id` not in the binary-pinned challenge-root anchor set | Refuse (unknown root) | §4.2 |
| NM-REG-05 | Bad `root_sig` | `root_sig` not valid over `JCS(payload)` under the pinned root | Refuse | §4.2, §7 |
| NM-REG-06 | Registry rotated between open and accept | Key removed/rotated after open-time, before acceptance | Acceptance-time re-resolve ⇒ **`challenge_invalidated`** | §5(3), §4.5 |
| NM-REG-07 | Revoked key at acceptance | Bound `challenge_key_id` has `revoked==true && revoked_at_ms <= challenge_accepted_at_ms` | Acceptance refuses (`challenge_invalidated`) | §4.2, §5 |
| NM-REG-08 | Revocation boundary | `revoked_at_ms == challenge_accepted_at_ms` (as-of-run) | Refused at acceptance (boundary) | §4.2 |
| NM-REG-09 | Historical as-of-run validity | Record whose key `revoked_at_ms > challenge_accepted_at_ms` | **Accepts** as-of-run (positive control — proves later revocation doesn't invalidate a past record) | §4.2, §7 |
| NM-REG-10 | Revocation schema — true/null | `revoked==true` with `revoked_at_ms == null` | Strict schema reject ⇒ `malformed` | §4.2 |
| NM-REG-11 | Revocation schema — false/non-null | `revoked==false` with non-null `revoked_at_ms` | Strict schema reject ⇒ `malformed` | §4.2 |
| NM-REG-12 | Revocation time bound | `revoked_at_ms < valid_from_ms` | Schema reject | §4.2 |
| NM-REG-13 | Revocation seconds-not-ms | `revoked_at_ms` carrying a seconds value | Range reject | §4.2 |
| NM-REG-14 | Duplicate registry key ids | Two entries with the same `challenge_key_id` | Refuse (uniqueness) | §4.2 |
| NM-REG-15 | Registry bounds | `keys` length > 256 or document > 256 KiB | Refuse (`oversize`) | §4.2 |
| NM-REG-16 | Key not valid-window | `challenge_accepted_at_ms` outside `[valid_from_ms, valid_to_ms]` | §7 predicate refuse | §7 |
| NM-REG-17 | Presence-only insufficiency | `challenge_key_id` present but `sig` invalid under that exact snapshot key | Refuse (presence ≠ validity) | §7 |
| NM-MAN-01 | Manifest rollback | Desktop manifest `manifest_epoch < highest_epoch` | Anti-rollback ⇒ **Block** | §1.6/§1.7 (3b-2 design) |
| NM-MAN-02 | Manifest same-epoch/diff-hash | `epoch == highest_epoch AND manifest_hash differs` | Anti-rollback ⇒ Block | §1.6 |
| NM-MAN-03 | Manifest expired | `now > expires_at` | Block | §1.6 |
| NM-MAN-04 | Receipt-key wrong usage | A `supervisor_attestation` key used to render a receipt "Verified" | Receipt resolver rejects `key_usage != receipt_signing` ⇒ Block | §1.7 type separation |
| NM-MAN-05 | Attestation-key wrong usage | A `receipt_signing` key used to verify the supervisor attestation | `resolve_attestation_key` rejects `key_usage != supervisor_attestation` ⇒ Block | §1.7, §4.2 |
| NM-MAN-06 | Unknown attestation key id | `supervisor_attestation_key_id` not in the accepted manifest snapshot | Persist-time re-verify ⇒ Block | §4.2, §7.1 |
| NM-MAN-07 | Wrong-supervisor attestation key | Attestation key whose bound `supervisor_id` ≠ turn `supervisor_id` | Block | §4.2 |
| NM-MAN-08 | Revoked/out-of-window attestation key | Attestation key revoked or `now_ms` outside validity | Block | §4.2 |
| NM-MAN-09 | Snapshot/floor mismatch on resolve | Concurrent manifest acceptance changes the floor mid-tx | In-tx floor re-read mismatch ⇒ `Unavailable` ⇒ Block | §1.7 |
| NM-MAN-10 | Wildcard scope | Manifest key with `workspace`/`audience` == `"*"` | Semantic validation reject | §1.6 |
| NM-MAN-11 | Duplicate/conflicting key_id | Same `key_id` with different `public_key`/`trust_class`/`key_usage` | Semantic validation reject | §1.6 |
| NM-MAN-12 | Trust-class inference attempt | `receipt_signing` key missing signed `trust_class` | Reject (render authority must be signed in, never inferred) | §1.6 |
| NM-MAN-13 | Attestation key carrying render scope | `supervisor_attestation` key carrying `trust_class`/`allowed_protocols`/workspace | Reject | §1.6 |
| NM-MAN-14 | Non-production trust_class render | Signature verifies but key `trust_class != production` | `development_untrusted`, **never** "Verified" | §1.8 |

---

## 4. Scope binding — wrong workspace / install / supervisor / audience / protocol (`NM-SCOPE-*`)

The resolver query is sourced from the **trusted `Expected`/turn**, never the unsigned receipt
(§1.7). All authoritative fields cross-bind through the signed lease/record.

| Test ID | Under test | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-SCOPE-01 | Workspace mismatch | Receipt/record `workspace_id` ≠ `turn.expected.request.workspace_id` | Cross-binding inequality ⇒ Block | §1.7, §7 |
| NM-SCOPE-02 | Install mismatch | `install_id` ≠ trusted install | Block | §1.7, §7 |
| NM-SCOPE-03 | Supervisor mismatch | `supervisor_id` ≠ trusted supervisor | Block | §1.7, §7 |
| NM-SCOPE-04 | Protocol out-of-scope | Key's `allowed_protocols` ∌ `brops.receipt.v1` | Resolver `Unavailable` ⇒ Block | §1.7 |
| NM-SCOPE-05 | Audience out-of-scope | Install not in signed `allowed_audiences` | `Unavailable` ⇒ Block | §1.6/§1.7 |
| NM-SCOPE-06 | Unsigned-field trust attempt | Try to source a query field (other than `key_id`) from the parsed unsigned receipt | Design exposes only `key_id` unsigned; all else from `Expected` — assert no unsigned field is trusted | §1.7 |
| NM-SCOPE-07 | Bare key escape | A resolved key used without binding its scopes downstream | `ResolvedManifestKey` scopes must be bound by `verify`/`bind`; unbound path is a fail | §1.7 |
| NM-SCOPE-08 | Create-pending context divergence | (A) `workspace_id`/`install_id` differ from the desktop's pre-stored values | Authority-recomputed `request_sha256` ≠ pre-stored ⇒ every turn Blocks (`receipt_store.rs:322-327`) | §2.1 |

---

## 5. Malformed / oversized frames, duplicate keys, non-canonical JCS, unknown fields (`NM-FRAME-*`)

Strict decode for **every** artifact: exact required-key set, unknown-field + duplicate-key
rejection, fixed types, no NaN/Inf, UTF-8, lowercase-64-hex handles. Domain-separated tags.

| Test ID | Under test | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-FRAME-01 | Unknown field | Any artifact carrying an extra JSON key | `additionalProperties:false` ⇒ `malformed` | §4 |
| NM-FRAME-02 | Duplicate JSON key | A frame with a duplicated object key | Strict-decode duplicate-key reject ⇒ `malformed` | §4, §1.9 |
| NM-FRAME-03 | Missing required key | Required field omitted | Reject ⇒ `malformed` | §4 |
| NM-FRAME-04 | Wrong type / NaN / Inf | `_ms` as string, or a float NaN/Inf | Reject ⇒ `malformed` | §1.9, §4 |
| NM-FRAME-05 | Non-canonical JCS (challenge) | `decoded_document_bytes != canonical_bytes({payload,sig})` | Canonicality gate ⇒ internal **`noncanonical`** ⇒ Block | §6.1(1), §7 |
| NM-FRAME-06 | Non-canonical JCS (registry) | Registry bytes not canonical for `{payload,root_sig}` | Re-hash/canonicality mismatch ⇒ refuse | §7 |
| NM-FRAME-07 | Oversize sign-request | `brops.governed-sign-request.v1` frame > 256 KiB | `oversize` refuse | §4.4, §1.9 |
| NM-FRAME-08 | Oversize sign-result | `brops.governed-sign-result.v1` > 64 KiB | `oversize`/`malformed` refuse (machine-checked worst case ≈9865 ≤ 65536) | §4.5 |
| NM-FRAME-09 | Oversize authority frame | Create-pending/issue frame > `AUTHORITY_*_FRAME_BYTES` (4096/8192) | Internal `oversize` ⇒ Block | §2.1, §2.1.1 |
| NM-FRAME-10 | Oversize diagnostic | `bridge.governed-turn-diagnostic.v1` > `MAX_DIAGNOSTIC_BYTES (256)` | `governed_turn_execute` "anything else" arm ⇒ terminal Block | §4.10(h) |
| NM-FRAME-11 | Oversize output pull | Reassembled output > 8 MiB bound | `output_oversize` / Block | §7.1, §4.10(f) |
| NM-FRAME-12 | Oversize stdout | Sidecar stdout > `MAX_STDOUT_BYTES (9 MiB)` | Terminal transport Block | §6.1 out-of-band |
| NM-FRAME-13 | Bad hex handle | `*_handle`/`*_hash`/`*_sha256` not `^[0-9a-f]{64}$` | Strict reject ⇒ `malformed` | §4 |
| NM-FRAME-14 | Bad b64url sig | Signature not 86-char b64url no-pad | Reject ⇒ `malformed` | §4.4/§4.5 |
| NM-FRAME-15 | Wrong domain tag | A `brops.sign-request.v1` (base) presented on the governed path | Governed decoder rejects (domain separation) | §1.9, §2.2 |
| NM-FRAME-16 | Diagnostic masquerade | `bridge.governed-turn-diagnostic.v1` shaped to look like a `signed` result | Distinct top-level discriminator; lacks `envelope_jcs_b64`/`signature_b64`/`output_stream_id` ⇒ classified internal refusal, never success | §4.10(h) |
| NM-FRAME-17 | Frozen-schema collision | Diagnostic pushed through the frozen `bridge.result` frame | `bridge.result` rejects (no `protocol` key); `bridge.governed-turn-result.v1` rejects (requires ok/receipt/error) | §4.10(h) |
| NM-FRAME-18 | Inline large payload | Any large artifact sent inline instead of by handle | Frame-cap/handle model ⇒ reject; signer reads only by handle | §1.9, §4.4 |
| NM-FRAME-19 | Unparseable stdout | Empty/garbage sidecar stdout | "Anything else" arm ⇒ terminal durable Block | §4.10(h) |
| NM-FRAME-20 | Unknown stage/reason | Diagnostic with `stage`/`upstream_reason` outside the closed sets | Terminal Block (not accepted as a verdict) | §4.10(h) |

---

## 6. Crash at each transition + restart recovery (`NM-CRASH-*`)

Each cut point maps to exactly one durable state; **auto-launch is possible ONLY from
`LEASE_READY`** (§5). "No live child + no output" does **not** prove non-execution.

| Test ID | Cut point (crash immediately …) | Expected durable state / recovery | § ref |
|---|---|---|---|
| NM-CRASH-01 | in `VERIFYING`/`UPLOADING`/`INPUTS_READY` (pre-accept staging) | Staging row alone never authorizes execution; sweep unlinks orphan `.tmp-*.part` + deletes staging row **without consuming the nonce** (re-issue allowed until `challenge_expires_at_ms`) | §5 |
| NM-CRASH-02 | before acceptance commit | No acceptance row persisted ⇒ clean retry | §5 |
| NM-CRASH-03 | after commit, before signature | `ACCEPTED_PREPARED` ⇒ re-sign from `lease_payload_bytes` (deterministic) | §5 |
| NM-CRASH-04 | after signature, before publish | Publish is create-if-absent ⇒ idempotent | §5 |
| NM-CRASH-05 | after publish, before `LEASE_READY` | Re-hash/re-verify then advance | §5 |
| NM-CRASH-06 | `LEASE_READY` found on restart, lease still valid | Re-run step-8a gate on current wall clock; if it passes, CAS→`EXECUTION_STARTING`, launch **once** | §5(8a) |
| NM-CRASH-07 | `LEASE_READY` found on restart, lease **expired** | `now_ms > lease_expires_at_ms` ⇒ **`EXPIRED`**, **zero launch** | §5(8a), §5 neg-tests |
| NM-CRASH-08 | after `EXECUTION_STARTING` commit, before launcher call | **`RECOVERY_REQUIRED`**, never relaunch | §5(10), §5 neg-tests |
| NM-CRASH-09 | inside the launcher, before `exec` | **`RECOVERY_REQUIRED`** | §5 neg-tests |
| NM-CRASH-10 | immediately after `exec` / child exits before `EXECUTING` persistence | **`RECOVERY_REQUIRED`**, never relaunch | §5 neg-tests |
| NM-CRASH-11 | a remote model call occurred but no output/receipt exists | **`RECOVERY_REQUIRED`** (external effect possible) | §5 neg-tests |
| NM-CRASH-12 | after receipt/evidence, before terminal record | Re-drive record signing from published verified artifacts (idempotent create-if-absent, no new execution) | §5 |
| NM-CRASH-13 | after terminal record, before ledger `COMPLETED` | Set `COMPLETED` from the existing verified record | §5 |
| NM-CRASH-14 | after evidence-head floor commit, before envelope response | Retry hits case B (equal head + equal content) ⇒ identical re-sign, no advance, no re-execution | §7 (P1-7) |
| NM-CRASH-15 | mid-registry-acceptance (before COMMIT) | Floor + exact bytes at prior consistent state; startup verifies the floor snapshot exists + re-hashes else fail-closed | §7, §1.7 |
| NM-CRASH-16 | Launch-start marker misuse | Present the `execution_started_marker` as authorization to re-execute | Marker MUST NOT authorize re-execution ⇒ still `RECOVERY_REQUIRED` | §5(9)-(10) |

---

## 7. No-grant-restoration-after-start (`NM-NORELAUNCH-*`)

Explicit isolation of the "lease/grant is never restored or reused after `EXECUTION_STARTING`"
law — the single fact that guarantees zero automatic second execution.

| Test ID | Under test | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-NORELAUNCH-01 | Post-start relaunch ban | Restart with a durable `EXECUTION_STARTING` row and a still-valid lease window | **No auto-relaunch**; `RECOVERY_REQUIRED`; operator may inspect but MUST NOT reuse `challenge_handle`/`request_nonce`/`execution_attempt_id` | §5(10) |
| NM-NORELAUNCH-02 | Grant reuse after recovery | Attempt a new execution reusing the same challenge/nonce/attempt after recovery | Refused — a new execution requires a **newly signed challenge + new nonce + new attempt** | §5(10) |
| NM-NORELAUNCH-03 | EXECUTING without terminal proof | Restart finds `EXECUTING` but no complete terminal record | `RECOVERY_REQUIRED`, never relaunch | §5(10) |
| NM-NORELAUNCH-04 | Dual-destination edge | Force a `EXECUTION_STARTING → EXECUTING` flip without durable process metadata | The single flip requires child-running **AND** durable `process_group_id`/`cgroup_id`; otherwise crash ⇒ `RECOVERY_REQUIRED` (no implicit edge) | §5 transition triggers |

---

## 8. Concurrency, DB serialization, duplicate persistence (`NM-CONC-*`)

| Test ID | Under test | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-CONC-01 | Concurrent duplicate submissions | N simultaneous identical submits | Exactly one `ACCEPTED_PREPARED` + one attempt; losers get the idempotent result, **never** a 2nd execution | §5 neg-tests |
| NM-CONC-02 | Acceptance CAS loss | `absent → ACCEPTED_PREPARED` CAS loses to a conflicting existing binding | **`acceptance_conflict`** | §4.5, §5 |
| NM-CONC-03 | Evidence-floor serialization | Concurrent same-chain envelope attempts | Serialize on `BEGIN IMMEDIATE` + `(install_id,task_id)` PK; closes TOCTOU; exactly one commits | §7 (P1-7) |
| NM-CONC-04 | Concurrent re-anchor vs extension | Unchanged re-anchor (case C) vs prefix-extension (case D) race | Exactly one commits; the other re-evaluates on the new floor | §7 tests (8) |
| NM-CONC-05 | Nested-tx rejection | Attempt store/network I/O inside the desktop `BEGIN IMMEDIATE` | `in_immediate_tx` rejects a nested tx ⇒ Block; output fetch/hash MUST be outside the lock | §7.1, §6.1(14) |
| NM-CONC-06 | Duplicate terminal write | Two writers to `<run_id>__<execution_attempt_id>.json` | `O_CREAT|O_EXCL`; `EEXIST` ⇒ byte-compare: identical=idempotent, differ=**refuse** | §6(4) |
| NM-CONC-07 | Duplicate artifact publish | Re-publish an existing content-addressed handle | Existing identical digest = idempotent success; other collision = error | §4.0/§6 |
| NM-CONC-08 | Lease-not-ready trigger | Execute trigger (§4.10(d)) arrives before the row is `LEASE_READY` | **`lease_not_ready`** | §4.5, §5 |
| NM-CONC-09 | Desktop double-consume | Two turns racing to consume the same `receipt_challenges` nonce | `UPDATE … WHERE consumed_at IS NULL` guards; loser ⇒ Replay Block | §7.1 |

---

## 9. Output-byte mutation (`NM-OUTPUT-*`)

The signed envelope's `output_sha256`/`output_bytes` is the **sole** output authority; the
transport `output_stream_id` is never authority. Hash over **raw** bytes, no normalization.

| Test ID | Under test | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-OUTPUT-01 | Single-byte flip | Flip one byte of the pulled output before hashing | `SHA256(bytes) != envelope.output_sha256` ⇒ **Block** | §7.1 |
| NM-OUTPUT-02 | Length mismatch | `len(bytes) != envelope.output_bytes` | Block | §7.1 |
| NM-OUTPUT-03 | Normalization smuggle | Sidecar returns trimmed/NFC/CRLF-normalized output | Raw-byte hash mismatch ⇒ Block (no normalization before the check) | §7.1 |
| NM-OUTPUT-04 | Invalid UTF-8 | Output bytes that hash-match but are invalid UTF-8 | Hash passes, strict-UTF8 decode for display fails ⇒ Block | §7.1 |
| NM-OUTPUT-05 | Recorder output vs receipt | `output_handle != output_sha256` in the execution receipt | §7 receipt check ⇒ `hash_mismatch` | §7, §4.7 |
| NM-OUTPUT-06 | Stream-id as authority | Trust `output_stream_id` instead of the signed `output_sha256` | Design forbids; assert authority is the envelope, not the stream id | §7.1, §3 |
| NM-OUTPUT-07 | Output timeout | Output pull loop exceeds the execution timeout | **`output_timeout`** / terminal transport Block | §4.5, §6.1 |
| NM-OUTPUT-08 | Stream binding | Output-read 3-tuple (`receipt_id`/`execution_attempt_id`/`output_stream_id`) mismatched | **`stream_binding_mismatch`** / `stream_unknown` / `stream_expired` | §4.5, §4.10(f) |
| NM-OUTPUT-09 | Seq out of range | Output-read chunk sequence outside range | **`seq_out_of_range`** | §4.5 |

---

## 10. Evidence fork / rollback — the A–E floor matrix (`NM-EVID-*`)

Signer-owned durable `governed_evidence_head_floor` (`0700`/`0600`), keyed on `head_sequence`
monotonicity + chain-content `(event_count, last_sequence, final_event_hash)`.

| Test ID | Case | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-EVID-01 | A | `head_sequence < stored.highest_head_sequence` (stale/rolled-back/truncated head) | **`stale_evidence`** | §7 case A |
| NM-EVID-02 | B (idempotent) | Equal `head_sequence` + equal content triple | Idempotent re-sign of the byte-identical envelope | §7 case B |
| NM-EVID-03 | B (fork) | Equal `head_sequence`, **any** content difference | **`evidence_fork`** | §7 case B |
| NM-EVID-04 | B (diff final hash) | Same `event_count`, **different** `final_event_hash` | **`evidence_fork`** | §7 tests (6) |
| NM-EVID-05 | C (regression guard) | Higher `head_sequence` + identical content (valid unchanged re-anchor) | **Accept**: advance ONLY `highest_head_sequence`; mint envelope with new `evidence_head_sequence`, identical content — NOT a fork (the exact rev-17 P0-2 regression this guards) | §7 case C |
| NM-EVID-06 | D (advance) | Higher `head_sequence`, `event_count`/`last_sequence` increased, new chain contains stored chain as exact prefix (i–iv hold) | **Accept**: update all floor fields | §7 case D |
| NM-EVID-07 | D (missing prefix) | Extension that does NOT reproduce the stored prefix (D-ii/D-iii fail) | **`evidence_fork`** (divergent lineage) | §7 case D |
| NM-EVID-08 | E (short + high head) | Higher `head_sequence` + **shorter** chain | **`evidence_fork`** | §7 case E |
| NM-EVID-09 | E (length/seq disagree) | Higher head, content differs, counts not increased | **`evidence_fork`** | §7 case E |
| NM-EVID-10 | Bootstrap | No floor row (first turn) | INSERT from the validated head (no A-branch) | §7 bootstrap |
| NM-EVID-11 | Startup integrity | Corrupt/malformed floor row (`final_event_hash` not 64-hex, `event_count < 1`, etc.) | Refuse malformed DB at open, fail-closed | §7 startup integrity |
| NM-EVID-12 | Sidecar cannot reach floor | In-scope sidecar attempts to read/write the `brops-signer` `0700`/`0600` floor DB | DENIED (ACL) — the fork/rollback defense holds against the in-scope actor | §7, §2.3 |
| NM-EVID-13 | Out-of-scope honesty | Full-DB restore to an older self-consistent backup | Documented **NOT** defended (requires admin/root, OUT of §0 threat model); external anchoring DEFERRED to 3b-2 — test asserts the honest boundary, not a false claim | §7 |

---

## 11. Filesystem — symlink / hardlink / traversal (`NM-FS-*`)

Content-addressed store, `O_NOFOLLOW` opens, `fstat` the opened `fd` (never a path re-lookup),
atomic temp→fsync→verify→exclusive-publish.

| Test ID | Under test | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-FS-01 | Store symlink swap | Replace a store artifact path with a symlink | `O_NOFOLLOW` open fails; `0640` non-owner cannot chmod/symlink-swap ⇒ DENY | §2.3, §6 |
| NM-FS-02 | Executor image symlink | Executor image path is a symlink at launch | Launcher opens `O_NOFOLLOW|O_RDONLY|O_CLOEXEC`, `fstat`s the `fd`, `fexecve`s that exact fd ⇒ refuse on mismatch | §4.7 |
| NM-FS-03 | TCB path symlink | A `TCB_ARTIFACT` path is a symlink | `fstat` the opened `fd` (`O_NOFOLLOW`); refuse | §2.5 |
| NM-FS-04 | Handle traversal | A handle/name containing `../` or absolute path segments | Handle is `sha256`-named only; non-digest names rejected; no path traversal reachable | §4.0 |
| NM-FS-05 | Hardlink to store | Hardlink an artifact into an attacker-writable dir to swap bytes | Content-addressing: a handle is valid only if `sha256(bytes)==handle`; swapped bytes ⇒ re-hash mismatch ⇒ refuse | §4.0/§7 |
| NM-FS-06 | Partial-read TOCTOU | Read a handle mid-write | Atomic publish: a handle only ever names fully-written, fsync'd, digest-verified bytes | §4.0 atomic publish |
| NM-FS-07 | Writable ancestor dir | A writable ancestor directory of a TCB path | Start refused (`verify_tcb_integrity`) | §2.5, §9(c) |
| NM-FS-08 | Orphan temp sweep | Leftover `.tmp-*.part` after a crash | Sweep unlinks orphans without consuming the nonce | §5 |

---

## 12. Store ACL — unauthorized read / list / write / delete / rename, wrong service principal (`NM-ACL-*`)

Store at `2750` (owner-write / group read-traverse, **no group-w**); artifacts `0640`; keys
`0700`. **Tests run AS each OS principal** (the 3b-1A login-user prover does not cover these).

| Test ID | Actor → target | Attempted op | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-ACL-01 | signer → `store/sup/` | create/overwrite/rename/unlink/chmod/symlink | **DENY all writes**; ALLOW list+read | §2.3 |
| NM-ACL-02 | signer → `store/rec/` | any write | **DENY all writes**; ALLOW list+read | §2.3 |
| NM-ACL-03 | recorder → `store/sup/` | any write | **DENY all writes in `sup/`**; ALLOW read/list | §2.3 |
| NM-ACL-04 | supervisor → `store/rec/` | any write | **DENY all writes in `rec/`**; ALLOW read/list | §2.3 |
| NM-ACL-05 | recorder → `store/rec/` | write | ALLOW (positive control) | §2.3 |
| NM-ACL-06 | supervisor → `store/sup/` | write | ALLOW (positive control) | §2.3 |
| NM-ACL-07 | sidecar → `sup/` or `rec/` | every op incl. list/read | **DENY every op** (not in `brops-store`, not owner) | §2.3 |
| NM-ACL-08 | executor → `sup/` or `rec/` | every op incl. list/read | **DENY every op** | §2.3 |
| NM-ACL-09 | desktop/login → store or keys | any read/write/list | **DENY** (no store or key access) | §2.3 |
| NM-ACL-10 | Mode-regression guard | Re-introduce `2770` (group-write) on store dirs | `stat` must equal `2750` (setgid set, group-w clear); `_harden_dir` refuses `S_IWGRP` at load ⇒ fail-closed | §2.3 |
| NM-ACL-11 | Any non-owner → artifact | Overwrite an existing `0640` artifact | DENY (needs file `w`) | §2.3 |
| NM-ACL-12 | Login/sidecar → private-key dir | Read the receipt-signing / attestation / recorder key `0700` dir | DENY (owner-only) | §2.3, §1.2 |
| NM-ACL-13 | Login/sidecar → evidence-head floor DB | Read/write the `brops-signer` `0700`/`0600` floor | DENY | §2.3, §7 |
| NM-ACL-14 | Login/sidecar → acceptance ledger / staging | Read/write the supervisor-only `0700` DB | DENY | §2.3, §5 |
| NM-ACL-15 | 3-actor × 6-asset denial grid | Each of {login, renderer, sidecar-service-UID} × {auth key, pending store, receipt/attestation keys, protected store, verifier DB+manifest, TCB binaries} | Each cell **DENIED** with the stated enforcing mechanism (Linux; Windows SID equivalent §0.W) | §9(n) |

---

## 13. IPC peer authentication — wrong IPC peer (`NM-IPC-*`)

`AF_UNIX` + `SO_PEERCRED` UID allowlists on every channel; Windows equivalent = named-pipe
`GetNamedPipeClientProcessId` → token-SID allowlist.

| Test ID | Channel | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-IPC-01 | Authority create-pending/issue | Connect as the sidecar UID (not the desktop-UI UID) | `SO_PEERCRED` allowlist ⇒ **`peer_denied`** on both messages | §2.1 |
| NM-IPC-02 | Authority channel | Connect as the login/renderer UID | `peer_denied` | §2.1, §9(j) |
| NM-IPC-03 | Signer socket | Sidecar-service UID connects the signer socket | Peer-auth DENY (signer's only peer is the supervisor) | §9(k), §1.1 |
| NM-IPC-04 | Supervisor socket | A non-allowlisted UID connects | DENY | §0.1(2), §2.3 |
| NM-IPC-05 | Peer-auth primitive absent | Platform shim removes `SO_PEERCRED`-equivalent | `platform_governed_execution_supported()` == false ⇒ no lease | §0.1 |
| NM-IPC-06 | Renderer → any service IPC | Renderer reaches sidecar/supervisor/signer IPC | Unreachable/denied; a forged renderer "Verified" cannot create a verified message | §9(j) |

---

## 14. Signer-oracle attempts + caller-supplied evidence (`NM-ORACLE-*`)

No `sign_payload(bytes)` / `attest(evidence)` anywhere; the supervisor **builds** evidence from
`{run_id, execution_attempt_id}`; the authority builds the challenge from its own row.

| Test ID | Under test | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-ORACLE-01 | Supervisor evidence endpoint | Send `brops.evidence-request.v1` carrying a caller **evidence object** | Endpoint accepts only `{run_id, execution_attempt_id}` ⇒ reject | §1.3, §4.4/§4.10 |
| NM-ORACLE-02 | Fabricated run | `{run_id, attempt_id}` for a run with no lease/terminal state | No lease/terminal state ⇒ supervisor produces **no evidence** (structured refusal) | §1.3 |
| NM-ORACLE-03 | Signer caller bytes | Send the signer arbitrary bytes / a prepared envelope / hash claims | Signer signs only its own canonically-constructed receipt for an independently-validated run ⇒ refuse | §1.4 |
| NM-ORACLE-04 | Attestation forgery | Missing/invalid supervisor attestation over `JCS(evidence)` | **`attestation_invalid`**; no signature | §1.5(0), §4.5 |
| NM-ORACLE-05 | Derived-hash trust | Supply an inline `*_sha256` instead of a handle | Every `*_sha256` DERIVED by the signer from store bytes; inline value ignored/rejected | §4.4, §1.5(3) |
| NM-ORACLE-06 | Reference-not-artifact | A handle whose bytes are absent from the store | **`handle_missing`** (a handle is valid only if the store holds bytes hashing to it) | §1.3, §4.5 |
| NM-ORACLE-07 | Handle byte tamper | Store bytes whose `sha256 != handle` | **`hash_mismatch`** | §1.5(3), §4.5 |
| NM-ORACLE-08 | Authority two-step oracle | `create-pending(arbitrary_bytes) → issue(id)` | Create-pending stores only strictly-validated fixed-shape hashes/ids (never free bytes); issue signs only what the authority assembles ⇒ closes the oracle | §2.1 |
| NM-ORACLE-09 | Create-pending carries hash | (A) carries a `request_sha256` field | Authority recomputes it; a supplied field ⇒ `malformed` | §2.1 |
| NM-ORACLE-10 | Authority re-mints nonce | Authority mints its own `request_nonce` | Desktop consume fails / supervisor `request_sha256` mismatch ⇒ Block (the rev-19 defect) | §2.1 |
| NM-ORACLE-11 | Governed-turn-recorder oracle | Ask the `governed-turn-recorder` authority to sign a non-record payload | No public `sign(payload)` oracle; it signs ONLY `brops.governed-turn-record.v1`; `verify_artifact` refuses any other artifact/signer | §8 |
| NM-ORACLE-12 | Cross-authority sign | Lease-issuer signs a receipt, or recorder signs a lease | `ARTIFACT_AUTHORITY` mapping ⇒ `verify_artifact` refuses wrong signer | §4.3, §8 |
| NM-ORACLE-13 | Caller-supplied `execution_attempt_id` | Desktop supplies `execution_attempt_id` | The supervisor **reserves** it inside §5; a caller-supplied value is not a request field ⇒ rejected | §3, §5 |

---

## 15. TCB integrity, distinct principals, platform gate — executable / config mutation (`NM-TCB-*`)

`platform_governed_execution_supported()` gates governed real-mode; the launcher re-hashes the
executor image at exec-time; leases may name only the start-time TCB pins.

| Test ID | Under test | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-TCB-01 | Login-writable executor | Executor image writable by the login user | `verify_tcb_integrity()` refuses at start ⇒ no governed mode | §9(a), §2.5 |
| NM-TCB-02 | Executor swap after pin | Swap executor bytes after start-time pinning | Launcher `fexecve` re-hash mismatch ⇒ **`tcb_integrity_violation`**, **no receipt** | §9(b), §2.5, §4.7 |
| NM-TCB-03 | Wrong-owner TCB | Wrong-owner launcher/signer/config, or writable ancestor dir of a TCB path | Start refused | §9(c) |
| NM-TCB-04 | Lease names wrong image | Lease `launcher_executable_sha256`/`executor_executable_sha256` ≠ start-time pins | `validate_governed_turn_lease` rejects | §9(d), §4.3 |
| NM-TCB-05 | Shared UID | Any two of the seven principals share a UID | `verify_distinct_principals()` Block | §9(e), §2.6 |
| NM-TCB-06 | Sidecar == login UID | `sidecar` UID == login/desktop-UI UID | `verify_distinct_principals()` Block | §9(e) |
| NM-TCB-07 | Unset principal UID | A runtime principal UID unset | `verify_distinct_principals()` Block | §9(e) |
| NM-TCB-08 | Verifier == renderer | The trusted verifier/broker UID == the login/renderer UID | Block (a compromised renderer can never become the final verifier) | §9(i) |
| NM-TCB-09 | Broker == authority | The broker UID == the `desktop-challenge-authority` UID | Block | §9(i) |
| NM-TCB-10 | Platform primitive missing | Shim reports any single §0.1 primitive missing | Gate false ⇒ governed turn Blocks, **no lease** | §9(f), §0.1 |
| NM-TCB-11 | Non-supported platform | Run on Windows today | Gate false ⇒ dev/blocked, **never** `trusted_verified` (`platform_unsupported`) | §9(g), §0.W |
| NM-TCB-12 | All-present positive control | 7-distinct-UID Linux fixture | Gate true; the four §2.1 same-service-UID isolation proofs still hold | §9(h) |
| NM-TCB-13 | Launcher wrong caller | Launcher invoked by a UID ≠ recorder | Refuse, **no receipt** | §9(m) |
| NM-TCB-14 | Launcher extra argv/env/FD | Extra argv, non-empty env, or extra inherited FD | Refuse, no receipt | §9(m) |
| NM-TCB-15 | Data FD CLOEXEC | Data FD 3–6 arrives `FD_CLOEXEC` (would close executor I/O) | Refuse | §9(m) |
| NM-TCB-16 | Wrong target UID/GID | Target UID or GID ≠ executor | Refuse | §9(m) |
| NM-TCB-17 | Residual privilege | Residual supplementary groups or eff/perm/inh/ambient/bounding capability after the drop | Refuse | §9(m) |
| NM-TCB-18 | Failed drop primitive | `setgroups`/`setresgid`/`setresuid`/`prctl`/`capset` fails | Refuse | §9(m) |
| NM-TCB-19 | Image/cgroup swap | Image hash/owner/mode/path swap, or cgroup mismatch, or `fexecve` failure | Refuse, no receipt | §9(m) |
| NM-TCB-20 | Launcher-drop success | Tiny pinned executor reads FDs 3/4/5, writes FD 6 | **MUST run E2E** (FD survival + privilege drop proven) — positive control | §9(m) |
| NM-TCB-21 | Config mutation (generation_config) | Staged `generation_config` bytes differ from the challenge's committed `generation_config_sha256` | `handle_not_challenge` internal refusal (§2.4) ⇒ Block | §2.4, §2 |
| NM-TCB-22 | Config not in allowlist | Staged `generation_config_sha256` ∉ `GOVERNED_EXECUTION_ALLOWLIST` | **`model_profile_unknown`** pre-launch Block; no lease | §2, §4.5 |
| NM-TCB-23 | Model-identity formula | Lease `model_profile_id != "cfg-sha256:" + generation_config_sha256` | Signer §7 recompute ⇒ refuse before envelope | §7, §2 |
| NM-TCB-24 | Config/challenge binding | Lease `generation_config_sha256 != challenge.generation_config_sha256` | Refuse | §7 |
| NM-TCB-25 | Allowlist mutated post-execution | Change the allowlist after a record is signed | Historical record still re-derives + verifies identically (identity is a pure function of signed bytes; no allowlist consulted in §7) — positive control | §2, §7 |

---

## 16. Capability & lease overgrant (`NM-CAP-*`)

Closed `governed-model-turn-v1` profile: exactly `["INVOKE_GOVERNED_MODEL"]`, `max_tool_calls == 0`.

| Test ID | Under test | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-CAP-01 | Capability overgrant | Lease `allowed_capabilities` includes `EXECUTE_CODE`/`WRITE_FILESYSTEM`/`WRITE_REPOSITORY` or anything ≠ `["INVOKE_GOVERNED_MODEL"]` | `validate_governed_turn_lease` rejects | §2, §4.3 |
| NM-CAP-02 | Tool calls | `max_tool_calls != 0` | Reject (tool use out of scope, fails closed) | §2, §4.3 |
| NM-CAP-03 | Base-validator confusion | A governed-turn lease presented to the base `validate_execution_lease` | Base validator MUST refuse the governed keys as unexpected | §4.3, §8 |
| NM-CAP-04 | Base lease on governed path | A base `execution-lease` presented to `validate_governed_turn_lease` | Refused (wrong artifact_type / missing governed fields) | §4.3 |
| NM-CAP-05 | Builder-field smuggle | Lease carries `repository`/`branch`/`worktree`/`protected_scope` | No verifier for a model turn ⇒ reject on unknown/extra key | §2 |
| NM-CAP-06 | schema/nonce-length | `schema != 1`, or lease `nonce` length ∉ [16,128] | Reject | §4.3 |

---

## 17. Terminal-refusal-once + no-agent-message-on-Blocked (`NM-TERM-*`)

The transport-failure / internal-refusal / verdict-refusal paths all consume the nonce and write
a durable `blocked` attempt with **no message row and no signed receipt**, and are **not
retryable**.

| Test ID | Under test | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-TERM-01 | Terminal-refusal-once (transport) | Sidecar spawn/connect/timeout/oversize/malformed/unexpected-exit at submit or pull | `governed_turn_execute` ⇒ `record_pre_verification_block`: consume nonce + one durable `blocked` attempt; `StreamEvent::Blocked`; **not retryable** | §6.1 out-of-band, §7.1 |
| NM-TERM-02 | Nonce not retryable | Re-ask the same challenge/nonce after a terminal Block | `consumed_at != NULL` ⇒ `NonceState::Replay` ⇒ Block | §6.1 out-of-band |
| NM-TERM-03 | No message on Block | Any Block path (verdict/internal/transport) | **No message row**, no signed receipt persisted; only the durable `blocked` attempt | §6.1, §7.1 |
| NM-TERM-04 | No partial output | A refusal after partial output is pulled | **No partial output persisted**; nothing renders | §6.1 out-of-band |
| NM-TERM-05 | Sidecar fabricates success | Sidecar emits a `signed` result / a `GOVERNED_REFUSAL_REASONS` reason to mask a transport failure | The sidecar originates no verdict; a fabricated `signed` fails signature/echo verify ⇒ Block; a fabricated reason is not a genuine verdict | §4.5, §6.1 |
| NM-TERM-06 | Internal-refusal single sink | Any §4.10(a0/a/b/c/d) or authority internal refusal | Exactly **one** durable Block `governed_internal_refusal:{stage}:{reason}`; **no** acceptance-ledger `BLOCKED` row; **no** `GOVERNED_REFUSAL_REASONS` verdict | §4.10(h), §5 |
| NM-TERM-07 | Namespace disjointness | An internal reason (e.g. `peer_denied`) appearing as a `GOVERNED_REFUSAL_REASONS` verdict | Rejected — the two namespaces are disjoint and never merged | §4.10(h), §4.5 |
| NM-TERM-08 | UNSEEN → BLOCKED | A pre-acceptance (pre-row) refusal attempting to write a `BLOCKED` acceptance row | UNSEEN is not a stored predecessor ⇒ no `BLOCKED` row; the pre-row path yields the §4.10(h) diagnostic Block only | §5 (P1-5) |

---

## 18. Cross-binding equality + terminal-authority (`NM-XBIND-*`)

Unsigned JSON is never authority; the sole terminal authority is the signed
`brops.governed-turn-record.v1`, binding all of #1/#2/#4/#6/#7/#8.

| Test ID | Under test | Fault injected | Expected fail-closed outcome | § ref |
|---|---|---|---|---|
| NM-XBIND-01 | Forged/edited record | Mutate any field of the terminal record | `verify_artifact` fails first (no unsigned JSON is authority) ⇒ refuse | §7 |
| NM-XBIND-02 | Wrong record signer | Terminal record signed by the evidence-recorder (not `governed-turn-recorder`) | `verify_artifact` refuses wrong authority | §8 |
| NM-XBIND-03 | Lease handle mismatch | Record `lease_handle` doesn't re-hash to the fetched lease bytes | Refuse (`handle_missing`/`hash_mismatch`) | §7 |
| NM-XBIND-04 | Receipt handle mismatch | Record `execution_receipt_handle` mismatch | Refuse | §7 |
| NM-XBIND-05 | Containment cross-bind | Containment run/attempt/lease/runner ≠ record's, or `contained != true` | **`containment_missing`** / refuse | §7, §4.7b |
| NM-XBIND-06 | `challenge_accepted_at_ms` chain | The value differs across lease→attestation→result→record→envelope | Byte-equality chain fails ⇒ refuse | §7 |
| NM-XBIND-07 | Transport-echo mismatch | A `bridge.governed-turn-result.v1` echo ≠ the verified envelope | Echo-equality fails ⇒ Block (a bare echo never authorizes) | §7.1 |
| NM-XBIND-08 | Identity mismatch | `executor_id`/`runner_id`/`supervisor_id` not in the allowed set | **`identity_denied`** | §1.5(6)-equiv, §4.5 |
| NM-XBIND-09 | Not-completed decision | `decision != "completed"` | **`not_completed`** | §4.5 |
| NM-XBIND-10 | Run-binding inconsistency | `run_id`/`execution_attempt_id`/`lease_id` internally inconsistent | **`run_binding_invalid`** | §4.5 |
| NM-XBIND-11 | Policy mismatch | `policy_id`/`policy_version`/`policy_bundle_handle` not in force | **`policy_mismatch`** | §4.5, §7 |
| NM-XBIND-12 | Envelope signature | Envelope signature invalid under the pinned isolated-signer key | Desktop Block | §7.1 |
| NM-XBIND-13 | Attestation digest bind | `SHA256(attestation_evidence_jcs) != envelope.attestation_evidence_sha256` | Block | §7.1 |

---

## 19. Cross-language parity (`NM-PARITY-*`) — dependency-safe fixtures

Not adversarial faults but the guardrails that make the derived-hash refusals meaningful; each is
a Python↔Rust identical-`sha256` assertion (one per §4.0a/§3 formula).

| Test ID | Formula | Assertion |
|---|---|---|
| NM-PARITY-01 | `system` (raw UTF-8) | identical `sha256` incl. Unicode/emoji/embedded-NUL |
| NM-PARITY-02 | `history` (JCS `[{content,role}]`) | identical; incl. empty-history + Unicode case |
| NM-PARITY-03 | `output` (raw UTF-8, no trim) | identical |
| NM-PARITY-04 | `generation_config` (object-JCS, §4.10(g)) | identical; matches the frozen-default hash `732b58634d0a83e9b7fdf1ca69db78df145bd9dd79ac8922fed3e79cf5faab22` |
| NM-PARITY-05 | `containment_evidence` (JCS) | identical |
| NM-PARITY-06 | `policy_bundle` (exact loaded bytes) | identical |
| NM-PARITY-07 | full-field receipt + governed envelope | identical `JCS` + `sha256` |
| NM-PARITY-08 | `request_sha256` (8-field envelope) | `receipt.rs::request_envelope_sha256` ↔ `brops_canonical.request_sha256` identical |
| NM-PARITY-09 | Time-unit parity | ms integers identical both sides |

---

## 20. Coverage cross-reference (Architect's required list → sections)

| Architect-required negative | Sections / representative IDs |
|---|---|
| replay | §1 (NM-REPLAY-01..10) |
| duplicate receipt / nonce | NM-REPLAY-01/02/04/05/06, NM-CONC-09 |
| expiry | NM-TIME-03/07/13, NM-CRASH-07 |
| skew | NM-TIME-12/17/18 |
| stale manifest | NM-MAN-01/03, NM-REG-01 |
| same-epoch different hash | NM-REG-02, NM-MAN-02 |
| revoked / wrong-usage key | NM-REG-07..09, NM-MAN-04..08 |
| wrong workspace / install / supervisor | §4 (NM-SCOPE-01..03) |
| malformed / oversized frames | §5 (NM-FRAME-01/03/04/07..12) |
| duplicate JSON keys | NM-FRAME-02 |
| non-canonical JCS | NM-FRAME-05/06 |
| crash at each transition | §6 (NM-CRASH-01..16) |
| restart recovery | NM-CRASH-06/07, NM-EVID-11, NM-CRASH-15 |
| concurrent execution | NM-CONC-01/03/04 |
| DB serialization | NM-CONC-03/05, NM-CONC-02 |
| duplicate persistence | NM-CONC-06/07 |
| output-byte mutation | §9 (NM-OUTPUT-01..09) |
| evidence fork / rollback | §10 (NM-EVID-01..13) |
| symlink / hardlink / traversal | §11 (NM-FS-01..08) |
| unauthorized read/list/write/delete/rename | §12 (NM-ACL-01..15) |
| wrong service principal | NM-ACL-15, NM-TCB-05..09 |
| wrong IPC peer | §13 (NM-IPC-01..06) |
| signer-oracle attempts | NM-ORACLE-03/08/11/12 |
| caller-supplied evidence | NM-ORACLE-01/02/05/13 |
| executable / config mutation | NM-TCB-01/02/19/21..24 |
| terminal-refusal-once | NM-TERM-01/02 |
| no-agent-message-on-Blocked | NM-TERM-03/04 |
| no-grant-restoration-after-start | §7 (NM-NORELAUNCH-01..04), NM-CRASH-08..11/16 |

---

## 21. Global stop condition (unchanged)

Per addendum §6 / §9: **no `trusted_verified` renders and `NoTrustedManifest` is not swapped
until the ENTIRE chain is GREEN.** Every row above must be provable **with `NoTrustedManifest`
still in place** — i.e. as a refusal/Block/no-render, never by observing a real "Verified" being
withheld. The single positive control (§9) is a genuinely-executed record; every other row here
is a fail-closed negative. This plan is complete when each Test ID has an executable assertion and
the engine + Linux-isolation exact-head CI is GREEN — **implementation deferred to Architect
design-GREEN; no code lands under this document.**

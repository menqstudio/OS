# Wave 3b-1B — authoritative execution→receipt binding · ARCHITECT ADDENDUM (design-lock, rev 11 — CONSOLIDATED)

> **STATUS: ❌ DESIGN RED being closed — rev 11 is a PROPOSED design-GREEN candidate, NOT
> Architect-GREEN. 3b-1B code has NOT started.** The Architect reviewed **rev 10** at exact
> HEAD `6b1f8f4a42a3cf9f8746af971187ea91f82232fa` (exact-head CI **#114** fully GREEN —
> **CI GREEN ≠ design GREEN**) and returned **Design RED** with **3 P0 + 2 P1**, and directed
> a **one-pass consolidation** rather than another append-only micro-revision. **rev 11 is a
> full rewrite of the CURRENT normative design** derived from **one artifact matrix (§3)** and
> **one durable acceptance state machine (§5)**; the revision history is now a **NON-NORMATIVE
> appendix (Appendix A)** and no historical prose redefines a current contract. The rev-10 →
> rev-11 findings closed here: **P0-1** mixed timestamp units (base lease is epoch **seconds**;
> the addendum compared it to epoch-**millisecond** `challenge_accepted_at`) → a single
> canonical **epoch-millisecond** time model with explicit `_ms` names for every governed-turn
> field (§1); **P0-2** an "issue or durably prepare a signed file in one DB transaction" claim
> that is not actually atomic → an exact **durable acceptance state machine + outbox** with
> real uniqueness constraints and crash recovery at every cut point (§5); **P0-3** the
> governed-turn lease inherited **code-builder overgrants** (`EXECUTE_CODE`/`WRITE_FILESYSTEM`/
> `WRITE_REPOSITORY`) and a string `protected_scope` → a **dedicated closed `governed-model-turn-v1`
> capability profile** with no builder grants, `max_tool_calls = 0`, and only fields that have a
> verifier (§2, §4); **P1-4** the relay schemas were only field-lists → **exact normative
> schemas** for sign-request / sign-result / bridge-result / record with transport-only echoes
> vs. authority (§4), and **§8** now references only `issue_governed_turn_lease` /
> `validate_governed_turn_lease`; **P1-5** the 3b-1 map body carried stale architecture → it is
> now a concise index pointing here (see `WAVE_3B1_EXECUTION_BINDING_MAP.md`). **All contracts
> below are OPEN until the Architect returns design-GREEN at the exact pushed HEAD.** STOP
> gates: `NoTrustedManifest` unchanged, no production "Verified", 3b-2/3b-3 not started, PR #31
> not merged.

> **DESIGN-ONLY.** No 3b-1B code ships until this addendum is Architect-GREEN. It reuses the
> existing lease / containment / receipt / evidence authorities — **no parallel executor**.
> **This document is the single normative source for the 3b-1B contracts; where any other
> file (including the 3b-1 map) and this document disagree, THIS document wins and the other
> is a bug to fix.**

---

## 0. Scope & topology

The governed AI turn (desktop `system`/`history` → model reply) becomes a
**`bro_supervisor`-owned supervised execution** that **atomically emits a signed terminal
record**. No unsigned run-state JSON is ever signing authority. The model executor is the
`builder_command` for this run — spawned + contained exactly as any builder, but under the
recorder (below), holding **no signing key**.

```
supervisor (owns the acceptance ledger §5 + the governed-turn lease issuer + the
            governed-turn-recorder key; signs the TERMINAL RECORD only)
  → EVIDENCE-RECORDER RUNNER  (dedicated recorder UID; holds the evidence-recorder key;
        signs the governed-turn execution RECEIPT + evidence chain/head; owns the
        executor pidfd/cgroup + output pipe + teardown measurement)
      → NARROW PRIVILEGED LAUNCHER  (tiny setuid helper: only setuid(executor)+exec the
            pinned model executor in a fresh cgroup/process group; holds NO key)
          → CONTAINED MODEL EXECUTOR  (executor UID; NO key/store access; reads 3 read-only
                input FDs, writes 1 output FD — nothing else, §2)
```

Distinct OS principals: **desktop-UI/challenge-authority**, **sidecar** (compromised
in-scope, same login user), **supervisor**, **evidence-recorder runner**, **privileged
launcher**, **contained executor**, **isolated receipt signer**, **governed-turn-recorder**.
Threat scope (from the ratified base design): sidecar RCE at the **same login user** is
IN scope; admin/root/kernel is OUT of scope. Where a platform cannot separate the
desktop-UI principal from the sidecar UID, governed real-mode is **FAIL-CLOSED** on that
platform (Windows is fail-closed until its broker is separately audited).

---

## 1. Canonical time model (P0-1) — ONE unit, explicit names

**Every governed-turn artifact uses integer epoch MILLISECONDS**, and **every field name
ends in `_ms`** so the unit is visible at the call site. The ratified base `execution-lease`
(`issued_at_epoch`/`expires_at_epoch`, epoch **seconds** via `int(time.time())`) is **left
unchanged and is NOT reused** by the governed-turn chain — the governed-turn lease is a
**separate artifact** with its own `_ms` fields (§4.3), never the base `*_epoch` names with
silently changed units.

- Canonical fields: `requested_at_ms`, `challenge_issued_at_ms`, `challenge_expires_at_ms`,
  `challenge_accepted_at_ms`, `lease_issued_at_ms`, `lease_expires_at_ms`, `started_at_ms`,
  `finished_at_ms`, `completed_at_ms`, `measured_at_ms`, `registry_issued_at_ms`,
  key `valid_from_ms` / `valid_to_ms` / `revoked_at_ms`.
- Type: JSON **integer**, `1 ≤ v ≤ 2^53-1` (fits an f64/i64 both sides; overflow/negative
  rejected). The desktop's Wave-3a `requested_at` is normalized to `requested_at_ms` (ms)
  **when the challenge authority builds the challenge** (§4.1); the whole chain is ms after
  that point.
- **`challenge_accepted_at_ms` is produced by exactly one supervisor clock read** (§5 step
  2) and is the **only** field the validity/expiry/revocation window is checked against.
- **Boundaries are inclusive on both ends:** a time `t` is in a window iff
  `lo_ms ≤ t ≤ hi_ms`. The acceptance predicate (§5, §7) is
  `requested_at_ms ≤ challenge_accepted_at_ms` **and**
  `challenge_issued_at_ms ≤ challenge_accepted_at_ms ≤ challenge_expires_at_ms`.
- **Negative tests (normative):** a value that is plausibly seconds not ms (≈10 digits vs
  ≈13) is rejected by range/consistency; overflow, negative, zero, far-future-skew, and each
  inclusive boundary (`== lo_ms`, `== hi_ms`, `lo-1`, `hi+1`) are covered. Cross-language
  (Python engine ↔ Rust desktop) parity asserts identical ms integers.

---

## 2. Principals & capabilities (P0-3) — the executor inherits NO builder authority

The base lease task classes (`STANDARD_BUILDER`, `SECURITY_MAINTENANCE`) each grant
`{EXECUTE_CODE, WRITE_FILESYSTEM, WRITE_REPOSITORY}` and are built around repos/worktrees.
The governed model executor's locked topology gives it **only three read-only input FDs and
one write-only output FD** (§4.7). It therefore uses a **dedicated, closed capability
profile — NOT a base-lease superset**:

- **task class `governed-model-turn-v1`** with a **CLOSED** capability set
  `["INVOKE_GOVERNED_MODEL"]` — the single narrow capability "run the pinned model executor
  once, read the three input FDs, write the one output FD". It **MUST NOT** include
  `EXECUTE_CODE`, `WRITE_FILESYSTEM`, `WRITE_REPOSITORY`, arbitrary path access, arbitrary
  executable selection, or arbitrary tool invocation. `validate_governed_turn_lease` (§4.3)
  rejects any lease whose `allowed_capabilities` is not exactly `["INVOKE_GOVERNED_MODEL"]`.
- **`max_tool_calls = 0`** — tool use is out of 3b-1B scope and **fails closed**. (If tool
  execution is ever added, it needs a separately-mediated, exactly-scoped tool-broker
  contract; builder capabilities are never inherited implicitly.)
- The **pinned launcher executable digest** (`launcher_executable_sha256`) and the **model
  profile** (`model_profile_id`) are explicit lease fields with real verifiers (§4.3): the
  launcher refuses any other executable/target UID (§4.7), and the recorder refuses a
  `model_profile_id` not in its allow-set.
- The governed-turn lease **omits** the builder-only fields `repository`, `branch`,
  `worktree`, `head_sha`, `tree_identity`, and `protected_scope` — none has a verifier for a
  model turn. (If a future justified use reintroduces `protected_scope`, its type is an
  **array of exact non-pattern paths**, never a string.)

Principal/ACL summary (full matrix in Appendix B): the pending-challenge store and the
acceptance ledger are owned by the **challenge-authority / supervisor** principals (`0700`),
sidecar UID denied read/write/list; the protected content-addressed store is writable only
by the **supervisor** (inputs, challenge doc, registry snapshot, lease doc) and the
**recorder** (output, containment); the executor/sidecar have no store or key access.

---

## 3. THE ARTIFACT MATRIX (single normative source)

Every 3b-1B artifact, locked. "Handle" = `SHA256(exact stored document bytes)` (protected
store). "Signed bytes" = detached Ed25519 over `JCS(payload)` unless noted. A field has
**one name, one type, one unit, one authority** everywhere; §4 gives the exact key sets.

| # | Artifact / protocol | Producer | Signer / authority | Verifier / consumer | Time unit | Handle formula | Durable owner | Replay/idempotency key | Key cross-bindings |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `brops.governed-turn-challenge.v1` | desktop-UI **challenge-authority** | `desktop-challenge-authority` key (`challenge_key_id`) | supervisor §5; `LiveRunStateProvider` §7 | ms | `challenge_handle = SHA256(JCS({payload,sig}))` | supervisor store (published §6) | `request_nonce` (one-time) | binds `run_id`/`task_id`/context + `*_sha256` |
| 2 | `brops.challenge-key-registry.v1` | operator (root-signed) | challenge-**root** anchor (`root_key_id`) | supervisor §5; provider §7 | ms | `challenge_registry_handle = SHA256(JCS({payload,root_sig}))` | supervisor store | `registry_epoch` + `registry_hash` (anti-rollback) | `registry_hash = SHA256(JCS(payload))` (identity, ≠ handle) |
| 3 | acceptance-ledger row (§5) | supervisor | — (durable DB, not signed) | supervisor (recovery); provider (indirect) | ms | — | supervisor acceptance DB (`0700`) | `UNIQUE(install_id,request_nonce)`, `UNIQUE(challenge_handle)`, `UNIQUE(execution_attempt_id)` | holds lease_payload bytes + state |
| 4 | `brops.governed-turn-lease.v1` | supervisor **governed-turn lease issuer** | lease-issuer key | recorder; supervisor; provider §7 | ms | `lease_handle = SHA256(JCS({payload,signature}))` | supervisor store | `nonce` (lease) + `execution_attempt_id` | binds challenge #1 via `challenge_handle`/`challenge_key_id` + registry #2 + `challenge_accepted_at_ms` |
| 5 | `brops.sign-request.v1` (governed-turn evidence) | supervisor | **supervisor attestation** key (`supervisor_attestation_key_id`) over `JCS(evidence)` | isolated signer; desktop re-verify | ms | (transported, not stored) | — | `request_nonce` + `execution_attempt_id` | echoes #4/#6 handles; every `*_sha256` DERIVED by signer |
| 6 | `brops.governed-turn-execution-receipt.v1` | recorder runner | **evidence-recorder** key | supervisor §6; `verify_governed_turn_receipt` §7 | ms | `receipt_handle = SHA256(JCS({payload,signature}))` | supervisor store | `receipt_id` (global unique) | `output_handle == output_sha256`; binds attempt/lease |
| 7 | `brops.governed-turn-containment.v1` | recorder runner | evidence event (evidence-recorder) | provider §7 | ms | `containment_evidence_sha256 = SHA256(JCS(artifact))` | supervisor store | attempt+lease | `contained==true`, closed `teardown_outcome` enum |
| 8 | evidence event / head (`bro_evidence`) | recorder runner | **evidence-recorder** key | provider §7; desktop floor §7 | ms | `event_hash` chain | evidence chain | `(install_id, task_id)` head floor | head seq strictly-increasing per chain |
| 9 | `brops.sign-result.v1` (governed-turn) | isolated signer | signer key (the receipt envelope) | supervisor → bridge → desktop | ms | (transported) | — | `receipt_id` | tagged union `signed`/`refused`; echoes TRANSPORT-ONLY |
| 10 | bridge result `receipt` | sidecar (transport) | — (carries #6/#9 signed bytes) | **desktop = final authority** | ms | (transported) | — | `receipt_id` | echoes TRANSPORT-ONLY; desktop equality-checks vs verified #4/#5/#11 |
| 11 | `brops.governed-turn-record.v1` | supervisor | **`governed-turn-recorder`** key (dedicated) | `LiveRunStateProvider` §7 | ms | `record_handle` (state dir, create-if-absent) | supervisor state dir | `(run_id, execution_attempt_id)` | binds ALL of #1,#2,#4,#6,#7,#8 + `challenge_accepted_at_ms` |

**Refusal is fail-closed everywhere:** any missing/extra key, wrong type/unit, handle
mismatch, signature failure, cross-binding inequality, or ledger conflict Blocks; nothing
renders.

---

## 4. Exact schemas (backing the matrix)

Strict decode for **every** artifact: exact required-key set, **unknown-field rejection**,
**duplicate-key rejection**, UTF-8, integers for `_ms`/epoch/counts, lowercase-64-hex for
`*_handle`/`*_hash`/`*_sha256`. `artifact_type`/`key_id` are injected by the signer and
echoed. Signed bytes = detached Ed25519 over `JCS(payload)` unless noted.

### 4.1 `brops.governed-turn-challenge.v1` (artifact #1)
```jsonc
{ "payload": {
    "protocol": "brops.governed-turn-challenge.v1",
    "challenge_key_id": "<string ≤128>",
    "run_id": "<string ≤128>", "task_id": "<string ≤128>",
    "workspace_id": "<string ≤128>", "install_id": "<string ≤128>",
    "supervisor_id": "<string ≤128>",
    "request_nonce": "<string ≤128>",                         // one-time (Wave-3a nonce)
    "system_sha256": "<64hex>", "history_sha256": "<64hex>",
    "generation_config_sha256": "<64hex>",
    "request_sha256": "<64hex>",                              // == sha256(JCS(request envelope))
    "requested_at_ms": <int>, "challenge_issued_at_ms": <int>,
    "challenge_expires_at_ms": <int> },
  "sig": "<b64url Ed25519 over JCS(payload), by the desktop-challenge-authority key>" }
```
The authority **builds** this from the trusted desktop DB (caller supplies only a
protected pending-challenge ID, never bytes; §5 P0-1 history); it does **not** carry
`challenge_accepted_at_ms` (the supervisor stamps that later — §1/§5).

### 4.2 `brops.challenge-key-registry.v1` (artifact #2)
```jsonc
{ "payload": {
    "artifact_type": "brops.challenge-key-registry.v1",
    "root_key_id": "<string ≤128>", "registry_epoch": <int>, "registry_issued_at_ms": <int>,
    "keys": [ { "challenge_key_id": "<string ≤128>", "public_key": "<b64url 32B→43 chars>",
                "valid_from_ms": <int>, "valid_to_ms": <int>, "key_epoch": <int>,
                "revoked": false, "revoked_at_ms": null } ] },
  "root_sig": "<b64url Ed25519 over JCS(payload), by the pinned challenge-root>" }
```
Two distinct digests (protected-store law): `registry_hash = SHA256(JCS(payload))`
(fork/epoch identity, anti-rollback) vs `challenge_registry_handle = SHA256(JCS({payload,
root_sig}))` (exact stored document bytes, store lookup + record binding). `root_key_id`
selects a **binary-pinned challenge-root anchor baked into the supervisor config**
(root-owned; separate root + registry from the receipt keys); an unknown root is refused.

### 4.3 `brops.governed-turn-lease.v1` (artifact #4) — dedicated, closed
```jsonc
{ "payload": {
    "artifact_type": "brops.governed-turn-lease.v1",   // injected + echoed
    "key_id": "<lease-issuer key id>",                  // injected + echoed
    "schema": 1,
    "lease_id": "<string ≤128>", "nonce": "<string 16..128>",   // LEASE nonce (not lease_nonce)
    "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>",
    "task_id": "<string ≤128>", "agent_id": "<string ≤128>", "session_id": "<string ≤128>",
    "workspace_id": "<string ≤128>", "install_id": "<string ≤128>", "supervisor_id": "<string ≤128>",
    "task_class": "governed-model-turn-v1",
    "allowed_capabilities": ["INVOKE_GOVERNED_MODEL"],  // CLOSED; exactly this
    "max_tool_calls": 0,
    "launcher_executable_sha256": "<64hex>",            // pinned setuid launcher digest
    "model_profile_id": "<string ≤128>",               // bound model endpoint/profile
    "lease_issued_at_ms": <int>, "lease_expires_at_ms": <int>,
    "challenge_accepted_at_ms": <int>,                  // supervisor-stamped (§5)
    "request_nonce": "<string ≤128>",                   // == challenge #1 request_nonce
    "challenge_handle": "<64hex>", "challenge_key_id": "<string ≤128>",
    "challenge_registry_handle": "<64hex>", "challenge_registry_hash": "<64hex>",
    "challenge_registry_epoch": <int>, "challenge_registry_root_key_id": "<string ≤128>"
  },
  "signature": "<detached Ed25519 over JCS(payload)>" }
```
- **Authority:** `ARTIFACT_AUTHORITY["brops.governed-turn-lease.v1"] = the governed-turn
  lease issuer` (the supervisor's lease-issuing authority; signs **leases only**, never
  receipts/records/evidence). `verify_artifact` refuses any other signer.
- **`issue_governed_turn_lease`:** the sole issuer; called **inside §5 step 4/6** with the
  accepted challenge, reserved `execution_attempt_id`, stamped `challenge_accepted_at_ms`, and
  resolved registry bindings; enforces `requested_at_ms ≤ challenge_accepted_at_ms` and
  `lease_issued_at_ms ≤ challenge_accepted_at_ms ≤ lease_expires_at_ms` at signing; signs.
- **`validate_governed_turn_lease`:** `verify_artifact` (issuer) → strict-decode the exact
  key set → return fields. Refuses a missing/extra key, non-int `_ms`, `schema != 1`,
  `nonce` length ∉ [16,128], `allowed_capabilities != ["INVOKE_GOVERNED_MODEL"]`,
  `max_tool_calls != 0`. **Separate** from the base `validate_execution_lease` (which would
  reject the governed-turn keys as unexpected — a governed-turn lease presented to the base
  validator MUST be refused, tested).

### 4.4 `brops.sign-request.v1` — governed-turn evidence (artifact #5)
Extends the ratified sign-request evidence to the exact governed-turn key set
(`additionalProperties:false`): the base evidence keys (`run_id, execution_attempt_id,
lease_id, request_nonce, receipt_id, decision="completed", workspace_id, install_id,
supervisor_id, executor_id, builder_id, policy_id, policy_version, system_handle,
history_handle, output_handle, generation_config_handle, containment_evidence_handle,
policy_bundle_handle`) **with `requested_at`/`completed_at` replaced by integer
`requested_at_ms`/`completed_at_ms`**, **plus** `challenge_accepted_at_ms`, `task_id`,
`challenge_handle`, `challenge_key_id`, `challenge_registry_handle`, `challenge_registry_hash`,
`challenge_registry_epoch`, `challenge_registry_root_key_id`, `evidence_head_sequence`
(int), `evidence_final_event_hash` (64hex). The **supervisor attestation**
(`brops.run-attestation.v1`, `supervisor_attestation_key_id`) signs `JCS(evidence)`; every
`*_handle`/`*_sha256` is **DERIVED by the signer** from the store bytes, never trusted from
the wire. Frame ≤ 256 KiB; large inputs are handles, never inline.

### 4.5 `brops.sign-result.v1` — governed-turn (artifact #9)
Tagged union. `signed`: the base signed fields (`receipt_id, envelope_jcs_b64,
signature_b64, key_id, attestation_evidence_jcs_b64, attestation_signature_b64,
supervisor_attestation_key_id, run_id, execution_attempt_id, lease_id`) **plus** the echoed
`challenge_accepted_at_ms`, `task_id`, and the four `challenge_registry_*` fields +
`challenge_handle`/`challenge_key_id` + `evidence_head_sequence`/`evidence_final_event_hash`
— **TRANSPORT-ONLY** (see below). `refused`: `{receipt_id|null, reason}` with the reason
enum extended to include the governed-turn cases `challenge_replay`, `acceptance_conflict`,
`lease_not_ready` alongside the ratified reasons. Frame ≤ 64 KiB.

### 4.6 bridge result `receipt` (artifact #10)
The ratified bridge `receipt` object + the same echoed governed-turn fields, all
**TRANSPORT-ONLY**. **Authority rule (locked):** the **desktop** takes authority from (a)
the **verified supervisor-attestation bytes** (re-verified against the manifest
`supervisor_attestation` key), (b) the **verified `brops.governed-turn-lease.v1`**, and (c)
the **verified `brops.governed-turn-record.v1`** — then **equality-checks** the bridge/
sign-result echoes against those verified values. **A bare bridge/sign-result echo is never
authority**; a mismatch Blocks.

### 4.7 `brops.governed-turn-execution-receipt.v1` (artifact #6), input FDs, containment
- **Receipt** (recorder-runner signed, evidence-recorder key; `verify_governed_turn_receipt`
  verifies — NOT `verify_passing_receipt`): binds `receipt_id`, `run_id`,
  `execution_attempt_id`, `lease_id`, `runner_id`, `executor_id`, `exit_code==0`,
  `contained==true`, `output_handle == output_sha256 == SHA256(exact binary reply bytes)`
  (no decode/trim/CRLF normalization), `started_at_ms ≤ finished_at_ms`.
- **Input FDs (canonical):** FDs `3`/`4`/`5` are **read-only regular-file descriptors** to
  the exact content-addressed `system`/`history`/`generation_config` bytes (no length
  prefix); FD `6` is the write-only output pipe. The launcher validates each input FD is
  `O_RDONLY`, `S_ISREG`, offset 0, size ≤ the per-artifact ceiling (system ≤256 KiB, history
  ≤8 MiB, generation_config ≤64 KiB), backed by a supervisor-owned store inode; it closes
  every other FD, validates the pinned `launcher_executable_sha256` + fixed caller/target
  UID, drops caps, then `setuid(executor)+exec`. The executor reads each input to EOF and
  writes only its reply.
- **Containment** (`brops.governed-turn-containment.v1`): recorder-measured firsthand;
  `contained==true`, closed `teardown_outcome ∈ {contained,orphan-quarantined,timed-out,
  failed}` (only `contained` accepted), both `cgroup_id`+`process_group_id`, `measured_at_ms`;
  `containment_evidence_sha256 = SHA256(JCS(artifact))` recorded as a containment-confirmed
  evidence event.

### 4.8 `brops.governed-turn-record.v1` (artifact #11) — the ONLY terminal authority
Signed by the dedicated **`governed-turn-recorder`** key, written atomically
(create-if-absent, §6) as `<run_id>__<execution_attempt_id>.json`. Its `payload` binds
(all `_ms`): identities (`run_id, execution_attempt_id, task_id, agent_id, session_id,
workspace_id, install_id, supervisor_id, executor_id, runner_id`), the lease
(`lease_id, lease_nonce == the lease's `nonce`, lease_issued_at_ms, lease_expires_at_ms`),
the request (`request_nonce, system_sha256, history_sha256, generation_config_sha256,
requested_at_ms, request_sha256`), the challenge (`challenge_handle, challenge_key_id,
challenge_issued_at_ms, challenge_expires_at_ms, challenge_accepted_at_ms`), the registry
snapshot (`challenge_registry_handle, challenge_registry_hash, challenge_registry_epoch,
challenge_registry_root_key_id`), the output (`output_sha256`), policy
(`policy_id, policy_version, policy_bundle_sha256`), containment
(`containment_evidence_sha256, containment_event_id`), the receipt (`receipt_id`), the
evidence head (`evidence_final_event_hash, evidence_head_sequence`), and `completed_at_ms`.

---

## 5. Durable supervisor acceptance — state machine + outbox (P0-2)

A database transaction **cannot** atomically include an external private-key signature and a
filesystem publish. Acceptance is therefore a **durable state machine with an outbox**, not a
single "issue-or-prepare" step.

**Acceptance ledger (supervisor-owned durable DB, `0700`):**
```sql
CREATE TABLE governed_turn_acceptance (
  install_id                     TEXT NOT NULL,
  request_nonce                  TEXT NOT NULL,
  challenge_handle               TEXT NOT NULL,   -- 64hex
  run_id                         TEXT NOT NULL,
  task_id                        TEXT NOT NULL,
  workspace_id                   TEXT NOT NULL,
  execution_attempt_id           TEXT NOT NULL,
  challenge_accepted_at_ms       INTEGER NOT NULL,
  challenge_registry_handle      TEXT NOT NULL,
  challenge_registry_hash        TEXT NOT NULL,
  challenge_registry_epoch       INTEGER NOT NULL,
  challenge_registry_root_key_id TEXT NOT NULL,
  lease_payload_sha256           TEXT NOT NULL,   -- sha256 of the EXACT canonical lease payload bytes
  lease_payload_bytes            BLOB NOT NULL,    -- the exact JCS(payload) to be signed
  lease_handle                   TEXT,             -- 64hex, set at LEASE_READY
  state                          TEXT NOT NULL,    -- enum below
  execution_started_marker       TEXT,
  cgroup_id                      TEXT,
  process_group_id               TEXT,
  terminal_record_handle         TEXT,
  failure_reason                 TEXT,
  created_at_ms                  INTEGER NOT NULL,
  updated_at_ms                  INTEGER NOT NULL,
  UNIQUE (install_id, request_nonce),
  UNIQUE (challenge_handle),
  UNIQUE (execution_attempt_id)
);
```
The three `UNIQUE` constraints (not a single composite "at least" key) mean: a reused
`request_nonce` collides on `(install_id, request_nonce)`; a reused `challenge_handle`
collides on `challenge_handle`; one challenge maps to **exactly one** `execution_attempt_id`.
A retry that presents a nonce/challenge pairing different from the stored row (different
`run_id`/`task_id`/`workspace_id`/`challenge_handle`) is a **conflict** and is refused. Any
new attempt requires a **new signed challenge + new nonce**.

**State enum:**
`UNSEEN` (absent) → `ACCEPTED_PREPARED` → `LEASE_READY` → `EXECUTION_STARTING` →
`EXECUTING` → `COMPLETED`; terminal `BLOCKED`, `FAILED`, `RECOVERY_REQUIRED`.

**Outbox sequence (exact):**
1. Verify the signed challenge (§4.1) and the bound registry snapshot (§4.2) — root sig,
   exact-document handle, full key-validity predicate (§7).
2. Read the supervisor clock **exactly once** → `challenge_accepted_at_ms`.
3. Validate the window + revocation using that exact value (§1, §7).
4. **One DB transaction:** CAS insert `absent → ACCEPTED_PREPARED` (the three UNIQUE
   constraints enforce the CAS); reserve `execution_attempt_id`; persist every authoritative
   binding (challenge/registry/context/`challenge_accepted_at_ms`); compute and persist the
   **exact canonical lease payload bytes** (`lease_payload_bytes` + `lease_payload_sha256`).
5. **Commit.**
6. **Idempotently sign + atomically publish** that exact persisted lease document
   (create-if-absent under `lease_handle = SHA256(JCS({payload,signature}))`; an existing
   identical handle is idempotent success).
7. CAS `ACCEPTED_PREPARED → LEASE_READY` **only after** the lease document exists in the
   store and **re-hashes + re-verifies** (`validate_governed_turn_lease`), recording
   `lease_handle`.
8. **Execution is forbidden before `LEASE_READY`.**
9. Persist `LEASE_READY → EXECUTION_STARTING` **before** launching the recorder/executor.
10. A crash after `EXECUTION_STARTING`/`EXECUTING` but before a terminal proof **MUST NOT
    auto-re-execute** side-effecting work: recovery inspects durable process/cgroup/receipt
    state; if it cannot prove the run neither started nor produced effects, it transitions to
    `BLOCKED`/`RECOVERY_REQUIRED` (fail-closed), never a silent re-run.
11. A `COMPLETED` retry returns **only** the same attempt's independently re-verified
    terminal record/result (idempotent).
12. A failed or conflicting retry **never** creates a new attempt.

**Crash recovery at every cut point** (each maps to a durable state):
before acceptance commit → nothing persisted, clean retry; after commit before signature →
`ACCEPTED_PREPARED`, re-sign from `lease_payload_bytes` (deterministic); after signature
before publish → publish is create-if-absent, idempotent; after publish before `LEASE_READY`
→ re-hash/re-verify then advance; after `LEASE_READY` before `EXECUTION_STARTING` → safe to
launch; after `EXECUTION_STARTING` before child creation → recovery checks for a child, none
⇒ may relaunch **only if** no output/receipt exists, else BLOCKED; after child before
`EXECUTING` persistence → treat as in-flight, do not relaunch, BLOCKED/RECOVERY_REQUIRED;
during execution → same; after receipt/evidence before terminal record → re-drive record
signing from verified artifacts (idempotent create-if-absent); after terminal record before
ledger `COMPLETED` → set `COMPLETED` from the existing verified record.

**Negative tests (normative):** concurrent duplicate submissions (exactly one
`ACCEPTED_PREPARED` + one attempt; losers get the idempotent result, never a 2nd execution);
same-nonce/different-challenge (refused); same-challenge/different-nonce (refused);
conflicting `run_id`/`task_id` on retry (refused); crash-retry at each cut point; and
mid-execution recovery that must NOT re-execute.

**Relationship to the desktop nonce (both hold):** the desktop's `request_nonce`
compare-and-consume in `verify_and_record_receipt` still governs final **receipt**
acceptance (whole-turn replay + `receipt_id` uniqueness, §7); the supervisor ledger above
governs **execution** replay. Neither substitutes for the other.

---

## 6. Atomic publish order (who signs what they published)

1. **Supervisor publishes, before execution:** the signed challenge document
   (`challenge_handle`), the accepted registry snapshot (`challenge_registry_handle`) under
   the crash-consistent publish→floor sequence (§7 anti-rollback), the three input artifacts
   + `policy_bundle`, and the governed-turn lease (`lease_handle`, §5 step 6). All are
   content-addressed create-if-absent (temp→fsync→verify size+sha256→exclusive publish).
2. **Recorder publishes what IT owns + signs over those handles:** the exact `output` bytes
   (`output_handle`) + the containment artifact (`containment_evidence_sha256`), then signs
   the `brops.governed-turn-execution-receipt.v1` (§4.7) + the containment-confirmed evidence
   event + head (evidence-recorder key).
3. **Supervisor verifies the recorder chain by handle** (`verify_governed_turn_receipt`;
   `load_head`+`validate_chain`; containment cross-bind) and **signs the terminal record**
   (`governed-turn-recorder` key) binding every verified handle/id/hash + the ledger's
   `challenge_accepted_at_ms` — never a caller input.
4. **Atomic terminal write:** temp→fsync→`os.link`/`O_CREAT|O_EXCL` into
   `<run_id>__<execution_attempt_id>.json`; `EEXIST` ⇒ byte-compare (identical=idempotent,
   differ=refuse); fsync dir. A crash before this leaves no record ⇒ Block; after ⇒ a
   complete re-verifiable record and ledger `COMPLETED`.

Store ACL: writable only by supervisor (its artifacts) + recorder (output/containment);
executor/sidecar have no write and no key read.

---

## 7. Verification — `LiveRunStateProvider` (all cross-bindings)

`verify_artifact(record, "brops.governed-turn-record.v1")` first (a forged/edited record
fails here — no unsigned JSON is authority), then require, all fail-closed:

- **Lease:** `verify_artifact` + `validate_governed_turn_lease` (§4.3, NOT the base
  validator); record `lease_id`/`lease_nonce`(==lease `nonce`)/`challenge_accepted_at_ms` +
  challenge/registry bindings equal the lease's; `allowed_capabilities ==
  ["INVOKE_GOVERNED_MODEL"]`, `max_tool_calls == 0`.
- **Challenge:** fetch by `challenge_handle`, verify `sig` under the key resolved from the
  bound registry snapshot; recompute `request_sha256`; the challenge's identities/`*_sha256`/
  `requested_at_ms` equal the record's. The challenge does **not** contain
  `challenge_accepted_at_ms`.
- **Registry snapshot:** fetch the exact signed document by `challenge_registry_handle`,
  re-hash the full document (`== challenge_registry_handle`), verify `root_sig` over
  `JCS(payload)` under the pinned `challenge_registry_root_key_id`, recompute `registry_hash
  == challenge_registry_hash`, `registry_epoch == challenge_registry_epoch`; then the **full
  key-validity predicate as of `challenge_accepted_at_ms`**: `challenge_key_id` present
  exactly once, `public_key` schema valid, `key_epoch` accepted,
  `valid_from_ms ≤ challenge_accepted_at_ms ≤ valid_to_ms`,
  `revoked_at_ms IS NULL OR revoked_at_ms > challenge_accepted_at_ms`, and the challenge
  `sig` valid under that exact snapshot key — presence alone is insufficient.
- **Temporal (as-of-acceptance, never wall-clock now):** `requested_at_ms ≤
  challenge_accepted_at_ms` and `challenge_issued_at_ms ≤ challenge_accepted_at_ms ≤
  challenge_expires_at_ms`; a record in-window stays valid forever.
- **`challenge_accepted_at_ms` equality chain (supervisor-authoritative only):** byte-equal
  across `brops.governed-turn-lease.v1` → `brops.sign-request.v1` attestation →
  `brops.sign-result.v1` → bridge result → record. It is **not** a challenge field.
- **Receipt/output:** `verify_governed_turn_receipt`; `output_sha256 == output_handle ==
  SHA256(exact output bytes)`; receipt/attempt/lease ids match.
- **Containment:** the containment artifact's run/attempt/lease/runner equal the record's,
  `contained==true`, its evidence event `payload_hash == containment_evidence_sha256`.
- **Evidence head + anti-rollback:** the head fields are authenticated via the supervisor
  attestation (§4.4) and checked against the **desktop** `evidence_head_floor(install_id,
  task_id, highest_sequence, final_event_hash)` inside the Wave-3a
  `verify_and_record_receipt` `BEGIN IMMEDIATE` tx (per-(install,task) chain; strictly-greater
  advances, `<` or `==`-with-different-hash refused).
- **Whole-turn replay:** desktop one-time `request_nonce` compare-and-consume + `receipt_id`
  global uniqueness.
- **Registry anti-rollback (supervisor side, crash-consistent):** verify full signed
  registry → create-if-absent publish exact doc + fsync file&dir → durable floor tx persists
  `(highest_registry_epoch, registry_hash, challenge_registry_handle, root_key_id)` → the
  floor is never usable unless its snapshot exists + re-hashes → same-epoch/different-hash +
  divergent-handle refused; startup verifies the floor's snapshot before use, else
  fail-closed.

`RunState` is built from the verified signed record only.

---

## 8. Authorities (governed-turn functions only)

- **Lease:** `issue_governed_turn_lease` (governed-turn lease issuer) +
  `validate_governed_turn_lease` (§4.3). The base `issue_lease`/`validate_execution_lease`
  are **NOT** used for this path (a governed-turn lease presented to the base validator is
  refused).
- **Terminal record:** the dedicated **`governed-turn-recorder`** authority signs **only**
  `brops.governed-turn-record.v1` (add `GOVERNED_TURN_RECORDER` to `bro_signature`
  `AUTHORITY_TYPES` / `broctl` key classes; map it in `ARTIFACT_AUTHORITY`; owner-only key at
  the supervisor boundary; it MUST NOT sign `evidence-event`/`evidence-head`/any lease, and
  `verify_artifact` refuses a record signed by any other authority).
- **Receipt + evidence:** `brops.governed-turn-execution-receipt.v1` and the containment/
  evidence events/head are signed by the **evidence-recorder runner** and verified by
  `verify_governed_turn_receipt` (NOT the generic `bro_run_receipt.run_and_sign` /
  `verify_passing_receipt`).
- **Challenge:** the dedicated `desktop-challenge-authority` (its own principal/UID; §5 P0-1).
- **Registry root:** the binary-pinned challenge-root anchor (separate from the receipt keys).
- **Authority separation is total:** no authority may sign another class's artifact
  (Appendix B authority matrix).

---

## 9. Acceptance criteria (for 3b-1B implementation, AFTER Architect design-GREEN)

Positive: a real desktop→sidecar→supervisor(accept+execute+record)→signer E2E yielding a
`signed` governed-result whose receipt binds the exact request + output; the Linux isolation
job's positive control uses a genuinely-executed record. Negative matrix: forged/edited
record; replayed old evidence head; output/containment/nonce not matching the signed
artifacts; missing lease/receipt; the §1/§2/§5/§7 negative tests (mixed-unit timestamps,
capability overgrant, ledger replay/conflict, crash-cut recovery, historical key-validity,
transport-only echo mismatch). Engine + isolation exact-head CI GREEN. **STOP unchanged:**
`NoTrustedManifest`, no production "Verified".

---

## Appendix A — NON-NORMATIVE revision history (does not define current contracts)

The current normative design is §0–§9 above. This log is historical only.
- **rev 1–5:** initial 3b-1B design-lock, closing Architect REDs on topology, oracle removal,
  containment binding, ingress, launcher TCB, schema de-dangling.
- **rev 6:** dedicated `desktop-challenge-authority`; challenge binds run/task; fixed input
  delivery; one bounded ingress; challenge bound in record.
- **rev 7:** authority builds challenge from trusted DB (no caller bytes); canonical launcher
  FD table; supervisor publishes signed challenge; self-contained challenge-key registry;
  as-of-run historical verification.
- **rev 8:** dedicated-principal pending-store + direct-file-mutation CI denial; supervisor
  `challenge_accepted_at`; full registry trust contract; read-only regular-file input FDs.
- **rev 9:** registry payload-hash vs exact-document handle split; crash-consistent
  snapshot-publish→floor; full historical key-validity predicate; (attempted) signed
  `challenge_accepted_at` schema.
- **rev 10:** supervisor atomic challenge consumption (first cut); governed-turn-lease as a
  "superset" (had unit/field conflicts + an impossible challenge equality).
- **rev 11 (this doc):** one-pass consolidation — canonical ms time model; dedicated durable
  acceptance state machine + outbox; closed `governed-model-turn-v1` capability profile; exact
  relay schemas + transport-only echoes; §8 governed-turn functions; single artifact matrix as
  the source of truth; revision history demoted to this appendix.

## Appendix B — consistency-audit matrices (verification aids, non-normative)

- **Authority matrix:** challenge-authority→challenge only; challenge-root→registry only;
  lease-issuer→leases only; evidence-recorder→receipt/containment/evidence only;
  governed-turn-recorder→terminal record only; supervisor-attestation→attestation only;
  isolated-signer→receipt envelope only. No overlap.
- **Handle matrix:** every `*_handle` = `SHA256(JCS({payload,sig}))` of the exact stored doc;
  every `*_hash`/`*_sha256` is a payload/identity digest, never used as a store handle.
- **Time matrix:** all governed-turn fields `_ms` integer; base lease `*_epoch` (seconds)
  untouched and unused here.
- **Replay matrix:** challenge `request_nonce` (one-time) + supervisor acceptance ledger
  (execution) + lease `nonce` + `receipt_id` (global) + `execution_attempt_id` (unique) +
  `registry_epoch`/`registry_hash` + evidence-head floor.
- **Capability matrix:** executor = `INVOKE_GOVERNED_MODEL` only; `max_tool_calls=0`; no
  builder grants; launcher digest + model profile pinned.

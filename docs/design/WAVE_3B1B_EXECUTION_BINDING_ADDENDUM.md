# Wave 3b-1B — authoritative execution→receipt binding · ARCHITECT ADDENDUM (design-lock, rev 4)

> **DESIGN-ONLY.** No 3b-1B code ships until this addendum is Architect-GREEN. Builds on
> the Architect-GREEN Wave 3b design ([`WAVE_3B_ISOLATED_SIGNER_DESIGN.md`](./WAVE_3B_ISOLATED_SIGNER_DESIGN.md))
> and the 3b-1 re-scope map ([`WAVE_3B1_EXECUTION_BINDING_MAP.md`](./WAVE_3B1_EXECUTION_BINDING_MAP.md)).
> Closes the 2nd code-audit finding: an **unsigned pre-written run record must never be
> signing authority**. Reuses the existing lease / containment / receipt / evidence
> authorities — **no parallel executor**. **STOP unchanged:** `NoTrustedManifest`, no
> production "Verified". 3b-2 does not start until 3b-1 is exact-head GREEN + merged.
>
> **rev 2** closes the Architect design RED on rev 1: **P0-1** the contained model
> executor holds NO signing key — a dedicated evidence-recorder RUNNER (separate OS
> identity) signs the receipt/evidence (§2); **P0-2** the governed-turn runner captures
> the reply in **binary** mode and hashes the EXACT bytes with NO CRLF/decode/trim
> normalization, via a **governed-turn-specific** receipt (§2, §3); **P1-3** the
> terminal-record authority is LOCKED to a **dedicated `governed-turn-recorder`** that
> cannot sign receipts/evidence-heads (§8); **P1-4** the record write is idempotent
> **create-if-absent** (O_EXCL + byte-identical re-check), not a clobbering rename (§4);
> **P1-5** the **supervisor** atomically reserves/generates `execution_attempt_id` (the
> desktop never supplies it) (§2.5); **P1-6** the evidence-head anti-rollback floor's
> owner + transaction semantics are locked (§6).
>
> **rev 3** closes the design RED on rev 2: **P0-1** recorder runner + model executor are
> **different OS principals** (dedicated UIDs, ptrace/key-dir denial, explicit output
> channel), machine-tested in Linux CI (§2); **P0-2** the recorder runner is itself the
> execution + containment **observer** (measures `contained` at teardown — no
> `sign(caller_claim)` oracle) (§2); **P1-3** §3 now signs with the dedicated
> `governed-turn-recorder` — no evidence-recorder alternative remains (§3, §8); **P1-4** a
> normative `brops.governed-turn-execution-receipt.v1` schema + dedicated verifier replaces
> the generic CRLF-normalizing receipt (§3.5, §4); crash-recovery wording aligned to
> create-if-absent (§6).
>
> **rev 4** closes the design RED on rev 3: **P0-1** one non-contradictory executor lifecycle owner — the supervisor launches the recorder runner; the recorder starts the executor under a different UID via a **narrow privileged launcher** (setuid-only, holds no key) and owns the pidfd/cgroup + teardown, so signing-capability and setuid-capability live in separate principals (§1, §2); **P1-2** the evidence-head floor is keyed **per (install, task/chain)**, not per-install (§6); **P1-3** the supervisor request carries the **exact** system/history/generation_config bytes + challenge, and the supervisor recomputes the three hashes and refuses on mismatch before reserving/executing (§2.5); **P1-4** a normative `brops.governed-turn-containment.v1` artifact binds run/attempt/lease/runner + cgroup + the measured `contained`, hashed into a containment-confirmed evidence event and cross-bound by the verifier (§3.6).

## 1. The governed AI turn IS a `bro_supervisor`-owned supervised execution

Today the governed AI turn (desktop `system`/`history` → model reply) runs in the sidecar
and is NOT lease-owned or receipted. 3b-1B moves it under the existing supervisor, with a
**single, non-contradictory lifecycle owner** (P0-1):

- The **supervisor** (`bro_supervisor.run_task` path) **issues the execution-lease**
  (`issue_lease`, issuer authority) and **launches the evidence-recorder runner** (under
  the recorder UID). The supervisor owns the lease + signs the governed-turn-record; it
  does **not** itself spawn the model executor or measure containment.
- The **evidence-recorder runner** owns the executor lifecycle + containment: it starts
  the model executor (via the narrow privileged launcher, §2) under the *executor* UID,
  owns its `pidfd`/cgroup + the output pipe, and performs the teardown + firsthand
  `contained` measurement (reusing `bro_supervisor`'s group-stop machinery). The turn is
  `COMPLETED` only under the existing rule: `not timed_out AND contained AND exit_code == 0`.

No new executor is invented: the model executor is the `builder_command` for this run,
spawned + contained exactly as any builder — but under the runner (§2 topology), not the
supervisor.

## 2. Key-custody topology + EXACT output bytes (P0-1, P0-2)

**Topology (P0-1) — the contained model executor holds NO signing key:**

```
supervisor  (recorder-launcher UID; owns the lease; signs the governed-turn-record
             via the dedicated governed-turn-recorder key, §8)
  → EVIDENCE-RECORDER RUNNER   (dedicated recorder UID; holds the evidence-recorder
        key; signs the execution receipt + evidence chain; owns the executor's
        pidfd/cgroup + output pipe + teardown measurement)
      → NARROW PRIVILEGED LAUNCHER   (a tiny setuid helper: its ONLY job is to drop to
            the executor UID + exec the model executor in a fresh cgroup/process group;
            holds NO signing key; no other capability)
          → CONTAINED MODEL EXECUTOR   (executor UID; NO signing key/path in its env or
                tree; writes ONLY its reply bytes to the recorder's output pipe)
      ← recorder reads the exact reply bytes, measures `contained` at teardown
  ← the runner returns the signed governed-turn execution receipt + evidence head
```

**Why a launcher (P0-1):** a dedicated recorder UID cannot itself `setuid` to a different
executor UID without a privileged capability. Rather than give the recorder `CAP_SETUID`
(broad forgery/impersonation power **and** it holds the evidence key), the recorder
`exec`s a **narrow privileged launcher** whose sole function is `setuid(executor) + exec`
in a fresh cgroup/process group. The launcher holds **no signing key** and does nothing
else; the recorder keeps ownership of the child's `pidfd`/cgroup + the output pipe (so it
still measures containment firsthand), while the *signing capability* and the *setuid
capability* live in **separate** principals. Neither the executor nor the launcher can
read a signing key.

**Principal separation is an OS-identity boundary, LOCKED (P0-1) — a process group is NOT
custody:**
- the **evidence-recorder runner** runs under its **dedicated recorder UID** (holds the
  evidence-recorder key in an owner-only dir; is NOT privileged/`CAP_SETUID`);
- the **model executor** runs under a **different unprivileged executor UID**;
- the executor principal is **denied read + list** on the recorder key directory and
  **cannot `ptrace`/debug** the recorder process (distinct UID + `ptrace_scope`/no shared
  debug rights) — it can read neither the key file nor the recorder's process memory;
- the runner→executor channel is the recorder-owned **output pipe** (the executor writes
  only its reply bytes to a fixed handle the recorder reads); the executor never touches
  the store or the keys;
- **Machine-tested:** the Linux `engine-isolation` job extends to prove the executor
  principal cannot read the recorder key dir nor `ptrace` the recorder (same dedicated-user
  pattern already used for the signer/supervisor denials).

**Authoritative containment verdict (P0-2) — no `sign(caller_claim)` oracle.** The final
`contained` verdict is known only after teardown; the runner never signs a supervisor
JSON claim. Because the **recorder owns the executor's `pidfd`/cgroup** (via the launcher
above), it performs the teardown/containment measurement itself and *measures* `contained`
firsthand before signing the containment artifact (§3.6) + the execution receipt. The
supervisor owns the lease + the governed-turn-record; the recorder owns the measured
containment; the launcher owns only the `setuid`. No principal signs an unmeasured claim.

**Exact output bytes (P0-2) — a byte-for-byte contract:** the governed-turn runner
1. captures the executor's reply from **stdout in BINARY mode** (`text=False`),
2. stores those **exact bytes** with **no decode / trim / newline (CRLF→LF) normalization**,
3. computes `output_sha256 = SHA256(exact bytes)`,
4. only THEN strict-UTF-8-decodes a copy for rendering.

The existing `bro_run_receipt.run_and_sign` transcript hash CRLF-normalizes (text mode),
so it is **not** byte-for-byte and is insufficient here. 3b-1B introduces a
**governed-turn-specific execution receipt** (a versioned `evidence-event` extension whose
`output_sha256` is over the exact binary bytes) so that **the bytes the desktop renders ==
`output_sha256` == the bytes bound by the signed receipt** — one source of the output, no
normalization drift.

## 2.5 Execution-attempt ownership (P1-5) — the SUPERVISOR reserves it

The desktop **never** supplies `execution_attempt_id`, but it MUST supply the **exact
execution bytes** the executor runs on (the executor needs `system`/`history`/
`generation_config`, not just hashes). Locked supervisor-service request schema
(`brops.governed-turn-request.v1`):

```jsonc
{ "protocol": "brops.governed-turn-request.v1",
  "run_id": "<string>",
  "system": "<exact system prompt bytes>",
  "history": [ { "role": "…", "content": "…" }, … ],
  "generation_config": "<exact generation-config bytes>",
  "request": {                       // the desktop's canonical request envelope (challenge)
    "request_nonce": "<string>", "system_sha256": "<64hex>", "history_sha256": "<64hex>",
    "generation_config_sha256": "<64hex>", "requested_at": "<ms>" } }
```

Flow (P1-3, P1-5):
1. **Recompute-and-bind first.** Before reserving an attempt or executing, the supervisor
   **recomputes** `system_sha256`/`history_sha256`/`generation_config_sha256` from the
   exact `system`/`history`/`generation_config` bytes (the §4.0a formulas) and **refuses**
   if any differs from the `request` envelope — the challenge is bound to the exact bytes,
   never trusted.
2. the **supervisor atomically reserves/generates** `execution_attempt_id` for that
   `run_id` (durable, one-time — a `run_id` cannot yield two live attempts racing);
3. the executor runs on the **verified exact bytes**; the reserved `execution_attempt_id`
   + the verified request hashes are **bound into** the signed governed-turn-record + the
   execution receipt;
4. the caller **cannot choose an arbitrary pre-existing attempt** — the supervisor owns
   the attempt namespace and returns `{execution_attempt_id, governed-result}`.

This removes the 3b-1A/3b-1B contradiction (the sidecar was requiring a desktop-supplied
attempt): the desktop sends the exact bytes + challenge + `run_id`; the supervisor
verifies, reserves, executes, signs, and returns the attempt id.

## 3. `brops.governed-turn-record.v1` — the ONLY signing authority (exact signed schema)

Signed by the **dedicated `governed-turn-recorder`** authority (§8 — NOT the
evidence-recorder), `verify_artifact`-checkable, written atomically (create-if-absent, §4)
to the protected state dir as `<run_id>__<execution_attempt_id>.json`.

```jsonc
{ "payload": {
    "artifact_type": "brops.governed-turn-record.v1",
    "key_id": "<governed-turn-recorder key id>",
    "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>",
    // lease binding (== the verified execution-lease)
    "lease_id": "<string>", "lease_nonce": "<string>",
    "task_id": "<string>", "agent_id": "<string>", "session_id": "<string>",
    "workspace_id": "<string>", "install_id": "<string>", "supervisor_id": "<string>",
    "executor_id": "<string>", "builder_id": "<string>",
    // exact request binding (== the desktop-issued canonical request envelope, design §2.2)
    "request_nonce": "<string>",
    "system_sha256": "<64hex>", "history_sha256": "<64hex>",
    "generation_config_sha256": "<64hex>", "requested_at": "<ms>",
    // output binding (the exact reply bytes; equals the receipt's transcript/stdout hash)
    "output_sha256": "<64hex>",
    // policy binding
    "policy_id": "<string>", "policy_version": "<string>", "policy_bundle_sha256": "<64hex>",
    // containment binding (== the hash carried by a signed evidence-chain event)
    "containment_evidence_sha256": "<64hex>", "containment_event_id": "<string>",
    // receipt binding (== the verified passing execution receipt)
    "receipt_id": "<string>",
    // evidence-head binding + anti-rollback (== the verified head)
    "evidence_final_event_hash": "<64hex>", "evidence_head_sequence": <int>,
    "completed_at": "<ms>", "issued_at_epoch": <int>
  },
  "signature": "<detached Ed25519 over JCS(payload)>" }
```

All `*_sha256` are lowercase-64-hex; ids are strings; the signature is detached Ed25519
over `JCS(payload)` (the same canonicalizer as every other engine artifact).

## 3.5 `brops.governed-turn-execution-receipt.v1` — the exact-byte receipt (P1-4)

The existing `bro_receipt`/`run_and_sign` is a test-command receipt whose transcript hash
CRLF-normalizes (text mode) — insufficient here. 3b-1B adds a **governed-turn-specific**
receipt with a byte-for-byte output contract, signed by the **evidence-recorder runner**.

```jsonc
{ "payload": {
    "artifact_type": "brops.governed-turn-execution-receipt.v1",
    "key_id": "<evidence-recorder key id>",         // the recorder RUNNER signs
    "run_id": "<string>", "execution_attempt_id": "<string>", "lease_id": "<string>",
    "runner_id": "<string>", "executor_id": "<string>", "builder_id": "<string>",
    "exit_code": 0, "contained": true,
    "output_handle": "<64hex>",        // content-addressed store handle of the exact reply
    "output_sha256": "<64hex>",        // == output_handle == SHA256(exact BINARY reply bytes)
    "started_at_epoch": <int>, "finished_at_epoch": <int>, "issued_at_epoch": <int>
  },
  "signature": "<detached Ed25519 over JCS(payload)>" }
```

- **Signed bytes:** detached Ed25519 over `JCS(payload)`.
- **Output-byte formula (normative):** `output_sha256 = SHA256(exact reply bytes)` where the
  bytes are captured in **binary** with NO decode/trim/CRLF normalization; `output_handle`
  is the content-addressed store handle of those exact bytes (so `output_handle ==
  output_sha256`, and the desktop re-hashes the SAME bytes it renders).
- **Fields/types:** ids are non-empty strings ≤128; `exit_code` an integer (must be `0`);
  `contained` a bool (must be `true`); the two handle/hash fields lowercase-64-hex;
  timestamps integer epochs with `started ≤ finished`.
- **Authority mapping:** `ARTIFACT_AUTHORITY["brops.governed-turn-execution-receipt.v1"] =
  evidence-recorder`; `verify_artifact` refuses any other signer.
- **Verifier contract (dedicated API, not the generic `verify_passing_receipt`):**
  `verify_governed_turn_receipt(document, keys, *, run_id, execution_attempt_id, lease_id,
  output_bytes, now) -> payload` — `verify_artifact` the receipt, require `exit_code == 0`
  and `contained is True`, require the run/attempt/lease ids to match, and require
  `output_sha256 == SHA256(output_bytes) == output_handle`. Any deviation is fail-closed.

## 3.6 `brops.governed-turn-containment.v1` — attempt-bound containment (P1-4)

The existing evidence event binds only `task_id`/`event_type`/`agent_id`/`payload_hash` —
NOT the attempt or lease, so a containment event from another attempt could be cited. 3b-1B
defines an explicit **containment artifact** the recorder produces from its firsthand
teardown measurement (§2), publishes to the content-addressed store, and records as a
**containment-confirmed evidence event** whose `payload_hash` is over this artifact:

```jsonc
{ "artifact_type": "brops.governed-turn-containment.v1",
  "run_id": "<string>", "execution_attempt_id": "<string>", "lease_id": "<string>",
  "runner_id": "<string>", "process_group_id": "<string>",   // or cgroup id
  "contained": true, "teardown_outcome": "<enum: contained|orphan-quarantined|…>",
  "measured_at": "<ms>" }
```

- **Canonical bytes:** `JCS(artifact)`; `containment_evidence_sha256 = SHA256(JCS(artifact))`
  is the store handle and the value in the governed-turn-record.
- **Evidence binding:** the recorder writes a **containment-confirmed** evidence event
  whose `payload_hash == containment_evidence_sha256`, chained + head-anchored as usual.
- **Verifier cross-bind:** `LiveRunStateProvider` requires the containment artifact's
  `run_id`/`execution_attempt_id`/`lease_id`/`runner_id` to **equal** the
  governed-turn-record's, `contained == true`, and the referenced evidence event's
  `payload_hash` to equal `containment_evidence_sha256` — so a containment measurement from
  a different attempt/lease can never be substituted.

## 4. Atomic write / sign / publish order (fail-closed, no partial)

The supervisor, on a `COMPLETED` + verified turn, performs strictly in order:

1. **Verify the executor's artifacts** — `verify_artifact` the lease;
   `verify_governed_turn_receipt` the governed-turn receipt (§3.5: exit 0, contained,
   exact output bytes, run/attempt/lease bound); `load_head` + `validate_chain` the
   evidence. Any failure ⇒ no record (fail-closed).
2. **Publish** the exact artifacts (`system`, `history`, `output`, `generation_config`,
   `containment_evidence`, `policy_bundle`) to the content-addressed store via the §4.0
   atomic publish (temp → fsync → verify sha → atomic exclusive publish under the digest).
3. **Construct** the §3 payload, binding every handle/id/hash from the VERIFIED artifacts
   (not from any caller input).
4. **Sign** the payload with the **dedicated governed-turn-recorder** key (§8) ⇒
   `{payload, signature}`.
5. **Atomically write, idempotent create-if-absent (P1-4):** temp file in the same dir →
   `fsync` the file → `sign`/`verify` → **`os.link` / `O_CREAT|O_EXCL`** into
   `<run_id>__<execution_attempt_id>.json` (create-if-absent, never a clobbering rename).
   On `EEXIST`: read the existing record and **compare byte-for-byte**; identical ⇒
   idempotent success, any difference ⇒ **refuse** (a second, divergent attempt for the
   same `(run_id, attempt_id)` is rejected). Finally `fsync` the directory.

Ordering guarantees: artifacts exist in the store before the record references them (2
before 3); the record is signed before it is visible (4 before 5); a crash before step 5
leaves **no** record (the turn is unattestable ⇒ the desktop Blocks); a crash after leaves
a complete, signed, re-verifiable record. The create-if-absent + byte-compare makes a
re-run idempotent and a divergent overwrite impossible.

## 5. Bindings (each cross-checked by `LiveRunStateProvider`, verifying the SIGNED record)

`LiveRunStateProvider` first `verify_artifact(record, "brops.governed-turn-record.v1")`
(a forged/edited record fails here — no unsigned JSON is authority), then requires:

| Field | Bound to |
|---|---|
| `request_nonce`, `system_sha256`, `history_sha256`, `generation_config_sha256`, `requested_at` | the desktop-issued canonical request envelope (the challenge); the signer recomputes `request_sha256` from these |
| `execution_attempt_id`, `run_id` | the requested handle |
| `lease_id`, `lease_nonce` | the verified execution-lease (`verify_artifact` + `validate_execution_lease`) |
| `policy_id`, `policy_version`, `policy_bundle_sha256` | the operator-authorized policy (the signer re-checks bundle digest, P1-7) |
| `containment_evidence_sha256` + `containment_event_id` | the `brops.governed-turn-containment.v1` artifact (§3.6) whose `run_id`/`execution_attempt_id`/`lease_id`/`runner_id` equal the record's + `contained==true`, recorded as a containment-confirmed evidence event whose `payload_hash == containment_evidence_sha256` |
| `receipt_id`, `output_sha256` | the verified governed-turn execution receipt (§3.5): receipt/attempt/lease ids match; the exact output bytes re-hash to `output_sha256 == output_handle` (binary, no normalization) |
| `evidence_final_event_hash`, `evidence_head_sequence` | the verified evidence head, with the sequence **≥ a durable per-install high-water mark** (anti-rollback) |

The `RunState` is built from the **verified signed record** only.

## 6. Replay / idempotency + crash-recovery

- **Whole-turn replay:** the desktop's one-time `request_nonce` (migration 0014, durable)
  is compare-and-consumed at verify time; a completed turn's receipt cannot be re-accepted
  (`receipt_id` global uniqueness). The signed record's `request_nonce` must equal the
  desktop challenge.
- **Evidence-head rollback floor — owner + transaction (P1-6, LOCKED):**
  - **Authority + scope (P1-2):** a durable high-water mark **per evidence chain** in the
    desktop's SQLite (`brops-core`) —
    `evidence_head_floor(install_id, task_id, highest_sequence, final_event_hash,
    PRIMARY KEY (install_id, task_id))` (equivalently keyed by the chain's immutable
    `chain_id`). The floor is **per (install, task/chain)**, NOT per-install: each task is a
    separate evidence chain whose `head_sequence` restarts, so an install-wide row would
    wrongly flag task B's sequence 1 as a rollback of task A's sequence 5. The DESKTOP is
    the anti-rollback authority (the verifier of record), not a loose engine-side file.
  - **Who updates:** the **desktop verify transaction** reads + checks + advances the floor
    **inside the same `BEGIN IMMEDIATE` transaction** that consumes the nonce and persists
    the attempt (the Wave-3a `verify_and_record_receipt` tx) — so acceptance and the floor
    advance are one atomic unit. The engine supervisor never writes the desktop floor.
  - **CAS / concurrency:** single-writer under `BEGIN IMMEDIATE`; a record with
    `evidence_head_sequence < highest_sequence`, or `== highest_sequence` with a different
    `final_event_hash`, is **refused**; a strictly-greater sequence advances the floor.
  - **Crash sync:** the floor advance and the accepted-attempt row commit together; a crash
    before COMMIT leaves both unchanged (the turn Blocks); after COMMIT both are durable and
    consistent — a stolen older signed head can never be re-accepted.
- **Idempotent record:** the record is keyed by `(run_id, execution_attempt_id)`; a second
  atomic write for the same attempt is allowed only if byte-identical, else refused. The
  content-addressed store is idempotent by construction.
- **Crash recovery:** a crash before the record's create-if-absent publish (§4 step 5) ⇒
  no record ⇒ the turn Blocks (fail-closed; nothing renders). A crash after ⇒ a complete
  signed record that re-verifies on restart. No reconciliation can turn a partial run into
  an accepted one.

## 7. No unsigned JSON is authority (explicit)

The pre-3b-1B code path where `LiveRunStateProvider` trusted a pre-written **unsigned**
record's `system`/`history`/`output`/`nonce`/policy/containment fields is **removed**. The
sole authority is the SIGNED `brops.governed-turn-record.v1` plus the independently-verified
lease / receipt / evidence — every field is cross-checked (§5). An attacker who can write
the state dir but cannot mint the **governed-turn-recorder** signature (§8, its key
owner-only to the recording boundary) cannot forge an accepted run.

## 8. Authorities (no parallel executor) + LOCKED terminal-record authority (P1-3)

**Terminal-record signing authority — LOCKED to a dedicated `governed-turn-recorder`**
(not the evidence-recorder, so the recording boundary does not gain the evidence-recorder's
full receipt/evidence-head forgery capability):
- add `GOVERNED_TURN_RECORDER = "governed-turn-recorder"` to the engine authority types
  (`bro_signature` `AUTHORITY_TYPES` / `broctl` key classes);
- map `brops.governed-turn-record.v1` in `ARTIFACT_AUTHORITY` to **only** this authority;
- its private key lives at the supervisor/recording boundary (its own owner-only custody),
  distinct from the evidence-recorder and issuer keys;
- it can sign **only** the governed-turn-record — it MUST NOT be an allowed signer for
  `evidence-event`, `evidence-head`, or `execution-lease`. `verify_artifact` therefore
  refuses a governed-turn-record signed by any other authority, and refuses a
  receipt/evidence-head signed by the governed-turn-recorder.

**Reused authorities (unchanged):**
- **Lease:** `bro_supervisor.issue_lease` (issuer) + `bro_execution_lease.validate_execution_lease`.
- **Containment:** `bro_supervisor.spawn_builder`'s process-group containment verdict + the
  containment evidence event.
- **Receipt + evidence:** signed by the **evidence-recorder RUNNER** (§2), not the model
  executor — `bro_run_receipt.run_and_sign` (governed-turn variant, exact-byte
  `output_sha256`, §2) + `bro_evidence` chain/head, verified by
  `bro_receipt.verify_passing_receipt` / `bro_evidence`.

## 9. Acceptance (for 3b-1B implementation, after this addendum is GREEN)

Positive: a real desktop→sidecar→supervisor(execute+record)→signer E2E yielding a `signed`
governed-result whose receipt binds the exact request + output; the Linux isolation job's
positive control uses a genuinely-executed record. Negative: forged/edited record, replayed
old evidence head, output/containment/nonce not matching the signed artifacts, missing
lease/receipt — all fail-closed. Engine + isolation exact-head CI GREEN.

**Ask:** Architect-GREEN on (a) the AI-turn-as-supervised-execution topology (§1–§2),
(b) the `brops.governed-turn-record.v1` schema + atomic order (§3–§4), (c) the binding +
anti-rollback + replay/crash model (§5–§6), and (d) the authority for signing the terminal
record (§8) — before any 3b-1B code.

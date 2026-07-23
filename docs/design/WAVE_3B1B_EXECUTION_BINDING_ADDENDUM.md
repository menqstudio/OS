# Wave 3b-1B — authoritative execution→receipt binding · ARCHITECT ADDENDUM (design-lock, rev 2)

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

## 1. The governed AI turn IS a `bro_supervisor`-owned supervised execution

Today the governed AI turn (desktop `system`/`history` → model reply) runs in the sidecar
and is NOT lease-owned or receipted. 3b-1B moves it under the existing supervisor:

- The **supervisor** (`bro_supervisor.run_task` path) **issues an execution-lease**
  (`issue_lease`, issuer authority) for the turn and **spawns the governed-turn executor
  as a contained builder** (`spawn_builder` — its own process group, the lease injected
  into the child env only, timeout + `contained` enforcement). The turn is `COMPLETED`
  only under the existing rule: `not timed_out AND contained AND exit_code == 0`.
- The supervisor **observes** the run; it does not itself invoke the model. It owns the
  lease, the containment verdict, and the terminal-record signing.

No new executor is invented: the governed-turn executor is the `builder_command` for this
run, spawned + contained exactly as any builder.

## 2. Key-custody topology + EXACT output bytes (P0-1, P0-2)

**Topology (P0-1) — the contained model executor holds NO signing key:**

```
supervisor  (owns the lease; signs the governed-turn-record via the dedicated
             governed-turn-recorder key, §8)
  → dedicated EVIDENCE-RECORDER RUNNER  (separate OS identity; holds the
        evidence-recorder key; signs the execution receipt + evidence chain)
      → CONTAINED MODEL EXECUTOR  (a builder under spawn_builder; own process
            group; NO signing key or key path in its env/tree)
      ← the executor returns the EXACT reply bytes only
  ← the runner returns the signed execution receipt + evidence head
```

The model executor is `spawn_builder`-contained and is handed only the lease + the
desktop `system`/`history`; it **never** receives the evidence-recorder (or any signing)
private key or path. Signing the receipt/evidence is the **evidence-recorder runner** — a
separate OS identity (the existing engine boundary: the receipt runner holds the evidence
key, not the builder). This matches the current engine security model rather than handing
a builder the forgery-capable evidence key.

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

The desktop **never** supplies `execution_attempt_id`. The final contract:

1. the desktop issues the governed **request challenge** (nonce + `request_sha256`) + the
   `run_id`/`task_id` (its own turn identity); it carries **no** attempt id (the bridge
   `task-request` has no such field — 3b-1A reverted it);
2. the **supervisor atomically reserves/generates** `execution_attempt_id` for that
   `run_id` (a durable, one-time reservation — a `run_id` cannot yield two live attempts
   racing);
3. the reserved `execution_attempt_id` is **returned** to the caller AND **bound into**
   the signed governed-turn-record + the execution receipt;
4. the sidecar (and any caller) **cannot choose an arbitrary pre-existing attempt** — it
   only relays the challenge + `run_id`; the supervisor owns the attempt namespace.

This removes the 3b-1A/3b-1B contradiction (the sidecar was requiring a desktop-supplied
attempt). The supervisor-service protocol becomes `{run_id, request-challenge}` → reserve
→ execute → sign → return `{execution_attempt_id, governed-result}`.

## 3. `brops.governed-turn-record.v1` — the ONLY signing authority (exact signed schema)

Signed by the **evidence-recorder** authority, `verify_artifact`-checkable, written
atomically to the protected state dir as `<run_id>__<execution_attempt_id>.json`.

```jsonc
{ "payload": {
    "artifact_type": "brops.governed-turn-record.v1",
    "key_id": "<evidence-recorder key id>",
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

## 4. Atomic write / sign / publish order (fail-closed, no partial)

The supervisor, on a `COMPLETED` + verified turn, performs strictly in order:

1. **Verify the executor's artifacts** — `verify_artifact` the lease; `verify_passing_receipt`
   the receipt (exit 0, task/candidate bound); `load_head` + `validate_chain` the evidence;
   confirm containment. Any failure ⇒ no record (fail-closed).
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
| `containment_evidence_sha256` + `containment_event_id` | a signed evidence-chain event whose payload hash equals it |
| `receipt_id`, `output_sha256` | the verified passing receipt (receipt id match; output bytes re-hash to the receipt's transcript/stdout hash) |
| `evidence_final_event_hash`, `evidence_head_sequence` | the verified evidence head, with the sequence **≥ a durable per-install high-water mark** (anti-rollback) |

The `RunState` is built from the **verified signed record** only.

## 6. Replay / idempotency + crash-recovery

- **Whole-turn replay:** the desktop's one-time `request_nonce` (migration 0014, durable)
  is compare-and-consumed at verify time; a completed turn's receipt cannot be re-accepted
  (`receipt_id` global uniqueness). The signed record's `request_nonce` must equal the
  desktop challenge.
- **Evidence-head rollback floor — owner + transaction (P1-6, LOCKED):**
  - **Authority:** a durable per-install high-water mark row in the desktop's SQLite
    (`brops-core`), `evidence_head_floor(install_id PK, highest_sequence, final_event_hash)`
    — the DESKTOP is the anti-rollback authority (it is the verifier of record), not a
    loose engine-side file.
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
- **Crash recovery:** a crash before the record's `rename` ⇒ no record ⇒ the turn Blocks
  (fail-closed; nothing renders). A crash after ⇒ a complete signed record that
  re-verifies on restart. No reconciliation can turn a partial run into an accepted one.

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

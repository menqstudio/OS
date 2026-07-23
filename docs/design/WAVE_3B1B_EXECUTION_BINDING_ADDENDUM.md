# Wave 3b-1B — authoritative execution→receipt binding · ARCHITECT ADDENDUM (design-lock)

> **DESIGN-ONLY.** No 3b-1B code ships until this addendum is Architect-GREEN. Builds on
> the Architect-GREEN Wave 3b design ([`WAVE_3B_ISOLATED_SIGNER_DESIGN.md`](./WAVE_3B_ISOLATED_SIGNER_DESIGN.md))
> and the 3b-1 re-scope map ([`WAVE_3B1_EXECUTION_BINDING_MAP.md`](./WAVE_3B1_EXECUTION_BINDING_MAP.md)).
> Closes the 2nd code-audit finding: an **unsigned pre-written run record must never be
> signing authority**. Reuses the existing lease / containment / receipt / evidence
> authorities — **no parallel executor**. **STOP unchanged:** `NoTrustedManifest`, no
> production "Verified". 3b-2 does not start until 3b-1 is exact-head GREEN + merged.

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

## 2. Which component invokes the model + captures the EXACT output bytes

- The **governed-turn executor** (the contained builder) invokes the model through the
  engine's existing isolated `claude` CLI discipline (the same subprocess isolation the
  desktop uses: `--tools ""`, `--strict-mcp-config`, owner-only sandbox, transcript on
  stdin, system prompt via a `0600` file — see `apps/desktop/SECURITY.md`). It reads the
  desktop-provided `system` + `history` (the signing authority) and captures the model's
  **exact reply bytes verbatim** (no trim/normalization), writing them to a fixed artifact
  path inside its sandbox.
- The executor then, using the **evidence-recorder** key, produces the **signed execution
  receipt** (`bro_run_receipt.run_and_sign` — `evidence-event`, `exit_code`,
  `stdout_sha256`/transcript hash over the exact output) and appends the **evidence
  chain** (`bro_evidence`), including a **containment-evidence event**.
- The supervisor captures the executor's exact output bytes (from the fixed artifact) and
  the executor's signed receipt + evidence head. **The bytes the desktop later renders ==
  the bytes hashed into `output_sha256` == the bytes bound by the signed receipt.** There
  is a single source of the output.

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
4. **Sign** the payload with the evidence-recorder key ⇒ `{payload, signature}`.
5. **Atomically write** the record to the state dir: temp file in the same dir → fsync →
   `rename` into `<run_id>__<execution_attempt_id>.json` (never a partial file).

Ordering guarantees: artifacts exist in the store before the record references them (2
before 3); the record is signed before it is visible (4 before 5); a crash before step 5
leaves **no** record (the turn is unattestable ⇒ the desktop Blocks); a crash after leaves
a complete, signed, re-verifiable record.

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
- **Evidence-head rollback:** a durable per-install high-water mark on
  `evidence_head_sequence` is advanced on acceptance; a record citing an older head
  (a stolen earlier signed head) is refused — closing the standing evidence-head-rollback
  threat the engine already documents.
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
the state dir but cannot mint the evidence-recorder signature (its key is owner-only to the
recorder principal) cannot forge an accepted run.

## 8. Reused authorities (no parallel executor)

- **Lease:** `bro_supervisor.issue_lease` (issuer) + `bro_execution_lease.validate_execution_lease`.
- **Containment:** `bro_supervisor.spawn_builder`'s process-group containment verdict + the
  containment evidence event.
- **Receipt:** `bro_run_receipt.run_and_sign` + `bro_receipt.verify_passing_receipt`
  (evidence-recorder).
- **Evidence:** `bro_evidence` chain + head (evidence-recorder).
- **Terminal record signature:** the evidence-recorder key (or a dedicated
  `governed-turn-record` authority added to `ARTIFACT_AUTHORITY`, Architect's call).

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

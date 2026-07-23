# Wave 3b-1 re-scope — implementation map (3b-1A + 3b-1B)

> **STATUS (2026-07-24):** **3b-1A is Architect Code GREEN** (@ `dffd164`, CI #108 8/8);
> **3b-1B is design-lock RED** — the Architect returned Design RED on addendum **rev 6**
> (2 P0 + 3 P1 narrow blockers); **rev 7 is the proposed closure, not yet GREEN, no code**.
> See `NEXT_CHAT.md` §3 for the authoritative current state, STOP gates, and next action.
>
> Owner-directed re-scope after the 2nd code-audit RED (PR #31). The isolated-signer /
> custody work is real but the P0-1/P0-3 chain is not yet an authoritative end-to-end.
> This map identifies the existing execution functions and fixes the **exact** atomic
> terminal-record schema, so 3b-1A then 3b-1B are built against reality, not invented.
> Both parts stay on PR #31. **3b-2 does not start** until 3b-1 is exact-head CI GREEN.

## 0. Where the seam is today

- `engine/tools/brops_live_runstate.py::LiveRunStateProvider` reads a **pre-written,
  unsigned** per-attempt JSON record. It independently verifies the signed lease /
  passing receipt / evidence-chain and now cross-binds `lease_id`/`receipt_id`, but the
  record's `system`/`history`/`output`/`request_nonce`/`containment`/policy fields are
  still taken from that unsigned JSON. **An unsigned record must never be signing
  authority (P0-3).**
- `engine/tools/brops_supervisor_service.py` only *reads + attests*; it does not run or
  observe anything, and the sidecar sends an already-existing `{run_id, attempt_id}` that
  no schema-valid desktop request can carry (`execution_attempt_id` ∉ `task-request`,
  `additionalProperties:false`) — so the production path can't execute (P0-1).

## 1. Existing execution functions (reuse — do NOT invent a parallel executor)

- `engine/tools/bro_supervisor.py::run_task(request, *, repository_root, keydir,
  registry_root, binding_path, builder_command, …)` (`bro_supervisor.py:529`) — the
  lease-owning supervisor. It `authorize_request` → `prepare_worktree` → `resolve_state`
  → **`issue_lease`** (`:602`, signs the `execution-lease`; the returned `lease` dict has
  `lease_id`, `nonce`) → **`spawn_builder`** (`:612`, runs the builder in its own process
  group; returns `code, stdout, stderr, timed_out, contained`) → returns a
  `SupervisorResult(status, message, exit_code, evidence)` where `COMPLETED` requires
  `not timed_out AND contained AND code == 0` (`:654`). `evidence` = the builder's
  `stdout` lines beginning `evidence:` (`:636`).
- `engine/tools/bro_supervisor.py::issue_lease(…)` (`:141`) — signs the `execution-lease`
  (issuer authority). `validate_execution_lease` / `verify_artifact("execution-lease")`
  verify it (`bro_execution_lease.py:94`, `bro_signature.py:620`).
- `engine/tools/bro_run_receipt.py::run_and_sign(command, *, key, task_id, root, …)`
  (`bro_run_receipt.py:93`) — produces the **signed execution receipt** (`evidence-event`,
  evidence-recorder authority; `exit_code`, `stdout_sha256`, `candidate_head/tree`,
  `test_catalog_sha256`). Verified by `bro_receipt.verify_passing_receipt`
  (`bro_receipt.py:132`).
- `engine/runtime/bro_evidence.py` — the signed **evidence chain + head**: `event_hash`
  (`:71`), `load_head` (`:84`), `validate_chain` (`:122`), `EvidenceHead`
  (`final_event_hash`, `last_sequence`, `head_sequence`).
- The **completion gate** (`engine/tests/test_completion_gate.py`) is the existing pattern
  that binds a signed completion manifest + a signed receipt + the evidence chain — the
  model 3b-1B follows for a *governed-turn* terminal record.

**Gap:** `run_task` supervises a **code builder** (worktree + command); the **governed AI
turn** (desktop `system`/`history` → model reply `output`) is NOT run through it, and
nothing emits a single signed record binding the turn's request + output to the
lease/receipt/evidence. 3b-1B closes exactly that, reusing `issue_lease` /
`spawn_builder` / `run_and_sign` / `bro_evidence` — no parallel executor.

## 2. The atomic terminal record (the ONLY signing authority) — `brops.governed-turn-record.v1`

Emitted **atomically** by the lease-owning supervisor at the end of a `COMPLETED`
governed turn, **signed** (evidence-recorder authority, `verify_artifact`-checkable), and
written to the protected state dir under `<run_id>__<attempt_id>.json`. Nothing unsigned
is authority; `LiveRunStateProvider` verifies this record's signature AND cross-checks
every binding against the independently-verified lease / receipt / evidence-head.

```jsonc
{ "payload": {
    "artifact_type": "brops.governed-turn-record.v1",
    "key_id": "<evidence-recorder key id>",
    "run_id": "…", "execution_attempt_id": "…",
    // --- lease binding (== the verified execution-lease) ---
    "lease_id": "…", "lease_nonce": "…",
    "task_id": "…", "agent_id": "…", "session_id": "…",
    "workspace_id": "…", "install_id": "…", "supervisor_id": "…",
    "executor_id": "…", "builder_id": "…",
    // --- exact request binding (== the desktop-issued governed request envelope) ---
    "request_nonce": "…",
    "system_sha256": "<64hex>", "history_sha256": "<64hex>",
    "generation_config_sha256": "<64hex>", "requested_at": "<ms>",
    // --- output binding (the exact reply bytes; also == the receipt's transcript hash) ---
    "output_sha256": "<64hex>",
    // --- policy binding ---
    "policy_id": "…", "policy_version": "…", "policy_bundle_sha256": "<64hex>",
    // --- containment binding (== a signed evidence-chain artifact) ---
    "containment_evidence_sha256": "<64hex>",
    "containment_event_id": "<evidence event carrying this hash>",
    // --- receipt binding (== the verified passing execution receipt) ---
    "receipt_id": "…",
    // --- evidence-head binding + anti-rollback (== the verified head) ---
    "evidence_final_event_hash": "<64hex>", "evidence_head_sequence": <int>,
    "completed_at": "<ms>", "issued_at_epoch": <int>
  },
  "signature": "<detached Ed25519 over JCS(payload)>" }
```

`LiveRunStateProvider` (3b-1B) must, in addition to today's lease/receipt/evidence checks:
1. `verify_artifact(record, "brops.governed-turn-record.v1", trusted_keys)` — the record
   itself is signed; a forged/edited record fails here.
2. `record.lease_id/lease_nonce == verified lease`; `record.receipt_id == verified
   receipt`; `record.evidence_final_event_hash/head_sequence == verified head`, and the
   head sequence is **≥ a durable high-water mark** (anti-rollback of an old signed head).
3. `record.containment_event_id` resolves to a signed evidence event whose payload hash ==
   `containment_evidence_sha256`.
4. `output_sha256` == the receipt's transcript/stdout hash for the run; the RunState's
   `output` bytes re-hash to it.
5. build the `RunState` from the **record** (now a verified signed artifact), never from
   loose unsigned JSON.

## 3. 3b-1A — isolated signing-boundary completion (make the two CI jobs GREEN)

Scope (no execution semantics; the boundary itself):
- **Service-owned socket dirs** — each service binds inside a dir it OWNS (world-
  traversable), so `bind()` succeeds; `SO_PEERCRED` is the connect-time gate. *(done in
  `isolation_proof.sh` + `brops_socket`.)*
- **Shared-store file modes** — published artifacts `0640`, store SETGID `2770`, shared
  `brops-store` group, so the signer principal can read what the supervisor wrote; world
  denied. *(done in `brops_evidence_store` + the script.)*
- **Strict response validation** — the supervisor schema-validates the signer's
  `sign-result`; `attestation.sig` + `sign-result` b64url fields pinned to canonical
  no-pad base64url. *(done.)*
- **Schema-valid request plumbing** — add `execution_attempt_id` to the governed
  `task-request` contract (authoritative, supplied by the desktop's governed request
  context) OR have the supervisor resolve the current attempt; add the E2E below.
- **Positive control BEFORE the denials** — the Linux `engine-isolation` job must first
  run a real allowed supervisor→signer signed round-trip (login→supervisor→signer →
  `signed`), THEN the four denials. A dead signing path must fail the positive control.
- **Engine governance job** — must be exact-head GREEN (diagnose from the CI log; likely
  a Linux-only socket/perm/timing behavior in the new service tests).

Acceptance: `Engine · governance runtime` AND `Engine · signer isolation proof` GREEN at
the exact head, with the positive round-trip proven before the denials.

## 4. 3b-1B — authoritative execution→receipt binding

Scope:
- A supervised **governed-turn execution** that reuses `bro_supervisor` primitives
  (`issue_lease` → run/observe the turn → the builder emits the signed receipt via
  `bro_run_receipt.run_and_sign` + the evidence chain via `bro_evidence`), and on
  `COMPLETED` **atomically emits the signed `brops.governed-turn-record.v1`** (§2) into
  the protected state dir. The exact request/output/containment are bound INTO that signed
  record; the pre-written unsigned JSON is deleted as an input.
- `LiveRunStateProvider` verifies the record's signature + all §2.1–§2.5 cross-bindings;
  a durable evidence-head high-water mark enforces anti-rollback.

Acceptance: a positive desktop→sidecar→supervisor→signer E2E producing a `signed`
governed-result whose receipt binds the exact request + output; negative matrix incl. a
forged/edited record, a replayed old evidence head, and an output/containment that does
not match the signed artifacts. Engine + isolation CI GREEN. **STOP unchanged:**
`NoTrustedManifest`, no production "Verified".

## 5. Order + non-goals

1. This map. 2. 3b-1A (CI GREEN). 3. 3b-1B (authoritative binding). All on PR #31 unless
the Architect finds a review-size reason to split. **3b-2 (desktop manifest/resolver)
does NOT start** until 3b-1 is exact-head zero-trust GREEN and merged.

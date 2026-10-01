# bridge/ 🔗

The integration layer between the desktop **cockpit** (`apps/desktop`) and the governance
**engine** (`engine/`). Slice by slice, this replaces the desktop's direct `claude` spawn
with a **governed** run: the engine's supervisor issues a lease to a separate builder, runs
it behind the wall, and returns a **receipt**. The desktop is a *conductor* and never holds
the lease/key/env.

`bridge`-ը cockpit-ի ու engine-ի ինտեգրման շերտն ա. desktop-ի ուղիղ `claude` spawn-ը փոխարինում ա
governed run-ով (supervisor→lease→wall→receipt). Desktop-ը երբեք lease/key չի պահում։

## Flow (target)
```
Webview → Tauri cmd (Rust) → localhost auth IPC → engine sidecar (Python)
   → engine_adapter.run_governed_turn → bro_supervisor.run_task
     → lease → 🧱 wall → sandboxed AI → {result, verified receipt}
   ← a VERIFIED receipt is mandatory; a failure never carries a result (fail-closed)
```

## What's here now — governed-turn transport + infrastructure (opt-in, default OFF)

> **This is the transport + plumbing, not a completed end-to-end feature.** Real governed turns are
> pending operator provisioning **and** the Wave 3b-1B execution-attempt binding (see below); until
> then every path is **fail-closed** — real mode returns no result at all.

- **`contracts/`** — the request/response contract: `task-request.schema.json` (desktop → sidecar)
  and `bridge-result.schema.json` (`{ ok, result, receipt, error }`, **VERIFIED-receipt-mandatory**).
- **`engine_adapter.py`** (adapter) — `run_governed_turn(request, *, run_task, read_result)`. **Fail-closed** (any error / non-`completed` run → NO result) and **signed-receipt
  mandatory** (a result only with a signed receipt — `envelope_jcs_b64` + `signature_b64` — that the
  DESKTOP verifies; there is deliberately **no** wire `verified` boolean the sidecar could self-assert,
  per `bridge-result.schema.json`). Holds no keys and makes no trust decision — there is no
  `verify_receipt` callable; an unsigned or missing receipt is carried through and the desktop Blocks
  it. Engine core untouched (the adapter only *calls* `run_task`).
- **`engine_sidecar.py`** (sidecar transport) — the process the desktop shells out to: reads one
  request on **stdin**, writes one reply on **stdout**. Always exits 0 (the verdict travels in `ok`);
  every error path is fail-closed. The request now carries an optional top-level **`op`**:
  without one it is the original task-request and the reply is a bridge-result (`run_governed_turn`);
  `op: "governance.read"` routes to the engine's `bro_control_room_api.governance_read` and relays its
  `brops.governance-read.v1` reply **verbatim**, so the three-valued shape survives the hop
  (`ok:true`+records / `ok:true`+`empty:true` / `ok:false`+error — a refusal never carries a `records`
  key). `op: "approval.request"` (`T-021b`) is the one WRITE: it appends one ask to the operator-provisioned
  log named by `BROPS_APPROVAL_REQUEST_LOG_DIR` and can decide nothing. An op this build does not
  implement is refused **by name**, never silently ignored. No op reaches `_real_callables`, the
  supervisor socket, the signer or the builder; the two `protocol`-keyed governed-turn frames
  (submit, output read) are not ops and do reach the supervisor socket.
  Protocol note: [`docs/BRIDGE_SIDECAR_OP_PROTOCOL.md`](../docs/BRIDGE_SIDECAR_OP_PROTOCOL.md).
- **`apps/desktop` `Provider::GovernedEngine`** (desktop provider, `src-tauri/src/ai.rs`) — **opt-in,
  default OFF**; spawns the sidecar (task-request via stdin, bounded reads, deadline, kill-on-drop) and
  **re-enforces** `ok` **and a desktop-verified signature** (recompute JCS + Ed25519 `verify_strict` over
  `envelope_jcs_b64` against a pinned key — never a wire `verified` flag), else fail-closed. The `claude-cli` /
  `anthropic` / `ollama` paths are no longer "byte-for-byte unchanged", as this line said: each now
  refuses unless `BROPS_ALLOW_UNGOVERNED=1` is set.
- **`tests/`** — unit tests (adapter + sidecar + op dispatch). `cd bridge && python -m unittest discover -s tests`.
  The governance route's engine-to-stdout join is covered by `engine/tests/test_governance_sidecar_route.py`.
  Plus 4 Rust tests for the desktop verify-gate + lease-free request shape.

## Activate (opt-in, default OFF)
The governed provider is reached only with **both**:
```
BROPS_AI_PROVIDER=governed-engine
BROPS_ALLOW_GOVERNED_ENGINE=1
```
Without the allow flag the desktop does **not** fall back to anything: `resolve_provider`
(`apps/desktop/src-tauri/src/ai.rs`) returns the error `BROPS_AI_PROVIDER=governed-engine requires
BROPS_ALLOW_GOVERNED_ENGINE=1`. With the allow flag and no provider forced, the governed engine is
selected. An ungoverned provider is never a default — each needs `BROPS_ALLOW_UNGOVERNED=1`, and with
neither flag the resolver refuses (`no AI provider configured`). Override the interpreter / sidecar
path with `BROPS_GOVERNED_PYTHON` / `BROPS_GOVERNED_SIDECAR`.

## Manual smoke (no provisioning needed)
Prove the transport with canned callables (self-test only). The request must carry every field
`contracts/task-request.schema.json` requires — `system`, `history` and `request` as well as the
three this example used to send alone, which the sidecar refuses with `invalid task request: 'system'
is a required property`:
```
REQ='{"task_id":"t-smoke","task_class":"standard-builder","rationale":"say hi","system":"You are Bro.","history":[{"role":"user","content":"say hi"}],"request":{"protocol":"brops.governed-turn.v1","workspace_id":"w","install_id":"i","request_nonce":"n","system_sha256":"","history_sha256":"","generation_config_sha256":"","requested_at":"2026-10-01T00:00:00Z"}}'
echo "$REQ" | python3 bridge/engine_sidecar.py --self-test
# → {"ok": true, "result": "SELF-TEST OK — governed round-trip plumbing verified. rationale=say hi",
#    "receipt": {"task_id": "t-smoke", "status": "completed", …, "envelope_jcs_b64": null, "signature_b64": null, …}, "error": null}
#   The plain self-test produces NO signature: both fields are null, which a desktop Blocks.
#   `--self-test-signed` is the flag that exercises the signer chain.
```
Unprovisioned **real** mode is fail-closed (no result):
```
echo "$REQ" | python3 bridge/engine_sidecar.py
# → {"ok": false, "result": null, "receipt": null, "error": "governed engine not provisioned: missing BRO_KEYDIR, BRO_REGISTRY_ROOT, BRO_BINDING, BRO_REPOSITORY_ROOT, BRO_BUILDER_COMMAND"}
```

The governance mirror (read-only, no execution reachable). Unprovisioned it refuses, and says so:
```
echo '{"protocol":"brops.governance-read.v1","op":"governance.read","surface":"decisionLedger","task_id":null,"read_only":true}' \
  | python bridge/engine_sidecar.py
# → {"protocol": "brops.governance-read.v1", "ok": false, …, "error": "governance mirror not provisioned: BROPS_GOVERNANCE_STATE_DIR …"}
#   note: NO `records` key — "I could not look" can never be read as "I looked and found nothing".
```
With `BROPS_GOVERNANCE_STATE_DIR` pointing at the engine's runtime state directory the same request
returns `ok:true` with `records` (or `records: []` + `empty: true` + an `empty_reason`).

## Real end-to-end (owner-provisioned) — pending
The sidecar refuses real mode while any of five variables is empty: `BRO_KEYDIR` · `BRO_REGISTRY_ROOT` ·
`BRO_BINDING` · `BRO_REPOSITORY_ROOT` · `BRO_BUILDER_COMMAND`. **That is a presence check and nothing
else** — no value of the five is read by anything. In particular `BRO_REGISTRY_ROOT` is **not** the
engine's trusted-key registry root: nothing consumes it, and setting it moves no verification anywhere.
The engine resolves its registry through `bro_signature.resolve_registry_root`, governed by
`BRO_TRUSTED_REGISTRY_ROOT` under custody rules this check does not apply. It also needs
`BROPS_SUPERVISOR_SOCKET`. See `DESIGN.md` §4 Q2.

## ⛔ Security seam — real mode still refuses (🛑)
Real mode deliberately **fails closed even when provisioned**: `_real_callables` raises on every path.
What it waits for is no longer a `verify_receipt` wiring — that callable was removed, and the desktop
is the party that verifies a signature. The blocker its own error names is the Wave 3b-1B
**supervisor-reserved execution attempt** and the authoritative execution→receipt binding. Until that
lands the sidecar never emits a result on the task-request path. The desktop
chat **receipt badge** lights up once the backend populates `message.receipt` (receipt-plumbing, same
follow-up); today the field is absent so the badge stays hidden (no false "verified").

Design + open decisions: [`DESIGN.md`](./DESIGN.md).

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
> pending operator provisioning **and** the verify-seam audit (see below); until then every path is
> **fail-closed** — no result is ever returned without a verified receipt.

- **`contracts/`** — the request/response contract: `task-request.schema.json` (desktop → sidecar)
  and `bridge-result.schema.json` (`{ ok, result, receipt, error }`, **VERIFIED-receipt-mandatory**).
- **`engine_adapter.py`** (adapter) — `run_governed_turn(request, *, run_task, verify_receipt,
  read_result)`. **Fail-closed** (any error / non-`completed` run → NO result) and **signed-receipt
  mandatory** (a result only with a signed receipt — `envelope_jcs_b64` + `signature_b64` — that the
  DESKTOP verifies; there is deliberately **no** wire `verified` boolean the sidecar could self-assert,
  per `bridge-result.schema.json`). Holds no keys — verification is an injected callback; engine core
  untouched (the adapter only *calls* `run_task`).
- **`engine_sidecar.py`** (sidecar transport) — the process the desktop shells out to: reads one
  request on **stdin**, writes one reply on **stdout**. Always exits 0 (the verdict travels in `ok`);
  every error path is fail-closed. The request now carries an optional top-level **`op`**:
  without one it is the original task-request and the reply is a bridge-result (`run_governed_turn`);
  `op: "governance.read"` routes to the engine's `bro_control_room_api.governance_read` and relays its
  `brops.governance-read.v1` reply **verbatim**, so the three-valued shape survives the hop
  (`ok:true`+records / `ok:true`+`empty:true` / `ok:false`+error — a refusal never carries a `records`
  key). An op this build does not implement is refused **by name**, never silently ignored. Ops are
  READS: none reaches `_real_callables`, the supervisor socket, the signer or the builder.
  Protocol note: [`docs/BRIDGE_SIDECAR_OP_PROTOCOL.md`](../docs/BRIDGE_SIDECAR_OP_PROTOCOL.md).
- **`apps/desktop` `Provider::GovernedEngine`** (desktop provider, `src-tauri/src/ai.rs`) — **opt-in,
  default OFF**; spawns the sidecar (task-request via stdin, bounded reads, deadline, kill-on-drop) and
  **re-enforces** `ok` **and a desktop-verified signature** (recompute JCS + Ed25519 `verify_strict` over
  `envelope_jcs_b64` against a pinned key — never a wire `verified` flag), else fail-closed. Existing `claude-cli` /
  `anthropic` / `ollama` paths are byte-for-byte unchanged.
- **`tests/`** — unit tests (adapter + sidecar + op dispatch). `cd bridge && python -m unittest discover -s tests`.
  The governance route's engine-to-stdout join is covered by `engine/tests/test_governance_sidecar_route.py`.
  Plus 4 Rust tests for the desktop verify-gate + lease-free request shape.

## Activate (opt-in, default OFF)
The governed provider is reached only with **both**:
```
BROPS_AI_PROVIDER=governed-engine
BROPS_ALLOW_GOVERNED_ENGINE=1
```
Without the allow flag the desktop falls back to its default provider. Override the interpreter / sidecar
path with `BROPS_GOVERNED_PYTHON` / `BROPS_GOVERNED_SIDECAR`.

## Manual smoke (no provisioning needed)
Prove the transport + the verified-receipt invariant with canned callables (self-test only):
```
echo '{"task_id":"t-smoke","task_class":"standard-builder","rationale":"say hi"}' \
  | python bridge/engine_sidecar.py --self-test
# → {"ok": true, "result": "SELF-TEST OK …", "receipt": {…, "envelope_jcs_b64": "…", "signature_b64": "…"}, "error": null}
#   (the desktop VERIFIES that signature; the sidecar never asserts a `verified` boolean)
```
Unprovisioned **real** mode is fail-closed (no result):
```
echo '{"task_id":"t","task_class":"standard-builder","rationale":"hi"}' | python bridge/engine_sidecar.py
# → {"ok": false, "result": null, "receipt": null, "error": "governed engine not provisioned: …"}
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
A real governed turn needs operator-provisioned state on disk (none may come from the desktop), via env:
`BRO_KEYDIR` (issuer key) · `BRO_REGISTRY_ROOT` (trusted-key registry) · `BRO_BINDING` (signed workspace
binding) · `BRO_REPOSITORY_ROOT` · `BRO_BUILDER_COMMAND` (the AI-under-the-wall). See `DESIGN.md` §4 Q2.

## ⛔ Security seam — pending Architect audit (🛑)
Real mode deliberately **fails closed even when provisioned**: deciding that a `SupervisorResult` carries
a genuine *verified* signed receipt — the `verify_receipt` wiring to the engine's signature/evidence
verification, and `read_result` extraction — is security-critical and is an **Architect-audited
follow-up** (roadmap §G/§I). Until it lands the sidecar never emits an unverified result. The desktop
chat **receipt badge** lights up once the backend populates `message.receipt` (receipt-plumbing, same
follow-up); today the field is absent so the badge stays hidden (no false "verified").

Design + open decisions: [`DESIGN.md`](./DESIGN.md).

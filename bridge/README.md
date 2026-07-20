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

## What's built now (Slices 1–3) ✅
- **`contracts/`** — the request/response contract: `task-request.schema.json` (desktop → sidecar)
  and `bridge-result.schema.json` (`{ ok, result, receipt, error }`, **VERIFIED-receipt-mandatory**).
- **`engine_adapter.py`** (Slice 1) — `run_governed_turn(request, *, run_task, verify_receipt,
  read_result)`. **Fail-closed** (any error / non-`completed` run → NO result) and **VERIFIED-receipt
  mandatory** (a result only with `receipt.verified == true`). Holds no keys — verification is an
  injected callback; engine core untouched (the adapter only *calls* `run_task`).
- **`engine_sidecar.py`** (Slice 2) — the process the desktop shells out to: reads one task-request on
  **stdin**, writes one bridge-result on **stdout**, hosting `run_governed_turn`. Always exits 0 (the
  verdict travels in `ok`); every error path is fail-closed.
- **`apps/desktop` `Provider::GovernedEngine`** (Slice 3, `src-tauri/src/ai.rs`) — **opt-in, default
  OFF**; spawns the sidecar (task-request via stdin, bounded reads, deadline, kill-on-drop) and
  **re-enforces** `ok && receipt.verified` desktop-side, else fail-closed. Existing `claude-cli` /
  `anthropic` / `ollama` paths are byte-for-byte unchanged.
- **`tests/`** — **18** unit tests (10 adapter + 8 sidecar). `cd bridge && python -m unittest discover -s tests`.
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
Prove the transport + the verified-receipt invariant end to end with canned callables:
```
echo '{"task_id":"t-smoke","task_class":"standard-builder","rationale":"say hi"}' \
  | python bridge/engine_sidecar.py --self-test
# → {"ok": true, "result": "SELF-TEST OK …", "receipt": {…,"verified": true}, "error": null}
```
Unprovisioned **real** mode is fail-closed (no result):
```
echo '{"task_id":"t","task_class":"standard-builder","rationale":"hi"}' | python bridge/engine_sidecar.py
# → {"ok": false, "result": null, "receipt": null, "error": "governed engine not provisioned: …"}
```

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

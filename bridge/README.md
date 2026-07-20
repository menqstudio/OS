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
     → lease → 🧱 wall → sandboxed AI → {result, receipt}
   ← receipt is mandatory; a failure never carries a result (fail-closed)
```

## What's here now (Slice 1 — T-003) ✅
- **`contracts/`** — the request/response contract:
  `task-request.schema.json` (desktop → sidecar) and `bridge-result.schema.json`
  (`{ ok, result, receipt, error }`, receipt-mandatory).
- **`engine_adapter.py`** — `run_governed_turn(request, *, run_task, read_result)`.
  Enforces the two invariants (Architect sign-off): **fail-closed** (any error or a
  non-`completed` run → NO result) and **receipt mandatory** (a result is returned only
  with a non-empty receipt). Engine core is untouched — it only *calls* `run_task`.
- **`tests/`** — unit tests pinning both invariants (supervisor dependency-injected, so
  no real keys/leases needed). `cd bridge && python -m unittest discover -s tests`.

## Next slices (not built yet)
- **Slice 2 — sidecar transport:** `engine_sidecar.py`, an operator-provisioned local
  service on `127.0.0.1` with authenticated IPC (bearer token) that holds the provisioning
  (issuer key, trusted-key registry, workspace binding, repo) and wires `run_task` +
  the `builder_command` that runs the AI under the wall.
- **Slice 3 — desktop client:** an opt-in `Provider::GovernedEngine` in `apps/desktop`
  behind `BROPS_AI_PROVIDER=engine` (**default OFF**, existing providers untouched),
  which calls the sidecar over localhost IPC and fails closed without a receipt.

Design + open decisions: [`DESIGN.md`](./DESIGN.md).

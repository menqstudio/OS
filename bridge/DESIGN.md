# Bridge — Design proposal (T-003, Phase 1)

> **Status: APPROVED** — Architect signed off (entrypoint = `bridge/engine_adapter.py`, no engine-core
> change; trust root = operator-provisioned local supervisor sidecar + localhost authenticated IPC;
> contracts in `bridge/contracts/` for now; slice 1 non-streaming; provider default OFF, fail-closed,
> receipt mandatory). **Slice 1 (contract + adapter + tests) is built & verified (8/8).** Slices 2–3 next.
> **Կարգավիճակ՝ ՀԱՍՏԱՏՎԱԾ** — Architect sign-off. Slice 1 (contract + adapter + tests) կառուցված ու verified։

Builder: Claude. Reviewer: ChatGPT (Architect). Approver: Gev (Owner).

---

## 1. The core insight · Գլխավոր insight

The engine's whole design (`engine/tools/bro_supervisor.py`) turns on one rule:

> *"The conductor must never hold the lease. The supervisor issues the lease into a **separate builder's** environment, and returns results + evidence to the conductor — never the lease."*

**The desktop cockpit is a conductor.** Today `apps/desktop/src-tauri/src/ai.rs` (`generate` / `generate_stream`) spawns the `claude` CLI **directly** — ungoverned. The bridge makes the desktop instead **ask the engine's supervisor** to run the AI turn as a governed builder, and receive back the result + a signed receipt. The desktop never holds the lease. This is exactly Bro's intended shape.

## 2. Target flow · Թիրախ flow

```
Webview (React)
  → Tauri command (Rust, ai.rs)
    → bridge adapter (Rust)
      → engine supervisor (Python subprocess: bro_supervisor.py)
        → authorize_request → issue_lease → spawn governed builder
          → 🧱 hook WALL → sandboxed AI turn
        → result + signed receipt + evidence
      ← adapter parses outcome
    ← Tauri command returns result (+ receipt id)
  ← Webview renders
```

**Boundary:** subprocess / sidecar (Rust → `python engine/tools/bro_supervisor.py`), per the resolved decision (matches the engine's CLI/hook model; no PyO3). The desktop passes a **TaskRequest** that carries *no lease, no key, no env* (as `bro_supervisor.TaskRequest` already mandates).

## 3. First vertical slice (this PR, after sign-off) · Առաջին slice

Minimal, **non-destabilizing**, opt-in:

1. **Contract** — define the request/response JSON shape (TaskRequest in → `{result, receipt}` out). Location TBD (see Q3).
2. **Opt-in provider** — add `Provider::GovernedEngine` behind `BROPS_AI_PROVIDER=engine` (**default OFF**). The existing `claude-cli` / `anthropic` / `ollama` paths stay **byte-for-byte unchanged**.
3. **Adapter** — a Rust module (`bridge`/ or in `ai.rs`) that spawns the supervisor for one AI turn and parses the outcome.
4. **Smoke** — prove ONE governed round-trip end to end (or a documented manual smoke if key/lease provisioning is heavy — see Q2). Existing tests stay green.

**Out of scope for slice 1:** ripping out the direct `claude` path, streaming through the governed path, multi-turn runs. Those come after the round-trip is proven.

## 4. Open questions for the Architect · Հարցեր Architect-ին

1. **Supervisor entrypoint.** Does `bro_supervisor.run_task` accept a one-shot AI-turn request over CLI/stdin as-is, or do we add a thin desktop-facing entrypoint? *(If it needs an engine addition, that's a separate audited change — flag it.)*
2. **Issuer key / trust root in a desktop deployment.** The supervisor needs the **issuer key** to sign leases and the operator-pinned trusted-key registry + workspace binding. The desktop must NOT hold these. **Where do they live for a desktop install?** (Operator-provisioned sidecar? A local supervisor service Gev configures?) This is the crux and an Owner/Architect call.
3. **Contract location** — `contracts/` (the eventual shared home) vs `bridge/` for now?
4. **Streaming** — slice 1 non-streaming (result at end) acceptable? The UI streams deltas today; governed streaming is a later slice.

## 5. What I will NOT do without sign-off · Ինչ չեմ անի առանց sign-off

- Touch any engine/security code (supervisor, leases, wall, signatures).
- Change the default AI path or any existing test.
- Provision or hardcode keys.

Once the Architect confirms §3 + answers §4, I build slice 1 on this branch and open a PR (with tests + evidence per the PR template).

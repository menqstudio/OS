## Phase 1 — Bridge · Կամուրջ  🔨 In progress

**Objective.** Route the desktop's AI execution through the engine's supervisor/lease/wall so every AI
turn the cockpit triggers is governed and returns a **verified** signed receipt — replacing the direct,
ungoverned `claude` spawn in `apps/desktop/src-tauri/src/ai.rs`.

**Scope.** In: the `bridge/` adapter, the request/result contracts, an **opt-in** governed provider
(default OFF), and a proven one-turn round-trip. Out (later slices): removing the direct `claude` path,
multi-turn runs. **No engine/security code is touched** — the entrypoint is `bridge/engine_adapter.py`
with no engine-core change (Architect-approved).

**Out — DESCOPED 2026-08-09: governed delta-streaming ("slice 3").** Not deferred; **descoped by
construction**, and the decision is now stated in one place rather than contradicted in three. The
desktop's sole authority over a governed reply is the isolated signer's envelope, which binds
`output_bytes` + `output_sha256` over the **whole** output; there is no per-delta signature and no
contract that could produce one. A streamed delta would therefore be unverified content rendered
*before any verdict exists* — the exact inverse of this phase's rule, "no verified signature ⇒ no
result". The transport says the same thing structurally: the renderer→broker channel is one framed
request and one framed reply (`governed_turn.rs`, `broker/src/main.rs`), and both call a governed turn
**buffered by design**. What remains genuinely open is a *different* thing that was being mistaken for
this one: the rev-30 §4.10(f) chunked **output pull**, which moves the COMPLETED output of a buffered
turn when it is too large to ride the reply frame, checked against that same whole-output digest.
**Its SUPERVISOR hop landed 2026-08-10** in the engine: `brops.governed-turn-output-read.v1` served to
the sidecar principal (`engine/runtime/governed_output_read.py`), the durable `governed_output_streams`
table in the canonical `supervisor_ledger.sql`, and a mint with a real production caller in the §5
`complete-run` op. The `core/src/governed_output_stream.rs` (deleted 2026-08-10, see this cell) ladder that used to be described here — a
one-shot token, TTL tombstone, sweep, per-install cap and nine unit tests, with **zero production
callers** and a table that diverged from the design it cited — was DELETED in that change rather than
wired, because wiring it was a rewrite and because its `CREATE TABLE IF NOT EXISTS` ran on the same
connection one line before `supervisor_ledger::create_schema`. What is STILL open is the DESKTOP hop:
`bridge.governed-turn-output-read.v1` and the internal helper that would drive the loop and apply the
§4.6/§7.1 whole-output digest. The `rust_symbols` section of `config/reachability-declarations.json` is
now empty, and the gate turns RED if a declaration outlives the file it describes.

**Architecture.** Subprocess/sidecar boundary (Rust → `python bro_supervisor`), per the resolved
decision. Trust root = an **operator-provisioned local supervisor sidecar** + localhost authenticated
IPC; the desktop holds **no lease, no key, no issuer**. Flow: `Webview → Tauri ai.rs → bridge adapter →
engine supervisor (authorize → issue lease into a separate builder → 🧱 wall → sandboxed turn) → result +
signed receipt + evidence → adapter verifies → Tauri returns result (+ receipt id)`.

**UI/UX work.** Minimal but real (UI is first-class even here):
- **Governed-provider status control** (Settings). **AMENDED 2026-08-09 — it reports; it does not set.**
- **Receipt indicator on the chat turn**: a small verified-receipt badge on each governed AI message
- Empty/first-run: if no governed turn has run, the badge area shows a one-line HY hint "Governed mode off".

**Backend work.** `bridge/engine_adapter.py` (spawn supervisor for one AI turn, parse outcome, run the
injected verifier, set `verified`) — **done on PR #3** (10/10). Rust (**slice 2, NOT yet implemented**):
add `Provider::GovernedEngine` in `ai.rs` behind the env flag; existing `claude-cli`/`anthropic`/`ollama`
paths stay **byte-for-byte unchanged**. Slice 1 is non-streaming (result at end).

**Contracts / schemas.** `bridge/contracts/task-request.schema.json` and `bridge/contracts/bridge-result.schema.json`
(see §F). `task-request` carries **no lease/key/env**; `bridge-result` is fail-closed + **VERIFIED-receipt-
mandatory** (`result` non-null iff `ok && receipt.verified`).

**Data models.** No shared DB table. The desktop stores the **receipt id** and `verified` flag alongside
the conversation turn (product state); the receipt/evidence themselves live in the engine ledger. IDs
cross the bridge; nothing else.

**Dependencies.** Phase 0. Requires an operator-provisioned supervisor sidecar + issuer key registry +
workspace binding **outside** the desktop (owner/architect provisioning — the crux question, answered:
local sidecar).

**Security gates.** Desktop never holds lease/key/env. Provider default OFF. Fail-closed: any missing
sidecar/lease/receipt → no result. `verified` set **only** after the injected verifier confirms signed
evidence. No engine security code modified (else → audited task).

**Tests.** `bridge/tests/test_engine_adapter.py` — slice 1 **10/10 green** (PR #3, commit `5be8d95`, a `menqstudio/BroPS` id from before the subtree import — it does not resolve in this repository). Cover: request shape rejects
lease/key/env; result fail-closed when `ok=false`; `result` null unless `verified`; verifier-negative →
no result. Existing engine + cockpit suites stay green.

**CI requirements.** Add a **bridge leg** (`cd bridge && BRO_ENV=ci python -m unittest discover -s tests`)
to the workflow; keep it green. A documented manual smoke is acceptable for the full round-trip if
key/lease provisioning is heavy (record the evidence).

**Documentation updates.** `bridge/DESIGN.md` (APPROVED), `bridge/README.md`, this roadmap's Phase-1
status, `PROJECT_STATE.md`. Update the F-index if a contract field changes.

**Acceptance criteria.** One governed AI round-trip proven end-to-end (or documented manual smoke);
`bridge.result` always fail-closed and verified-receipt-mandatory; default path unchanged; all suites +
bridge leg green.

**Merge gate.** Architect sign-off on the adapter + contracts (given for slice 1); bridge tests green;
no engine/security diff; Owner approval.

**Stop conditions.** If the round-trip needs a new engine entrypoint or any supervisor change → **stop**,
flag it as a separate audited engine task; do not edit engine code inside this PR. If key/trust-root
provisioning is unresolved → stop and escalate to Owner/Architect (do not hardcode keys).

> **Nine ticks, six facts — read this before counting.** The Definition of Done and the Task checklist
> restate the same work: the adapter + its 10 tests, the `bridge` CI job, and the badge + provider control
> each appear twice. A reader scanning nine `[x]` boxes saw roughly 50% more delivered than exists.
> Reduced honestly, of the six distinct facts: **two are true and reached** (the `task-request` contract is
> validated at runtime; the `bridge` CI job exists and passes), **two are true but dead** (the adapter and
> the governed-provider transport are built and tested and nothing can invoke them), **one is true but
> hollow** (the UI ships and a user reaches it, but it can only paint a Windows-only demonstration badge),
> and **one was false** (the end-to-end governed round-trip — see its row). Checked against the code on
> 2026-08-10, not against the commit messages the boxes cite.

**Definition of Done.**
- [x] `task-request` + `bridge-result` contracts defined and tested — **but only `task-request` is
- [x] Adapter (`engine_adapter.py`) built; slice-1 tests **10/10** (PR #3, commit `5be8d95`) — re-run
- [x] Opt-in `Provider::GovernedEngine` in desktop `ai.rs` (default OFF) — **transport shipped** (PR #8,
- [ ] One governed round-trip proven end-to-end. **Still open, and an independent auditor has now
- [ ] Governed output delivery through the wall. **Delta-streaming is DESCOPED** (see Scope — a governed
- [x] Bridge CI leg added and green (PR #3, merged to `main`) — job `bridge` at `ci.yml:574-586`, no
- [x] Chat receipt badge + governed-provider status control shipped in the cockpit UI — **shipped and

**Task checklist.**
- [x] T-003 slice 1 — contract + adapter + tests (verified **10/10**, PR #3, commit `5be8d95`). *Same
- [x] Slice 2 — prove one governed round-trip (adapter ↔ real supervisor), record evidence — **done
- [x] Bridge CI leg added to the unified workflow (PR #3, merged `41cf4ff`) — job `bridge`, one of
- [x] Slice 2 — ship the chat verified-receipt badge + Settings governed-provider control (per UI/UX
- [x] Slice 3 — the §4.10(f) chunked output pull — **done 2026-08-12, on a real Linux runner.**
- [ ] Update `PROJECT_STATE.md` + this roadmap when each slice lands. **Standing — never permanently

---

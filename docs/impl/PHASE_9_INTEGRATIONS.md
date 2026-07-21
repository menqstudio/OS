# Phase 9 — Integrations · Implementation Spec

> Blueprint for a cold-start session. Grounds roadmap **Phase 9** (`MASTER_EXECUTION_ROADMAP.md`
> L1135–1211) in the real code. Scope: connect OS to the outside world **through the wall** —
> connectors, inbound events → **governed** tasks, outbound sinks that send **only verified** results,
> and **no external secret ever stored on the desktop** (auth delegated to engine/operator). Ownership:
> 🔨 Builder · 📐 Audit (no-desktop-secret) · 🛑 Gev + Architect security sign-off **before
> implementation** (external boundary, roadmap §G.1 P9). Depends on P7 (group as output surface) + P8
> (automation as trigger source).

## 1. Objective & current state

**Intent.** External input can *start* governed work; governed output can *reach* external sinks —
never ungoverned, never holding external secrets in the desktop.

**What exists today (prototype/mock — a status toggle, nothing external):**
- `apps/desktop/src/features/Integrations.tsx` — lists `Integration{id,name,provider,status}` records
  (`desktop.listIntegrations`) and flips `status` between `connected`/`disconnected` via
  `desktop.setIntegrationStatus`. **No connector runs, no inbound events, no outbound sends, no secrets,
  no health checks.** It is a labelled toggle over a SQLite row.
- IPC boundary `apps/desktop/src/services/desktop.ts`: `listIntegrations`, `setIntegrationStatus`.
- Entity `apps/desktop/src/domain/entities.ts`: `Integration{id,name,provider,status,createdAt,updatedAt}`
  — **no `auth_ref`, no config, no health, and (correctly) no credential column yet.**
- The governed path Phase 9 reuses for inbound work: `apps/desktop/src-tauri/src/ai.rs`
  `Provider::GovernedEngine` → `governed_engine()` → `bridge/engine_sidecar.py`
  (`bridge.task-request` in → `bridge.result` out; adapter `run_governed_turn` enforces
  verified-receipt-mandatory).

**Gap Phase 9 closes:** a connector registry with config + health; inbound triggers that *normalize an
external event into a governed `bridge.task-request`*; outbound sinks that emit *only* a payload
carrying a verified result; and **secret delegation** so the desktop stores references, never secrets.

## 2. Integration mechanics (through the wall)

**Connectors are declared on the desktop; secrets and the external call boundary live with the
engine/operator.** A connector descriptor is product state: `{type, config_schema, auth_location:
"operator", enabled, health}`. Enabling a connector that needs credentials performs an **auth handoff**
— the desktop stores an `auth_ref` (opaque handle) and the operator/engine sidecar holds the actual
secret. There is no code path that writes a credential to desktop SQLite.

**Inbound: external event → governed task.** An inbound trigger normalizes a received external event
into a `bridge.task-request` (`bridge/contracts/task-request.schema.json`: `{task_id, task_class,
rationale, protected_scope[]}` — carries **no** lease/key/env) and dispatches it through the *same*
sidecar path as chat/automation (`ai.rs::governed_engine` → `engine_sidecar.py`). The supervisor
(`engine/tools/bro_supervisor.py`) issues the lease into a builder behind the wall; the result comes
back with a verified receipt or fail-closes. **Inbound events cannot start ungoverned work** — the only
way in is a governed task-request.

**Outbound: only verified results leave.** An outbound sink sends a small **sink-payload** shape
`{result, receipt_id, verified}` — **never raw secrets, never an unverified result**. The sink refuses
to send unless `verified===true` (mirroring `bridge/engine_adapter.py`: `result` is non-null iff
`ok && receipt.verified`). The actual network send happens on the engine/operator side of the boundary
where the connector's secret lives; the desktop passes the verified payload + the connector's `auth_ref`.

**Refuse governance-breaking connectors.** A connector that would require the desktop to hold a secret,
or that would run ungoverned, is refused at enable time → the UI shows **`blocked`** with the reason and
the lawful provisioning step (hand auth to the operator/engine).

## 3. Data models / contracts

**Cross-boundary:**
- Inbound reuses `bridge.task-request` / `bridge.result` (no new contract).
- **New** outbound **sink-payload** shape `{result, receipt_id, verified}` (add
  `bridge/contracts/sink-payload.schema.json`, versioned; a contract change ⇒ 📐 mandatory audit,
  consumers updated in the same PR, roadmap §G.2).
- **New** connector descriptor `{type, config_schema, auth_location}`. If a connector needs an
  engine-side secret holder, that provisioning is an **operator/engine step, not desktop code**.

**Desktop SQLite (`core/src/domain.rs`+`repo.rs`) — no credential columns, only references:**
- `connector` — `{id, type, name, provider, config(json), enabled, health('healthy'|'degraded'|
  'unreachable'), auth_ref(nullable), created_at, updated_at}`.
- `inbound_trigger` — `{id, connector_id, event_match, task_class, protected_scope(json)}`.
- `outbound_sink` — `{id, connector_id, channel, filter(json)}`.
- `integration_event` — audit of inbound receipts / outbound sends `{id, connector_id, direction,
  task_id(nullable), receipt_id(nullable), verified(bool), status, at}`.

## 4. UI wiring & states (per roadmap §D)

**`integrations` ✦ Ինտեգրումներ** (`Integrations.tsx`):
- Components: connector **catalog** (available/connected, `role=list`), per-connector config panel,
  health/status chip (`statusTone`), inbound-trigger ↔ outbound-sink mapping, and an **auth-handoff**
  control clearly labelled as delegating to the operator/engine (never a secret input on the desktop).
- States: `default`(list) · `loading`(`Skeleton`) · `empty`("no integrations" HY + browse CTA) ·
  `error`(connector unhealthy) · **`blocked`** (auth not provisioned / would run ungoverned / would
  need a desktop secret → reason + how to provision). Reuse `components/ui` (`Async`,`Panel`,`Badge`,
  `Button`,`Modal`).
- Motion: connect `--enter`, health pulse; honor `prefers-reduced-motion`. Keyboard: `/` search
  catalog, `Enter` open, `Space` enable/disable. A11y: catalog `role=list`, health/status in accessible
  name, auth-handoff labelled HY.
- Replace the current single `connect/disconnect` toggle with the catalog + config + mapping flow; the
  toggle's `setIntegrationStatus` becomes `enableConnector`/`disableConnector` with health.

## 5. Exact files to touch

- `apps/desktop/src/features/Integrations.tsx` — catalog, config, health, inbound/outbound mapping, auth handoff, `blocked`.
- `apps/desktop/src/services/desktop.ts` — `listConnectors`, `enableConnector(authHandoff)`, `disableConnector`, `setConnectorConfig`, `mapInbound`, `mapOutbound`, `connectorHealth`.
- `apps/desktop/src/domain/entities.ts` — `Connector`, `InboundTrigger`, `OutboundSink`, `IntegrationEvent` (no credential fields).
- `apps/desktop/src-tauri/src/commands.rs` — the above commands; inbound normalization → governed dispatch; outbound verified-only send.
- `apps/desktop/src-tauri/core/src/{domain.rs,repo.rs,db.rs}` — new tables + atomic migration; assert **no credential column**.
- **New** `apps/desktop/src-tauri/src/integrations.rs` — inbound event normalizer (→ `bridge.task-request`, reuse the shared governed dispatch from Phase 8) + outbound sink (verified-only, sends `{result,receipt_id,verified}` + `auth_ref`).
- **New** `bridge/contracts/sink-payload.schema.json` (+ tests in `bridge/tests/`).
- `apps/desktop/src/i18n/*` — HY/EN keys.

## 6. Tests & acceptance

- Rust: inbound event → governed task (a receipt is required before any effect); outbound sink **refuses
  to send** an unverified result and sends only `{result,receipt_id,verified}`; a connector cannot be
  enabled if it would persist a desktop secret (**contract/DB test: no credential column is ever
  written**); health + `blocked` states.
- Bridge: `sink-payload` schema validation (`bridge/tests/`), verified-only invariant.
- Frontend (`npm run test`): `integrations` state coverage incl. `blocked`; auth-handoff never renders a
  secret field; `jest-axe` a11y pass.
- **Merge-gate acceptance:** owner connects an external source that triggers **governed** work and a
  sink that receives **verified** output, with **no desktop-held secret**; refuses connectors that would
  break governance; page meets full §D incl. `blocked`. All CI legs green.

## 7. Security notes

- **🛑 External boundary — Owner approval + Architect security sign-off are mandatory *before*
  implementation** (roadmap §G.1 P9 + trust-boundary/secret task class §G.2).
- **The desktop stores no external secrets.** Auth handoff to engine/operator; only `auth_ref` handles
  live on the desktop. A connector that would require a desktop secret is refused (`blocked`).
- Inbound cannot start ungoverned work (only a `bridge.task-request`); outbound sends only verified
  results (`verified===true`, else no send). Verified-receipt-mandatory holds on every inbound-triggered
  run (`bridge/engine_adapter.py`).
- If the external boundary needs an **engine** change (a secret holder, a new gate), that is a separate
  🛑 audited engine task — never edit `engine/` security code inside this phase (§E serialization).

## 8. Dependencies & CI

Requires **P7** (group/collaboration as an output surface) + **P8** (automation as a trigger source).
CI (`.github/workflows/ci.yml`): cockpit legs green; integration paths exercise the **bridge** leg; add
a test asserting **no credential is persisted on the desktop**; the new `sink-payload` schema gets bridge
tests. Docs to sync at merge: `docs/ARCHITECTURE.md` (integration boundary + secret delegation),
`docs/SECURITY_MODEL.md` note on external-secret handling, this spec, `PROJECT_STATE.md`.

**Stop conditions:** a connector needing a desktop secret, or that would run ungoverned → stop, refuse
it. External boundary needing engine changes → audited task.

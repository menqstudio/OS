# Phase 8 — Automation · Implementation Spec

> ⚠️ **PROPOSAL — NOT EXECUTION AUTHORITY.** This spec is a *proposal* for review, not canonical.
> It does NOT authorize execution. Its architecture / trust / contract decisions are **§I controlled
> changes** requiring Architect audit + Owner approval before any build, and are **superseded where they
> conflict with the Challenger-Deep audit** (round 1) — esp. the receipt/sidecar/provider findings.


> Blueprint for a cold-start session. Grounds roadmap **Phase 8** (`MASTER_EXECUTION_ROADMAP.md`
> L1055–1131) in the real code. Scope: wire `automations` + `calendar` to a scheduler that fires
> **governed** dispatches — every unattended run is a `bridge.task-request` returning a **verified**
> receipt; ungoverned automation is impossible (refused at authoring); guard trips halt + surface.
> Ownership: 🔨 Builder · 📐 Audit (no-ungoverned-fire) · ✅ Gev. Depends on P4 (design system) + P5
> (knowledge). Parallel with P6 (§E).

## 1. Objective & current state

**Intent.** The owner schedules recurring/triggered work that Bro runs on a cadence *without ever
escaping the wall*. Each fire = a lease + verified receipt; the calendar shows schedule + run history.

**What exists today (prototype/mock — no governance, no scheduler):**
- `apps/desktop/src/features/Automations.tsx` — a CRUD list. `NewRuleForm` collects free-text
  `{name, trigger, action}` and calls `desktop.createAutomation`. Rows toggle `enabled` and delete.
  **Nothing fires; `trigger`/`action` are opaque strings; no lease, no receipt.**
- `apps/desktop/src/features/Calendar.tsx` — a month grid + agenda over `CalendarEvent` records
  (`desktop.listEvents/createEvent/deleteEvent`). Pure manual events; **no run history, no now-line
  pulse, no receipt ids.**
- IPC boundary `apps/desktop/src/services/desktop.ts`: `listAutomations`, `createAutomation`,
  `setAutomationEnabled`, `deleteAutomation`; `listEvents`, `createEvent`, `deleteEvent`.
- Rust commands in `apps/desktop/src-tauri/src/commands.rs` (`list_events`/`create_event`/… at
  `repo::events`); the SQLite core is `apps/desktop/src-tauri/core/src/{db.rs,domain.rs,repo.rs}`.
- Entities `apps/desktop/src/domain/entities.ts`: `Automation{id,name,trigger,action,enabled,…}`,
  `NewAutomation{name,trigger,action}`, `CalendarEvent{…startsAt,endsAt}`.
- The **governed dispatch path already exists** and is what Phase 8 reuses:
  `apps/desktop/src-tauri/src/ai.rs` `Provider::GovernedEngine{python,sidecar}` → `governed_engine()`
  spawns `bridge/engine_sidecar.py`, writes ONE `bridge.task-request` to stdin, reads ONE
  `bridge.result` from stdout (gated by `BROPS_ALLOW_GOVERNED_ENGINE=1`).

**Gap Phase 8 closes:** a scheduler; an `action` that is a *typed governed task class* not free text;
persisted `automation_run` rows carrying `receipt_id`/`verified`; authoring that refuses ungoverned
actions; guard trips; the calendar surfacing runs.

## 2. Governed-automation mechanics (the core of this phase)

**Every fire is a governed dispatch.** The scheduler never executes an action itself. On each fire it
builds a `bridge.task-request` (`bridge/contracts/task-request.schema.json`: `{task_id, task_class,
rationale, protected_scope[]}` — **no lease, no key, no env**) and routes it through the *same* sidecar
path `ai.rs` uses. The engine supervisor (`engine/tools/bro_supervisor.py`) issues a single-use lease
**into a separate builder**, runs behind the wall, and returns a `bridge.result`. The adapter
(`bridge/engine_adapter.py::run_governed_turn`) sets `receipt.verified=true` **only** after the injected
verifier confirms signed evidence; **no verified receipt ⇒ no result** (fail-closed, per §F of the
roadmap).

**Refuse ungoverned at authoring.** An automation's `action` is no longer opaque text — it is a
`task_class` drawn from the engine's known classes (mirror `engine/tools/bro_supervisor.py`'s
`TASK_CLASSES` via `bro_protected`) plus a `protected_scope[]`. `create_automation` validates that the
authored action maps to a legal governed task-request; if it cannot (unknown class, empty scope, or an
action that would need direct execution), the command returns `Err(...)` and the authoring UI renders
the **`blocked`** state with the reason. There is no code path that stores an automation whose fire
would bypass the wall.

**Guards.** A guard is a predicate (mode/scope precondition) evaluated *before* dispatch, referencing
the engine's scope/mode rules. A guard trip halts the automation (`state=blocked`), writes an
`automation_run` with `status="guard_tripped"` + the verdict reason, and surfaces it in `automations`
and `notifications` — it never silently retries or degrades to ungoverned.

**Honest dependency on Phase 1.** Real-mode receipt verification is still Architect-audit-pending
(`bridge/engine_sidecar.py::_real_callables` raises until the verify seam lands). So in a real,
un-provisioned deployment every fire **fail-closes** (no result) — which is the *correct* governed
behavior, not a bug. Phase-8 tests exercise the happy path through the injected/`--self-test` seam
(documented mock supervisor); the wall invariant is what is being proven, not a live model turn.

## 3. Data models / contracts

**Cross-boundary:** none new. Fires reuse `bridge.task-request` / `bridge.result`. Guards reference
engine scope/mode rules (read-only).

**Desktop SQLite (product state, in `core/src/domain.rs` + `repo.rs`):**
- `automation` — extend to `{id, name, trigger, task_class, protected_scope (json), guard (json|null),
  enabled, state('idle'|'flowing'|'throttled'|'blocked'|'completed'), created_at, updated_at}`.
  (Migrate the old free-text `action` → `task_class`; keep the column nullable during migration.)
- `schedule` — `{id, automation_id, kind('cron'|'interval'|'event'), spec, next_fire_at, enabled}`.
- `automation_run` — `{id, automation_id, fired_at, task_id, receipt_id (nullable), verified (bool),
  status('completed'|'failed'|'denied'|'guard_tripped'|'blocked'), reason}`. The receipt/evidence
  themselves stay in the engine ledger; the desktop stores only `receipt_id` + `verified`.

**TS entities** (`apps/desktop/src/domain/entities.ts`): update `Automation`/`NewAutomation`, add
`AutomationRun` and `Schedule`. **IPC** (`desktop.ts`): add `listAutomationRuns(automationId)`,
`runAutomationNow(id)` (governed manual fire), `setSchedule(...)`; keep existing CRUD.

## 4. UI wiring & states (per roadmap §D)

**`automations` ⇶ Ավտոմատներ** (`Automations.tsx`, reproducing prototype `arows`/`aCount`/`afilter`/
`manifold`/`schem`/`auSched`):
- Components: automation index (`role=list`), per-row state chip (idle/flowing/throttled/blocked/
  completed) from `statusTone`, schematic/manifold view with a **step-list fallback**, scheduler editor.
- `NewRuleForm` becomes a governed authoring form: name + trigger + **task-class picker** +
  protected-scope + optional guard + schedule. On a would-be-ungoverned action it shows `blocked`.
- States: `default`(list) · `loading`(`Skeleton`) · `empty`("no automations yet" HY + create CTA) ·
  `error`(`ErrorState`+retry) · **`blocked`** (wall/guard denied → reason + how-to-fix). Reuse
  `apps/desktop/src/components/ui` (`Async`, `Panel`, `Badge`, `Modal`, `ConfirmDialog`).
- Motion: flow `stream`, `suspend` on throttle, honor `prefers-reduced-motion`. Keyboard: `n` new, `/`
  filter, `↑/↓`, `Enter` open, `Space` enable/disable. A11y: state in accessible name; run verdicts in
  an `aria-live` region.

**`calendar` ▦ Օրացույց** (`Calendar.tsx`, reproducing `daygrid`/`calNow`/`calAgenda`/`calClock`/`calPlay`):
- Overlay `automation_run` history onto the existing month grid + agenda; add the **now-line**
  (`nowPulse`) and a per-run badge with `verified` state + `receipt_id` on hover.
- States: `empty`(no scheduled runs) · `error`. Keyboard: arrow-navigate days/slots, `Enter` open, `t`
  today. A11y: grid `role=grid`; slots labeled date+time+run; agenda `role=list`.

## 5. Exact files to touch

- `apps/desktop/src/features/Automations.tsx` — governed authoring form, run history, `blocked` state.
- `apps/desktop/src/features/Calendar.tsx` — now-line, run overlay, receipt badge.
- `apps/desktop/src/services/desktop.ts` — new IPC calls (`runAutomationNow`, `listAutomationRuns`, `setSchedule`).
- `apps/desktop/src/domain/entities.ts` — updated + new entities.
- `apps/desktop/src-tauri/src/commands.rs` — `run_automation_now`, `list_automation_runs`, `set_schedule`; validate task-class on `create_automation`.
- `apps/desktop/src-tauri/core/src/{domain.rs,repo.rs,db.rs}` — `automation`/`schedule`/`automation_run` tables + atomic migration.
- **New** `apps/desktop/src-tauri/src/scheduler.rs` — tick loop → build `bridge.task-request` → reuse the `ai.rs` governed dispatch → persist `automation_run`. (Factor the sidecar spawn out of `ai.rs::governed_engine` so both chat and scheduler share one governed path.)
- `apps/desktop/src/i18n/*` — HY/EN keys for the new states/labels.

## 6. Tests & acceptance

- Rust: scheduler fire → governed dispatch → verified receipt (inject a mock/`--self-test` supervisor);
  `create_automation` **rejects** an ungoverned/unknown-class action; guard trip → `automation_run`
  `status="guard_tripped"` + reason, automation halted; run history persists `receipt_id`/`verified`.
- Frontend (`npm run test`): `automations`/`calendar` state coverage incl. `blocked`; authoring shows
  the wall reason; calendar renders run badges. `jest-axe` a11y pass.
- **Merge-gate acceptance:** owner authors an automation that fires on schedule, each run governed +
  verified and visible in `calendar`; ungoverned automations are impossible; guard trips surface. Both
  pages meet §D incl. `blocked`. All CI legs green.

## 7. Security notes

- Governed automation is **Architect-audited** (roadmap §G.1 P8; no-ungoverned-fire is the audit focus).
- The desktop **holds no lease/key/env** — the scheduler only emits `bridge.task-request` (schema
  forbids lease/key/env) and consumes `bridge.result`. Trust root stays in the operator sidecar.
- Verified-receipt-mandatory applies to *every* unattended run: `run_governed_turn` returns a non-null
  `result` iff `ok && receipt.verified`. A missing/failed verify ⇒ `automation_run.verified=false`,
  `status` records the fail-closed reason, no action output is trusted.
- If a guard or task class needs an **engine** change, that is a separate 🛑 audited engine task
  (engine golden rule, §E serialization) — do not touch `engine/` security code inside this phase.

## 8. Dependencies & CI

Requires **P4** (component library / `blocked` primitive) and **P5** (knowledge the automations act on).
CI: cockpit-frontend + cockpit-core legs stay green; the scheduler path exercises the **bridge** leg
(`.github/workflows/ci.yml`); add a test asserting no ungoverned automated action is constructible.
Docs to sync at merge: `docs/ARCHITECTURE.md` (governed automation model), this spec, `PROJECT_STATE.md`.

**Stop conditions:** a scheduled fire that could run without a lease/receipt → stop (invariant break).
A guard needing engine changes → audited task.

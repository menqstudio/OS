# Phase 6 — Multi-Agent · Implementation Spec

> ⚠️ **PROPOSAL — NOT EXECUTION AUTHORITY.** This spec is a *proposal* for review, not canonical.
> It does NOT authorize execution. Its architecture / trust / contract decisions are **§I controlled
> changes** requiring Architect audit + Owner approval before any build, and are **superseded where they
> conflict with the Challenger-Deep audit** (round 1) — esp. the receipt/sidecar/provider findings.


> Blueprint for a next session. Grounds `MASTER_EXECUTION_ROADMAP.md` §"Phase 6" in the real
> code. **Governed change:** anything under §I of the roadmap (new engine `task_class`, trust
> boundary) is a 🛑 Architect-audited change — this spec routes around engine edits wherever it
> can and flags the one place it cannot. **Depends on Phase 4 (design system) + Phase 5 (memory),
> per roadmap §E.** Read alongside `PHASE_7_GROUP_CHAT.md` (its consumer).

---

## 1. Objective & current state

**Roadmap intent.** Surface and govern Bro's pack model: the live agent network (`agents`), the
command core that dispatches governed work (`command`), and the mission/flow surfaces (`tasks`,
`projects`) — so the owner watches and steers multiple specialized agents, each governed by its
own single-use lease. **The desktop never holds a lease.**

**What exists today (all prototype / product-mock, no engine in the loop):**

| Page | File | Today | Data source |
|---|---|---|---|
| `agents` | `apps/desktop/src/features/Agents.tsx` | Static card grid of `Agent` rows. No live state, no lattice. | `desktop.listAgents()` → `list_agents` (SQLite) |
| `command` | `apps/desktop/src/features/Command.tsx` | CRUD over `Run`/`RunStep`; `streamRunStep` → `stream_run_step` runs the **ungoverned** `ai.rs` provider directly. | `desktop.listRuns()` / `streamRunStep()` |
| `tasks` | `apps/desktop/src/features/Tasks.tsx` | Drag board over `Task.status` (`inbox…cancelled`). Pure product state. | `desktop.listTasks()` / `setTaskStatus()` |
| `projects` | `apps/desktop/src/features/Projects.tsx` | Card grid + detail over `Project`; links `Task`s. | `desktop.listProjects()` |

**What the engine already models** (`engine/tools/bro_supervisor.py`): one conductor + a governed
builder per `run_task` call. Each `run_task`:
- authorizes a `TaskRequest{task_id, task_class, rationale, protected_scope}` (no lease/key/env),
- creates an **isolated worktree** (`prepare_worktree`), issues a **single-use lease into a separate
  builder** (`issue_lease` → `spawn_builder`, lease only in the builder's env), reaps the process
  tree, and returns a `SupervisorResult{task_id, status, message, exit_code, evidence}`.
- Statuses: `completed` / `denied` / `failed` / `expired` / `uncontained`. Task classes:
  `standard-builder`, `security-maintenance` (`bro_execution_lease.CLASS_CAPABILITIES`).

**The gap.** A *pack* is N of these governed builders running as one mission. The engine can already
run each builder; nothing on the desktop/bridge fans out, tracks per-builder lease/receipt state, or
renders it. Phase 6 builds that fan-out **as bridge/sidecar orchestration over N single-builder
governed runs** — keeping `engine/` security code untouched.

---

## 2. Phase 6 specifics — governed PACK dispatch through the bridge

### The pack = N governed single-builder runs, orchestrated in the sidecar

The bridge today is **one request → one result**: the desktop writes one `bridge.task-request` to
`engine_sidecar.py` stdin and reads one `bridge.result` (`run_governed_turn` in `engine_adapter.py`,
which enforces fail-closed + verified-receipt-mandatory). A pack is the same primitive, N times.

Do **not** invent a new engine `task_class` value (`TASK_CLASSES` lives in `engine/bro_protected.py`;
adding one is a 🛑 audited engine change). Instead:

1. Add a **task-force envelope** at the bridge layer — a `bridge.task-force-request` that carries a
   list of member `task-request`s, each with an existing class (`standard-builder`).
2. The sidecar/adapter **fans out**: for each member it invokes the supervisor's `run_task` (one
   isolated worktree, one single-use lease **into that builder**), collects each `SupervisorResult`,
   and runs `run_governed_turn`'s verify-and-extract per member.
3. It streams back **one `bridge.result` per member** (each with its own `verified` receipt) plus a
   terminal roll-up. The desktop renders each member as one agent node.

The one-conductor rule holds: the desktop is the conductor, holds nothing, and observes N governed
builders. If fan-out later needs a real engine `task_class` (e.g. a capped concurrency lease), that
is the flagged 🛑 audited engine task — not this phase.

### IPC / transport wiring

- **New Rust command** `dispatch_pack(request: TaskForceRequest, onEvent: Channel<PackEvent>)` in
  `src-tauri` — spawns `python bridge/engine_sidecar.py` (real mode; operator-provisioned env only,
  never `--self-test`), writes the task-force JSON to stdin, and forwards each per-member
  `bridge.result` as a `PackEvent` over a Tauri `Channel` (mirrors `stream_run_step`'s channel model
  in `desktop.ts`). The desktop passes **no** `BRO_KEYDIR/BRO_BINDING/...`; those are operator env on
  the sidecar host.
- **`desktop.ts` additions:** `dispatchPack(req, onEvent)`, `listAgentViews()`, `listMissions()`,
  `listFlows()` — each a real `invoke`, no mock layer (`hasBackend()` gate already present).
- **Reality check:** `engine_sidecar._real_callables` currently **fails closed** — receipt
  verification is the Architect-pending seam. Until it lands, `dispatch_pack` returns `blocked`
  member results carrying that exact reason string. The UI must render this as the governed
  `blocked` state, not an error. This is expected Phase-6 behavior and its acceptance is "blocked
  renders faithfully," with the verified path proven via `--self-test` in CI only.

### Per-page wiring & states (all four honor roadmap §D: default/loading/empty/error/blocked)

- **`agents` ⬡ (live lattice).** Replace the static grid with an `agent_view`-driven lattice; keep a
  `role=list` node fallback (a11y). Node state ← per-builder lifecycle mapped from `SupervisorResult`:
  `idle → flowing (running) → throttled → blocked (denied/verify-fail) → completed`. Dossier on
  `Enter`; state announced via `aria-live`. Data: live `PackEvent` stream + `listAgentViews()`.
- **`command` ❖ (governed dispatch).** This is where the pack is launched. Keep the `Run`/`RunStep`
  scaffold but route "execute" through **`dispatch_pack`** instead of the ungoverned `stream_run_step`.
  Show the active dispatch, a `role=log aria-live` trace, the assigned team (one row per member with
  its receipt badge), and `blocked` with the wall's verdict reason. `⌘K`/`Enter` dispatch, `Esc` abort.
- **`tasks` ◈ (missions).** Board unchanged in shape; each card gains a `mission` mirror linking to the
  engine task contract that a pack member executes (`receipt_id`, evidence link). `blocked` column
  already exists in `COLUMNS`.
- **`projects` ❖ (flows).** Flow = pipeline of missions; per-flow status rolls up member receipts.
  Step-list fallback for the flow graph.

### Per-builder verified receipts — reuse the existing invariant

Each member result flows through the **existing** `run_governed_turn`: `verified` is set **only**
after the injected verifier confirms signed evidence; no verified receipt ⇒ no result. Surface it with
the **already-defined** `Message.receipt: 'verified' | 'blocked' | null` badge vocabulary
(`domain/entities.ts:114`) reused as `AgentView.receipt`. The desktop stores only `receipt_id` +
`verified` (product state); receipts/evidence stay in the engine ledger.

---

## 3. Data models / contracts

**New bridge contract (versioned, consumers same PR — roadmap §G task-class = Contract change, 📐
mandatory, ✅ approval):**

- `bridge/contracts/task-force-request.schema.json`
  ```json
  { "task_force_id": "str", "rationale": "str",
    "members": [ { "$ref": "task-request.schema.json" } ] }
  ```
  Each member is exactly today's `task-request` (no lease/key/env). No new engine class.
- Reuse `bridge/contracts/bridge-result.schema.json` **per member** (unchanged). Add a small
  `pack-roll-up` shape (`{task_force_id, members:[{task_id, ok, verified, status}]}`) for the terminal
  event — bridge-only, no cross-boundary secret.

**Desktop product tables (SQLite, mirror only — engine holds authoritative leases/receipts):**

- `agent_view(id, role, state, lease_id?, receipt_id?, verified, updated_at)` — `lease_id` is an
  **opaque id string only**, never lease material.
- `mission(id, task_id, status, claim, evidence_ref, receipt_id, verified)`.
- `flow(id, name, steps[], status)`.

Extend `domain/entities.ts` with `AgentView`, `Mission`, `Flow`, `TaskForceRequest`, `PackEvent`
(`{type:'member'|'rollup'|'error', ...}`), mirroring the Rust structs (camelCase).

---

## 4. UI wiring & states

Per roadmap §D each page fills: components / layout+responsive / default·loading·empty·error·blocked /
loading skeleton / empty copy (HY) / error / **blocked (governance verdict + lawful next step)** /
motion (§C.1 tokens, `prefers-reduced-motion`) / keyboard / a11y / data source.

- **blocked is mandatory** on `agents` (node denied), `command` (dispatch denied — show verdict from
  the `bridge.result.error`), `tasks`/`projects` (member blocked). Blocked offers "request approval"
  (Phase 2 approvals) as the lawful next step, never a dead end.
- Reuse Phase-4 library primitives (lattice/board/rails); no bespoke CSS.

---

## 5. Exact files to touch

**Frontend (`apps/desktop/src`):**
- `features/Agents.tsx` — live lattice + list fallback + dossier + state machine.
- `features/Command.tsx` — route execute → `dispatch_pack`; trace/team/receipt badges/blocked.
- `features/Tasks.tsx`, `features/Projects.tsx` — mission/flow mirror + receipt links.
- `services/desktop.ts` — `dispatchPack`, `listAgentViews`, `listMissions`, `listFlows`, `PackEvent`.
- `domain/entities.ts` — `AgentView`, `Mission`, `Flow`, `TaskForceRequest`, `PackEvent`.
- `app/store.tsx` — already has `governedEngine`; add pack-live state if needed.

**Backend (`apps/desktop/src-tauri`):** `dispatch_pack` command + sidecar spawn/stream; `agent_view`/
`mission`/`flow` tables + read commands in `core/`.

**Bridge (`bridge/`):** `contracts/task-force-request.schema.json`; fan-out in `engine_adapter.py`
(new `run_governed_pack(members, *, run_task, verify_receipt, read_result)` looping `run_governed_turn`)
and `engine_sidecar.py` (parse task-force, fan out, stream per-member results). **No `engine/` edit.**

---

## 6. Tests & acceptance

- **Bridge unit** (`bridge/tests/test_engine_adapter.py` sibling): pack fan-out returns one result per
  member; a denied/verify-fail member yields `blocked`, never a result; roll-up shape valid; a
  task-force with a member carrying a lease/key/env field is rejected (mirrors the slice-1 tests).
- **Contract test (merge gate):** the desktop never serializes a lease/key — assert `dispatch_pack`'s
  outbound JSON matches `task-force-request.schema.json` (`additionalProperties:false`) and contains no
  `*lease*`/`*key*`/`BRO_*` field.
- **Frontend:** lattice/board state rendering; `blocked` on denied dispatch renders the verdict;
  per-member badge = `verified`/`blocked`/pending; a11y (jest-axe) on lattice list fallback.
- **CI:** cockpit legs green; pack path exercises the **bridge leg** (`cd bridge && BRO_ENV=ci python
  -m unittest discover -s tests`) via `--self-test` fan-out; real mode asserted fail-closed.
- **Acceptance (roadmap DoD):** owner dispatches a governed pack from `command`, watches agents live in
  `agents`, tracks missions/flows in `tasks`/`projects`, sees each agent's **verified** receipt (or a
  faithful `blocked`). All four pages meet §D incl. `blocked`. **No desktop-held lease.**

---

## 7. Security notes (📐 Audit: "no lease leakage" — roadmap §G Phase 6)

- **Desktop holds nothing.** `dispatch_pack` sends only a `task-force-request` (no lease/key/env);
  `agent_view.lease_id` is an opaque id string, never lease material. Contract test enforces it.
- **Per-agent verified-receipt-mandatory.** Every member runs through `run_governed_turn`; `verified`
  set only after the injected verifier confirms signed evidence; no verified receipt ⇒ no result.
- **Single-use lease per builder, into the builder only** — unchanged `issue_lease`/`spawn_builder`
  semantics; the supervisor stays outside both processes.
- **Fan-out must not become an engine change by stealth.** Any new engine `task_class`, concurrency
  lease, or supervisor change is a **🛑 Architect-audited engine task** (roadmap §E serialization + §I
  change control) — this phase must **stop** and raise a controlled-change proposal rather than edit
  `engine/`.
- **Real-mode verify seam is Architect-pending** (`engine_sidecar._real_callables` fails closed);
  shipping `blocked` for real dispatch until it lands is correct, not a regression.

---

## 8. Dependencies

- **Phase 4** (design system) — lattice/board/rail primitives, tokens, a11y baseline.
- **Phase 5** (memory & knowledge) — the substrate packs consume.
- Runs **parallel with Phase 8** (§E). **Blocks Phase 7** (group chat consumes per-agent governance).
- Requires Phase 1's operator-provisioned sidecar (keys/registry/binding/builder command) **outside the
  desktop** for real dispatch; `--self-test` proves plumbing in CI meanwhile.

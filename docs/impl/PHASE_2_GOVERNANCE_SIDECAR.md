# Phase 2 — Governance Sidecar · Implementation Spec

> Execution blueprint for `MASTER_EXECUTION_ROADMAP.md` §"Phase 2 — Governance Sidecar"
> (roadmap lines 529–621). Grounded in the code as it stands on `main`. This is a build plan,
> not a change to the plan — nothing here alters architecture, trust boundary, security, or
> execution order (no §I event). Adding an **engine-side** schema (approval-request intake) IS a
> controlled change and is flagged as an audited engine task, never done inline (§8).

---

## 1. Objective & current state

**Roadmap intent.** Give the cockpit four *read-only, faithful surfaces* onto the engine's
governance truth — `approvals`, `decisions`, `security`, `notifications` — plus an approve/deny
**request** path where the desktop *requests* and the engine *decides*. Mirror, never decide
(`docs/ARCHITECTURE.md` principle 2). Every page implements all §D states incl. `blocked`.

**What already exists (do NOT rebuild the shell/pages from scratch):**

- All four pages exist as thin real screens wired through `features/registry.tsx:40-45`:
  - `features/Approvals.tsx` — `desktop.listApprovals()` + `decideApproval()` (queue, A3 dual-confirm).
  - `features/Decisions.tsx` — `desktop.listDecisions()` (card list).
  - `features/Security.tsx` — `desktop.getSecuritySummary()` (3 count tiles + sensitive-events panel).
  - `features/Notifications.tsx` — `desktop.listNotifications()` + `markNotificationRead()` (unread/all tabs).
- The typed IPC surface `services/desktop.ts:63-78, 150-152` and its Rust commands
  `src-tauri/src/commands.rs:176-266, 873-883`.
- The domain types `domain/entities.ts`: `Approval` (43-56), `Notification` (58-68),
  `Decision` (70-78), `SecuritySummary` (246-251), `ActivityEvent` (80-87).
- The `<Async>` state wrapper (`components/ui.tsx`) already gives default/loading/empty/error;
  `StatusPill status="blocked"` already maps to `danger` (`domain/enums.ts`).

**The critical gap — what these pages mirror today is NOT the engine.** Every page above reads the
desktop's **own SQLite product tables** (`brops-core` repo: `repo::approvals`, `repo::decisions`,
`repo::notifications`, `repo::security`), seeded by `repo::seed`. Those tables are the *product's*
approval flow (e.g. the run-step gate in `commands.rs:572-663`), not the engine's governance
truth. Phase 2's real work is to add a **second, read-only data path onto the engine** (evidence
chain, receipts, audit ledger, verdicts) and render it faithfully alongside — or in place of — the
seeded product data, with an honest `blocked`/empty state when the engine is not provisioned.

**Engine governance truth that must be surfaced (all read-only, all on disk):**

| Truth | Source module | Shape |
|---|---|---|
| Evidence chain | `engine/runtime/bro_evidence.py` | SHA-256-chained signed `{event_id}.json` events + a signed `{task_id}.head.json` anchor. `validate_chain()` returns the final hash / raises on tamper. |
| Execution receipts | `engine/runtime/bro_receipt.py` | Ed25519-signed; `verify_receipt()` binds a run to `task_id`/`candidate_head`/`candidate_tree`/`exit_code`/transcript hashes. |
| Audit / decision ledger | `engine/runtime/bro_audit_log.py` | Append-only hash-chained JSONL + signed `audit-head` anchor; `verify()` refuses a truncated chain. This is the natural `decisions` feed. |
| Verifier / skill verdicts | `engine/schemas/verifier-receipt.schema.json`, `skill-receipt.schema.json` | Independent verdict + skill-run evidence. |

There is **no approval-queue module** in the engine: owner approvals are Ed25519 `protected-authority`
artifacts consumed by `bro_supervisor.authorize_request()` (`tools/bro_supervisor.py:109-137`). A
desktop→engine *approval-request intake* does not exist and is an audited engine task (§8).

---

## 2. Backend / IPC to build

**Principle: mirror-never-decide, and every engine read is read-only.** The engine modules above
**only verify** (they hold no signing key). The desktop reads their on-disk artifacts through a new
Python reader hosted next to the existing bridge, then Rust IPC exposes typed JSON. No gate logic,
no key, no lease ever enters the desktop.

### 2a. New Python reader — `bridge/governance_reader.py`

Mirror the sidecar contract (`bridge/engine_sidecar.py`): stdin one request `{op, ...}`, stdout one
JSON document; always exit 0; fail-closed. Ops (all read-only, provisioning-gated exactly like
`engine_sidecar._real_callables`, `bridge/engine_sidecar.py:98-118`):

- `list_decisions` → read + `bro_audit_log.verify()` the ledger, return the records (tamper → `blocked`).
- `list_evidence` / `chain_status` → `bro_evidence.validate_chain()` for a task; return integrity + events.
- `list_receipts` → `bro_receipt.verify_receipt()` over the receipt store; return verdicts.
- `security_posture` → chain-integrity + audit-head status + residual-tracker (O-1..O-5, static).

Requires the same operator-provisioned env as the turn path (`BRO_KEYDIR`, `BRO_REGISTRY_ROOT`,
`BRO_BINDING`, `BRO_REPOSITORY_ROOT` — `engine_sidecar.py:50-56`). **Absent provisioning → a
fail-closed document `{ok:false, error:"governance engine not provisioned: ..."}`**, which the UI
renders as `blocked` (honest "not wired yet"), never as fabricated data.

### 2b. New Rust IPC — `src-tauri/src/governance.rs` (new module, registered in `lib.rs`)

Read-only commands that spawn the reader with the same subprocess discipline already proven in
`ai.rs:1097-1163` (`governed_engine`): stdin payload, bounded reads (`MAX_STDOUT_BYTES`),
one absolute deadline, `kill_on_drop`, `env_remove` of any fake flag. New `#[tauri::command]`s:

- `governance_decisions() -> Vec<GovDecision>`
- `governance_evidence(task_id) -> ChainStatus`
- `governance_receipts() -> Vec<GovReceipt>`
- `governance_posture() -> GovPosture`
- `governance_signals() -> Vec<GovSignal>` (derived from ledger events + receipt verdicts)

Register each in the `tauri::generate_handler!` block (`lib.rs:63-131`). The **approval-request**
POST (`request_approval(...)`) is a *stub that returns "not available: engine intake pending audit"*
until the engine schema lands (§8) — never a local grant.

### 2c. Data flow

```
engine on-disk artifacts                bridge (read-only)            desktop (mirror, never decide)
────────────────────────                ──────────────────           ──────────────────────────────
bro_evidence store   ─┐
bro_audit_log ledger ─┼─ verify() ──▶ governance_reader.py ──stdout JSON──▶ governance.rs (#[command])
bro_receipt store    ─┘   (no keys)     (provision-gated,                        │ typed
verifier/skill verdicts                  fail-closed)                            ▼
                                                                    services/desktop.ts (typed)
                                                                                 │
                                                                                 ▼
                                              Approvals / Decisions / Security / Notifications pages
                                              + optional desktop mirror cache (rebuildable)
```

The engine ledger stays authoritative; desktop mirror tables are display caches only.

---

## 3. Data models / contracts

**TypeScript (add to `domain/entities.ts`) — the engine-truth types (distinct from the existing
product `Approval`/`Decision`):**

```ts
export interface GovDecision {           // one audit-ledger record
  id: string; taskId: string; eventType: string; agentId: string;
  verdict: 'granted' | 'denied' | 'completed' | 'uncontained' | string;
  sequence: number; issuedAtEpoch: number; verified: boolean; // false ⇒ chain suspect
}
export interface ChainStatus {           // evidence-chain integrity for a task
  taskId: string; intact: boolean; eventCount: number; finalHash: string | null;
  brokenReason: string | null;           // non-null ⇒ render `blocked`
}
export interface GovReceipt {            // one execution receipt verdict
  receiptId: string; taskId: string; exitCode: number; verified: boolean;
  runnerId: string; runnerPlatform: string; finishedAtEpoch: number;
}
export interface GovPosture {            // security page
  chainIntact: boolean; auditHeadOk: boolean; residual: { id: string; status: string }[];
  keyRegistryOk: boolean; provisioned: boolean; // false ⇒ blocked/empty
}
export interface GovSignal {             // notifications feed
  id: string; severity: 'info' | 'warning' | 'danger'; kind: string;
  title: string; body: string; taskId: string | null; createdAtEpoch: number;
}
```

**Contract that crosses the wall = only ids + verdicts + hashes.** No key, no lease, no evidence
key material. The bridge reader documents mirror the engine's own verified payloads byte-for-byte
(`bro_receipt.REQUIRED_FIELDS`, `bro_evidence.EVENT_FIELDS`). Add `services/desktop.ts` methods
mapping 1:1 to the 2b commands (`invoke<...>('governance_decisions')`, etc.).

---

## 4. UI wiring

For each page, wire the *engine* source and implement every §D state. When the reader returns
`provisioned:false` (the default today), the honest state is `blocked` (or an "all clear" empty for
notifications) — never a spinner that never resolves, never fake rows.

| Page (file) | Wire to | default | loading | empty | error | blocked |
|---|---|---|---|---|---|---|
| `Approvals.tsx` | keep product queue; add an **engine verdicts** panel (`governance_receipts`) | queue + verdicts | `<Skeleton>` rows | "no pending approvals" (HY) | engine unreachable → `ErrorState` + retry | owner not authenticated / engine intake pending → `BlockedState` w/ lawful next step (request approval) |
| `Decisions.tsx` | `governance_decisions()` (audit ledger, read-only, `aria-readonly` rows, `role=log`) | ledger rows | skeleton | "no decisions" | reader error | chain tamper (`verified:false`) → `blocked`, disable evidence open |
| `Security.tsx` | `governance_posture()` + `governance_evidence()` | integrity + residual + key/lease status | skeleton | — | chain break → `danger` live region | `provisioned:false` → `blocked` guidance |
| `Notifications.tsx` | `governance_signals()` merged with product `list_notifications` | signal feed (`role=feed`, `aria-live=polite`) | skeleton | "all clear" (HY) | reader error | severity-gated actions blocked when engine down |

Reuse the §D affordances the roadmap names (lines 550-568): `reveal`+`--stagger` on new items,
mint `stamp` on grant / danger `strike` on deny, `↑/↓` list nav, `g`/`d`/`e` on Approvals,
`Enter`/`Esc` confirm/cancel with a confirm-before-commit dialog (already present as
`ConfirmDialog`, used in `Approvals.tsx:86-95`). Integrity status is a live region; a broken chain
is announced. Add a first-class `BlockedState` component (also called for in Phase 4) so all four
pages share one governance-denied panel: gate reason from the engine verdict + the lawful next
step.

**Honest handling when data isn't available yet:** real engine reads require operator provisioning
that does not ship (§8). Until then, gate the engine panels behind the reader's `provisioned` flag
and render `blocked` with copy that says the sidecar is not provisioned — mirroring how
`ai.rs:432-439` reports the governed provider as `ready:false` today.

---

## 5. Exact files to touch

**New:**
- `bridge/governance_reader.py` — read-only engine reader (ops in 2a); provision-gated, fail-closed.
- `bridge/tests/test_governance_reader.py` — parse/fail-closed/no-key tests.
- `apps/desktop/src-tauri/src/governance.rs` — the read-only IPC commands (2b) + request stub.
- `apps/desktop/src/features/BlockedState.tsx` (or extend `components/ui.tsx`) — governance-denied panel.

**Changed:**
- `apps/desktop/src-tauri/src/lib.rs` — `mod governance;` + register the new commands in
  `generate_handler!` (`lib.rs:63-131`).
- `apps/desktop/src/services/desktop.ts` — add `governance*` typed methods (after line 152).
- `apps/desktop/src/domain/entities.ts` — add the §3 `Gov*` / `ChainStatus` types.
- `apps/desktop/src/features/{Approvals,Decisions,Security,Notifications}.tsx` — wire engine panels + `blocked`.
- `apps/desktop/src/i18n/en.ts` (+ `hy.ts`) — new keys (blocked reasons, "all clear", chain-break).
- `docs/ARCHITECTURE.md` (governance-surfaces section), `PROJECT_STATE.md`, `TASKS.md` — same-commit sync.

**Never touched here:** any file under `engine/` (read-only consumers only) and `bridge/engine_adapter.py`.

---

## 6. Tests & acceptance

**Tests (roadmap lines 586-592):**
- Rust: `governance.rs` read/parse tests; a contract test that an approval-**request** payload carries
  no key/lease/env (mirror `interpret_bridge_result` discipline, `ai.rs:1064-1090`).
- Python: `test_governance_reader.py` — provisioning-absent → fail-closed `{ok:false}`; tampered
  ledger/chain → `blocked`, never data; verdicts echo the engine payload byte-for-byte.
- Frontend: each page renders `blocked`/`error` on engine-unreachable and chain-break; verdict text
  matches the engine verdict.
- Existing `cargo test -p brops-core` (29), `npm run build`, engine + bridge suites stay green (§B.4).

**Acceptance (roadmap lines 597-599, 608-612):** the four pages render live engine governance data
faithfully (or an honest `blocked` when unprovisioned); the owner can *request* an approval the
engine adjudicates (stub until §8 intake lands); every page implements all §D states incl.
`blocked`; **no desktop-side decision authority** exists; no cached keys/leases.

---

## 7. Security notes

**Needs Architect audit (🛑 mirror-never-decide gate, roadmap G.1 row "Phase 2"):**
- `bridge/governance_reader.py` — it touches engine evidence/receipts/verdicts. Confirm it only
  *verifies* (imports no signing path) and cannot mutate the store.
- Any approval-request intake (§8) — a new engine schema is a 🛑 audited engine task, never inline.
- The `request_approval` command — must be a fail-closed stub, never a local grant, until intake exists.

**Safe (normal PR flow):** the four page components, TS types, i18n copy, the desktop mirror cache
tables (display-only, rebuildable, keyed by engine ids), and the read-only Rust IPC wiring — none
hold a key/lease or make a governance decision.

**Invariants to preserve:** desktop cannot mint/alter/approve; a chain-integrity break forces
`blocked` and disables dependent actions (roadmap lines 604-605); verdicts render byte-for-byte.

---

## 8. Dependencies & open questions

- **Depends on Phase 1** (the bridge produces the receipts/evidence these surfaces read). Can start
  as soon as the P1 contract exists, in parallel with early P3 shell work (roadmap §E, lines 231-233).
- **Owner (provisioning) — blocking for *live* data:** the reader needs `BRO_KEYDIR`,
  `BRO_REGISTRY_ROOT`, `BRO_BINDING`, `BRO_REPOSITORY_ROOT` on the machine (same crux as the governed
  turn, `ai.rs:435-438`). Until provisioned, ship the pages with the honest `blocked` state — this is
  acceptable for merge (the states are the deliverable, not live data that needs keys).
- **Architect (audit) — blocking for approve/deny:** the engine has **no approval-request intake**
  (approvals are `protected-authority` artifacts, `bro_supervisor.py:109-137`). Adding a desktop→engine
  intake schema is a §G contract/engine change → 🛑 propose → audit → approve → implement. **Open
  question for the Architect:** does the owner approve through the existing signed-artifact path
  (offline `broctl` sign) that the desktop merely *surfaces*, or is a new online intake wanted? Until
  answered, `request_approval` stays a stub.
- **Open question:** do the Phase-2 pages *replace* the seeded product SQLite tables as their source,
  or show both (product flow + engine truth) side by side? Recommendation: keep both — the product
  run-step gate (`commands.rs`) is real product behavior; the engine panels are the governance mirror.

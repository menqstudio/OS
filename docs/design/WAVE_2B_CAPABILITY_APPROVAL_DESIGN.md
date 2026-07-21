# Wave 2b — Capability boundary + durable approval · DESIGN (design-only)

> **Status:** DESIGN-ONLY. No product code ships under this document. It exists to be
> **Architect-audited and Owner-approved** before any implementation branch is opened.
> Tasks **T-010** (capability boundary) and **T-011** (durable approval) are designed
> **jointly** here; implementation order is **T-010 first, then T-011, then Wave 3**.
>
> **Design-only · միայն դիզայն։** Այս փաստաթղթի ներքո product code չի գրվում մինչև
> Architect audit + Owner approval։

---

## 0. Why this ordering (Architect ruling, recorded)

Receipt Protocol v1 (Wave 3) is the larger trust-win, but the **real governed path is
already fail-closed** (Wave 1). Meanwhile **broad webview authority** (T-010) and the
**restart-lost self-approval protection** (T-011) are an **already-live attack surface**.
Adding a signed receipt on top of a compromisable control-plane is the wrong order.
Therefore: **T-010 → T-011 → Wave 3.**

---

## 1. The correction that reshapes T-010

**Tauri v2 capabilities are scoped to a window/webview `label`, not to a React route.**

- The app runs **one window, label `main`** (`tauri.conf.json` declares a single window;
  no explicit `label` ⇒ Tauri's default label `main`; `capabilities/default.json` targets
  `"windows": ["main"]`).
- Every capability granted to that window is **unioned**. Inside one SPA window, the
  `settings`, `approvals`, and `chat` routes share **exactly one** permission set.
- **Consequence:** "route → capability group" is **not a security boundary.** A compromised
  renderer on any route can invoke every command the `main` window is granted, regardless of
  which route is "showing".

So T-010 is **not** a mapping of routes to groups. It is a decision about **privilege
topology** — which authorities may live behind the `main` webview at all, and which must be
moved to a boundary the renderer cannot cross (native Rust, or a separate locked webview).

A second, independent rule from the same ruling:

> **Custom command scope must be enforced *inside* the Rust command.** Declaring a command in
> the manifest and granting/denying it in `capabilities/*.json` controls **whether the window
> may call it at all** — it does **not** validate arguments, ownership, or policy. Config is
> the outer gate; the command body is the inner gate. Both are required.

---

## 2. Current state (facts, at design time)

- **68 webview-reachable commands** are registered in `generate_handler!` (`lib.rs`).
- **Only 3** are in the app manifest (`build.rs`) and therefore capability-gated:
  `list_dir`, `read_file`, `write_file` (the M-8 filesystem surface). Removing their
  `allow-*` grant in `capabilities/default.json` disables them for the window.
- **The other 65 `commands::*` are ungated** — Tauri v2 gates *plugin* commands by default,
  but app commands not in the manifest are invokable by the webview **with no permission entry
  at all**. This is the open half of the M-8 TODO and the core of T-010.
- **Approval self-approval protection is process-memory only.** `decide_approval` refuses a
  decision whose deciding window label matches the recorded request origin — but the origin
  lives in an in-process `Mutex<HashMap>` (`approval_origins()`), so **after a restart the map
  is empty and the check cannot fire.** Native out-of-band confirmation is a `TODO`. This is
  T-011.
- **Migrations** are forward-only, idempotent, one exclusive transaction per version
  (`db.rs`); `SCHEMA_VERSION = 11`. T-011's schema change is **migration 0012**.
- **`approvals` columns today:** `id, action_type, target, level, risk_level, status,
  requested_by, entity_type, entity_id, requested_at` (+ decided fields).

---

## 3. Full command inventory + risk tiers

Risk tiers classify **what authority the command exercises**, independent of which route calls
it (because route is not a boundary — §1).

### Tier R — Read-only (24)
No mutation, no external effect, no spend. Safe for the `main` webview.

`list_projects` · `list_tasks_by_project` · `list_tasks_by_status` · `list_tasks` ·
`list_task_dependencies` · `list_agents` · `list_approvals` · `list_notifications` ·
`list_decisions` · `list_activity` · `list_conversations` · `list_messages` ·
`list_knowledge` · `search_knowledge` · `list_memory` · `list_runs` · `list_run_steps` ·
`list_events` · `list_automations` · `list_integrations` · `search_all` · `get_analytics` ·
`get_security_summary` · `ai_status`

### Tier L — Local reversible mutation (23)
Writes only to the app's own local SQLite; no external effect, no execution, no spend. Blast
radius is local user data. Acceptable behind `main` **with deny-by-default manifest gating +
in-command input bounds**.

`create_project` · `set_project_status` · `update_project` · `create_task` ·
`set_task_status` · `update_task` · `add_task_dependency` · `remove_task_dependency` ·
`mark_notification_read` · `create_decision` · `create_conversation` · `post_message` ·
`post_user_message` · `save_ask_to_chat` · `delete_conversation` · `rename_conversation` ·
`create_knowledge` · `delete_knowledge` · `create_memory` · `set_memory_pinned` ·
`delete_memory` · `create_event` · `delete_event`

> Note: `post_message` / `post_user_message` / `save_ask_to_chat` already carry the Wave 2a
> provenance controls (user-role only; agent body server-held). They stay Tier L.

### Tier A — Approval authority (1) — **must leave `main`'s unconditioned reach**
`decide_approval`

This is the command that **grants gated actions**. If the `main` webview can call it freely, a
compromised renderer can approve its own requested privileged action. Process-memory origin
pinning does not survive restart (T-011). **Design decision:** an *approve* decision on a
privileged approval must require **native out-of-band confirmation** the renderer cannot
forge (§5). *Reject* stays cheap (fail-safe direction).

### Tier X — Execution / external-effect / spend (17) — **scoped request + server-side policy**
Drives the agent runtime, external integrations, the AI provider, or the raw filesystem.

- **Runs (agent execution):** `create_run` · `set_run_status` · `add_run_step` ·
  `set_run_step_status` · `advance_run` · `stream_run_step`
- **Automations (triggered execution):** `create_automation` · `set_automation_enabled` ·
  `delete_automation`
- **Integrations (external surface):** `set_integration_status`
- **AI generation (provider spend / agent content):** `reply_in_conversation` ·
  `stream_reply` · `stream_ask`
- **Filesystem (direct disk):** `list_dir` (read) · `read_file` (read) · `write_file` (write)
  — already manifest-gated + path-confined; folded in here for completeness.

Tier X commands must **not** be a bare capability grant. Each must, **in its own body**,
re-check server-side policy (path confinement, run/step ownership, the approval gate for
`requires_approval` steps, provider fail-closed from Wave 1). Several already do; the design
makes it uniform and asserts it with negative tests.

---

## 4. Privilege topology (the T-010 target)

```
┌─ main webview (label: "main") ───────────────────────────────────────────┐
│  MAY call:                                                                │
│    • Tier R  (read-only)            — granted                             │
│    • Tier L  (local reversible)     — granted, deny-by-default manifest   │
│    • Tier X  (execution)            — granted ONLY as a "request";        │
│                                       the command body enforces policy    │
│  MUST NOT hold unconditioned authority for:                              │
│    • Tier A  (decide_approval on a privileged approval)                   │
└──────────────────────────────────────────────────────────────────────────┘
             │ privileged approval decision
             ▼
┌─ out-of-band confirmation boundary (renderer cannot cross) ──────────────┐
│  Native Rust confirmation (Tauri native dialog / OS prompt), OR a         │
│  separate locked webview with its own capability set.                     │
│  decide_approval(approved) on a privileged approval is recorded ONLY      │
│  after this boundary returns success.                                     │
└──────────────────────────────────────────────────────────────────────────┘
```

**Decision to ratify (Architect):** for T-011's confirmation boundary, choose

- **Option A — native Rust confirmation** (Tauri native dialog invoked from the command,
  before `repo::approvals::decide`). Lower surface, no second webview to harden. **Recommended.**
- **Option B — separate locked webview** with a distinct `label` + minimal capability set,
  used only to render/confirm privileged approvals.

Recommendation: **Option A** now (smaller trusted surface, no new renderer to secure);
revisit Option B only if a richer confirmation UI is later required.

---

## 5. T-010 design — enforcement (implementation shape, not code)

1. **Manifest:** extend `build.rs` `AppManifest::new().commands(&[…])` from the 3 filesystem
   commands to **all 68**. This makes tauri-build generate `allow-<cmd>` / `deny-<cmd>` for
   every command, so an ungranted command is **uninvokable** — closing the "no permission entry
   at all" hole.
2. **Deny-by-default:** `capabilities/default.json` for `main` grants **only** Tier R + Tier L
   + Tier X-as-request. It **omits** `decide_approval` (Tier A) so the `main` window cannot
   invoke it as an ordinary command; the privileged decision path goes through the confirmation
   boundary (§4). *Reject*-only decisions may be exposed through a narrow, explicitly-scoped
   path if UX requires (fail-safe direction).
3. **In-command scope (inner gate):** each Tier X/A command body **re-validates** server-side —
   filesystem path confinement (exists), run/step ownership + the `requires_approval` gate
   (exists), provider fail-closed (Wave 1, exists), input length bounds (exists for runs). The
   design **audits every Tier X/A command for a real in-body check** and adds any missing one.
   Config gating alone is explicitly declared insufficient.
4. **No capability without a body check for Tier X/A.** A grant that only relies on the config
   layer is treated as a defect in review.

**Rollout guard:** because extending the manifest to 68 commands regenerates the permission set,
the change is landed with the **full negative-test matrix green** (§7). If any privileged path
cannot yet be safely exposed, the design **prefers temporarily denying it** (sensitive action
`Blocked`) over shipping it ungated — fail-closed over convenience.

---

## 6. T-011 design — durable approval + native confirmation

### 6.1 Schema — migration 0012 (forward-only)
Add to `approvals` (nullable, backfill-safe):

| Column | Type | Purpose |
|---|---|---|
| `origin` | TEXT | Persisted request origin (window label / session id). Replaces the in-memory `approval_origins()` map — **survives restart**. |
| `request_digest` | TEXT | Hash of the gating tuple `(action_type, entity_type, entity_id, target)`. Binds a decision to the exact request so a stale/mutated request cannot be approved by replay. |
| `confirmation_method` | TEXT | `none` \| `native` — how an *approve* was confirmed. |
| `confirmed` | INTEGER | 0/1 — native out-of-band confirmation completed. Required = 1 for a privileged *approve* to be recorded. |
| `nonce` | TEXT | One-time token consumed on decision; a second decision with a spent/again nonce is refused (replay-safe). |

`SCHEMA_VERSION → 12`; `db.rs` migration table gains `(12, MIGRATION_0012)`; idempotency test
(`migrate_is_idempotent`) extended.

### 6.2 Decision flow (server-side, restart-safe)
```
decide_approval(id, decision, note, window):
  load approval row  (origin, request_digest, risk_level, status, nonce)
  refuse if status != pending            # no re-decide
  refuse if nonce already consumed       # replay-safe (durable, not in-memory)
  if decision == approved:
      # self-approval check now reads persisted origin → fires after restart
      refuse if row.origin == this session's origin
      if approval is privileged (Tier A / high risk_level):
          require native out-of-band confirmation → refuse if not confirmed
          record confirmation_method = native, confirmed = 1
      recompute request_digest from the CURRENT gated entity;
      refuse if it != row.request_digest   # request mutated since it was raised
  consume nonce; write decision + server-derived approver; append audit row
```

- **Self-approval, restart-safe:** origin persisted in the row, not in process memory.
- **Native confirmation:** the privileged *approve* is recorded **only after** the native
  boundary (§4, Option A) returns success — the renderer cannot fabricate it.
- **Replay/mutation-safe:** one-time `nonce` + `request_digest` recheck.
- `approval_origins()` in-memory map is **removed**; the request path writes `origin`/`nonce`
  at creation time instead.

---

## 7. Negative-test matrix (must be green before each implementation lands)

**T-010**
1. A command **not granted** to `main` (e.g. `decide_approval` on the ordinary path) is
   **uninvokable** from the webview (permission-denied), not silently executed.
2. A Tier X command with an **out-of-scope argument** (path escape for `write_file`; foreign
   run/step id) is **refused in-body**, even though the capability is granted.
3. Removing a Tier L `allow-*` grant disables exactly that command and nothing else.
4. A `requires_approval` run step still **cannot execute** without a granted approval (Wave-1 +
   gate invariant preserved after re-manifest).

**T-011**
5. **Self-approval after restart:** raise an approval, restart the process, attempt to approve
   from the same origin → **refused** (origin came from the DB, not memory).
6. **Replay:** decide once, decide again with the same `nonce` → **refused**.
7. **Request mutation:** raise approval for entity E, mutate E's gating tuple, approve →
   **refused** on `request_digest` mismatch.
8. **Privileged approve without native confirmation** → **refused**; with confirmation →
   recorded, `confirmed = 1`.
9. **Reject** requires no native confirmation (fail-safe direction) and always succeeds for a
   pending approval.

---

## 8. Rollout plan

1. **This design PR** (docs only) → Architect audit + Owner approval. **Gate.**
2. **T-010 implementation PR** — manifest to 68 commands; deny-by-default `capabilities`;
   remove `decide_approval` from `main`'s ordinary grant; audit every Tier X/A body for an
   in-command check; add any missing. Land with negative tests 1–4 green. Sensitive actions
   that cannot yet be safely exposed are temporarily **Blocked** rather than shipped ungated.
3. **T-011 implementation PR** — migration 0012; persist `origin`/`request_digest`/`nonce`;
   restart-safe self-approval; native out-of-band confirmation (Option A); remove the in-memory
   `approval_origins()` map. Land with negative tests 5–9 green.
4. **Then Wave 3** — Receipt Protocol v1 (signed per-turn provenance), now on a
   capability-bounded, restart-safe control plane.

Each implementation PR carries its own coordination-doc sync and its own zero-trust re-audit,
per the established Wave-1/Wave-2a cadence.

---

## 9. Open questions for Architect / Owner

1. **Confirmation boundary:** ratify **Option A (native Rust confirmation)** vs Option B
   (separate locked webview). Design recommends A.
2. **Reject path exposure:** may `main` expose a **reject-only** `decide_approval` path
   (fail-safe direction), or must *all* decisions cross the native boundary?
3. **"Privileged" threshold:** which `risk_level` / action types require native confirmation —
   proposal: `risk_level` high **or** any Tier A/Tier-X-destructive action.
4. **Digest inputs:** confirm the gating tuple `(action_type, entity_type, entity_id, target)`
   is the complete set to bind, or whether more (e.g. run intent) must be included.

---

## 10. Scope boundary (explicit)

- **In scope:** capability topology + enforcement (T-010); durable, restart-safe, replay-safe,
  natively-confirmed approvals (T-011).
- **Out of scope (Wave 3):** signed per-turn governed **receipt** provenance — deliberately
  sequenced *after* the control plane is bounded.
- **Unrelated:** the prior Anthropic Agent-Platform note remains a **separate read-only harvest
  proposal**; it does not change this security sequencing and is not part of this gate.

**No product code is authored under this document.** Implementation begins only after this
design is Architect-audited and Owner-approved.

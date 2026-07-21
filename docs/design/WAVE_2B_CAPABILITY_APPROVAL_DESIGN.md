# Wave 2b — Capability boundary + durable approval · DESIGN (design-only)

> **Status:** DESIGN-ONLY. No product code ships under this document. It exists to be
> **Architect-audited and Owner-approved** before any implementation branch is opened.
> Tasks **T-010** (capability boundary) and **T-011** (durable approval) are designed
> **jointly** here; implementation order is **T-010 first, then T-011, then Wave 3**.
>
> **Revision 2** — incorporates the Architect YELLOW redlines: corrected 64-command
> inventory + CI invariant; L1/L2 split; "renderer-independent native confirmation"
> wording; canonical-JSON request-envelope digest; `origin_principal` vs
> `origin_session_id`; richer confirmation columns; migration 0012 reserved for T-011.
> The four boundary questions are now **ratified decisions** (§9), not open questions.

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
moved to a boundary the renderer cannot cross (renderer-independent native Rust).

A second, independent rule from the same ruling:

> **Custom command scope must be enforced *inside* the Rust command.** Declaring a command in
> the manifest and granting/denying it in `capabilities/*.json` controls **whether the window
> may call it at all** — it does **not** validate arguments, ownership, or policy. Config is
> the outer gate; the command body is the inner gate. Both are required.

---

## 2. Current state (facts, at design time)

- **64 webview-reachable commands** are registered in `generate_handler!` (`lib.rs`) — 61
  `commands::*` + 3 `files::*`.
- **Only 3** are in the app manifest (`build.rs`) and therefore capability-gated:
  `list_dir`, `read_file`, `write_file` (the M-8 filesystem surface). Removing their
  `allow-*` grant in `capabilities/default.json` disables them for the window.
- **The other 61 are ungated** — Tauri v2 gates *plugin* commands by default, but app
  commands not in the manifest are invokable by the webview **with no permission entry at
  all**. This is the open half of the M-8 TODO and the core of T-010.
- **Approval self-approval protection is process-memory only.** `decide_approval` refuses a
  decision whose deciding window label matches the recorded request origin — but the origin
  lives in an in-process `Mutex<HashMap>` (`approval_origins()`), so **after a restart the map
  is empty and the check cannot fire.** Native confirmation is a `TODO`. This is T-011.
- **Migrations** are forward-only, idempotent, one exclusive transaction per version
  (`db.rs`); `SCHEMA_VERSION = 11`. T-011's schema change is **migration 0012** (reserved; §8).
- **`approvals` columns today:** `id, action_type, target, level, risk_level, status,
  requested_by, entity_type, entity_id, requested_at` (+ decided fields). `target` is **UI
  display text** (for run steps it is built from truncated run intent/title) and therefore
  **cannot be the security authority** — see the digest design (§6.3, §9.4).

---

## 3. Full command inventory + risk tiers (64)

Risk tiers classify **what authority the command exercises**, independent of which route calls
it (route is not a boundary — §1). **Tier math: R 24 + L 23 (L1 19 + L2 4) + A 1 + X 16 = 64.**

### Tier R — Read-only (24)
No mutation, no external effect, no spend. Safe for the `main` webview.

`list_projects` · `list_tasks_by_project` · `list_tasks_by_status` · `list_tasks` ·
`list_task_dependencies` · `list_agents` · `list_approvals` · `list_notifications` ·
`list_decisions` · `list_activity` · `list_conversations` · `list_messages` ·
`list_knowledge` · `search_knowledge` · `list_memory` · `list_runs` · `list_run_steps` ·
`list_events` · `list_automations` · `list_integrations` · `search_all` · `get_analytics` ·
`get_security_summary` · `ai_status`

### Tier L1 — Local reversible mutation (19)
Writes only to the app's own local SQLite; no external effect, no execution, no spend, and the
change is reversible (re-editable / re-addable). Acceptable behind `main` with deny-by-default
manifest gating + in-command input bounds.

`create_project` · `set_project_status` · `update_project` · `create_task` ·
`set_task_status` · `update_task` · `add_task_dependency` · `remove_task_dependency` ·
`mark_notification_read` · `create_decision` · `create_conversation` · `post_message` ·
`post_user_message` · `save_ask_to_chat` · `rename_conversation` · `create_knowledge` ·
`create_memory` · `set_memory_pinned` · `create_event`

> `post_message` / `post_user_message` / `save_ask_to_chat` already carry the Wave 2a
> provenance controls (user-role only; agent body server-held). They stay L1.

### Tier L2 — Local destructive (4) — **privileged confirmation OR soft-delete/undo**
Irreversible local deletion. Even though local-only, data loss is unrecoverable, so L2 is
**pulled into the privileged-confirmation policy** (§9.3) — OR converted to **soft-delete with
undo** (tombstone + retention) so the destructive step is itself reversible. Design ratifies
one of the two per command in the T-010 PR; default recommendation is **soft-delete/undo** for
user content and native confirmation for anything without an undo path.

`delete_conversation` · `delete_knowledge` · `delete_memory` · `delete_event`

### Tier A — Approval authority (1) — **must leave `main`'s unconditioned reach**
`decide_approval`

The command that **grants gated actions**. A compromised `main` renderer must not be able to
approve its own requested privileged action. The generic `decide_approval` is **not granted to
`main`** (§9.1). *Approve* goes through renderer-independent native confirmation; *reject* is a
separate fail-safe command (§9.2).

### Tier X — Execution / external-effect / spend (16) — **scoped request + in-body policy**
Drives the agent runtime, external integrations, the AI provider, or the raw filesystem.

- **Runs (agent execution) — 6:** `create_run` · `set_run_status` · `add_run_step` ·
  `set_run_step_status` · `advance_run` · `stream_run_step`
- **Automations (triggered execution) — 3:** `create_automation` · `set_automation_enabled` ·
  `delete_automation`
- **Integrations (external surface) — 1:** `set_integration_status`
- **AI generation (provider spend / agent content) — 3:** `reply_in_conversation` ·
  `stream_reply` · `stream_ask`
- **Filesystem (direct disk) — 3:** `list_dir` (read) · `read_file` (read) · `write_file`
  (write) — already manifest-gated + path-confined; folded in for completeness.

Tier X commands must **not** be a bare capability grant. Each must, **in its own body**,
re-check server-side policy (path confinement, run/step ownership, the approval gate for
`requires_approval` steps, provider fail-closed from Wave 1, input bounds). The T-010 PR audits
every Tier X/A body for a real check and adds any missing one.

### 3.1 CI invariant (required T-010 deliverable)
A fail-closed CI check must assert the three inventories are **identical sets**:

```
registered commands (generate_handler! in lib.rs)
  == AppManifest commands (build.rs)
  == capability-policy inventory (the tier table / capabilities policy)
```

so adding a command in one place without the others **fails CI** — no silent drift, no manual
recount. This check is authored in the T-010 implementation PR (design-only here).

---

## 4. Privilege topology (the T-010 target)

```
┌─ main webview (label: "main") ───────────────────────────────────────────┐
│  MAY call:                                                                │
│    • Tier R  (read-only)             — granted                            │
│    • Tier L1 (local reversible)      — granted, deny-by-default manifest  │
│    • Tier L2 (local destructive)     — soft-delete/undo OR native-confirm │
│    • Tier X  (execution)             — granted ONLY as a "request";       │
│                                        the command body enforces policy   │
│    • reject_approval (fail-safe)     — granted (pending-only, rate-limited)│
│  MUST NOT hold:                                                           │
│    • generic decide_approval (Tier A approve authority)                   │
└──────────────────────────────────────────────────────────────────────────┘
             │ privileged approval (approve)
             ▼
┌─ renderer-independent native confirmation (renderer cannot forge) ───────┐
│  Native Rust confirmation dialog (Tauri native), invoked from the Rust    │
│  command. NOT full independent authentication — it is a boundary the      │
│  webview cannot fabricate, showing canonical details loaded from SQLite.  │
│  An approve is recorded ONLY after this boundary returns success.         │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 5. T-010 design — enforcement (implementation shape, not code)

1. **Manifest:** extend `build.rs` `AppManifest::new().commands(&[…])` from the 3 filesystem
   commands to **all 64**. This makes tauri-build generate `allow-<cmd>` / `deny-<cmd>` for
   every command, so an ungranted command is **uninvokable** — closing the "no permission entry
   at all" hole.
2. **Deny-by-default:** `capabilities/default.json` for `main` grants **only** Tier R + L1 +
   L2-as-policy + Tier X-as-request + `reject_approval`. It **omits** generic
   `decide_approval` (Tier A) so `main` cannot invoke it; the approve path goes through native
   confirmation (§4, §9.1).
3. **In-command scope (inner gate):** each Tier X/A command body **re-validates** server-side —
   filesystem path confinement, run/step ownership + the `requires_approval` gate, provider
   fail-closed (Wave 1), input length bounds. The T-010 PR audits every Tier X/A command for a
   real in-body check and adds any missing one. **Config gating alone is insufficient** and a
   grant that relies only on config is a review defect.
4. **CI invariant** (§3.1) lands in this PR.

**Rollout guard:** extending the manifest to 64 commands regenerates the permission set, so the
change lands with the negative-test matrix green (§7). A sensitive action that cannot yet be
safely exposed is **temporarily denied** (`Blocked`) rather than shipped ungated — fail-closed
over convenience.

---

## 6. T-011 design — durable approval + native confirmation

### 6.1 Schema — migration 0012 (forward-only, reserved for T-011)
Add to `approvals` (nullable, backfill-safe):

| Column | Type | Purpose |
|---|---|---|
| `origin_principal` | TEXT | **Stable** enforcement identity of the requester, e.g. `webview:main`. Persisted → survives restart. The self-approval check compares this. |
| `origin_session_id` | TEXT | Per-process/session **forensic** id (audit only, not an enforcement authority — an ephemeral id alone is not restart-safe). |
| `request_digest` | TEXT | `SHA256(canonical_json(request_envelope))` — binds the decision to the exact request (§6.3). Recomputed from current state at decision time; a mismatch refuses. |
| `nonce` | TEXT | One-time token consumed on decision; a second decision with a spent nonce is refused (durable replay-safety). |
| `confirmed_at` | TEXT | When native confirmation completed (NULL until confirmed). |
| `confirmed_by` | TEXT | Server-derived confirmer identity. |
| `confirmation_method` | TEXT | `native` (renderer-independent Rust dialog) — extensible. |
| `confirmation_digest` | TEXT | Digest of the exact envelope shown in the native dialog, so the confirmed request provably equals the recorded one. |

`SCHEMA_VERSION → 12`; `db.rs` gains `(12, MIGRATION_0012)`; `migrate_is_idempotent` extended.
`approval_origins()` in-memory map is **removed**; the request path writes
`origin_principal` / `origin_session_id` / `nonce` at creation.

### 6.2 Decision flow (server-side, restart-safe)
```
reject_approval(id, note, window):           # fail-safe, separate command (§9.2)
  pending-only atomic update → rejected; audit; rate-limited. No confirmation needed.

approve path (native, §9.1) — NOT a generic decide_approval from main:
  1) load approval (origin_principal, request_digest, risk_level, status, nonce)
  2) refuse if status != pending           # no re-decide
  3) refuse if nonce already consumed       # durable replay-safety
  4) refuse if origin_principal == this requester's principal   # self-approval, restart-safe
  5) native confirmation (renderer-independent):
        - Rust loads CANONICAL details from SQLite (never trusts webview args)
        - dialog shows action, risk, scope, exact target
        - one prompt at a time + rate-limit; DB lock NOT held while human reads
  6) in ONE new transaction, after the human confirms:
        - reload row; recheck status == pending, nonce unspent
        - recompute request_digest from CURRENT entity state; refuse on mismatch
        - write decision + confirmed_at/by/method/confirmation_digest; consume nonce; audit
```

- **Self-approval, restart-safe:** `origin_principal` is persisted, not in process memory.
- **Native confirmation:** approve recorded only after the renderer-independent boundary; the
  webview never sends a `confirmed` boolean/text.
- **Replay/mutation-safe:** one-time `nonce` + `request_digest` recheck from current state.

### 6.3 Request digest — canonical JSON envelope (not the old tuple)
The old `(action_type, entity_type, entity_id, target)` tuple is **insufficient** — `target`
is UI text. Instead hash a canonical JSON **request envelope**:

```
schema_version, approval_id, workspace_id, action_type, entity_type, entity_id,
exact_parameters_or_scope, risk_level, approval_level, requested_by,
origin_principal, entity_revision_or_state_hash, requested_at
```
For **run steps**, additionally:
```
run_id, run_intent_sha256, step_id, step_title_sha256, step_detail_sha256, requires_approval
```
Then `request_digest = SHA256(canonical_json(request_envelope))`. `target` remains a **UI
display field only**, never the authority. After native confirmation the same envelope is
recomputed from current state and checked (digest + pending status + unspent nonce) inside the
one decision transaction.

---

## 7. Negative-test matrix (green before each implementation lands)

**T-010**
1. A command **not granted** to `main` (generic `decide_approval`) is **uninvokable** from the
   webview (permission-denied), not silently executed.
2. A Tier X command with an **out-of-scope argument** (path escape for `write_file`; foreign
   run/step id) is **refused in-body**, even though the capability is granted.
3. Removing a Tier L1 `allow-*` grant disables exactly that command and nothing else.
4. A `requires_approval` run step still **cannot execute** without a granted approval
   (Wave-1 + gate invariant preserved after re-manifest).
5. **CI invariant:** registered == manifest == capability-policy inventory; adding a command in
   only one place fails CI.

**T-011**
6. **Self-approval after restart:** raise an approval, restart the process, attempt to approve
   from the same `origin_principal` → **refused** (principal came from the DB, not memory).
7. **Replay:** decide once, decide again with the same `nonce` → **refused**.
8. **Request mutation:** raise approval for entity E, mutate E's state, approve → **refused** on
   `request_digest` mismatch (recomputed from current state).
9. **Approve without native confirmation** → **refused**; the webview cannot supply a
   `confirmed` flag; only the native boundary sets `confirmed_at`.
10. **`reject_approval`** succeeds for a pending approval with no confirmation (fail-safe),
    is audited + atomic + pending-only, and is rate-limited (DoS guard).
11. **`decide_approval(id,"approved")` from `main`** is impossible — the command is not granted
    and the approve verb does not exist on `main`'s surface.

---

## 8. Rollout plan + migration reservation

1. **This design PR** (docs only) → Architect audit + Owner approval. **Gate.**
2. **T-010 implementation PR** — manifest to 64 commands; deny-by-default `capabilities`;
   remove generic `decide_approval` from `main`; add `reject_approval`; audit every Tier X/A
   body for an in-command check; add the CI invariant. Land with negative tests 1–5 green.
   L2 handled as soft-delete/undo or native-confirm per command.
3. **T-011 implementation PR** — **migration 0012** (reserved here for T-011); persist
   `origin_principal`/`origin_session_id`/`request_digest`/`nonce`/confirmation columns;
   restart-safe self-approval; native confirmation; remove in-memory `approval_origins()`.
   Land with negative tests 6–11 green.
4. **Then Wave 3** — Receipt Protocol v1. **Migration note:** the old PR #13
   `0012_message_receipt` migration **must be renumbered to a later version** when Wave 3
   rebuilds it, because 0012 is now reserved for T-011.

Each implementation PR carries its own coordination-doc sync and its own zero-trust re-audit,
per the established Wave-1/Wave-2a cadence.

---

## 9. Ratified Architect decisions

### 9.1 Confirmation boundary — Option A: renderer-independent native confirmation
- Generic `decide_approval` is **not** granted to `main`.
- The Rust command loads the **canonical** request from SQLite; it **never** accepts a
  confirmation boolean/text from the webview.
- The native dialog shows exact **action, risk, scope, target**.
- **One** confirmation prompt at a time; prompt spam is rate-limited.
- The **DB lock is not held** while the human reads the dialog.
- After confirmation, a **new transaction** reloads the row and rechecks **status, nonce,
  digest, and current entity state** before commit.
- Named **renderer-independent native confirmation** — a boundary the webview cannot forge,
  **not** full independent authentication.

### 9.2 Reject-only path from `main` — YES, as a separate command
- `reject_approval(id, note)` exists as its own command; there is **no**
  `decide_approval(id, decision)` string-argument verb on `main` (a compromised renderer must
  not be able to turn `"rejected"` into `"approved"`).
- Reject adds no privilege; it is audited, atomic, **pending-only**, and **rate-limited**
  (acknowledged DoS surface).

### 9.3 Privileged threshold — EVERY approve requires native confirmation
- Confirmation is required for **every** approved decision, not only high risk. Tier A approval
  is **always** native.
- **Risk level determines the strength** (step-up), not whether confirmation happens. Step-up
  applies to: high/critical risk, external effect or spend, filesystem write, automation
  execution, integration enable/connect, run execution, and **all destructive deletes incl.
  Tier L2**.

### 9.4 Digest — canonical JSON envelope
- Hash the envelope in §6.3, not the display tuple. `target` stays UI-only.
- Recompute from current state after confirmation; verify in the decision transaction.

---

## 10. Scope boundary (explicit)

- **In scope:** capability topology + enforcement + CI invariant (T-010); durable, restart-safe,
  replay-safe, natively-confirmed approvals with envelope digest (T-011).
- **Out of scope (Wave 3):** signed per-turn governed **receipt** provenance — deliberately
  sequenced *after* the control plane is bounded. Its migration is renumbered past 0012 (§8).
- **Unrelated:** the prior Anthropic Agent-Platform note remains a **separate read-only harvest
  proposal**; it does not change this security sequencing and is not part of this gate.

**No product code is authored under this document.** Implementation begins only after this
design is Architect-audited and Owner-approved.

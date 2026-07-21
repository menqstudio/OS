# T-010 — in-command enforcement audit (Tier X / Tier A)

> Per the Wave-2b design (§5.3): a capability grant is the **outer** gate; each
> Tier X/A command must **also** enforce policy **in its own body** — config alone is
> insufficient. This audits every Tier X and Tier A command for a real server-side
> check. Verified at implementation of T-010.

## Tier A — approval authority

| Command | Grant | In-body check |
|---|---|---|
| `decide_approval` | **deny** (main) | Approve verb **fails closed** (`Err`, native confirmation lands in T-011); denied at the capability layer too. Reject via a separate command. |
| `reject_approval` | allow | Rate-limited (fixed window / webview label); `repo::approvals::decide` is **pending-only** (`WHERE status='pending'`, 0 rows → NotFound) + **atomic** + audited. Reject grants no privilege (fail-safe). |

## Tier X — execution / external-effect / spend

| Command(s) | In-body check |
|---|---|
| `list_dir`, `read_file`, `write_file` | Path **confinement** in `files.rs` (root clamp; escape + sensitive-path denial; size/type/count caps) — verified by `files::tests`. |
| `create_run`, `add_run_step` | `require_len` bounds on intent/plan/title/detail (M-4) so attacker-controlled text cannot forge prompt/step boundaries. `add_run_step` gates in one transaction (never persisted ungated). |
| `stream_run_step` | **Approval gate**: a `requires_approval` step cannot run without an `approved_for` grant matching the full `(entity_id, entity_type, action_type)` tuple; rejection is terminal; run context passed as JSON so multi-line values cannot inject step boundaries (M-4). |
| `set_run_status`, `set_run_step_status`, `advance_run` | Status validated against the domain enum at the repo layer (`is_valid`); FK-checked; atomic. |
| `create_automation` | `require_len` bounds on name/trigger/**action** (T-010 — action can drive execution); repo validates + persists atomically. |
| `set_automation_enabled`, `delete_automation` | Repo-layer FK + atomic write; enum/boolean validated. |
| `set_integration_status` | Status validated against the integration-status enum at the repo layer; atomic. |
| `reply_in_conversation`, `stream_reply`, `stream_ask` | Provider **fail-closed** via `resolve()` (Wave 1) — no silent governed→ungoverned fallback; AI input caps (`ai::validate_input`). `stream_ask` trims/rejects empty; server holds the answer (Wave 2a). |

## Findings

- **No Tier X/A command is config-only.** Every one performs a real server-side
  check (path confinement, approval gate, provider fail-closed, enum/FK validation,
  input bounds, or a fail-closed error).
- **Gap closed in T-010:** `create_automation` free-text fields were unbounded at the
  command layer; `require_len` bounds added (action can reach execution).
- **Tier L2 (hard-delete) denied, fail-closed:** `delete_conversation`,
  `delete_knowledge`, `delete_memory`, `delete_event` are irreversible SQL deletes with
  no undo (a conversation cascades its messages). They are **DENIED** to `main`
  (`deny-*` in `capabilities/default.json`, `grant: "deny"`, `protection: "none"` in
  `command-policy.json`) until they gain soft-delete+undo or T-011 native confirmation.
  `check_capabilities.py` enforces that an L2 command may be `allow` only with a declared
  `protection` of `soft-delete`/`native-confirm`. The UI delete buttons are disabled with
  an explanatory note.
- **Deferred (by design, not a T-010 gap):** cryptographic per-turn receipt binding
  (Wave 3); durable approval origin + native confirmation (T-011). Until T-011, the
  *approve* path is intentionally unavailable (fail-closed), reject remains.

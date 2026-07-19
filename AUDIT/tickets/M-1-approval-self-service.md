# M-1 — Approval gate is self-serviceable from the webview

- **Severity:** Medium
- **Confidence:** High
- **Type:** Access control / human-in-the-loop bypass
- **Files:** `src-tauri/src/commands.rs:136-144` (`decide_approval`), interacts with `commands.rs:443-496` (`stream_run_step`)
- **Status:** Proposed patch (read-only audit)
- **Shared-file note:** touches `commands.rs` (also M-4).

## Problem
`decide_approval` is a plain `#[tauri::command]` with no out-of-band confirmation and no proof the caller is the human owner. An attacker who compromises the renderer (or any frontend bug) does:

1. call `stream_run_step` → a pending approval is created,
2. read the `approval_id` from the `ApprovalRequired` event,
3. call `decide_approval(id, "approved")`,
4. re-invoke `stream_run_step`.

Every `requires_approval` step is thus auto-approvable **by the same principal that requested it**. Blast radius is bounded today (a run step only calls the AI provider and stores text — no host execution), but the control it defeats is presented as *the* security boundary.

## Fix
Route approval decisions through a channel the renderer cannot script. Options, strongest first:
- A **native Tauri dialog / OS prompt** confirming the decision, invoked from Rust, not scriptable by the webview.
- Bind the approval to a **nonce shown only in a native window**; `decide_approval` requires that nonce.
- **Minimum:** forbid the same session/window that created an approval from deciding it, and record a distinct approver identity rather than trusting the caller.

## Acceptance criteria
- [ ] A purely programmatic `invoke('decide_approval', ...)` from the webview cannot move an approval to `approved` without the out-of-band step.
- [ ] The human sees non-forgeable context before approving (include the run intent, not just the attacker-controlled step title — see M-2/M-4).
- [ ] Existing legitimate approve/reject UX still works.

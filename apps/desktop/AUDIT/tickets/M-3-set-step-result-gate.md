# M-3 — `set_step_result` completes a gated step with no approval check (latent invariant break)

- **Severity:** Medium (latent — not directly command-reachable today)
- **Confidence:** High that the gap exists
- **Type:** Access control / defense-in-depth
- **Files:** `src-tauri/core/src/repo.rs:869-879`
- **Status:** Proposed patch (read-only audit)
- **Shared-file note:** touches `repo.rs` (also M-2, M-5, M-6).

## Problem
`set_step_result` runs unconditionally:
```rust
"UPDATE run_steps SET result = ?1, status = 'done', updated_at = ?2 WHERE id = ?3"
```
Its sibling `set_step_status` (`repo.rs:908-932`) **does** enforce the gate for `status == "done"`, and even documents the invariant:
> *"a gated step can never be marked done without an approval, whichever command sets it"*

`set_step_result` violates that invariant.

**Verified nuance:** the only current caller is `stream_run_step`, which checks the gate upstream (`commands.rs:454-483`) before calling this, so there is **no live command-level bypass today**. This is a footgun — one new caller of this `pub fn` reintroduces a real bypass.

## Fix
Move the gate into the function so the guarantee lives with the write, not each caller:
```rust
pub fn set_step_result(conn: &Connection, id: &str, result: &str) -> CoreResult<RunStep> {
    let step = get_step(conn, id)?;
    if step.requires_approval && !super::approvals::approved_for(conn, id /* + type/action per M-2 */)? {
        return Err(CoreError::Invalid {
            field: "status",
            value: "step requires approval before it can be completed".to_string(),
        });
    }
    // ... existing UPDATE, ideally read + update in one transaction ...
}
```

## Acceptance criteria
- [ ] Calling `set_step_result` directly on a gated, un-approved step returns an error (does not mark it `done`).
- [ ] The existing `stream_run_step` happy path (gate approved upstream) still stores the result.
- [ ] The read (`get_step` + `approved_for`) and the `UPDATE` run in one transaction (no TOCTOU).

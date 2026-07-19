# M-6 — `advance()` marks a run `succeeded` even when steps failed or were skipped

- **Severity:** Medium
- **Confidence:** High (verified in source)
- **Type:** Correctness
- **Files:** `src-tauri/core/src/repo.rs:982-993`
- **Status:** Proposed patch (read-only audit)
- **Shared-file note:** touches `repo.rs` (also M-2, M-3, M-5).

## Problem
The terminal branch fires whenever no `pending` step remains:
```rust
None => set_status(&tx, run_id, "succeeded").map(|_| ())?,
```
If the active step was set to `failed` (via `set_step_status`), or remaining steps are `skipped`/`failed`, `advance` finds no active and no pending rows and still stamps **`succeeded`**. A run with failed work reports success, and the seeded automation *"Notify on failed run"* (keyed on `run.status = failed`) never fires.

## Fix
In the `None` branch, inspect step outcomes before choosing the terminal status:
```rust
None => {
    let failed: i64 = tx.query_row(
        "SELECT COUNT(*) FROM run_steps WHERE run_id = ?1 AND status = 'failed'",
        [run_id], |r| r.get(0))?;
    let terminal = if failed > 0 { "failed" } else { "succeeded" };
    set_status(&tx, run_id, terminal).map(|_| ())?;
}
```
(Decide the intended policy for `skipped`/`cancelled` steps — treat only `done` as success, everything else as non-success, if that matches product intent.)

## Acceptance criteria
- [ ] A run with a `failed` step ends in `failed`, not `succeeded`.
- [ ] A run whose every step is `done` still ends in `succeeded`.
- [ ] The "Notify on failed run" automation fires for a run that had a failed step.

# M-5 — Multi-statement writes are not transactional → partial-write corruption + audit-log gaps

- **Severity:** Medium
- **Confidence:** High
- **Type:** Data integrity
- **Files:** `src-tauri/core/src/repo.rs` — `chat::post_message` (572-592) plus the same "mutate then `audit::record`" pattern in ~12 functions (47, 111, 213, 342, 391, 457, 532, 638, 709, 782, …). Only `runs::advance` (969) currently uses a transaction.
- **Status:** Proposed patch (read-only audit)
- **Shared-file note:** touches `repo.rs` (also M-2, M-3, M-6); wide but mechanical.

## Problem
Each mutation does an INSERT/UPDATE then a **separate** `audit::record` with no transaction. A crash between them leaves e.g. a message whose conversation `updated_at` never bumped (breaks `ORDER BY updated_at DESC` list ordering) or a mutation with **no audit trail** — and `security::summary` presents that audit log as the security posture, so it can silently miss events on any interrupted write.

## Fix
Wrap every mutate+audit pair in `conn.unchecked_transaction()` (already the pattern in `advance`), commit once. Example for `post_message`:
```rust
let tx = conn.unchecked_transaction()?;
tx.execute("INSERT INTO messages(...)", ...)?;
tx.execute("UPDATE conversations SET updated_at = ?1 WHERE id = ?2", ...)?;
super::audit::record(&tx, "message.posted", &input.author, "conversation", &input.conversation_id)?;
tx.commit()?;
```
Apply the same shape to each `create` / `set_status` / `delete` + audit pair listed above.

## Acceptance criteria
- [ ] For each converted function, the data mutation and its audit row commit atomically.
- [ ] Simulated failure between mutation and audit → neither is persisted (verify on at least `post_message` and one `delete`).
- [ ] All existing repo tests pass; list ordering (`ORDER BY updated_at DESC`) unaffected in the happy path.

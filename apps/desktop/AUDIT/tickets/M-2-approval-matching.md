# M-2 — Approval matching by bare `entity_id`: forgeable, reusable forever, no action binding

- **Severity:** Medium
- **Confidence:** High (verified in source)
- **Type:** Access control
- **Files:** `src-tauri/core/src/repo.rs:352-359` (`approved_for`), `repo.rs:340-349` (`create`), `src-tauri/core/schema/0008_approval_gating.sql`
- **Status:** Proposed patch (read-only audit)
- **Shared-file note:** touches `repo.rs` (also M-3, M-5, M-6).

## Problem
```rust
// approved_for:
"SELECT COUNT(*) FROM approvals WHERE entity_id = ?1 AND status = 'approved'"
```
This ignores `action_type`, `entity_type`, `level`, and `risk_level`. `create` accepts an arbitrary `entity_id`/`entity_type` with **no foreign key** (0008 adds plain TEXT columns). Consequences:

- An approval minted for a low-risk action satisfies the gate for a **critical** step with the same `entity_id`.
- A caller can create an approval pointing at any step id.
- The approval is **never consumed** — `COUNT > 0` stays true across re-runs and `done → pending → done` status flip-flops, so **one grant unlocks the step permanently**.

## Fix
Match the full tuple and consume the grant:

```rust
// approved_for(conn, entity_id, entity_type, action_type):
"SELECT COUNT(*) FROM approvals
   WHERE entity_id = ?1 AND entity_type = ?2 AND action_type = ?3
     AND status = 'approved' AND decided_at IS NOT NULL"
```
Plus:
- Mark the approval `consumed` in the **same transaction** that completes the step (so it can't be reused).
- Add referential cleanup: deleting a step deletes its approvals (app-level or a trigger; 0008 has no FK/cascade for these columns).
- Callers of `approved_for` (`repo.rs:917`, `repo.rs:963`, `commands.rs:456`) must pass the gated action's `action_type`/`entity_type`.

## Acceptance criteria
- [ ] An approval created for `action_type` A does **not** satisfy the gate for a step whose gated action is B.
- [ ] After a gated step completes, its approval is `consumed` and re-running the step re-requires approval.
- [ ] An approval whose `entity_id` doesn't reference a real step is rejected (or cannot be created).
- [ ] Existing approve → execute flow still succeeds end-to-end.

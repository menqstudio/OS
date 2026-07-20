# Delegation and Skill Loading

Bro classifies every request by risk and execution shape:

- `SOLO`: one specialist, small and low risk.
- `PACK`: one coordinated specialist pack.
- `TASK_FORCE`: multiple packs with explicit boundaries.
- `CRITICAL`: builders plus independent audit/verifier and owner approvals.

Every specialist has:

- **Core skills**: permanent professional capability.
- **Task skills**: additional skills required by the current task.
- **Reference skills**: narrow consultation for a specific issue.

Before work, the specialist must run a skill-load operation against the task contract. The receipt records skill paths, hashes, task ID, repository tree, agent ID, and time. Any task change that alters needed expertise invalidates the receipt and requires additional loading.

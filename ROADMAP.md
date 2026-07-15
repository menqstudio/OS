# Bro Roadmap — Post-Merge

**Reviewed:** 2026-07-15  
**Repository:** `menqstudio/Bro`  
**Canonical branch:** `main`  
**Merged PR:** `#4`  
**Merge commit:** `61bf9bc4a42b512926bf848b79a0cac063196993`

## Completed foundation

1. Execution Control Plane V2 is merged.
2. Canonical orchestration and Control Room V1 contracts are merged.
3. Task lifecycle, queue classes, routing policy, checkpoints, budgets, recovery, quarantine, schemas, deterministic projection, and governed command validation are canonical.
4. Final evidence: Windows and Ubuntu GREEN, independent artifact audit GREEN, 102/102 unique tests GREEN, documentation inventory 60/60, and no open P0/P1 findings.

## Next product phases

1. **Orchestration Runtime V1:** durable task/event storage, deterministic queue claim/lease semantics, routing execution, checkpoints, cancellation, retries, budgets, escalation, crash recovery, and Execution Control Plane V2 integration.
2. **Control Room API and surfaces:** live task/agent status, evidence drill-down, recovery/quarantine views, approvals, governed commands, and audit timeline.
3. **Credential and evidence services:** isolate production credentials and deploy external append-only ledgers/evidence storage.
4. **Operational rollout:** shadow mode, canary tasks, failure drills, monitoring, backup/restore, and operator runbooks.
5. **Product UX:** command surface, project/task views, agent controls, notifications, and owner approval workflows.

Each phase requires a dedicated branch, draft PR, exact-head CI, independent verification, current documentation, and Gev's explicit merge approval.

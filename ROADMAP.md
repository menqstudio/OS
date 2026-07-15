# Bro Roadmap — Post-Merge

**Reviewed:** 2026-07-15  
**Repository:** `menqstudio/Bro`  
**Canonical branch:** `main`  
**Merged PR:** `#6`  
**Merge commit:** `2395570bc9571e6c721373751a6dbfa2b6a8f75b`

## Completed foundation

1. Execution Control Plane V2 is merged.
2. Canonical orchestration and Control Room V1 contracts are merged.
3. Orchestration Runtime V1 foundation is merged.
4. Runtime truth now includes validated immutable task contracts, append-only hash-chained records, deterministic queue claims, cross-process serialization, expiring leases, evidence-backed checkpoints, budget gates, owner retry, cooperative cancellation, proof-backed recovery, terminal immutability, Control Room projection, and integrity roots.
5. Final PR #6 evidence: Windows and Ubuntu GREEN, independent real-worktree audit GREEN, runtime tests 14/14 GREEN, full unique suite 116/116 GREEN, documentation inventory 61/61, and no open P0/P1 findings.

## Next product phases

1. **Control Room API V1:** governed read endpoints for runtime projections, task/agent/queue status, evidence drill-down, approval inbox, recovery/quarantine views, audit timeline, and validated command intents.
2. **Control Room visual surfaces:** owner-facing mission overview, task detail, agent/pack views, approvals, recovery, and audit timeline.
3. **Credential and evidence services:** isolate production credentials and deploy external append-only ledgers/evidence storage.
4. **Operational rollout:** shadow mode, canary tasks, failure drills, monitoring, backup/restore, and operator runbooks.
5. **Product UX:** command surface, project/task views, agent controls, notifications, and owner approval workflows.

Each phase requires a dedicated branch, draft PR, exact-head CI, independent verification, current documentation, and Gev's explicit merge approval.

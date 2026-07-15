# Bro Roadmap — Post-Merge

**Reviewed:** 2026-07-15  
**Repository:** `menqstudio/Bro`  
**Canonical branch:** `main`  
**Merged PR:** `#8`  
**Merge commit:** `f736bce585e0e911c36a73d0181c8eb4ef3aebef`

## Completed foundation

1. Execution Control Plane V2 is merged.
2. Canonical orchestration and Control Room V1 contracts are merged.
3. Orchestration Runtime V1 foundation is merged.
4. Control Room API V1 is merged as a governed read-only boundary over validated runtime state.
5. Runtime and API truth now include immutable task contracts, append-only hash-chained records, deterministic queue claims, canonical agent workload, checkpoints, budgets, approval inbox, recovery/quarantine, audit timeline, integrity roots, honest missing-data markers, and validation-only command intents.
6. Final PR #8 evidence: Windows and Ubuntu GREEN, independent exact-head real-worktree audit GREEN, Control Room API tests 12/12 GREEN, full unique suite 128/128 GREEN, documentation inventory 62/62, and no open P0/P1 findings.

## Next product phases

1. **Control Room visual surfaces V1:** owner-facing mission overview, task detail, queue and canonical agent workload, approvals, recovery/quarantine, evidence drill-down, and audit timeline over the merged API.
2. **Credential and evidence services:** isolate production credentials and deploy external append-only ledgers/evidence storage.
3. **Operational rollout:** shadow mode, canary tasks, failure drills, monitoring, backup/restore, and operator runbooks.
4. **Product UX:** command surface, project/task views, agent controls, notifications, and owner approval workflows.

Each phase requires a dedicated branch, draft PR, exact-head CI, independent verification, current documentation, and Gev's explicit merge approval.

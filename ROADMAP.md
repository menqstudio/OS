# Bro Roadmap — Post-Merge

**Reviewed:** 2026-07-14  
**Repository:** `menqstudio/Bro`  
**Canonical branch:** `main`  
**Merged PR:** `#2`  
**Merge commit:** `3250d4cc55edc2adf8e5247deab8060983de3b47`

## Completed foundation

Bro Execution Control Plane V2 is merged to `main`.

1. Canonical capability registry and unknown-action denial.
2. Canonical agent identity and exact designated verifier authority.
3. Verified worktree, CWD, branch, HEAD, full current tree, and exclusive task binding.
4. Signed one-time execution leases with replay denial and quarantine.
5. Signed evidence, completion manifest, verifier receipt, and Stop gate.
6. Release Grant V3 with owner binding and canonical Push Executor.
7. Signed interruption recovery with guarded CAS and proof-backed settlement.

Final evidence: Windows and Ubuntu GREEN, independent audit 95/95 tests GREEN, documentation inventory 59/59, and no open P0/P1 findings.

## Next product phases

1. **Orchestration runtime:** durable task queue, pack selection, cross-pack task forces, checkpoints, cancellation, retries, and budgets.
2. **Control Room:** live task/agent status, evidence drill-down, recovery/quarantine views, approvals, and audit timeline.
3. **Credential and evidence services:** isolate production credentials and deploy external append-only ledgers/evidence storage.
4. **Operational rollout:** shadow mode, canary tasks, failure drills, monitoring, backup/restore, and operator runbooks.
5. **Product UX:** command surface, project/task views, agent controls, notifications, and owner approval workflows.

Each phase requires a dedicated branch, draft PR, exact-head CI, independent verification, current documentation, and Gev's explicit merge approval.

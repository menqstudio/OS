# Bro Post-Merge Handoff — 2026-07-15

Continue only in `menqstudio/Bro` from current `main`. Do not touch BroPS.

## Merged baseline

- PR `#4` is closed and merged.
- approved candidate HEAD: `3c31255056b0bcedf4733be81a4b5a335a1eacd6`
- main merge commit: `61bf9bc4a42b512926bf848b79a0cac063196993`
- final CI run: `29376410325`
- Windows and Ubuntu: GREEN
- independent audit: foundation GREEN; 102/102 unique tests GREEN
- targeted orchestration tests: 5/5 GREEN, included in the 102 total
- documentation inventory: 60/60

## Mandatory startup

1. Fetch current `main` and confirm HEAD.
2. Read `README.md`, `CLAUDE.md`, `AGENTS.md`, `ROADMAP.md`, and every canonical startup path.
3. Run foundation, documentation freshness, and full tests.
4. Report exact baseline before editing.
5. Create a new scoped branch and draft PR; never work directly on `main`.

## Locked foundation

Execution Control Plane V2 plus Orchestration and Control Room V1 canonical contracts are now the merged baseline. Lifecycle truth, queue classes, routing policy, checkpoints, budgets, recovery/quarantine semantics, event schemas, deterministic Control Room projection, and governed command validation are canonical and fail closed.

## Next task

Start **Orchestration Runtime V1** with a narrow branch and specification for durable task/event persistence, deterministic queue claim/lease semantics, routing execution, evidence-backed checkpoints, cancellation, retries, budgets, escalation, crash recovery, and integration with Execution Control Plane V2.

Do not mix Control Room visual UI, production credentials, external evidence-service deployment, BroPS changes, deployment, or production rollout into the same PR unless Gev explicitly expands scope.

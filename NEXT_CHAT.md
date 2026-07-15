# Bro Post-Merge Handoff — 2026-07-15

Continue only in `menqstudio/Bro` from current `main`. Do not touch BroPS.

## Merged baseline

- PR `#6` is closed and merged.
- approved candidate HEAD: `65f95171853cecacbfdff98be8e15884c1029909`
- main merge commit: `2395570bc9571e6c721373751a6dbfa2b6a8f75b`
- final CI run: `29392001475`
- Windows and Ubuntu: GREEN
- independent real-worktree audit: foundation GREEN; docs freshness GREEN
- runtime targeted tests: 14/14 GREEN
- full unique suite: 116/116 GREEN
- documentation inventory: 61/61 at merge
- open P0/P1 findings: none

## Mandatory startup

1. Fetch current `main` and confirm HEAD.
2. Read `README.md`, `CLAUDE.md`, `AGENTS.md`, `ROADMAP.md`, `NEXT_CHAT.md`, and every path in `config/canonical-read-manifest.json`.
3. Run foundation, documentation freshness, and full tests.
4. Report exact baseline before editing.
5. Create a new scoped branch and draft PR; never work directly on `main`.
6. Never merge without Gev's explicit approval bound to the exact candidate HEAD.

## Locked foundation

Execution Control Plane V2, Orchestration/Control Room V1 contracts, and Orchestration Runtime V1 foundation are merged. Runtime state lives outside Git and is reconstructed from immutable task contracts plus append-only SHA-256 chained records. Queue claims are deterministic, serialized across processes, and bound to expiring leases. Checkpoints, usage, retries, cancellation, recovery, terminal-state rules, Control Room projections, and integrity checks fail closed.

## Next task

Start **Control Room API V1** on a new branch from current `main`.

Narrow scope:

- governed read-only API boundary over validated runtime state;
- mission overview and task-detail projections;
- task, queue, agent, checkpoint, budget, recovery, quarantine, and audit views;
- evidence source/freshness/drill-down metadata;
- approval inbox read model;
- command-intent validation only, with no direct repository, credential, release, or production mutation;
- exact integration with existing orchestration SST, runtime records, identity, authorization, and Execution Control Plane V2.

Out of scope unless Gev explicitly expands it:

- visual UI;
- production credentials;
- external evidence-service deployment;
- distributed queue/database deployment;
- BroPS changes;
- deployment or production rollout.

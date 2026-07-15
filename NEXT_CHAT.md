# Bro Post-Merge Handoff — 2026-07-15

Continue only in `menqstudio/Bro` from current `main`. Do not touch BroPS.

## Merged baseline

- PR `#8` is closed and merged.
- approved candidate HEAD: `f2c457a675248eb805c02889509a40d8a5e1c520`
- main merge commit: `f736bce585e0e911c36a73d0181c8eb4ef3aebef`
- final CI run: `29434543079`
- Windows and Ubuntu: GREEN
- independent exact-head real-worktree audit: foundation GREEN; docs freshness GREEN
- Control Room API targeted tests: 12/12 GREEN
- full unique suite: 128/128 GREEN
- documentation inventory: 62/62 at merge
- open P0/P1 findings: none

## Mandatory startup

1. Fetch current `main` and confirm HEAD.
2. Read `README.md`, `CLAUDE.md`, `AGENTS.md`, `ROADMAP.md`, `NEXT_CHAT.md`, and every path in `config/canonical-read-manifest.json`.
3. Run foundation, documentation freshness, and full tests.
4. Report exact baseline before editing.
5. Create a new scoped branch and draft PR; never work directly on `main`.
6. Never merge without Gev's explicit approval bound to the exact candidate HEAD.

## Locked foundation

Execution Control Plane V2, Orchestration/Control Room V1 contracts, Orchestration Runtime V1, and Control Room API V1 are merged. Runtime state remains outside Git and is reconstructed from immutable task contracts plus append-only SHA-256 chained records. The merged API is read-only, integrity-bound, fail-closed, honest about unavailable data, and validates command intent without executing or authorizing mutation.

## Next task

Start **Control Room visual surfaces V1** on a new branch from current `main`.

Narrow scope:

- owner-facing mission overview over `ControlRoomAPIV1`;
- task detail with state, evidence source/freshness, checkpoints, budgets, and integrity root;
- queue and canonical agent workload views;
- approval inbox;
- recovery and quarantine views;
- append-only audit timeline;
- explicit loading, empty, stale, unavailable, integrity-failure, and error states;
- command-intent preparation and validation only, with no execution or mutation path;
- accessibility, deterministic rendering, and tests bound to API contracts.

Out of scope unless Gev explicitly expands it:

- production credentials;
- external evidence-service deployment;
- distributed queue/database deployment;
- direct repository, release, deployment, or production mutation;
- BroPS changes;
- deployment or production rollout.

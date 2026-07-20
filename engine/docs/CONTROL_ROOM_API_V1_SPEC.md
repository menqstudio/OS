# Bro Control Room API V1 — Foundation Specification

**Status:** merged to `main` in PR #8  
**Reviewed:** 2026-07-15  
**Repository:** `menqstudio/Bro`  
**Approved candidate HEAD:** `f2c457a675248eb805c02889509a40d8a5e1c520`  
**Merge commit:** `f736bce585e0e911c36a73d0181c8eb4ef3aebef`

## Purpose

Expose a governed read-only application boundary over validated Orchestration Runtime V1 state without weakening the orchestration SST, canonical identity, evidence, recovery, or Execution Control Plane V2 boundaries.

## Source of truth

Every response is derived from:

- validated immutable task contracts;
- append-only SHA-256 chained runtime records;
- `orchestration/registry.json` lifecycle, queue, checkpoint, budget, command, recovery, quarantine, and surface contracts;
- canonical agent and pack identities;
- existing runtime integrity and Control Room projection builders.

The API owns no competing lifecycle, routing, authorization, or release truth.

## Read models

V1 exposes deterministic read models for:

- mission overview;
- task detail;
- queue state;
- canonical agent workload;
- checkpoint history and freshness;
- budget limits and usage;
- approval inbox;
- recovery and quarantine;
- append-only audit timeline.

Every response carries source, generated-at, freshness, integrity root, and drill-down metadata. Unknown, stale, malformed, conflicting, or unverifiable runtime state is never presented as GREEN.

## Honest missing-data handling

Runtime V1 does not yet model approval expiry or a structured observed-effect object. The API must expose those fields as explicitly unavailable instead of inventing values.

## Command intent boundary

The API validates canonical command intent only. Validation requires:

- exact canonical command fields;
- exact owner (`owner-gev`) or Bro (`bro-000`) identity;
- current task-state binding;
- unexpired request time;
- policy-required evidence;
- non-mutating task scope.

Validation returns `executed: false` and `mutation_authorized: false`. It cannot mutate runtime state, Git, credentials, evidence ledgers, release state, deployment state, or production systems.

## Included implementation

- `runtime/bro_control_room_api.py`
- `tests/test_control_room_api.py`
- canonical startup, documentation, validator, and test-catalog wiring

## Explicitly out of scope

- visual UI;
- production credentials;
- external evidence-service deployment;
- distributed queue or database deployment;
- direct repository or release mutation;
- BroPS changes;
- deployment or production rollout.

## Verification evidence

- exact candidate HEAD: `f2c457a675248eb805c02889509a40d8a5e1c520`
- GitHub Actions run `29434543079`: Windows GREEN and Ubuntu GREEN
- exact artifact digest: `sha256:3f5d944b6aceea4084b7a1836da3dff1e98e6562bbeedb4a9f9ad0edf1c00ae1`
- independent exact-head real-worktree audit: foundation GREEN; documentation freshness GREEN
- targeted Control Room API tests: 12/12 GREEN
- full unique suite: 128/128 GREEN
- documentation inventory at merge: 62/62
- unresolved review threads: 0
- open P0/P1 findings at merge: none

## Next phase

The next scoped phase is **Control Room visual surfaces V1**, implemented strictly as a consumer of the merged read-only API. The UI must not recreate lifecycle, authorization, integrity, or command-execution truth.

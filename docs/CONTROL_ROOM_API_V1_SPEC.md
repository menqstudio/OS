# Bro Control Room API V1 — Foundation Specification

**Status:** implementation active in draft PR #8  
**Reviewed:** 2026-07-15  
**Repository:** `menqstudio/Bro`  
**Baseline:** `main` at `6bb29bd61b171757a6aaef016fbd46e8b970ada9`  
**Branch:** `control-room-api-v1`

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

## Merge gate

The exact final candidate HEAD requires Windows and Ubuntu GREEN, independent exact-head artifact audit, complete documentation inventory, no open P0/P1 findings, and Gev's explicit merge approval bound to that exact HEAD.

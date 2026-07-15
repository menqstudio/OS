# Bro Orchestration Runtime V1 — Foundation Specification

**Status:** merged to `main`  
**Reviewed:** 2026-07-15  
**Repository:** `menqstudio/Bro`  
**Approved candidate HEAD:** `65f95171853cecacbfdff98be8e15884c1029909`  
**Merge commit:** `2395570bc9571e6c721373751a6dbfa2b6a8f75b`

## Purpose

The first durable runtime layer above the canonical orchestration SST is merged without changing lifecycle truth or weakening the Execution Control Plane V2 boundary.

## Runtime state boundary

Runtime state is stored outside Git. Repository files remain policy, schema, validator, and implementation truth only.

Each task contains:

- one validated immutable task contract;
- append-only SHA-256 chained runtime records;
- lifecycle transitions validated against `orchestration/registry.json`;
- queue, checkpoint, budget, cancellation, recovery, and integrity evidence.

## Queue and claim safety

Queue selection is deterministic by canonical queue priority, creation time, and task ID.

Claims require:

- exact canonical assignee identity;
- cross-process exclusive claim serialization;
- an expiring claim lease;
- exact lease ID and agent binding for renewal or release;
- evidence for lease release;
- fail-closed recovery of expired queued leases.

A task may never be returned to more than one concurrent claimant.

## Checkpoints and freshness

A checkpoint is accepted only from the exact task assignee while the task is running. It requires completed criteria, open risks, next action, and non-empty evidence references.

Staleness is derived from the canonical checkpoint maximum age.

## Budgets

Supported budget dimensions come from the orchestration SST. Usage records are append-only and evidence-backed.

- soft limit exceedance moves the task to `waiting-approval`;
- hard limit exceedance moves the task to `blocked`;
- silent overrun is forbidden.

## Cancellation, retry, and recovery

- only Gev or `bro-000` may cancel;
- in-flight effects require evidence and move to `recovery-required`;
- retry from a blocked state requires exact owner authority and evidence;
- recovery requires exact owner authority and proof;
- terminal tasks remain immutable.

## Integrity

Task records form a SHA-256 chain. Sequence gaps, identity mismatches, previous-hash mismatches, and record-hash mismatches fail closed.

Control Room projections are derived from validated transition records. Empty or unverifiable state is never GREEN.

## Merged implementation

- `runtime/bro_orchestration_runtime.py`
- `runtime/bro_orchestration_runtime_v1.py`
- `tests/test_orchestration_runtime.py`
- `tests/test_orchestration_runtime_claims.py`

## Verification evidence

- exact candidate HEAD: `65f95171853cecacbfdff98be8e15884c1029909`
- GitHub Actions run `29392001475`: Windows GREEN and Ubuntu GREEN
- exact artifact digest: `sha256:2a8c9e0150a335f5be1a4b982f59162f28fb2ce957f8dbd8f13aaad5f2f27b8a`
- independent real-worktree audit: foundation GREEN; documentation freshness GREEN
- runtime targeted tests: 14/14 GREEN
- full unique suite: 116/116 GREEN
- documentation inventory at merge: 61/61
- open P0/P1 findings at merge: none

## Next phase

The next scoped phase is **Control Room API V1**: governed read-only endpoints over validated runtime projections, evidence drill-down, task/agent/queue views, approval inbox, recovery/quarantine views, audit timeline, and command-intent validation.

## Out of scope

- distributed database or network queue deployment;
- Control Room visual UI;
- production credentials;
- external append-only evidence service deployment;
- autonomous production release;
- BroPS changes;
- deployment or production rollout.

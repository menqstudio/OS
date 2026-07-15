# Bro Orchestration Runtime V1 — Foundation Specification

**Status:** implementation active in PR #6  
**Reviewed:** 2026-07-15  
**Repository:** `menqstudio/Bro`  
**Baseline:** `main` at `b5d1a343a8777738d4113e3e28cf27527f04020a`  
**Branch:** `orchestration-runtime-v1`

## Purpose

Implement the first durable runtime layer above the merged orchestration SST without changing lifecycle truth or weakening the Execution Control Plane V2 boundary.

## Runtime state boundary

Runtime state is stored outside Git. Repository files remain policy, schema, validator, and implementation truth only.

Each task contains:

- one validated immutable task contract;
- append-only hash-chained runtime records;
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

## Included implementation

- `runtime/bro_orchestration_runtime.py`
- `runtime/bro_orchestration_runtime_v1.py`
- `tests/test_orchestration_runtime.py`
- `tests/test_orchestration_runtime_claims.py`

## Out of scope

- distributed database or network queue deployment;
- Control Room API or visual UI;
- production credentials;
- external append-only evidence service;
- autonomous production release;
- BroPS changes;
- deployment or production rollout.

## Merge gate

The exact final HEAD requires Windows and Ubuntu GREEN, independent artifact audit, complete documentation inventory, no open P0/P1 findings, and Gev's explicit merge approval.

# Bro Orchestration and Control Room V1 — Scope Specification

**Status:** Phase 0 specification and SST proposal  
**Reviewed:** 2026-07-15  
**Repository:** `menqstudio/Bro`  
**Baseline:** `main` at `bec6c77f622065ee302acf23d26d4c73329a400a`  
**Branch:** `bro-orchestration-control-room-v1`

## 1. Purpose

Define the first owner-facing product layer above the merged Execution Control Plane V2 without weakening its security boundaries.

This phase covers orchestration contracts and Control Room surfaces. It does not deploy production credentials, external evidence services, or production automation.

## 2. Locked actors

- Gev is the owner and final approval authority.
- `bro-000` is the only conductor and owner-facing conversational agent.
- Specialist agents keep immutable canonical IDs.
- Builders cannot self-verify medium, high, or critical work.
- Only the canonical Push Executor may perform release transport under Release Grant V3.

## 3. Proposed orchestration SST

Create one canonical orchestration domain before runtime objects are introduced.

Proposed source:

```text
orchestration/registry.json
```

The SST must own:

- task lifecycle states and valid transitions;
- queue classes and priority rules;
- pack-selection and cross-pack task-force rules;
- checkpoint and heartbeat contracts;
- cancellation, retry, timeout, and budget policies;
- approval-request contracts;
- recovery and quarantine presentation states;
- event schemas used by Control Room read models.

No competing orchestration truth may be added to prose, analytics files, or UI code.

## 4. Task lifecycle

The initial canonical lifecycle is:

```text
draft
-> awaiting-approval | queued
-> routing
-> running
-> blocked | waiting-approval | verification | recovery-required | quarantined
-> completed | failed | cancelled
```

Every transition must bind:

- task ID;
- previous and next state;
- canonical actor ID;
- timestamp;
- reason code;
- evidence references;
- repository binding when code mutation is involved.

Unknown or impossible transitions fail closed.

## 5. Routing and task forces

Bro selects one specialist, one pack, or a cross-pack task force from canonical pack and skill registries.

A routing decision must record:

- requested capability;
- selected pack and agents;
- loaded skills;
- risk level;
- verifier requirement;
- budget and deadline;
- fallback or escalation path.

Display names never replace canonical IDs.

## 6. Checkpoints, cancellation, retries, and budgets

Long-running work must emit evidence-backed checkpoints. A checkpoint includes progress state, completed criteria, open risks, next action, freshness time, and evidence links.

Cancellation is cooperative first and fail-closed when a mutation or external effect may be in flight.

Retries require a reason code and may not reuse consumed execution leases or release nonces.

Budgets may constrain time, token usage, tool calls, retries, concurrency, and monetary cost. Exceeding a hard budget moves the task to `blocked` or `waiting-approval`.

## 7. Control Room surfaces

The owner-facing Control Room V1 contains:

1. **Mission overview** — active, queued, blocked, approval, verification, recovery, quarantined, and completed tasks.
2. **Task detail** — contract, routing, agents, skills, checkpoints, evidence, tests, approvals, recovery state, and audit timeline.
3. **Agent and pack view** — canonical identity, current task, status freshness, workload, recent outcomes, and verification separation.
4. **Approval inbox** — exact requested action, scope, risk, expiry, evidence, and approve/deny decision.
5. **Recovery and quarantine view** — original state, observed effect, proof, allowed recovery actions, and unresolved ambiguity.
6. **Audit timeline** — append-only owner-readable sequence of routing, execution, policy, evidence, verification, and release events.

Every KPI and status must provide source, freshness, drill-down, and evidence links. Unknown status is never GREEN.

## 8. Read/write boundary

Control Room is read-first.

Allowed V1 writes are limited to governed commands such as approve, deny, cancel, retry, reassign within policy, request verification, and open evidence. Each write must call canonical authorization and produce an audit event.

The UI must not directly mutate repository, credentials, evidence ledgers, or release state.

## 9. Existing analytics compatibility

Existing analytics SSTs remain canonical for metrics and dashboards:

- `analytics/metrics.json`
- `analytics/dashboards.json`
- `analytics/registry.json`

The orchestration SST owns task/event semantics. Analytics consumes those events and must not redefine lifecycle truth.

## 10. Phase plan

### Phase 0 — specification and SST proposal

- register this document;
- add orchestration domain proposal;
- define schemas and tests required for implementation;
- keep runtime behavior unchanged.

### Phase 1 — canonical orchestration contracts

- create orchestration SST and schemas;
- add validators and negative transition tests;
- define deterministic read models for Control Room.

### Phase 2 — orchestration runtime

- durable queue and routing;
- checkpoints, cancellation, retry, budgets, and escalation;
- integration with Execution Control Plane V2.

### Phase 3 — Control Room API and surfaces

- owner-facing read models and governed command endpoints;
- mission, task, agent, approval, recovery, and audit views.

### Phase 4 — shadow rollout

- replay and simulation;
- canary tasks;
- failure and recovery drills;
- monitoring and operator runbooks.

## 11. Definition of Done for this Phase 0 PR

- specification is complete and registered;
- no runtime behavior changes;
- documentation inventory and validator are current;
- exact-head Windows and Ubuntu CI are GREEN;
- PR remains unmerged until Gev explicitly approves the exact HEAD.

## 12. Out of scope

- production credential deployment;
- external append-only evidence service deployment;
- autonomous production release;
- BroPS changes;
- final visual design implementation;
- operational rollout beyond specification and contracts.

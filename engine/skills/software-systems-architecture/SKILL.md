---
id: software-systems-architecture
version: 1.1.0
status: active
---

# Software Systems Architecture

## Trigger
Use when the task decides or changes system structure: service and module boundaries, API and contract design, data-flow and consistency models, sync-vs-async and event-driven choices, failure/isolation domains, scaling and state-partition strategy, or a significant refactor/migration. Also when reviewing an ADR, resolving coupling/cohesion problems, or arbitrating a cross-component design conflict.

## Inputs
Task contract with the decision to be made and its constraints; current architecture (service map, schemas, dependency graph); non-functional requirements (latency, throughput, availability, consistency, cost); existing ADRs and interface contracts; failure and load characteristics; risk level and required output format.

## Workflow
1. Confirm identity, mode, scope, and evidence; read the affected interfaces, schemas, and existing ADRs to EOF.
2. State the problem as forces and constraints; make invariants (consistency, ordering, idempotency, backward compat) explicit.
3. Map the current boundaries and coupling; identify the blast radius and the isolation domains a change touches.
4. Produce at least two options; evaluate each against the NFRs and failure modes; name the trade-offs (coupling, latency, operability, cost, migration risk) rather than asserting one winner.
5. Design contracts explicitly: versioned interfaces, backward/forward compatibility, and a phased migration (expand/contract) that never breaks live consumers.
6. Record the decision and its consequences as an ADR; define the observable signals that would prove or disprove it.
7. Produce evidence, rollback/migration-reversal steps, and a residual-risk verdict.

## Outputs
An ADR with chosen option, rejected alternatives, and consequences; updated interface/contract definitions; a phased migration and compatibility plan; a diagram or dependency delta; residual risks and the metrics that would invalidate the decision.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Architecture proposals do not authorize implementation or data migration; those require their own grants. Ambiguous mutation targets fail closed.

## Handoffs
Escalate cross-domain decisions to the owning SST role. Implementation hands to the relevant engineering skill; schema/storage changes to Databases & Storage; rollout to DevOps/SRE. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
Success requires an ADR whose invariants and compatibility guarantees are explicit and testable, a reversible migration path, alternatives genuinely weighed, and traceability to the constraints. Unstated trade-offs or one-option decisions remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, inconsistent SSTs, or a design that breaks a live contract without a migration path. Revert the ADR/interface change to its prior state before reporting recovery and never call partial recovery GREEN.

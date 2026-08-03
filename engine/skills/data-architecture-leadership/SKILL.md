---
id: data-architecture-leadership
version: 1.1.0
status: active
---

# Data Architecture Leadership

## Trigger
Use when the task requires designing or evolving data platform structure — schema and dimensional/data-vault modeling, a warehouse/lakehouse layout, pipeline/orchestration topology, a contract or SLA between producers and consumers, partitioning/clustering strategy, CDC, or a governance decision (lineage, retention, PII classification, cost/performance trade-off).

## Inputs
Task contract with the architectural decision at stake; current schema/DDL and lineage; data volumes, growth, and query patterns; freshness/SLA and cost targets; source-system contracts; governance/retention/PII policy (SST); and required output format (design doc, DDL, or migration plan).

## Workflow
1. Confirm identity, mode grant, scope, and read the canonical data model, contracts, and governance policy to EOF.
2. Map the current state: sources, grain, lineage, ownership, and every downstream consumer that a change would break.
3. Define target modeling — layered medallion/staging→core→mart, keys and grain, SCD strategy, and idempotent load semantics; prefer additive, backward-compatible changes.
4. Specify contracts: schema with explicit types, nullability, PII tags, freshness SLA, and a versioning/deprecation policy; forbid silent breaking changes.
5. Design partitioning, clustering, and retention for the real query patterns; estimate storage/compute cost and scan volume before committing.
6. Plan migration as reversible steps: expand → backfill → dual-write/validate → contract, with a rollback at each gate; never drop columns in the same change that stops writing them.
7. Emit DDL/IaC, a lineage-updated design doc, and a data-quality test set (freshness, volume, uniqueness, referential integrity).

## Outputs
A target design doc with grain/keys/SLAs; reviewed DDL or migration scripts; producer/consumer contracts with versioning; updated lineage; cost/performance estimate; and a reversible rollout plan with rollback gates.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. No destructive DDL (DROP/TRUNCATE/type-narrowing) on shared assets, no PII declassification, and no breaking contract change without owner sign-off. Ambiguous mutation targets fail closed.

## Handoffs
Escalate metric semantics to the metric owner, security classification to Cybersecurity Operations, and irreversible migrations to the platform owner. Medium, high, and critical work requires an independent verifier. Release/DDL execution hands off only to the Push Executor.

## Verification
Success requires schema-valid DDL, passing data-quality tests, an expand-before-contract migration proven reversible in staging, lineage updated, no undeclared consumer breakage, and cost within target. A migration lacking a proven rollback stays RED.

## Failure and rollback
Stop on missing authority, undeclared consumers, failed quality tests, irreversible steps, or classification conflicts. Roll back to the pre-migration schema via the reverse step, restore the original tree, and never call a partially migrated or unvalidated model GREEN.

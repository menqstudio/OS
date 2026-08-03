---
id: databases-storage-engineering
version: 1.1.0
status: active
---

# Databases Storage Engineering

## Trigger
Use when the task designs or changes data-at-rest: schema and index design, query performance tuning, transactions and isolation levels, online schema migrations, partitioning/sharding, consistency and constraint design, connection/pool tuning, or storage-engine and caching choices. Also when diagnosing lock contention, slow queries, or data-integrity anomalies.

## Inputs
Task contract with the query/write pattern and its target (latency, integrity, or scale); current schema, indexes, and constraints; representative query plans and slow-query logs; data volume, growth, and access distribution; the engine and its isolation/durability settings; risk level and output format.

## Workflow
1. Confirm identity, mode, scope, and evidence; read the affected schema, migrations, and query paths to EOF.
2. Reproduce the problem with real query plans (EXPLAIN/ANALYZE) and representative data volume before changing anything.
3. Fix at the right layer: covering/composite indexes matched to actual predicates and sort order, query rewrites to be sargable, and constraints that enforce integrity in the database rather than only in app code.
4. Design every migration as online and reversible using expand/contract — add nullable/defaulted columns and backfill in batches, never a blocking rewrite on a hot table; write the down-migration.
5. Choose the correct isolation level for the invariant and guard against the anomalies it permits (lost update, write skew); size pools to avoid saturation.
6. Validate on a production-like dataset: re-check the query plan, migration lock behavior, and integrity constraints; measure against baseline.
7. Produce evidence, rollback/down-migration steps, and a residual-risk verdict.

## Outputs
Schema/index/query changes with before/after query plans and timings; a reversible online migration with a batched backfill and tested down-path; integrity-constraint additions; connection/isolation settings with rationale; residual risks (lock windows, hot-partition skew).

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, data deletion, external communication, or production database mutation without the exact governing grant and approval boundary. No destructive DDL, unbounded backfill, or DROP on production without the specific grant and a proven backup/rollback. Ambiguous mutation targets fail closed.

## Handoffs
Escalate cross-domain decisions to the owning SST role. Application query changes hand to the relevant engineering skill; migration rollout and backups to DevOps/SRE. Production migration execution hands off only to the Push Executor. Medium, high, and critical work requires an independent verifier.

## Verification
Success requires the improved query plan proven on production-like data, the migration shown to be online and reversible (down-path tested), integrity constraints enforced, no lock window beyond the agreed budget, clean rollback, and exact-head evidence. Migrations without a tested down-path remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, inconsistent SSTs, a blocking migration, or unverifiable integrity. Restore schema via the down-migration and confirm data integrity before reporting recovery and never call partial recovery GREEN.

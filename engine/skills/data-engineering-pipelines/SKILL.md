---
id: data-engineering-pipelines
version: 1.1.0
status: active
---

# Data Engineering Pipelines

## Trigger
Use when the task builds or fixes data movement and transformation: batch/streaming ETL/ELT, orchestration DAGs, ingestion connectors, incremental/CDC loads, data modeling for analytics (staging/marts), data-quality and freshness checks, backfills, or schema-evolution handling. Also when diagnosing a stuck DAG, duplicate/late data, or a broken downstream metric.

## Inputs
Task contract with the dataset/pipeline and its SLA (freshness, completeness, correctness); source and sink schemas and volumes; the orchestrator and transform framework in use; current DAG/transform definitions; partitioning, watermark, and late-arrival semantics; risk level and output format.

## Workflow
1. Confirm identity, mode, scope, and evidence; read the affected DAG, transforms, and schema contracts to EOF.
2. Reproduce on a sample/partition and establish a baseline for row counts, freshness, and key metrics before changing anything.
3. Make every step idempotent and safely re-runnable: partition- or watermark-scoped writes, deterministic dedup on a stable key, and no in-place mutation that a retry would double-apply.
4. Handle late and out-of-order data and schema drift explicitly; separate staging (raw, append-only) from modeled marts; parameterize backfills to a bounded window.
5. Embed data-quality gates in the pipeline — row-count/nullness/uniqueness/referential and freshness assertions — that fail the run loudly rather than silently propagating bad data.
6. Run on a bounded partition, reconcile output against the baseline and source-of-truth counts, then plan (not execute) any production backfill.
7. Produce evidence, rollback/re-run instructions, and a residual-risk verdict.

## Outputs
Idempotent DAG/transform changes; data-quality and freshness assertions with proof they catch bad input; reconciliation of output vs. source counts; a bounded backfill plan; reproducible run commands and lineage notes; residual risks (skew, late data, upstream contract drift).

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, data deletion, external communication, or production pipeline/table mutation without the exact governing grant and approval boundary. No unbounded backfill, overwrite of a production table, or connector run against live sinks without the specific grant. Ambiguous mutation targets fail closed.

## Handoffs
Escalate cross-domain decisions to the owning SST role. Storage schema/index changes hand to Databases & Storage; orchestrator infra and scheduling to DevOps/SRE; model-training consumers to LLMOps. Production backfill execution hands off only to the Push Executor. Medium, high, and critical work requires an independent verifier.

## Verification
Success requires idempotent re-runs producing identical output, data-quality gates proven to fail on bad input, output reconciled against source-of-truth counts within tolerance, freshness SLA met, a bounded reversible backfill, clean rollback, and exact-head evidence. Pipelines without quality gates remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, inconsistent SSTs, failed quality gates, or reconciliation mismatch. Halt the run, restore/re-run the affected partitions to the prior state before reporting recovery, and never call partial recovery GREEN.

---
id: devops-platform-sre
version: 1.1.0
status: active
---

# Devops Platform Sre

## Trigger
Use when the task concerns build/release automation, CI/CD pipelines, infrastructure-as-code, container/orchestration config, observability (metrics/logs/traces/alerts), SLOs and error budgets, capacity/scaling, or incident response and reliability hardening. Also when diagnosing a failing pipeline, a flaky deploy, or an alerting gap.

## Inputs
Task contract with the reliability or delivery objective; pipeline and IaC definitions; environment topology and current SLOs/alerts; deploy strategy in use (rolling, blue-green, canary) and rollback mechanism; incident timeline or failing-run logs; risk level and output format.

## Workflow
1. Confirm identity, mode, scope, and evidence; read the affected pipeline, IaC, and alert/SLO definitions to EOF.
2. Reproduce the failure or establish a baseline in a non-production environment; capture the exact failing step, logs, and config diff.
3. Make changes as reviewable, idempotent IaC/pipeline diffs — never hand-mutate live infrastructure out of band; keep them small and least-privilege.
4. Ensure every change is observable and reversible: health checks, a defined rollback/rollforward, and a canary or staged rollout with automatic abort thresholds.
5. Add or tighten the signal — SLO-based alerting on symptoms (latency/error rate/saturation), not just host metrics — and confirm alerts fire and page correctly.
6. Validate in a lower environment, then plan the production rollout as a proposal; do not execute the production deploy without the exact grant.
7. Produce evidence, rollback instructions, and a residual-risk verdict.

## Outputs
Scoped IaC/pipeline diffs; a staged rollout plan with abort thresholds and rollback steps; observability/alerting additions with proof they fire; baseline-vs-after reliability/latency evidence; reproducible commands; residual risks and error-budget impact.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, production deploy, infrastructure deletion, external communication, or environment mutation without the exact governing grant and approval boundary. No `terraform apply`, cluster mutation, or teardown against production without the specific grant. Ambiguous mutation targets fail closed.

## Handoffs
Escalate cross-domain decisions to the owning SST role. Application-level fixes hand to the relevant engineering skill; schema/data migration to Databases & Storage. Production deploy and push hand off only to the Push Executor. Medium, high, and critical work requires an independent verifier.

## Verification
Success requires the change validated in a lower environment, rollback proven, alerts confirmed firing on the target symptom, staged rollout with abort thresholds defined, no SLO/error-budget regression, clean revert, and exact-head evidence. Unrehearsed rollback or unproven alerts remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, inconsistent SSTs, failed lower-env validation, or unverifiable rollback. Restore infra/pipeline state to the prior known-good revision before reporting recovery and never call partial recovery GREEN.

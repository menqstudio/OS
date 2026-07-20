---
id: auditing
version: 1.0.0
status: active
---

# Auditing

## Trigger
Use this skill when a task materially requires auditing expertise.

## Inputs
A bounded task contract, repository evidence, constraints, risk level, and required output format.

## Workflow
1. Confirm identity, mode grant, task scope, and required evidence.
2. Read the canonical SST and relevant source files to EOF.
3. Reproduce defects or establish a baseline before mutation.
4. Make the smallest scoped change and preserve append-only identifiers.
5. Run registered validation and negative tests.
6. Produce evidence, rollback instructions, and an explicit residual-risk verdict.

## Outputs
A scoped implementation or analysis, reproducible commands, evidence paths, verification results, and residual risks.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Ambiguous mutation targets fail closed.

## Handoffs
Escalate cross-domain decisions to the owning SST role. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
Success requires schema-valid artifacts, registered tests, exploit regression coverage, clean rollback, and exact-head evidence. Claims without reproducible evidence remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, inconsistent SSTs, failed tests, or unverifiable state. Restore the original tree before reporting recovery and never call partial recovery GREEN.

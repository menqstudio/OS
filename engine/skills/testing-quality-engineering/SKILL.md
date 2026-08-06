---
id: testing-quality-engineering
version: 1.1.0
status: active
---

# Testing Quality Engineering

## Trigger
Use when the task designs or strengthens automated verification: unit/integration/e2e test design, coverage of a specific defect, flaky-test diagnosis, test-data and fixture strategy, contract/property-based testing, mutation testing, or CI test-gate tuning. Also when a bug must be locked behind a regression test before it can be called fixed.

## Inputs
Task contract with the behavior or defect under test and its acceptance criteria; the code under test and its dependencies; existing test suites, fixtures, and CI config; a reproduction of the defect if one exists; the test framework and coverage baseline; risk level and output format.

## Workflow
1. Confirm identity, mode, scope, and evidence; read the code under test and existing tests to EOF.
2. For a defect, write a failing test that reproduces it first (red) and confirm it fails for the right reason before any fix.
3. Choose the test level deliberately — unit for logic, integration for boundaries/contracts, e2e only for critical user paths — and follow the test pyramid rather than piling on brittle e2e.
4. Cover the risk surface: boundaries, error paths, concurrency/ordering, and adversarial inputs; use property-based or table-driven cases where the input space is large.
5. Make tests deterministic and isolated: control time, randomness, and I/O; remove order-dependence and shared mutable state to kill flakiness at the source.
6. Run the suite, measure meaningful coverage of the changed lines/branches, and quarantine or fix any flaky test rather than retrying it.
7. Produce evidence, rollback instructions, and a residual-risk verdict.

## Outputs
New/updated deterministic tests including a regression test per fixed defect; coverage delta on changed code; flakiness diagnosis and fix; reproducible test commands and results; residual risks (untested paths, environmental coupling).

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Tests must not call live external services with real credentials or mutate production data. Ambiguous mutation targets fail closed.

## Handoffs
Escalate cross-domain decisions to the owning SST role. Code fixes hand to the relevant engineering skill; CI-gate/pipeline wiring to DevOps/SRE. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
Success requires the regression test failing before and passing after the fix, deterministic re-runs (no flakiness across repeated runs), meaningful branch coverage of the changed code, negative/adversarial cases present, clean rollback, and exact-head evidence. Coverage numbers without asserted behavior remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, inconsistent SSTs, non-deterministic tests, or a test that passes without exercising the target behavior. Restore the prior test suite before reporting recovery and never call partial recovery GREEN.

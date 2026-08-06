---
id: product-project-management
version: 1.1.0
status: active
---

# Product Project Management

## Trigger
Use this skill when the task requires product or delivery planning: writing a PRD or spec, prioritizing a backlog/roadmap, defining success metrics, scoping an MVP, sequencing a project plan with dependencies and critical path, managing scope/risk, or driving a launch/release to a definition of done.

## Inputs
The problem statement and target users/segment; business objective and success metrics; existing backlog, roadmap, and constraints; effort/estimate and capacity data; dependencies and known risks; the decision-maker, timeline, and definition of done; and the required output format.

## Workflow
1. Confirm identity, mode grant, the outcome to be achieved, its owner, and the fixed vs flexible constraints (scope, time, resources).
2. Read the existing spec, backlog, and roadmap SSTs to EOF; establish the current plan-of-record baseline.
3. Write the problem and success metric before the solution — define the user, the job-to-be-done, and the measurable outcome that signals success.
4. Prioritize with an explicit framework (RICE/impact-effort/WSJF) tied to the objective; scope an MVP that tests the riskiest assumption cheapest.
5. Build the delivery plan: work breakdown, estimates, dependency map, critical path, milestones, and the definition of done and acceptance criteria per item.
6. Surface risks and unknowns with mitigations and decision points; set the review cadence and the change-control rule for scope.
7. Produce the spec/plan, prioritized backlog, and residual-risk verdict.

## Outputs
A PRD/spec with problem, users, success metrics, and non-goals; a prioritized backlog/roadmap with the scoring framework shown; a delivery plan with dependencies, critical path, milestones, and per-item acceptance criteria/DoD; a risk register with mitigations; and a residual-risk statement.

## Safety limits
Planning and coordination only; does not authorize scope, commit dates externally, ship, or reallocate people. No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Do not make external launch commitments. Ambiguous mutation targets fail closed.

## Handoffs
Escalate strategic tradeoffs to business-strategy-operations, pricing/packaging of the release to pricing-packaging-strategy, and ROI modeling to finance-unit-economics. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
The success metric and non-goals are defined before the solution; prioritization traces to the objective via a stated framework; every backlog item has acceptance criteria; the plan has a dependency map and identified critical path; risks carry mitigations and decision points. Claims without reproducible evidence remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, an undefined outcome or owner, solutions without a success metric, or items without acceptance criteria. Revert to the plan of record and never call a metric-less or acceptance-criteria-less plan GREEN.

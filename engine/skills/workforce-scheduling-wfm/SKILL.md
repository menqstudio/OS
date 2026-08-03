---
id: workforce-scheduling-wfm
version: 1.1.0
status: active
---

# Workforce Scheduling Wfm

## Trigger
Use this skill when the task requires forecasting workload, computing staffing requirements, building shift/roster schedules, planning breaks and intraday coverage, sizing headcount to a service level, or managing adherence, shrinkage, and overtime against labor budget — in contact centers, retail, healthcare, or operations teams.

## Inputs
Interval-level volume/workload history and forecast; average handle time or task duration; target service level, occupancy, or coverage ratio; staff roster with skills, contracts, availability, and cost; shrinkage assumptions (breaks, training, absence); labor rules (max hours, rest, fairness) and budget; and the required output format.

## Workflow
1. Confirm identity, mode grant, the planning horizon and interval, and the governing service-level/coverage target.
2. Read volume history, AHT, and roster data to EOF; establish baseline service level, occupancy, and shrinkage.
3. Forecast workload per interval accounting for seasonality, trend, and known events; separate volume from handle time.
4. Compute required staffing per interval with the correct model — Erlang C/A for queued arrival work, coverage ratios for task/appointment work — and gross up for shrinkage explicitly.
5. Build schedules that meet interval requirements while respecting hard labor rules (max hours, minimum rest, contract terms) and fairness; minimize over/understaffing and overtime.
6. Stress the plan against a volume-spike and an absence scenario; identify intervals that breach coverage and the flex/overtime needed.
7. Produce the staffing plan, schedule, and residual-risk verdict.

## Outputs
Interval-level required vs scheduled staffing with the service model used; a compliant shift roster respecting labor rules and fairness; a shrinkage-adjusted headcount number; over/under-coverage and overtime exposure with spike/absence scenarios; and a residual-risk statement.

## Safety limits
Planning recommendation only; does not publish rosters, assign shifts to individuals as binding, or notify staff. No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production/WFM-system mutation without the exact governing grant and approval boundary. Never violate legal rest/max-hours rules or contractual terms. Ambiguous mutation targets fail closed.

## Handoffs
Escalate field routing to field-service-dispatch-ops, labor-cost/budget impact to finance-unit-economics, and hiring decisions to the accountable owner. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
Required staffing uses the correct model for the work type and is grossed up for shrinkage; every scheduled shift respects max-hours, rest, and contract rules; interval coverage meets the target including the spike/absence scenarios; overtime stays within budget. Claims without reproducible evidence remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, a service model mismatched to the work, shrinkage omitted, or schedules breaching labor law. Revert to the current roster of record and never call an under-covered or non-compliant schedule GREEN.

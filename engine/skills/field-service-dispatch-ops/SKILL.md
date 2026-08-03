---
id: field-service-dispatch-ops
version: 1.1.0
status: active
---

# Field Service Dispatch Ops

## Trigger
Use this skill when the task requires routing and dispatching field technicians or vehicles, assigning jobs to skills and territories, sequencing appointments within time windows and SLAs, handling emergency/reactive insertions, or optimizing travel, first-time-fix, and on-time-arrival against labor cost.

## Inputs
The job queue with location, priority, SLA/appointment window, required skills, parts, and duration; technician roster with skills, certifications, shift, start location, and capacity; travel-time matrix or traffic model; parts/truck-stock availability; SLA definitions and penalty structure; and the required output format.

## Workflow
1. Confirm identity, mode grant, the dispatch horizon (live vs next-day), and the governing SLA/priority rules.
2. Read the job queue, roster, and travel/skills data to EOF; establish baseline on-time %, first-time-fix, and utilization.
3. Enforce hard constraints first — skills/certification match, parts availability, appointment windows, shift and legal duty/drive-time limits — before optimizing anything soft.
4. Build routes minimizing travel and SLA-breach risk while balancing utilization; sequence within time windows and leave buffer for overruns.
5. Reserve capacity for reactive/emergency insertions and define the bump rule: which lower-priority jobs yield and how customers are re-slotted.
6. Verify each assignment has the right skill, parts on the truck, and a feasible ETA; flag jobs that cannot meet SLA rather than silently overbooking.
7. Produce the dispatch plan, exception/at-risk list, and residual-risk verdict.

## Outputs
A technician-by-technician route and sequence with ETAs; a skill/parts feasibility check per job; an SLA-at-risk and unassignable-job exception list; a utilization and expected on-time/first-time-fix projection; the emergency-insertion reserve and bump rule; and a residual-risk statement.

## Safety limits
Planning recommendation only; does not dispatch, notify technicians or customers, or commit schedules. No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production/dispatch-system mutation without the exact governing grant and approval boundary. Never send customer/technician notifications or override duty-time/safety limits. Ambiguous mutation targets fail closed.

## Handoffs
Escalate shift capacity and labor rules to workforce-scheduling-wfm, parts/truck-stock shortfalls to supply-chain-inventory. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
Every assignment satisfies skills, parts, appointment window, and duty/drive-time limits; ETAs are feasible on the travel model; SLA-at-risk jobs are flagged not hidden; emergency reserve and bump rule are defined; utilization stays within legal shift bounds. Claims without reproducible evidence remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, assignments violating skills/parts/duty-time, or silent SLA breaches. Revert to the prior dispatch plan of record and never call an infeasible or safety-violating plan GREEN.

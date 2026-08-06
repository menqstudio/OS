---
id: operating-data-roles
version: 1.1.0
status: active
---

# Operating Data Roles

## Trigger
Use when the task concerns the data function's operating model — RACI and ownership between data engineering, analytics engineering, analytics/DS, and platform; on-call and incident ownership for pipelines; data-product stewardship; SLA/SLO definition; access governance; or resolving who owns a dataset, metric, or failing job.

## Inputs
Task contract naming the operational question; current role/ownership map and RACI (SST); data-product and pipeline inventory with owners; SLA/SLO and on-call policy; access-control and data-classification policy; incident and escalation runbooks; and required output format (RACI, runbook, or ownership decision).

## Workflow
1. Confirm identity, mode grant, and scope; read the ownership map, RACI, and operating policies to EOF.
2. Inventory the assets, pipelines, and data products in scope and their current declared owners, consumers, and SLAs.
3. Identify gaps and overlaps: unowned datasets, orphaned jobs, duplicated responsibility, or SLAs with no accountable role.
4. Assign each responsibility to exactly one accountable role with clear responsible/consulted/informed parties; avoid diffused ownership that produces on-call ambiguity.
5. Define or tighten SLOs (freshness, completeness, availability) with measurable thresholds, monitoring, and an escalation path per data product.
6. Align access grants to role and data classification on least-privilege; flag any standing broad grant for review rather than widening access.
7. Emit the updated RACI/runbook with owners, SLOs, escalation, and a change log; socialize deltas to affected teams via the sanctioned channel.

## Outputs
An updated ownership map/RACI with a single accountable owner per asset; per-data-product SLOs with monitoring and escalation; a least-privilege access alignment; identified gaps with assigned remediation; and a change log.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. This skill defines operating structure; it does not grant access, page people, or reassign ownership in live systems without the owning parties' approval. No privilege escalation or broadening of access under the guise of clarification. Ambiguous ownership fails closed to escalation.

## Handoffs
Escalate contested ownership to the data leadership owner, access changes to Cybersecurity Operations, and schema implications to Data Architecture Leadership. Medium, high, and critical changes require an independent verifier. Any system-level grant or change hands off only to the Push Executor.

## Verification
Success requires every in-scope asset mapped to exactly one accountable owner, SLOs measurable and monitored, access consistent with least-privilege and classification, and affected teams acknowledging the change. An asset left unowned or an SLO with no monitor stays RED.

## Failure and rollback
Stop on missing authority, unresolved ownership conflict, or an access change lacking approval. Revert the RACI/policy to its prior committed version, restore the original record, and never publish an ownership model with unowned assets or unapproved access grants as GREEN.

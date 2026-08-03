---
id: regulatory-telecom-licensing
version: 1.1.0
status: active
---

# Regulatory Telecom Licensing

## Trigger
Use for telecom regulatory and licensing tasks — assessing license conditions and scope, spectrum authorization, interconnection and numbering obligations, universal-service/lawful-intercept/data-retention duties, tariff and reporting filings, or a compliance gap analysis against a regulator's rules for a specific jurisdiction. Not for general legal advice outside telecom regulation.

## Inputs
Task contract with the regulatory question and jurisdiction; the operator's license(s) and their conditions; applicable regulator rules, spectrum grants, and filing calendars; the compliance register and prior findings (SST); the fact pattern (services, coverage, technology); and required output format (compliance memo, filing checklist, or gap analysis).

## Workflow
1. Confirm identity, mode grant, and scope; read the license conditions, applicable rules, and compliance register to EOF — jurisdiction and license class govern everything downstream.
2. Pin the exact jurisdiction, regulator, license class, and effective rule versions/dates; regulatory obligations are date- and geography-specific and must not be generalized.
3. Map the fact pattern to each applicable obligation: authorized service scope, spectrum/technical limits, interconnection, numbering, USO, lawful intercept, data retention, consumer protection, and reporting deadlines.
4. Identify gaps and deadlines: where current operations exceed license scope, breach a condition, or miss a filing; rate each by regulatory severity and exposure (penalty, suspension, enforcement).
5. Cite the specific rule/section and license clause for every obligation and finding; never assert a requirement without a traceable regulatory source.
6. Draft the required output (filing checklist, remediation plan, or memo) as advisory; flag that legal review and the licensee's authorized signatory are required before any submission.
7. Emit the compliance artifact with obligations, gaps, severity, deadlines, and cited sources.

## Outputs
A jurisdiction-specific compliance memo/gap analysis mapping obligations to the operation; cited license clauses and rule sections; severity-rated gaps with deadlines and exposure; a filing/remediation checklist; and explicit flags for required legal review and authorized sign-off.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. No regulatory filing, submission, or communication with a regulator, and no legal opinion issued as authoritative, without the exact grant and licensee/legal authorization. Do not generalize obligations across jurisdictions or assert an uncited requirement. Ambiguity fails closed to escalation.

## Handoffs
Escalate binding legal interpretation and any regulator submission to the licensee's legal counsel and authorized signatory; escalate technical/spectrum specifics to Telecom ISP Network Ops. Medium, high, and critical analyses require an independent verifier of the citations. Any external filing or communication hands off only to the Push Executor with explicit authorization.

## Verification
Success requires every obligation and finding traceable to a cited license clause or rule section with the correct jurisdiction and effective date, deadlines confirmed against the current filing calendar, and legal-review flags present. An uncited requirement or a jurisdiction/date mismatch stays RED.

## Failure and rollback
Stop on missing authority, wrong or ambiguous jurisdiction, an uncited obligation, or any pressure to file without authorization. Withdraw the affected conclusion, restore the prior compliance record, and never present an unsourced or unauthorized regulatory action as GREEN.

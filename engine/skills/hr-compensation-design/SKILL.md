---
id: hr-compensation-design
version: 1.1.0
status: active
---

# HR Compensation Design

## Trigger
Use when the task is to design or evaluate compensation structure: leveling frameworks, salary bands, pay-mix (base/bonus/equity), geo differentials, offer construction, merit/promotion cycles, pay-equity analysis, or sales commission plans. Do NOT use for individual performance-management coaching (route to people-org-leadership) or binding employment-contract language (route to legal-compliance-contracts).

## Inputs
- Role, level, location, and job architecture/leveling definitions.
- Market data source and percentile target (e.g., 50th/75th), and the compensation philosophy (lead/match/lag).
- Budget/merit pool, current pay of affected population, and pay-equity constraints.
- For variable pay: quota/OTE targets, accelerators, caps, and payout mechanics.

## Workflow
1. Anchor to job architecture: confirm the level and its scope/impact definition before touching numbers; comp follows leveling, never the reverse.
2. Benchmark against the stated market source and percentile; adjust for geo and function; document the data vintage.
3. Construct or validate the band (min/mid/max), targeting the philosophy; check band overlap between adjacent levels is intentional.
4. Set pay mix appropriate to role (higher variable for sales/exec, higher base for eng/ops); model total-comp not just base.
5. Run pay-equity check: compare like-for-like (level, location, tenure) across gender/ethnicity where data permits; flag unexplained gaps for remediation before finalizing.
6. Model cost: individual offer/change × affected population against budget; show merit-pool impact and compression risks.
7. For commission plans: verify plan pays for the right behavior, has no perverse incentive, defines quota relief and clawback, and caps only where deliberate.

## Outputs
- Band structure or offer recommendation with market rationale and percentile positioning.
- Pay-mix and total-comp model with budget/cost impact.
- Pay-equity findings and remediation flags.
- Commission plan mechanics (OTE, accelerators, caps, clawback) where applicable.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Never expose individual compensation data beyond the grant, extend binding offers, or alter payroll. Treat all comp data as confidential PII. Do not invent market benchmarks. Ambiguous mutation targets fail closed.

## Handoffs
Binding offer letters and employment terms to legal-compliance-contracts. Performance calibration and manager coaching to people-org-leadership. Sales-quota strategy to sales-revenue-growth. Escalate cross-domain decisions to the owning SST role; medium, high, and critical work requires an independent verifier; any offer/payroll action hands off only to the authorized executor.

## Verification
Confirm every number traces to a cited market source and stated percentile; bands respect leveling and intended overlap; pay-equity check ran and gaps are flagged; cost model reconciles to budget; commission plans have no unbounded or perverse payout. Comp figures without a benchmark source remain RED.

## Failure and rollback
Stop on missing leveling, absent market data, undefined budget, or a request to finalize offers/payroll without grant. Discard the model, restore prior figures, and report the missing input. Never present an unbenchmarked or equity-unchecked structure as final or GREEN.

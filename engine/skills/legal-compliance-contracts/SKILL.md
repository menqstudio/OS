---
id: legal-compliance-contracts
version: 1.1.0
status: active
---

# Legal Compliance Contracts

## Trigger
Use when the task is to review, redline, or draft contract language (MSA, SOW, NDA, DPA, order forms), assess a compliance obligation (privacy, data protection, export, licensing), or map a policy requirement to controls. Produces analysis and proposed language only. Do NOT use for final legal advice, signing authority, or as a substitute for qualified counsel — always flag for attorney review.

## Inputs
- The contract/clause or regulation text, and the party you represent.
- Deal context: value, term, data flows, jurisdiction/governing law, and risk appetite.
- Standard positions/playbook: fallback positions, non-negotiables, and approval thresholds.
- Applicable regimes named (e.g., GDPR/CCPA, SOC 2, DORA, sector rules) — do not assume.

## Workflow
1. Identify document type, governing law, and which party's interest you protect; note anything outside your grant.
2. Read the operative clauses to the end: liability cap and carve-outs, indemnity, IP ownership/license, warranty/disclaimer, termination, data protection, and limitation of liability — the high-risk core.
3. Redline against the playbook: flag each clause as acceptable / negotiate / reject, with the specific risk and a proposed fallback in plain language.
4. For compliance: map the obligation to the named regime, identify the concrete control or contractual term that satisfies it, and flag gaps; cite the regime, not memory, and mark uncertainty.
5. Check cross-references and defined terms for internal consistency; a term redefined elsewhere is a common trap.
6. Separate legal-material issues (liability, IP, data, indemnity) from commercial preferences; prioritize the former.
7. Produce a redline summary with risk ranking and an explicit "requires qualified counsel sign-off" flag on anything binding.

## Outputs
- Clause-by-clause redline with risk rating, rationale, and proposed alternative language.
- Compliance gap analysis mapping obligations to controls/terms, with citations.
- Prioritized issues list (material vs. commercial) and open questions for counsel.
- Explicit statement that output is analysis, not legal advice, pending attorney review.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Never sign, execute, or bind the organization; never send to a counterparty; never state legal conclusions as final advice. Do not fabricate statutes, case law, or clause citations. Ambiguous mutation targets fail closed.

## Handoffs
Final approval and signature to qualified counsel and the authorized signatory. Compensation/employment terms to hr-compensation-design. Commercial negotiation strategy to communication-writing-negotiation or sales-revenue-growth. Escalate cross-domain decisions to the owning SST role; medium, high, and critical work requires an independent verifier; execution/send hands off only to the authorized executor.

## Verification
Confirm every cited statute/clause exists and is quoted accurately (no invented authority), risk ratings cover the material core (liability, IP, indemnity, data, termination), defined terms are internally consistent, and the counsel-review flag is present on binding items. Any legal citation not verifiable in source remains RED.

## Failure and rollback
Stop on missing governing law, absent playbook thresholds, unverifiable citations, or a request to execute/send without grant. Discard the redline, restore the original text, and report the blocker with the missing input named. Never present contract analysis as executed, final, or GREEN without counsel sign-off.

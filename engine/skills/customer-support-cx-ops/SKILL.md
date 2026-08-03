---
id: customer-support-cx-ops
version: 1.1.0
status: active
---

# Customer Support CX Ops

## Trigger
Use when the task is to design or improve support operations: macros/canned replies, triage and routing rules, tiering and escalation paths, SLA/queue design, deflection via help content, CSAT/QA rubrics, or root-cause analysis of a ticket spike. Also for drafting individual high-stakes customer responses (outage, churn-risk, refund dispute). Do NOT use for outbound sales/upsell motions (route to sales-revenue-growth).

## Inputs
- Ticket/issue detail, customer tier/entitlement, sentiment, and prior interaction history.
- Current queue metrics: volume by category, first-response time, resolution time, backlog, CSAT/DSAT drivers.
- Policy boundaries: refund/credit limits, entitlements, what requires approval.
- Product/known-issue status and any active incident.

## Workflow
1. Classify the contact: category, severity, customer tier, and whether it maps to a known issue or active incident.
2. For a single reply: acknowledge and empathize, state what you know and don't, give the concrete next step with a timeline, and set expectation on follow-up — never over-promise resolution you can't guarantee.
3. For ops design: pull the top contact drivers by volume × handle time × CSAT impact; attack the highest-leverage driver first.
4. Design triage/routing so severity and entitlement map deterministically to tier and SLA; define explicit escalation triggers and owners.
5. Build deflection where root cause is documentation or UX: propose help-center content or in-product fix, not just a faster macro.
6. Instrument QA: a scored rubric (accuracy, tone, resolution, compliance) and a CSAT/DSAT feedback loop that routes systemic defects to product.
7. Close the loop: recommend the permanent fix for recurring drivers, not only the reactive patch.

## Outputs
- Customer-ready reply drafts (empathy + facts + next step + timeline), never auto-sent.
- Macros, triage/routing rules, SLA and escalation matrices.
- Contact-driver analysis with prioritized remediation and deflection proposals.
- QA rubric and CSAT instrumentation plan.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Never send messages to customers, issue refunds/credits, or alter entitlements without the exact grant. Do not expose other customers' data or invent policy. Ambiguous mutation targets fail closed.

## Handoffs
Product defects and recurring root causes to the owning product/eng role. Billing or legal disputes beyond policy to legal-compliance-contracts. Expansion/renewal opportunities surfaced in-ticket to sales-revenue-growth. Escalate cross-domain decisions to the owning SST role; medium, high, and critical work requires an independent verifier; refund/send actions hand off only to the authorized executor.

## Verification
Confirm replies are factually grounded, promise only what policy permits, and include a timed next step; triage rules are deterministic and cover the edge cases; remediation targets the highest-leverage driver by data; no unauthorized refund or send. Unsupported policy claims or promised resolutions without backing remain RED.

## Failure and rollback
Stop on missing policy limits, unknown entitlement, request to auto-send, or an active incident without confirmed status. Discard the draft, restore prior state, and report the blocker. Never mark a customer promise or ops change GREEN without evidence it holds.

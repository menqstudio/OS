---
id: business-strategy-operations
version: 1.1.0
status: active
---

# Business Strategy Operations

## Trigger
Use this skill when the task requires a strategic or operating decision: market entry/exit, build-buy-partner, portfolio prioritization, org or process redesign, OKR/goal cascade, capacity or resource allocation, or turning a strategy into a measurable operating plan with owners and metrics.

## Inputs
The decision or objective and its constraints; market, competitive, and customer evidence; current P&L and operating metrics; capacity and headcount data; existing goals/OKRs and their status; the decision-maker, timeframe, and success criteria; and the required output format.

## Workflow
1. Confirm identity, mode grant, the exact decision to be made, its owner, and the reversibility/risk class before analyzing.
2. Read the canonical strategy and operating SSTs to EOF; establish the current-state baseline with quantified metrics, not adjectives.
3. Frame the decision explicitly: options, the "do nothing" counterfactual, and the criteria and weights that separate them.
4. Test each option against evidence — market size and growth, competitive response, capability fit, unit economics, and execution risk — and record disconfirming evidence, not just supporting.
5. Translate the chosen option into an operating plan: outcome metrics, leading indicators, owners, sequencing, dependencies, and a resourcing envelope.
6. Define the review cadence and the pre-committed kill/scale criteria so the bet is falsifiable.
7. Produce a decision memo with recommendation, rationale, plan, and residual-risk verdict.

## Outputs
A structured decision memo (options, criteria, recommendation, counterfactual); a current-state baseline with metrics; an operating plan with owners, sequencing, dependencies, and leading/lagging indicators; pre-committed review and kill/scale thresholds; and a residual-risk statement.

## Safety limits
Recommends; does not authorize spend, hiring, reorgs, or commitments. No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Do not commit the organization to external parties. Ambiguous mutation targets fail closed.

## Handoffs
Escalate financial modeling to finance-unit-economics, pricing to pricing-packaging-strategy, and execution planning to product-project-management. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
The decision, owner, and criteria are explicit; the baseline is quantified; the recommendation is traceable to weighted criteria and cited evidence including disconfirming data; every plan item has an owner and a metric; kill/scale thresholds are pre-committed. Claims without reproducible evidence remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, an undefined decision or owner, or recommendations unsupported by evidence. Withdraw the recommendation, restore the prior plan of record, and never call an unfalsifiable or owner-less plan GREEN.

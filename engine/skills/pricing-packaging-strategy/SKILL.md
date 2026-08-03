---
id: pricing-packaging-strategy
version: 1.1.0
status: active
---

# Pricing Packaging Strategy

## Trigger
Use this skill when the task requires setting or changing price points, the pricing metric/value axis, tier/package structure, discounting or usage bands, freemium/trial gates, or when a price change, monetization model, or packaging redesign must be justified against willingness-to-pay and margin.

## Inputs
Current price list, tiers, and packaging; the pricing metric (seat, usage, outcome, flat); segment-level willingness-to-pay or survey data; COGS and contribution margin per unit; competitor price points and value framing; win/loss and discount-realization data; and the objective (growth, margin, expansion) with required output format.

## Workflow
1. Confirm identity, mode grant, the objective (acquisition vs expansion vs margin), and which segments are in scope.
2. Read current pricing, margin, and realization data to EOF; establish effective (post-discount) price and margin per segment as the baseline.
3. Choose the pricing metric deliberately — it should scale with realized customer value and be predictable to the buyer; test whether the current metric penalizes adoption.
4. Design packaging with a clear good/better/best value ladder: fence tiers on features that map to segment value, avoid feature overlap that erodes upsell, and set an anchor and a target tier.
5. Set price points from willingness-to-pay bands (e.g., Van Westendorp / conjoint or observed win rates), not cost-plus alone; verify each tier clears its contribution-margin floor.
6. Model the change: migration path for existing customers, expected mix shift, discount guardrails, and revenue/margin impact with a downside case.
7. Produce the pricing/packaging proposal, migration plan, and residual-risk verdict.

## Outputs
A pricing and packaging proposal (metric, tiers, fences, price points, anchors); effective-price and margin baseline vs proposed; a WTP/win-rate justification per segment; an existing-customer migration and discount-guardrail plan; a revenue/margin impact model with downside; and a residual-risk statement.

## Safety limits
Proposal only; does not publish prices, change billing, or grant discounts. No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production/billing-system mutation without the exact governing grant and approval boundary. Do not alter live price books or customer contracts. Ambiguous mutation targets fail closed.

## Handoffs
Escalate margin/LTV modeling to finance-unit-economics, incentive-rule effects to economics-market-design, and rollout execution to product-project-management. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
The pricing metric scales with value and is buyer-predictable; tiers are fenced without upsell-eroding overlap; every price point clears its margin floor and is backed by WTP or win-rate evidence; the migration plan covers existing customers; the impact model includes a downside case. Claims without reproducible evidence remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, cost-plus-only pricing, tiers below margin floor, or a change with no migration path. Revert to the current price book and never call an unjustified or margin-dilutive proposal GREEN.

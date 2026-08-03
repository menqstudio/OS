---
id: finance-unit-economics
version: 1.1.0
status: active
---

# Finance Unit Economics

## Trigger
Use this skill when the task requires modeling per-unit or per-cohort profitability: CAC, LTV, payback, contribution margin, gross margin, churn/retention, magic number, burn multiple, or a driver-based revenue/cost model — or when a pricing, growth, or fundraising decision hinges on whether the unit economics close.

## Inputs
Revenue and cost ledgers by product/segment; cohort acquisition, retention, and expansion data; blended and paid CAC by channel; COGS build and gross-margin definition; discount rate and time horizon; the unit of analysis (customer, order, seat, account); and the decision the model must inform with its required output format.

## Workflow
1. Confirm identity, mode grant, the unit of analysis, time horizon, and which margin definition (gross vs contribution) governs.
2. Read the source ledgers and cohort exports to EOF; establish an actuals baseline before projecting.
3. Build LTV from retained gross margin per cohort, not revenue — decay retention on observed curves, discount future periods, and cap the horizon explicitly rather than assuming infinite life.
4. Compute CAC as fully-loaded acquisition spend (media + sales + onboarding) over new units in the same period; keep blended and paid separate.
5. Derive LTV:CAC, CAC payback in months, contribution margin, and burn multiple; state every assumption inline and tie each driver to a source cell.
6. Run sensitivity on the three highest-leverage drivers (retention, CAC, price/margin) and show break-even thresholds.
7. Produce the model, a one-page verdict on whether economics close, and the assumptions/risk log.

## Outputs
A driver-based model with a labeled assumptions block; LTV, CAC, LTV:CAC, payback, contribution and gross margin, and burn multiple by cohort/segment; a sensitivity table with break-even thresholds; source cell references; and a residual-risk statement on data sufficiency and horizon.

## Safety limits
Analytical only; produces projections, not booked figures. No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Do not present modeled or projected numbers as audited actuals. Ambiguous mutation targets fail closed.

## Handoffs
Escalate accounting-basis or recognition questions to accounting-bookkeeping-tax; escalate pricing decisions to pricing-packaging-strategy. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
Every metric recomputes from the source ledger; cohort retention ties to raw counts; LTV uses margin not revenue and a stated finite horizon; CAC and LTV cover the same population; sensitivity ranges bracket the base case. Claims without reproducible evidence remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, mismatched CAC/LTV populations, infinite-horizon LTV, or unsourced drivers. Revert to the actuals baseline, discard the projection, and never call an unvalidated or population-mismatched model GREEN.

---
id: economics-market-design
version: 1.1.0
status: active
---

# Economics Market Design

## Trigger
Use this skill when the task requires designing or auditing the rules of a market or mechanism: matching, auctions, two-sided platform incentives, referral/rewards programs, credit/token systems, reputation or ranking rules, congestion pricing, or any allocation rule where participants respond strategically and incentive compatibility, efficiency, or gaming risk is in question.

## Inputs
The allocation objective and the goods/agents involved; participant preferences, budgets, and outside options; current rules, fees, and matching/ranking logic; observed behavior and any gaming or thin-market symptoms; fairness, liquidity, and stability constraints; and the required output format.

## Workflow
1. Confirm identity, mode grant, the objective (efficiency, fairness, revenue, liquidity), and the constraints that trade off against it.
2. Read the current mechanism spec and behavioral data to EOF; model each side's strategy set and best response.
3. Diagnose failure modes explicitly: misaligned incentives, thin/congested markets, unraveling, adverse selection, and profitable manipulation strategies.
4. Design or adjust the rule against known-good properties — incentive compatibility (truthful reporting), individual rationality, stability/no-blocking-pairs, and budget balance — naming which properties you keep and which you knowingly trade.
5. Stress-test the rule against strategic play: find the most profitable deviation and confirm it is unprofitable or bounded; check thick- and thin-market regimes.
6. Specify safeguards — reserve prices, rate limits, eligibility, tie-breaks, anti-collusion — and a monitoring metric per failure mode.
7. Produce the mechanism spec, the property/tradeoff ledger, and a residual-risk verdict.

## Outputs
A precise mechanism specification (rules, fees, matching/ranking logic, tie-breaks); a property ledger stating which incentive properties hold and which are traded; a manipulation analysis with the best deviation and its bound; monitoring metrics per failure mode; and a residual-risk statement.

## Safety limits
Design and analysis only; does not launch, price, or change any live market. No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Do not alter live incentive parameters or payouts. Ambiguous mutation targets fail closed.

## Handoffs
Escalate money-in/money-out pricing to pricing-packaging-strategy and unit-economics impact to finance-unit-economics. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
The objective and traded-off constraints are explicit; each claimed property (IC, IR, stability, budget balance) is demonstrated, not asserted; the most profitable deviation is identified and shown bounded; safeguards map one-to-one to named failure modes. Claims without reproducible evidence remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, an unstated objective, or a property claimed without proof and with an unbounded profitable deviation. Revert to the documented current mechanism and never call a manipulable or unproven design GREEN.

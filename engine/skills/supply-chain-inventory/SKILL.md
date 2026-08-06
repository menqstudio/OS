---
id: supply-chain-inventory
version: 1.1.0
status: active
---

# Supply Chain Inventory

## Trigger
Use this skill when the task requires demand/supply planning, inventory policy (reorder point, safety stock, EOQ), replenishment, allocation across locations, stockout or excess/obsolete remediation, supplier lead-time risk, or setting service-level targets against holding cost.

## Inputs
SKU-level demand history and forecast; on-hand, in-transit, and allocated inventory by location; supplier lead times and their variability; unit cost, holding-cost rate, and stockout/backorder penalty; MOQs, lot sizes, and shelf-life/perishability; target service level or fill rate; and the required output format.

## Workflow
1. Confirm identity, mode grant, the SKUs/locations in scope, and the governing service-level target.
2. Read demand, inventory, and lead-time data to EOF; establish current fill rate, turns, and days-of-supply as the baseline.
3. Characterize demand (mean, variability, seasonality, intermittency) and lead-time variability separately — safety stock must cover both, not demand alone.
4. Set safety stock from the service-level z-score and combined demand+lead-time variance; compute reorder point (lead-time demand + safety stock) and an order quantity respecting EOQ, MOQ, and lot size.
5. Classify SKUs (ABC/XYZ) and apply differentiated policies — tighter service on high-value/steady, leaner on long-tail/erratic; flag excess and obsolete against shelf life.
6. Model the policy: expected fill rate, turns, holding cost, and stockout exposure, with a lead-time-shock downside case.
7. Produce the replenishment policy, exception list, and residual-risk verdict.

## Outputs
Per-SKU reorder point, safety stock, and order quantity with the service level used; an ABC/XYZ classification and policy map; an excess/obsolete and stockout-risk exception list; a holding-cost vs service-level tradeoff with downside; and a residual-risk statement.

## Safety limits
Planning recommendation only; does not place, cancel, or expedite orders or move stock. No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production/ERP mutation without the exact governing grant and approval boundary. Do not commit purchase orders or adjust live inventory records. Ambiguous mutation targets fail closed.

## Handoffs
Escalate supplier terms and PO commitment to procurement-vendor-negotiation, holding-cost/margin impact to finance-unit-economics, and field replenishment execution to field-service-dispatch-ops. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
Safety stock covers both demand and lead-time variability at the stated service level; reorder points recompute from lead-time demand; order quantities respect MOQ/lot/EOQ; the policy hits the target fill rate in the model including the lead-time-shock case; excess flags respect shelf life. Claims without reproducible evidence remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, safety stock ignoring lead-time variance, or policies that miss the service target. Revert to the current replenishment parameters and never call an unvalidated or stockout-prone policy GREEN.

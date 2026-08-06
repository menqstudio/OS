---
id: procurement-vendor-negotiation
version: 1.1.0
status: active
---

# Procurement Vendor Negotiation

## Trigger
Use this skill when the task requires sourcing a supplier, running an RFP/RFQ, evaluating bids, structuring a contract or SOW, negotiating price/terms/SLAs, renewing or consolidating vendors, or assessing total cost of ownership and supplier risk before a commitment.

## Inputs
The requirement/spec and demand volume; category spend history and incumbent contracts; candidate suppliers and their quotes; must-have vs nice-to-have requirements and acceptance criteria; budget envelope and target price; SLA, security, compliance, and exit requirements; and the required output format.

## Workflow
1. Confirm identity, mode grant, the requirement, budget authority boundary, and whether this is competitive or sole-source.
2. Read incumbent contracts, spend data, and quotes to EOF; build the current total-cost-of-ownership baseline (price + implementation + support + switching + risk).
3. Normalize bids to a like-for-like comparison: unbundle line items, convert to per-unit and per-term cost, and score against weighted requirements.
4. Establish your BATNA and reservation price, and identify the supplier's likely constraints and concession levers (volume commit, term length, payment terms, references).
5. Structure the ask: target price with justification, SLA with credits, security/compliance and data-exit clauses, price-protection caps, and termination-for-convenience rights — never accept auto-renew without a cap.
6. Draft the negotiation plan and a redline of key terms; document concessions given and received.
7. Produce the recommendation, scored comparison, and residual-risk verdict — stopping short of signature.

## Outputs
A normalized TCO bid comparison with weighted scores; a recommended supplier with rationale and BATNA; a term sheet / redline of price, SLA, security, and exit clauses; a negotiation plan with concession ledger; and a residual-risk statement on supplier and lock-in risk.

## Safety limits
Advisory and preparatory only. No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Never sign, execute, issue a PO, commit spend, or communicate a binding offer to a supplier without the exact grant. Ambiguous mutation targets fail closed.

## Handoffs
Escalate legal terms to counsel, budget authorization to the accountable owner, and spend/margin impact to finance-unit-economics; coordinate demand/volume with supply-chain-inventory. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
Bids are normalized to like-for-like TCO; scores trace to weighted, pre-agreed criteria; BATNA and reservation price are explicit; the redline covers SLA credits, data exit, renewal caps, and termination rights; every concession is logged. Claims without reproducible evidence remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, non-comparable bids, missing exit/renewal protections, or spend beyond the authorized envelope. Withdraw any draft offer, revert to the incumbent terms of record, and never call an uncapped or unprotected agreement GREEN.

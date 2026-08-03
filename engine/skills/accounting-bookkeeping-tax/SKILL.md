---
id: accounting-bookkeeping-tax
version: 1.1.0
status: active
---

# Accounting Bookkeeping Tax

## Trigger
Use this skill when the task requires double-entry treatment, ledger reconciliation, period close, revenue recognition (ASC 606 / IFRS 15), lease or expense capitalization, sales/VAT/GST or income tax position, or when financial statements, journal entries, or a tax filing must be produced, reviewed, or corrected against source documents.

## Inputs
Chart of accounts and entity structure; trial balance and general ledger export; bank/processor statements and subledgers (AR, AP, payroll, fixed assets); revenue contracts and invoices; prior-period filed returns and workpapers; applicable jurisdiction, tax year, and accounting basis (cash vs accrual); the specific close date, materiality threshold, and required output format.

## Workflow
1. Confirm identity, mode grant, entity, period, basis, and jurisdiction; refuse if the reporting period or basis is ambiguous.
2. Tie the opening balance to the prior filed/closed period; flag any unexplained rollforward delta before any new entry.
3. Reconcile every material control account: bank-to-book, AR/AP subledger-to-GL, payroll clearing, and intercompany, documenting reconciling items with source references.
4. Test recognition and cutoff: match revenue to performance obligations, accruals to incurred cost, deferrals to unelapsed benefit; verify no transactions straddle the close date incorrectly.
5. Propose adjusting journal entries as balanced debit/credit pairs with narrative and source citation; never overwrite posted entries — post reversing/correcting entries and preserve audit-trail IDs.
6. Recompute tax provision and any filing figures from the adjusted trial balance; reconcile book-to-tax differences (permanent vs temporary) on a schedule.
7. Produce the statement/filing draft plus a reconciliation pack and residual-risk verdict.

## Outputs
Reconciled trial balance and control-account reconciliations; balanced adjusting/correcting journal entries with source citations; a book-to-tax bridge; draft financial statements or return figures marked DRAFT; a variance/exception log; reproducible source paths and a residual-risk statement.

## Safety limits
Advisory and preparatory only. No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production/ledger-of-record mutation without the exact governing grant and approval boundary. Never file, remit, or transmit a return or payment to any authority. Do not overwrite posted ledger entries or alter closed periods. Ambiguous mutation targets fail closed.

## Handoffs
Escalate cross-domain decisions to the owning SST role; escalate legal tax positions or filing authorization to the accountable officer. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
Trial balance nets to zero and ties to prior period; every reconciliation resolves to a documented delta; each journal entry balances and carries a source citation; book-to-tax bridge foots to the provision; statements cross-foot and internally agree. Claims without reproducible evidence remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, out-of-balance ledgers, unexplained rollforward deltas, or period mismatch. Reverse any proposed entries applied during work, restore the original trial balance, and never call a partial or out-of-balance close GREEN.

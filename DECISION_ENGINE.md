# Decision Engine / Որոշումների շարժիչ

## Purpose / Նպատակ
The Decision Engine converts discussions and proposals into explicit, attributable, reviewable decisions.
Որոշումների շարժիչը քննարկումներն ու առաջարկները դարձնում է հստակ, վերագրելի և վերանայվող որոշումներ։

## Decision States / Որոշման վիճակներ
proposed → under review → approved | rejected | deferred → superseded

## Required Fields / Պարտադիր դաշտեր
- decision ID
- title
- context
- options considered
- chosen option
- rationale
- owner
- approver
- scope
- effective date
- consequences
- rollback or replacement path

## Rules / Կանոններ
- Silence is not approval.
- Chat agreement is not canonical until recorded.
- High-impact decisions require explicit owner approval.
- A superseding decision MUST reference the prior decision.
- Agents MAY recommend; they MUST NOT impersonate the approver.

## Outputs / Արդյունքներ
Approved decisions update project truth, tasks, documentation, and affected runtime policies through explicit events.
Հաստատված որոշումները հստակ իրադարձությունների միջոցով թարմացնում են նախագծի ճշմարտությունը, առաջադրանքները, փաստաթղթերը և համապատասխան runtime կանոնները։

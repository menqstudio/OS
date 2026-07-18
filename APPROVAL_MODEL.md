# Approval Model / Հաստատման մոդել

## Purpose / Նպատակ
The Approval Model ensures that authority remains with the correct human owner while allowing safe autonomy.
Հաստատման մոդելը պահպանում է ճիշտ մարդկային սեփականատիրոջ լիազորությունը՝ միաժամանակ թույլ տալով անվտանգ ինքնավարություն։

## Approval Levels / Հաստատման մակարդակներ
- A0: no approval — read-only and harmless analysis
- A1: policy-preapproved — bounded reversible action
- A2: explicit approval — meaningful write or external communication
- A3: dual confirmation — destructive, security-sensitive, financial, or irreversible action

## Approval Object / Հաստատման օբյեկտ
An approval MUST bind to:
- exact action
- exact target
- exact scope
- known consequences
- expiry time
- approving identity
- candidate version or hash where applicable

## Rules / Կանոններ
- Approval for one action MUST NOT be reused for another.
- Material changes invalidate prior approval.
- Ambiguous approval is not approval.
- Agents MUST present the decision, risk, and rollback path clearly.
- Emergency stop overrides all active approvals.
- Rejected actions MUST remain blocked unless a new approval is issued.

## Auto-Mode / Ինքնավար ռեժիմ
Auto-mode MAY execute only actions covered by an explicit policy envelope. Anything outside that envelope returns to approval-required state.
Ինքնավար ռեժիմը ԿԱՐՈՂ Է կատարել միայն հստակ policy envelope-ով թույլատրված գործողություններ։ Դրանից դուրս ամեն ինչ վերադառնում է հաստատում պահանջող վիճակի։

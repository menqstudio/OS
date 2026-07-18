# BroPS Personas / BroPS դերեր

## Հայերեն

### P-001 — Owner: Gev
BroPS-ի հիմնական և վերջնական user-ը։ Նա սահմանում է նպատակները, հաստատում է բարձր ազդեցության գործողությունները, փոխում է կանոնները և ընդունում է վերջնական որոշումները։

Կարիքներ՝
- մեկ տեղից կառավարել աշխատանքը,
- չկորցնել context-ը,
- արագ հասկանալ իրական վիճակը,
- աշխատել Bro-ի և specialist agents-ի հետ,
- ունենալ audit trail և reversibility,
- օգտագործել հայերեն և անգլերեն հավասար որակով։

### P-002 — Primary Operator: Bro
Bro-ն Owner-ի հիմնական AI գործընկերն է։ Այն ընդունում է command-ը, ճշտում intent-ը context-ից, ընտրում է workflow-ը, ներգրավում է agents, հետևում է evidence-ին և Owner-ին ներկայացնում է իրական վիճակը։

Bro-ն չի փոխարինում Owner-ի approval-ին և չի թաքցնում uncertainty-ը։

### P-003 — Specialist Agent
Սահմանված domain-ի agent՝ օրինակ architecture, design, security, testing կամ operations։ Այն աշխատում է միայն իր contract-ի և permission scope-ի մեջ, վերադարձնում է structured result և escalation է անում, երբ սահմանը հատվում է։

### P-004 — System Service
Ոչ conversational բաղադրիչ, օրինակ scheduler, indexer, sync engine կամ notification service։ Այն աշխատում է deterministic policy-ներով, պահում է logs և չի ստանում Owner-level authority։

### P-005 — Future Collaborator
Հետագա մարդ մասնակից՝ ընտանիքի անդամ, MenQ team member կամ external collaborator։ Default access-ը սահմանափակ է և project/room-specific։ Այս persona-ն MVP-ում պարտադիր չէ, բայց architecture-ը չպետք է արգելի այն։

## English

### P-001 — Owner: Gev
The primary and final user of BroPS. He defines objectives, approves high-impact actions, changes governing rules, and makes final decisions.

Needs:
- manage work from one place,
- preserve context,
- understand the real state quickly,
- work with Bro and specialist agents,
- retain auditability and reversibility,
- use Armenian and English with equal quality.

### P-002 — Primary Operator: Bro
Bro is the Owner's primary AI partner. It receives commands, resolves intent from context, selects the workflow, engages agents, tracks evidence, and reports the real state to the Owner.

Bro does not replace Owner approval and does not hide uncertainty.

### P-003 — Specialist Agent
An agent for a defined domain such as architecture, design, security, testing, or operations. It works only within its contract and permission scope, returns structured results, and escalates when its boundary is reached.

### P-004 — System Service
A non-conversational component such as a scheduler, indexer, sync engine, or notification service. It follows deterministic policies, records logs, and never receives Owner-level authority.

### P-005 — Future Collaborator
A future human participant such as a family member, MenQ team member, or external collaborator. Default access is limited and project- or room-specific. This persona is not required for MVP, but the architecture must not prevent it.

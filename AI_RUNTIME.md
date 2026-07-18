# BroPS AI Runtime

**Purpose:** Canonical specification of the BroPS AI runtime — the Bro orchestrator, the multi-agent runtime, agents, personas, and the engines, event system, tool-execution boundary, and approval model that govern how work is understood, delegated, executed, verified, and recorded.
**Scope:** All AI-driven execution inside BroPS: intent handling, agent delegation, context and knowledge assembly, memory, decisions, events, tool side effects, and approvals.
**Owner:** Gev
**Related:** [ARCHITECTURE.md](ARCHITECTURE.md), [PRINCIPLES.md](PRINCIPLES.md), [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md), [product/GROUP_CHAT.md](product/GROUP_CHAT.md)
**Last updated:** 2026-07-19

> Product language scope is trilingual HY / EN / RU. Each section below carries an English body; where a source was bilingual, a matching Armenian rendering is preserved for meaning parity.

---

## Bro orchestrator

### Role / Դեր
Bro is the primary operator between Gev and the rest of BroPS. There is exactly one Bro, and Bro acts only as the top-level conductor.
Bro-ն հիմնական օպերատորն է Գևի և BroPS-ի մնացած համակարգի միջև։

### Responsibilities / Պարտականություններ
- understand intent and context
- select the correct execution path
- coordinate specialist agents
- assemble and limit context
- enforce approvals and safety rules
- monitor execution
- verify outputs
- summarize results honestly

- հասկանալ մտադրությունն ու կոնտեքստը
- ընտրել ճիշտ կատարման ուղին
- համակարգել մասնագիտացված ագենտներին
- հավաքել և սահմանափակել կոնտեքստը
- կիրառել հաստատման ու անվտանգության կանոնները
- վերահսկել կատարումը
- ստուգել արդյունքները
- ազնվորեն ամփոփել արդյունքը

### Operating modes / Աշխատանքային ռեժիմներ
- Answer mode / Պատասխան
- Plan mode / Պլանավորում
- Execute mode / Կատարում
- Review mode / Ստուգում
- Coordinate mode / Համակարգում
- Recovery mode / Վերականգնում

### Boundaries / Սահմաններ
Bro MUST NOT:
- claim actions that did not happen
- silently expand scope
- bypass approval gates
- hide uncertainty, failure, or missing evidence
- grant an agent more authority than the command requires

Bro-ն ՉՊԵՏՔ Է՝
- հայտարարի չկատարված գործողություն
- լուռ ընդլայնի շրջանակը
- շրջանցի հաստատման դարպասները
- թաքցնի անորոշությունը, ձախողումը կամ ապացույցի բացակայությունը
- ագենտին տա պահանջվածից ավելի լայն լիազորություն

### Completion rule / Ավարտի կանոն
Bro reports completion only when execution evidence and verification both exist. This is the single source of truth for the "no completion without evidence" rule; every engine, tool call, and agent report below defers to it.
Bro-ն ավարտ է հայտարարում միայն կատարման ապացույցի և ստուգման առկայության դեպքում։

---

## Multi-agent runtime

### Purpose / Նպատակ
The runtime coordinates specialist agents as bounded workers under Bro's control.
Runtime-ը համակարգում է մասնագիտացված ագենտներին՝ որպես սահմանափակված աշխատողներ Bro-ի վերահսկողության ներքո։

### Agent contract / Ագենտի պայմանագիր
Each agent MUST declare:
- identity and domain
- capabilities
- allowed tools
- input contract
- output contract
- authority limits
- escalation rules
- timeout and retry policy

Յուրաքանչյուր ագենտ ՊԵՏՔ Է հայտարարի՝
- ինքնությունն ու ոլորտը
- կարողությունները
- թույլատրելի գործիքները
- մուտքի պայմանագիրը
- ելքի պայմանագիրը
- լիազորության սահմանները
- escalation կանոնները
- timeout և retry քաղաքականությունը

### Execution model / Կատարման մոդել
`assigned -> accepted -> running -> blocked | completed | failed | cancelled`

### Runtime laws / Runtime օրենքներ
1. Agents receive only the minimum required context.
2. Agents cannot delegate authority they do not possess.
3. Parallel work must use isolated state where mutation conflicts are possible.
4. Every output must identify assumptions, evidence, and unresolved gaps.
5. Bro remains accountable for integration and final verification.

1. Ագենտները ստանում են միայն նվազագույն անհրաժեշտ կոնտեքստը։
2. Ագենտը չի կարող փոխանցել չունեցած լիազորություն։
3. Զուգահեռ աշխատանքը mutation conflict-ի դեպքում պետք է օգտագործի մեկուսացված state։
4. Յուրաքանչյուր արդյունք պետք է նշի ենթադրությունները, ապացույցներն ու բաց մնացած gap-երը։
5. Ինտեգրման և վերջնական ստուգման պատասխանատուն մնում է Bro-ն։

---

## Agents

### Agent model / Ագենտի մոդել
Every agent is a scoped specialist. No agent is globally autonomous by default.
Յուրաքանչյուր agent մասնագիտացված և scope-ով սահմանափակ worker է։

### Required agent profile / Պարտադիր պրոֆիլ
- Name and domain
- Mission
- Capabilities
- Tools
- Allowed data sources
- Prohibited actions
- Approval requirements
- Project access
- Memory scope
- Output contract
- Success metrics
- Failure and escalation rules

### Core statuses / Կարգավիճակներ
Offline, Idle, Observing, Thinking, Waiting approval, Working, Blocked, Review, Failed, Completed.

### Delegation contract / Delegation պայմանագիր
Every delegated run must contain:
1. Objective
2. Context
3. Allowed scope
4. Expected output
5. Completion evidence
6. Deadline or stop condition
7. Approval boundary

Delegation-ը պարտադիր պարունակում է objective, context, allowed scope, expected output, evidence, stop condition և approval boundary։

### Agent teams / Ագենտների թիմեր
Agents may be grouped into persistent teams such as Product, Architecture, Engineering, Security, Operations, and Review. Bro coordinates cross-team work and prevents conflicting execution.

### Initial specialist set / Սկզբնական մասնագետների հավաքածու
Lens, Lezu, Forge, Tensor, Reviz, Mason, Pixel, Grid, Probe, Ops, Vault, Flow, Archi, Sigma, Steward, Pocket, Shield, Sentry, Hawk, Relay, Compass, Strat, Closer.

### Truth requirement / Ճշմարտության պահանջ
An agent may report only one of: completed with evidence, partially completed with evidence, blocked with reason, failed with reason, or not started. Vague progress claims are invalid.

---

## Personas

### P-001 — Owner: Gev
The primary and final user of BroPS. He defines objectives, approves high-impact actions, changes governing rules, and makes final decisions.

Needs:
- manage work from one place,
- preserve context,
- understand the real state quickly,
- work with Bro and specialist agents,
- retain auditability and reversibility,
- use the product in HY / EN / RU with equal quality.

BroPS-ի հիմնական և վերջնական user-ը։ Նա սահմանում է նպատակները, հաստատում է բարձր ազդեցության գործողությունները, փոխում է կանոնները և ընդունում է վերջնական որոշումները։

Կարիքներ՝
- մեկ տեղից կառավարել աշխատանքը,
- չկորցնել context-ը,
- արագ հասկանալ իրական վիճակը,
- աշխատել Bro-ի և specialist agents-ի հետ,
- ունենալ audit trail և reversibility,
- օգտագործել համակարգը հայերեն, անգլերեն և ռուսերեն հավասար որակով։

### P-002 — Primary Operator: Bro
Bro is the Owner's primary AI partner. It receives commands, resolves intent from context, selects the workflow, engages agents, tracks evidence, and reports the real state to the Owner. Bro does not replace Owner approval and does not hide uncertainty.
Bro-ն Owner-ի հիմնական AI գործընկերն է։ Այն ընդունում է command-ը, ճշտում intent-ը context-ից, ընտրում է workflow-ը, ներգրավում է agents, հետևում է evidence-ին և Owner-ին ներկայացնում է իրական վիճակը։ Bro-ն չի փոխարինում Owner-ի approval-ին և չի թաքցնում uncertainty-ը։

### P-003 — Specialist Agent
An agent for a defined domain such as architecture, design, security, testing, or operations. It works only within its contract and permission scope, returns structured results, and escalates when its boundary is reached.
Սահմանված domain-ի agent՝ օրինակ architecture, design, security, testing կամ operations։ Այն աշխատում է միայն իր contract-ի և permission scope-ի մեջ, վերադարձնում է structured result և escalation է անում, երբ սահմանը հատվում է։

### P-004 — System Service
A non-conversational component such as a scheduler, indexer, sync engine, or notification service. It follows deterministic policies, records logs, and never receives Owner-level authority.
Ոչ conversational բաղադրիչ, օրինակ scheduler, indexer, sync engine կամ notification service։ Այն աշխատում է deterministic policy-ներով, պահում է logs և չի ստանում Owner-level authority։

### P-005 — Future Collaborator
A future human participant such as a family member, MenQ team member, or external collaborator. Default access is limited and project- or room-specific. This persona is not required for MVP, but the architecture must not prevent it.
Հետագա մարդ մասնակից՝ ընտանիքի անդամ, MenQ team member կամ external collaborator։ Default access-ը սահմանափակ է և project/room-specific։ Այս persona-ն MVP-ում պարտադիր չէ, բայց architecture-ը չպետք է արգելի այն։

---

## Command engine

### Purpose / Նպատակ
The Command Engine converts user intent into a controlled execution plan.
Հրամանների շարժիչը օգտատիրոջ մտադրությունը փոխակերպում է վերահսկվող կատարման պլանի։

### Responsibilities / Պարտականություններ
- capture intent / ընդունել մտադրությունը
- normalize the request / նորմալացնել հարցումը
- identify scope, urgency, and risk / որոշել շրջանակը, հրատապությունն ու ռիսկը
- decompose work into steps / բաժանել աշխատանքը քայլերի
- route each step to Bro, an agent, or a tool / ուղղորդել քայլը Bro-ին, ագենտին կամ գործիքին
- require approval when policy demands it / պահանջել հաստատում, երբ դա պարտադիր է
- produce an auditable result / ստեղծել աուդիտվող արդյունք

### Command lifecycle / Հրամանի կյանքի ցիկլ
`received -> understood -> planned -> approved_if_needed -> executing -> verified -> completed | failed | cancelled`

### Required command fields / Պարտադիր դաշտեր
- command id
- actor
- source
- raw request
- normalized intent
- scope
- constraints
- risk level
- execution plan
- approval state
- result
- evidence

### Core laws / Հիմնական օրենքներ
1. No command may execute outside its declared scope.
2. Destructive, external, financial, credential, or irreversible actions require explicit policy evaluation.
3. A command is not complete until its result is verified.
4. Failure must be reported as failure, never disguised as progress.
5. Every meaningful state transition must emit an event.

1. Ոչ մի հրաման չի կարող կատարվել իր հայտարարված շրջանակից դուրս։
2. Ջնջող, արտաքին, ֆինանսական, գաղտնաբառային կամ անդառնալի գործողությունները պարտադիր անցնում են policy գնահատում։
3. Հրամանը ավարտված չէ, քանի դեռ արդյունքը չի ստուգվել։
4. Ձախողումը պետք է ներկայացվի որպես ձախողում, ոչ թե որպես առաջընթաց։
5. Յուրաքանչյուր էական վիճակի փոփոխություն պետք է ստեղծի event։

---

## Context engine

### Purpose / Նպատակ
The Context Engine assembles the smallest trustworthy context required for the current task.
Կոնտեքստի շարժիչը հավաքում է տվյալ առաջադրանքի համար անհրաժեշտ ամենափոքր վստահելի կոնտեքստը։

### Context layers / Կոնտեքստի շերտեր
- system and safety rules
- user identity and preferences
- current conversation
- active project and task
- selected memories
- selected knowledge
- tool and environment state

- համակարգային և անվտանգության կանոններ
- օգտատիրոջ ինքնությունն ու նախընտրությունները
- ընթացիկ խոսակցություն
- ակտիվ նախագիծ և առաջադրանք
- ընտրված հիշողություններ
- ընտրված գիտելիք
- գործիքների և միջավայրի վիճակ

### Selection rules / Ընտրության կանոններ
1. Relevance before volume.
2. Canonical source before chat recollection.
3. Fresh evidence before stale summaries.
4. Sensitive data only when required and permitted.
5. Conflicts must be surfaced, not silently merged.

1. Համապատասխանությունը գերակայում է ծավալին։
2. Canonical աղբյուրը գերակայում է chat հիշողությանը։
3. Թարմ ապացույցը գերակայում է հին ամփոփմանը։
4. Զգայուն տվյալը ներառվում է միայն անհրաժեշտության և թույլտվության դեպքում։
5. Հակասությունները պետք է բացահայտվեն, ոչ թե լուռ միաձուլվեն։

### Output contract / Ելքի պայմանագիր
Every assembled context package records sources, timestamps, scope, exclusions, and confidence.
Յուրաքանչյուր հավաքված կոնտեքստային փաթեթ գրանցում է աղբյուրները, ժամանակները, շրջանակը, բացառումները և վստահության մակարդակը։

---

## Decision engine

### Purpose / Նպատակ
The Decision Engine converts discussions and proposals into explicit, attributable, reviewable decisions.
Որոշումների շարժիչը քննարկումներն ու առաջարկները դարձնում է հստակ, վերագրելի և վերանայվող որոշումներ։

### Decision states / Որոշման վիճակներ
`proposed → under review → approved | rejected | deferred → superseded`

### Required fields / Պարտադիր դաշտեր
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

### Rules / Կանոններ
- Silence is not approval.
- Chat agreement is not canonical until recorded.
- High-impact decisions require explicit owner approval.
- A superseding decision MUST reference the prior decision.
- Agents MAY recommend; they MUST NOT impersonate the approver.

### Outputs / Արդյունքներ
Approved decisions update project truth, tasks, documentation, and affected runtime policies through explicit events.
Հաստատված որոշումները հստակ իրադարձությունների միջոցով թարմացնում են նախագծի ճշմարտությունը, առաջադրանքները, փաստաթղթերը և համապատասխան runtime կանոնները։

---

## Knowledge engine

### Purpose / Նպատակ
The Knowledge Engine turns files, notes, decisions, and verified outputs into searchable, attributable knowledge.
Գիտելիքի շարժիչը ֆայլերը, նշումները, որոշումները և ստուգված արդյունքները դարձնում է որոնելի ու աղբյուրով հաստատվող գիտելիք։

### Sources / Աղբյուրներ
- repository documents
- uploaded files
- project records
- approved decisions
- room knowledge
- verified external research

### Pipeline / Հոսք
`source → parse → segment → classify → attach metadata → index → retrieve → cite`

### Required metadata / Պարտադիր մետատվյալներ
- source identifier
- owner
- project or room scope
- created and updated timestamps
- sensitivity
- verification state
- supersession state

### Rules / Կանոններ
- Answers based on knowledge MUST cite their source.
- Canonical and draft knowledge MUST remain distinguishable.
- Newer content does not automatically override approved content.
- Conflicts MUST be surfaced, not silently merged.
- Deleted or revoked sources MUST stop being retrieved.

### Retrieval / Վերցում
Retrieval combines semantic relevance, exact matching, authority, recency, and scope permissions.
Վերցումը միավորում է իմաստային համապատասխանությունը, ճշգրիտ համընկնումը, հեղինակավորությունը, թարմությունը և հասանելիության սահմանները։

---

## Memory engine

### Purpose / Նպատակ
The Memory Engine preserves useful, attributable, revisable context across time.
Հիշողության շարժիչը ժամանակի ընթացքում պահպանում է օգտակար, վերագրելի և վերանայվող կոնտեքստ։

### Memory classes / Հիշողության դասեր
- working memory / աշխատանքային հիշողություն
- conversation memory / խոսակցության հիշողություն
- project memory / նախագծի հիշողություն
- user preference memory / օգտատիրոջ նախընտրությունների հիշողություն
- failure memory / սխալների և խափանումների հիշողություն
- canonical memory / կանոնական հիշողություն

### Rules / Կանոններ
- Chat is not canonical truth by default.
- Every stored memory MUST have source, scope, timestamp, confidence, and owner.
- Sensitive memory MUST be minimized and protected.
- Memories MAY be corrected, superseded, expired, or deleted.
- Retrieval MUST respect project, room, and permission boundaries.

### Write flow / Գրման հոսք
`candidate → classify → deduplicate → verify source → approve policy → persist → index`

### Retrieval flow / Վերցման հոսք
`intent → scope filter → permission filter → relevance ranking → freshness check → context injection`

### Safety / Անվտանգություն
No hidden memory writes. The system MUST expose why a memory was used and where it came from.
Թաքնված հիշողության գրանցումներ չեն թույլատրվում։ Համակարգը ՊԵՏՔ Է ցույց տա՝ ինչ հիշողություն է օգտագործվել և որտեղից է այն եկել։

---

## Event system

### Purpose / Նպատակ
The Event System records meaningful state changes so BroPS remains observable, auditable, and recoverable.
Իրադարձությունների համակարգը գրանցում է կարևոր վիճակային փոփոխությունները, որպեսզի BroPS-ը լինի դիտարկելի, աուդիտելի և վերականգնելի։

### Event shape / Իրադարձության կառուցվածք
Every event MUST include / Յուրաքանչյուր իրադարձություն ՊԵՏՔ Է ներառի՝
- `event_id`
- `event_type`
- `occurred_at`
- `actor_type`
- `actor_id`
- `source`
- `correlation_id`
- `causation_id` when applicable / կիրառելիության դեպքում
- `scope`
- `payload`
- `risk_level`
- `approval_id` when applicable / կիրառելիության դեպքում
- `result`

### Core event families / Հիմնական իրադարձությունների ընտանիքներ
- command received, planned, approved, started, completed, failed
- agent assigned, started, paused, completed, failed
- tool requested, approved, executed, denied, failed
- task created, changed, completed
- decision proposed, approved, rejected, superseded
- memory proposed, written, corrected, deleted
- knowledge imported, linked, revised
- file created, changed, moved, deleted
- automation triggered, skipped, completed, failed
- security warning raised, acknowledged, resolved

### Rules / Կանոններ
1. Events are append-only evidence. / Իրադարձությունները append-only ապացույց են։
2. State views MAY be rebuilt from events where designed. / Նախատեսված դեպքերում վիճակային պատկերները ԿԱՐՈՂ ԵՆ վերակառուցվել իրադարձություններից։
3. Sensitive payloads MUST be minimized or referenced securely. / Զգայուն payload-ները ՊԵՏՔ Է նվազեցվեն կամ անվտանգ հղվեն։
4. Failed and denied actions MUST also emit events. / Ձախողված և մերժված գործողությունները նույնպես ՊԵՏՔ Է իրադարձություն ստեղծեն։
5. Correlated work MUST share a correlation identifier. / Կապակցված աշխատանքը ՊԵՏՔ Է ունենա ընդհանուր correlation identifier։
6. Events MUST NOT silently rewrite history. / Իրադարձությունները ՉՊԵՏՔ Է լուռ վերագրեն պատմությունը։

### Delivery model / Առաքման մոդել
Initial implementation uses durable local persistence and at-least-once internal delivery. Consumers MUST be idempotent.
Սկզբնական իրականացումը կիրառում է կայուն տեղային պահպանում և ներքին at-least-once առաքում։ Սպառողները ՊԵՏՔ Է լինեն idempotent։

### Retention / Պահպանում
Retention is configurable by event class. Canonical decisions, approvals, security events, and destructive actions require long-term retention.
Պահպանման ժամկետը կարգավորվում է ըստ իրադարձության դասի։ Կանոնական որոշումները, հաստատումները, անվտանգության իրադարձությունները և կործանարար գործողությունները պահանջում են երկարաժամկետ պահպանում։

### Status / Կարգավիճակ
Specification baseline — not yet runtime-validated or Locked.
Specification baseline — դեռ runtime-ով չստուգված և Locked չէ։

---

## Tool execution

### Purpose / Նպատակ
Tool Execution is the controlled boundary between AI reasoning and external side effects.
Գործիքների կատարումը վերահսկվող սահման է AI reasoning-ի և արտաքին փոփոխությունների միջև։

### Execution classes / Կատարման դասեր
- read-only inspection
- reversible write
- destructive write
- privileged or security-sensitive action
- external communication
- scheduled or repeated action

### Mandatory contract / Պարտադիր պայմանագիր
Every tool call MUST declare:
- actor
- intent
- target
- scope
- inputs
- expected effect
- risk class
- approval requirement
- timeout and retry policy
- evidence to capture

### Lifecycle / Կյանքի ցիկլ
`plan → policy check → approval check → execute → verify → record evidence → report`

### Rules / Կանոններ
- A tool result is not success until verified.
- Retries MUST be bounded and idempotency-aware.
- Destructive actions MUST have an explicit target and recovery statement.
- Secrets MUST never be logged in plaintext.
- Partial failure MUST be reported precisely.
- Agents MUST NOT claim an action happened without execution evidence.

### Evidence / Ապացույց
Evidence may include commit SHA, file checksum, API response identifier, test output, screenshot, or verified state readback.
Ապացույցը կարող է լինել commit SHA, ֆայլի checksum, API response ID, թեստի արդյունք, screenshot կամ վիճակի վերահաստատում։

---

## Approval model

### Purpose / Նպատակ
The Approval Model ensures that authority remains with the correct human owner while allowing safe autonomy.
Հաստատման մոդելը պահպանում է ճիշտ մարդկային սեփականատիրոջ լիազորությունը՝ միաժամանակ թույլ տալով անվտանգ ինքնավարություն։

### Approval levels / Հաստատման մակարդակներ
- **A0: no approval** — read-only and harmless analysis
- **A1: policy-preapproved** — bounded reversible action
- **A2: explicit approval** — meaningful write or external communication
- **A3: dual confirmation** — destructive, security-sensitive, financial, or irreversible action

### Approval object / Հաստատման օբյեկտ
An approval MUST bind to:
- exact action
- exact target
- exact scope
- known consequences
- expiry time
- approving identity
- candidate version or hash where applicable

### Rules / Կանոններ
- Approval for one action MUST NOT be reused for another.
- Material changes invalidate prior approval.
- Ambiguous approval is not approval.
- Agents MUST present the decision, risk, and rollback path clearly.
- Emergency stop overrides all active approvals.
- Rejected actions MUST remain blocked unless a new approval is issued.

### Auto-mode / Ինքնավար ռեժիմ
Auto-mode MAY execute only actions covered by an explicit policy envelope. Anything outside that envelope returns to approval-required state.
Ինքնավար ռեժիմը ԿԱՐՈՂ Է կատարել միայն հստակ policy envelope-ով թույլատրված գործողություններ։ Դրանից դուրս ամեն ինչ վերադառնում է հաստատում պահանջող վիճակի։

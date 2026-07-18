# BroPS Terminology / BroPS տերմինաբանություն

## Հայերեն

- **Owner** — Gev-ը՝ վերջնական որոշում և approval տվող անձը։
- **Bro** — BroPS-ի հիմնական AI operator-ը և orchestrator-ը։
- **Agent** — սահմանված մասնագիտացում, թույլատրություններ և contract ունեցող AI դերակատար։
- **Command** — Owner-ի կամ թույլատրված համակարգի կողմից տրված նպատակային հրահանգ։
- **Run** — command-ի մեկ վերահսկելի կատարման ցիկլ։
- **Task** — հստակ արդյունք, վիճակ, սեփականատեր և deadline ունեցող աշխատանքային միավոր։
- **Project** — նույն նպատակի շուրջ միավորված tasks, decisions, files, chats և agents։
- **Room** — direct կամ group chat տարածք՝ իր մասնակիցներով, context-ով և memory-ով։
- **Context** — տվյալ run-ի համար հավաքված և սահմանափակված տեղեկություն։
- **Memory** — նախկին փորձից պահպանված, source և confidence ունեցող տեղեկություն։
- **Knowledge** — կազմակերպված և որոնելի փաստաթղթեր, facts և references։
- **Decision** — ընդունված ընտրություն՝ պատճառաբանությամբ, owner-ով և ազդեցությամբ։
- **Approval** — Owner-ի հստակ թույլտվություն սահմանված գործողության համար։
- **Evidence** — claim-ը հաստատող ստուգելի output, log, artifact, diff կամ result։
- **Canonical** — տվյալ թեմայի պաշտոնական և առաջնային truth source։
- **Draft** — դեռ չհաստատված և արտաքին ազդեցություն չունեցող վիճակ։
- **Sandbox** — մեկուսացված միջավայր, որտեղ աշխատանքը չի ազդում production կամ canonical վիճակի վրա։
- **GREEN** — պահանջը ստուգված է իրական evidence-ով։
- **RED** — պահանջը չի անցել կամ հայտնաբերվել է defect։
- **YELLOW** — վիճակը մասնակի է, անորոշ կամ սպասում է evidence/approval-ի։
- **LOCKED** — scope-ը և բովանդակությունը հաստատված են, փոփոխությունը պահանջում է նոր որոշում։

## English

- **Owner** — Gev, the person with final decision and approval authority.
- **Bro** — the primary AI operator and orchestrator of BroPS.
- **Agent** — an AI role with defined specialization, permissions, and contract.
- **Command** — an intent-bearing instruction issued by the Owner or an authorized system.
- **Run** — one controlled execution cycle of a command.
- **Task** — a work unit with a defined outcome, state, owner, and deadline.
- **Project** — tasks, decisions, files, chats, and agents grouped around one objective.
- **Room** — a direct or group chat space with its own participants, context, and memory.
- **Context** — information assembled and bounded for a specific run.
- **Memory** — information retained from prior experience with source and confidence.
- **Knowledge** — organized and searchable documents, facts, and references.
- **Decision** — an accepted choice with rationale, owner, and impact.
- **Approval** — explicit Owner authorization for a defined action.
- **Evidence** — verifiable output, log, artifact, diff, or result supporting a claim.
- **Canonical** — the official and primary truth source for a subject.
- **Draft** — an unapproved state with no external effect.
- **Sandbox** — an isolated environment that does not affect production or canonical state.
- **GREEN** — the requirement is verified with real evidence.
- **RED** — the requirement failed or a defect was found.
- **YELLOW** — the state is partial, uncertain, or awaiting evidence or approval.
- **LOCKED** — scope and content are approved; change requires a new decision.

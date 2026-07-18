# BroPS Success Criteria / BroPS հաջողության չափանիշներ

- **Purpose:** Define the MVP definition of done — the criteria that must be GREEN to ship.
- **Scope:** Acceptance criteria only. Future work is in [ROADMAP.md](ROADMAP.md).
- **Owner:** Gev.
- **Related:** [ROADMAP.md](ROADMAP.md), [PRINCIPLES.md](PRINCIPLES.md), [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md), [product/USER_FLOWS.md](product/USER_FLOWS.md).
- **Last updated:** 2026-07-19.

## Հայերեն

MVP-ն պատրաստ է միայն եթե ստորև նշված բոլոր պարտադիր չափանիշները GREEN են։

### Product
- Owner-ը կարող է մեկ command-ից ստեղծել կամ շարունակել իրական աշխատանքային run։
- Direct chat և Group Chat-ը պահպանում են participants, context, tasks, decisions և room memory։
- Projects, tasks, decisions, approvals, files, knowledge և memory կապվում են իրար canonical IDs-ով։
- Bro-ն կարող է route անել specialist agent-ին և ներկայացնել արդյունքը evidence-ով։

### Trust and control
- Համակարգը չի հայտարարում completion առանց evidence-ի։
- Բարձր ազդեցության գործողությունները չեն կատարվում առանց approval-ի։
- Յուրաքանչյուր run ունի state, owner, timestamps, inputs, outputs և activity trail։
- Failure-ը, cancellation-ը և interruption-ը չեն թողնում կեղծ GREEN կամ անհայտ mutation։

### Runtime
- Desktop app-ը աշխատում է supported Windows environment-ում։
- Core data-ն պահպանվում է local database-ում և վերականգնվում restart-ից հետո։
- Backup և restore flow-ը ստուգված է իրական artifact-ով։
- Secrets-ը չեն պահվում plaintext canonical files-ում կամ logs-ում։

### UX
- Armenian, English և Russian (HY/EN/RU) runtime switch-ը ամբողջ core UI-ում իմաստային parity ունի։
- Light և Dark modes-ը usable են։
- Core workflows-ը keyboard-accessible են և command palette-ից հասանելի։
- Loading, empty, error, blocked և awaiting-approval states-ը նախագծված և իրականացված են։

### Quality
- Architecture, data model, security model և UI contracts-ը implementation-ի հետ synchronized են։
- Required automated tests-ը GREEN են supported environments-ում։
- Release candidate-ը անցել է independent gap audit։
- Open P0 defects չկան, իսկ P1 defects-ը կամ փակ են, կամ Owner-ի կողմից բացահայտ ընդունված։

## English

The MVP is ready only when every mandatory criterion below is GREEN.

### Product
- The Owner can create or continue a real work run from one command.
- Direct chat and Group Chat preserve participants, context, tasks, decisions, and room memory.
- Projects, tasks, decisions, approvals, files, knowledge, and memory are connected through canonical IDs.
- Bro can route work to a specialist agent and present the result with evidence.

### Trust and control
- The system does not claim completion without evidence.
- High-impact actions are not executed without approval.
- Every run has a state, owner, timestamps, inputs, outputs, and activity trail.
- Failure, cancellation, and interruption do not leave a false GREEN state or unknown mutation.

### Runtime
- The desktop application works in the supported Windows environment.
- Core data persists in a local database and survives restart.
- Backup and restore are verified with a real artifact.
- Secrets are not stored in plaintext canonical files or logs.

### UX
- Armenian, English, and Russian (HY/EN/RU) runtime switching has semantic parity across the core UI.
- Light and Dark modes are usable.
- Core workflows are keyboard-accessible and available from the command palette.
- Loading, empty, error, blocked, and awaiting-approval states are designed and implemented.

### Quality
- Architecture, data model, security model, and UI contracts remain synchronized with implementation.
- Required automated tests are GREEN in supported environments.
- The release candidate passes an independent gap audit.
- No P0 defects remain open, and P1 defects are either closed or explicitly accepted by the Owner.

# BroPS Project Context

- **Purpose:** Canonical product-framing document for BroPS — the single source for identity, mission, vision, scope, users, and constraints.
- **Scope:** Product framing and boundaries only. Deep architecture, principles, roadmap, design, and terminology live in their own canonical files.
- **Owner:** Gev.
- **Related:** [PRINCIPLES.md](PRINCIPLES.md), [ARCHITECTURE.md](ARCHITECTURE.md), [ROADMAP.md](ROADMAP.md), [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md), [TERMINOLOGY.md](TERMINOLOGY.md).
- **Last updated:** 2026-07-19.

## English

## Identity

BroPS means **Bro's Personal Space**. It is Gev's personal AI Operating System, built under **MenQ Studio**. Owner: **Gevorg Ohanyan / MenQ Studio**.

It is a personal AI operating environment centered on Bro, Gev's primary AI operator. There is exactly one Bro. Bro is the primary operator, coordinator, moderator, and synthesizer of the system; specialist agents are scoped experts delegated by Bro or Gev.

## Mission

BroPS unifies commands, conversations, projects, tasks, agents, knowledge, memory, decisions, files, calendar, and automations inside one trusted environment. It turns conversations, intent, files, projects, decisions, and agent capabilities into controlled, visible, evidence-backed execution.

BroPS must help Gev think, decide, organize, execute, and supervise work without hiding the real state, fabricating progress, or performing unauthorized actions. Bro is the primary operator and coordinator; specialist agents work within explicit boundaries, with evidence and approval gates.

The core outcome is not a simple dashboard. The core outcome is a trustworthy, local-first, command-first personal operating environment where every action has an owner, state, evidence, and a controlled next step.

## Vision

BroPS is the place where Gev can think, decide, communicate, organize, and execute with an AI team without losing control, context, or truth.

**Product promise — BroPS should answer five questions at any moment:**

1. What matters now?
2. What is being worked on?
3. Who or which agent owns it?
4. What needs Gev's approval?
5. What real evidence proves completion?

**Experience principles:**

- Command-first, not menu-first
- Bro-first, not tool-first
- Conversational, but operationally precise
- Powerful, but controlled
- Context-rich, but not cluttered
- Premium and calm, not noisy or game-like
- One connected system, not disconnected mini-apps

**Long-term direction:** BroPS becomes a unified AI Operating System containing communication, projects, tasks, agents, knowledge, memory, decisions, research, files, calendar, automations, integrations, analytics, and security. It may later run as a desktop client connected to a Debian-based personal AI server, but the product model must be correct before infrastructure deployment.

## Product scope

### BroPS includes

- command-first interaction,
- direct and group chat,
- Bro orchestration,
- specialist agents,
- projects and tasks,
- decisions and approvals,
- knowledge and memory,
- files and document references,
- calendar and reminders,
- automations,
- search and command palette,
- notifications and activity history,
- analytics and usage visibility,
- settings, permissions, secrets, and security controls,
- a local-first desktop runtime,
- controlled integrations with external systems.

Surfaces span: Home, Chat and Group Chat, Projects, Tasks, Agents, Knowledge, Memory, Decisions, Research, Approvals, Activity, Notifications, Calendar, Files, Automations, Integrations, Analytics, Security, and Settings.

### Mandatory MVP scope

1. Owner identity and secure local access.
2. Command workspace.
3. Direct chat and Group Chat.
4. Bro plus specialist-agent routing.
5. Projects, tasks, decisions, and approvals.
6. Knowledge, memory, and files.
7. Search, notifications, and activity log.
8. Trilingual runtime switching — Armenian, English, Russian (HY/EN/RU).
9. Light/Dark appearance.
10. Local database, backup, and restore foundation.
11. Permission and approval gates for externally impactful actions.
12. Auditable execution states: planned, running, blocked, awaiting approval, completed, failed.

### Outside MVP but architecture-ready

- multi-user organization administration,
- public SaaS tenancy,
- marketplace,
- autonomous financial transactions,
- unrestricted background execution,
- mobile client as the primary runtime,
- full enterprise IAM,
- public plugin ecosystem.

### BroPS is NOT

- merely a chat wrapper,
- a conventional admin dashboard,
- an unrestricted autonomous agent,
- a conversation archive independent of canonical truth,
- an automation engine that bypasses approvals,
- one monolith replacing every future MenQ product.

## Core users

- **Gev:** Owner and final authority.
- **Bro:** primary operator, coordinator, moderator, and synthesizer.
- **Specialist agents:** scoped experts delegated by Bro or Gev, working within explicit boundaries, with permissions, approval gates, and real evidence.

## Constraints

- Local-first, command-first. The core outcome is a trustworthy personal operating environment, not a dashboard.
- The repository is the canonical source of truth. Chat is an interface; important approved decisions must be written into canonical repository documentation.
- Every action must carry an owner, state, evidence, and a controlled next step.
- The runtime supports three languages: Armenian, English, and Russian (HY/EN/RU).
- The product model must be correct before any infrastructure deployment (e.g. a desktop client on a Debian-based personal AI server).

## Non-negotiable laws

BroPS is governed by non-negotiable laws — including evidence-backed completion, chat as interface (not canonical truth), written approved decisions, approval gates for high-impact actions, agent transparency of authority and result, equal-meaning multilingual documentation, and the AI-Operating-System (not admin-dashboard) product feel. These are defined canonically in [PRINCIPLES.md](PRINCIPLES.md); do not restate or fork them here.

---

# Հայերեն

## Ինքնություն

BroPS նշանակում է **Bro's Personal Space** (Bro-ի անձնական տարածք)։ Այն Gev-ի անձնական AI Operating System-ն է՝ կառուցված **MenQ Studio**-ի ներքո։ Սեփականատեր՝ **Գևորգ Օհանյան / MenQ Studio**։

Այն անձնական AI օպերացիոն միջավայր է՝ կենտրոնացած Bro-ի՝ Gev-ի գլխավոր AI օպերատորի շուրջ։ Գոյություն ունի ուղիղ մեկ Bro։ Bro-ն համակարգի գլխավոր օպերատորն է, համակարգողը, մոդերատորն ու սինթեզատորը. մասնագիտացված գործակալները սահմանված scope ունեցող փորձագետներ են՝ delegate արված Bro-ի կամ Gev-ի կողմից։

## Առաքելություն

BroPS-ը մեկ վստահելի միջավայրում միավորում է հրամանները, խոսակցությունները, նախագծերը, առաջադրանքները, գործակալներին, գիտելիքը, հիշողությունը, որոշումները, ֆայլերը, օրացույցը և ավտոմատացումները։ Այն խոսակցությունները, մտադրությունը, ֆայլերը, նախագծերը, որոշումները և գործակալների հնարավորությունները վերածում է վերահսկվող, տեսանելի, ապացույցներով ամրագրված կատարման։

BroPS-ը պետք է օգնի Gev-ին մտածել, որոշել, կազմակերպել, գործարկել և վերահսկել աշխատանքը՝ առանց թաքցնելու իրական վիճակը, առանց կեղծ առաջընթացի և առանց չարտոնված գործողությունների։ Bro-ն համակարգի հիմնական օպերատորն ու համակարգողն է, իսկ մասնագիտացված գործակալները աշխատում են հստակ սահմաններով, ապացույցներով և approval gate-երով։

Հիմնական արդյունքը պարզ dashboard-ը չէ։ Հիմնական արդյունքը վստահելի, local-first, command-first անձնական օպերացիոն միջավայրն է, որտեղ յուրաքանչյուր գործողություն ունի սեփականատեր, վիճակ, ապացույց և վերահսկելի հաջորդ քայլ։

## Տեսլական

BroPS-ը այն միջավայրն է, որտեղ Gev-ը կարող է մտածել, որոշել, հաղորդակցվել, կազմակերպել և գործել AI թիմի հետ՝ առանց control-ը, context-ը կամ truth-ը կորցնելու։

**Արտադրանքի խոստումը — BroPS-ը ամեն պահի պետք է պատասխանի հինգ հարցի.**

1. Ի՞նչն է կարևոր հիմա։
2. Ի՞նչ աշխատանք է կատարվում։
3. Ո՞վ կամ ո՞ր գործակալն է պատասխանատուն։
4. Ի՞նչն է պահանջում Gev-ի approval-ը։
5. Ի՞նչ իրական evidence է ապացուցում ավարտը։

**Փորձառության սկզբունքներ.**

- Command-first, ոչ menu-first
- Bro-first, ոչ tool-first
- Խոսակցական, բայց օպերացիոն առումով ճշգրիտ
- Հզոր, բայց վերահսկվող
- Context-ով հարուստ, բայց ոչ գերբեռնված
- Premium ու հանգիստ, ոչ աղմկոտ կամ խաղանման
- Մեկ կապակցված համակարգ, ոչ իրարից անկախ mini-app-եր

**Երկարաժամկետ ուղղություն.** BroPS-ը դառնում է միասնական AI Operating System՝ ներառելով հաղորդակցություն, նախագծեր, առաջադրանքներ, գործակալներ, գիտելիք, հիշողություն, որոշումներ, հետազոտություն, ֆայլեր, օրացույց, ավտոմատացումներ, ինտեգրացիաներ, analytics և security։ Այն հետագայում կարող է աշխատել որպես desktop client՝ միացած Debian-ի վրա հիմնված անձնական AI սերվերին, բայց արտադրանքի մոդելը պետք է ճիշտ լինի մինչև ենթակառուցվածքի deploy-ը։

## Արտադրանքի սահմաններ

### BroPS-ը ներառում է

- command-first interaction,
- direct և group chat,
- Bro orchestration,
- specialist agents,
- projects և tasks,
- decisions և approvals,
- knowledge և memory,
- files և document references,
- calendar և reminders,
- automations,
- search և command palette,
- notifications և activity history,
- analytics և usage visibility,
- settings, permissions, secrets և security controls,
- local-first desktop runtime,
- controlled integrations արտաքին համակարգերի հետ։

Մակերեսներն ընդգրկում են՝ Home, Chat և Group Chat, Projects, Tasks, Agents, Knowledge, Memory, Decisions, Research, Approvals, Activity, Notifications, Calendar, Files, Automations, Integrations, Analytics, Security և Settings։

### MVP-ի պարտադիր scope

1. Owner identity և secure local access։
2. Command workspace։
3. Direct chat և Group Chat։
4. Bro + specialist-agent routing։
5. Projects, tasks, decisions և approvals։
6. Knowledge, memory և files։
7. Search, notifications և activity log։
8. Եռալեզու runtime switch — հայերեն, անգլերեն, ռուսերեն (HY/EN/RU)։
9. Light/Dark appearance։
10. Local database, backup և restore հիմք։
11. Permission/approval gates արտաքին ազդեցություն ունեցող գործողությունների համար։
12. Auditable execution state՝ planned, running, blocked, awaiting approval, completed, failed։

### MVP-ից դուրս, բայց architecture-ready

- multi-user organization administration,
- public SaaS tenancy,
- marketplace,
- autonomous financial transactions,
- unrestricted background execution,
- mobile client որպես primary runtime,
- full enterprise IAM,
- public plugin ecosystem։

### BroPS-ը ՉԷ

- պարզապես chat wrapper,
- սովորական admin dashboard,
- անսահմանափակ ինքնավար agent,
- canonical truth-ից անկախ conversation archive,
- approval-ները շրջանցող automation engine,
- MenQ-ի բոլոր future products-ի փոխարինող մեկ monolith։

## Հիմնական օգտատերեր

- **Gev:** Սեփականատեր և վերջնական authority։
- **Bro:** գլխավոր operator, coordinator, moderator և synthesizer։
- **Մասնագիտացված գործակալներ:** սահմանված scope ունեցող փորձագետներ՝ delegate արված Bro-ի կամ Gev-ի կողմից, որ աշխատում են հստակ սահմաններով, permission-ներով, approval gate-երով և իրական evidence-ով։

## Սահմանափակումներ

- Local-first, command-first։ Հիմնական արդյունքը վստահելի անձնական օպերացիոն միջավայրն է, ոչ թե dashboard-ը։
- Repo-ն canonical source of truth-ն է։ Chat-ը interface է. հաստատված կարևոր որոշումները պետք է գրվեն համապատասխան canonical փաստաթղթեր։
- Յուրաքանչյուր գործողություն պետք է ունենա սեփականատեր, վիճակ, evidence և վերահսկելի հաջորդ քայլ։
- Runtime-ը աջակցում է երեք լեզու՝ հայերեն, անգլերեն և ռուսերեն (HY/EN/RU)։
- Արտադրանքի մոդելը պետք է ճիշտ լինի մինչև ցանկացած ենթակառուցվածքի deploy (օրինակ՝ desktop client՝ Debian-ի վրա հիմնված անձնական AI սերվերի վրա)։

## Անխախտ օրենքներ

BroPS-ը կառավարվում է անխախտ օրենքներով՝ ներառյալ evidence-ով ամրագրված ավարտը, chat-ը որպես interface (ոչ canonical truth), գրավոր հաստատված որոշումները, approval gate-երը high-impact գործողությունների համար, գործակալների թափանցիկությունը authority-ի ու result-ի վերաբերյալ, հավասար իմաստ ունեցող բազմալեզու փաստաթղթերը և AI-Operating-System (ոչ admin-dashboard) արտադրանքի զգացողությունը։ Դրանք canonical կերպով սահմանված են [PRINCIPLES.md](PRINCIPLES.md)-ում. մի՛ վերաշարադրեք և մի՛ պատառեք դրանք այստեղ։

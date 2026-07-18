# BroPS Decisions

**Purpose:** Single canonical source for the BroPS decision format and the accepted decision log. It defines how decisions are recorded and lists every accepted product, architecture, security, and governance decision.

**Scope:** All product, architecture, security, and governance decisions for BroPS. This file supersedes any earlier separate `DECISION_RECORDS.md` format file and any earlier standalone decision log.

**Owner:** Gev

**Related:** [PRINCIPLES.md](PRINCIPLES.md) · [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) · [ROADMAP.md](ROADMAP.md) · [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md)

**Last updated:** 2026-07-19

---

## Record format

Accepted product and architecture decisions are recorded here (or in individual ADR files) using the canonical contract below. There is one source of truth: no decision is stated twice, and decision IDs are stable once assigned.

### Status values

- **Proposed** — raised, not yet a canonical mandate.
- **Approved** — authorizes implementation; not yet locked.
- **Implementing** — actively being built against its contract.
- **Locked** — fixed; changing it requires a new record that identifies the supersession.
- **Superseded** — replaced (fully or in part) by a later decision.
- **Rejected** — considered and declined.

### Canonical ADR template

```text
ID:
Title:
Status:
Date:
Owner:
Decision:
Context:
Rationale:
Consequences:
Alternatives considered:
Affected canonical files:
Validation or evidence:
Supersedes:
Superseded by:
```

### Decision rules

1. Every significant product, architecture, security, or governance change MUST have a decision ID.
2. A Proposed decision is not a canonical mandate.
3. An Approved decision authorizes implementation but is not yet LOCKED.
4. Changing a LOCKED decision requires a new decision record that explicitly identifies the supersession.
5. Agreement given in chat MUST be transferred into the repository to become canonical.
6. A decision cannot be considered GREEN when its required implementation or validation has not actually occurred.
7. Armenian and English versions MUST carry equal meaning.

---

## Decision log

The accepted decisions below reconcile the earlier D-001..D-006 log and the D-001..D-008 canonical list into one non-contradictory set. IDs follow the canonical D-001..D-008 numbering; each entry keeps a single, distinct decision.

### D-001 — BroPS is a personal AI Operating System

**Status:** Locked

BroPS is a unified, personal AI operating environment — not a generic dashboard or a simple chat application.

### D-002 — Bro is the primary operator

**Status:** Approved

Gev interacts primarily with Bro. Bro is the primary operator and orchestrator, coordinating tools, projects, and specialist agents.

### D-003 — Group Chat is a first-class core workspace

**Status:** Approved

Group Chat is a core workspace for multi-agent collaboration and must support tasks, decisions, approvals, files, room context, and summaries.

### D-004 — Command-first and local-first by default

**Status:** Approved

The system is command-first and local-first by default in its interaction model and architecture.

### D-005 — Controlled autonomy with approval gates

**Status:** Approved

Agents act only inside explicit scope. Risky, destructive, external, irreversible, financial, security-sensitive, or otherwise high-impact actions require explicit Owner approval.

### D-006 — Repository or governed data model is canonical

**Status:** Approved

Canonical truth lives in the repository or the governed data model, not only in chat. Approved product and architecture decisions must be recorded in repository documentation; chat alone is not canonical evidence.

### D-007 — Armenian and English have equal product status

**Status:** Superseded by D-009 (language-count point only)

Armenian and English have equal, first-class product status. This decision remains in force for the equal-status principle; its earlier bilingual (HY/EN only) wording is superseded by D-009, which locks a trilingual scope (HY/EN/RU).

### D-008 — Implementation follows validated design and explicit contracts

**Status:** Approved

Product, UX, and architecture are designed and validated before server/Debian deployment decisions. Implementation begins only against explicit, versioned contracts, and implementation status must never be confused with specification status.

### D-009 — Trilingual product scope (Armenian, English, Russian)

**Status:** Approved

- **Decision:** BroPS supports three first-class runtime languages: HY / EN / RU.
- **Context:** Earlier docs said bilingual HY/EN, while `DESIGN_SYSTEM.md`, `LOCALIZATION_AND_THEMES` and the two most recent commits locked a trilingual scope. This resolved a real contradiction in the foundation.
- **Consequence:** Supersedes the bilingual wording of D-007. All docs must state HY/EN/RU.
- **Supersedes:** D-007 (wording / language-count only).

---

# Հայերեն

**Նպատակ.** BroPS-ի որոշումների ձևաչափի և ընդունված որոշումների գրանցամատյանի միասնական canonical աղբյուր։ Այն սահմանում է, թե ինչպես են գրանցվում որոշումները, և թվարկում է BroPS-ի բոլոր ընդունված product, architecture, security և governance որոշումները։

**Շրջանակ.** BroPS-ի բոլոր product, architecture, security և governance որոշումները։ Այս ֆայլը փոխարինում է նախկին առանձին `DECISION_RECORDS.md` ձևաչափի ֆայլը և ցանկացած նախկին առանձին որոշումների գրանցամատյան։

**Սեփականատեր.** Gev

**Առնչվող.** [PRINCIPLES.md](PRINCIPLES.md) · [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) · [ROADMAP.md](ROADMAP.md) · [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md)

**Վերջին թարմացում.** 2026-07-19

---

## Գրառման ձևաչափ

Ընդունված product և architecture որոշումները գրանցվում են այստեղ (կամ առանձին ADR ֆայլերում)՝ ստորև բերված canonical contract-ով։ Կա մեկ ճշմարտության աղբյուր. ոչ մի որոշում չի կրկնվում, և որոշման ID-ները մնում են կայուն՝ մեկ անգամ նշանակվելուց հետո։

### Վիճակներ

- **Proposed / Առաջարկված** — բարձրացված է, բայց դեռ canonical mandate չէ։
- **Approved / Հաստատված** — թույլատրում է իրականացումը, բայց դեռ փակված չէ։
- **Implementing / Իրականացվում է** — ակտիվորեն կառուցվում է իր contract-ի դեմ։
- **Locked / Փակված** — ամրագրված է. փոփոխությունը պահանջում է նոր գրառում, որը նշում է supersession-ը։
- **Superseded / Փոխարինված** — փոխարինվել է (ամբողջությամբ կամ մասամբ) հետագա որոշմամբ։
- **Rejected / Մերժված** — դիտարկվել և մերժվել է։

### Canonical ADR ձևանմուշ

```text
ID:
Title / Վերնագիր:
Status / Վիճակ:
Date / Ամսաթիվ:
Owner / Սեփականատեր:
Decision / Որոշում:
Context / Համատեքստ:
Rationale / Հիմնավորում:
Consequences / Հետևանքներ:
Alternatives considered / Դիտարկված այլընտրանքներ:
Affected canonical files / Ազդվող canonical ֆայլեր:
Validation or evidence / Ստուգում կամ ապացույց:
Supersedes / Փոխարինում է:
Superseded by / Փոխարինված է:
```

### Որոշումների կանոններ

1. Յուրաքանչյուր նշանակալի product, architecture, security կամ governance փոփոխություն ՊԵՏՔ Է ունենա decision ID։
2. Proposed որոշումը canonical mandate չէ։
3. Approved որոշումը թույլատրում է իրականացումը, բայց դեռ LOCKED չէ։
4. LOCKED որոշման փոփոխությունը պահանջում է նոր decision record, որը հստակ նշում է supersession-ը։
5. Chat-ում տրված համաձայնությունը ՊԵՏՔ Է փոխանցվի repository, որպեսզի դառնա canonical։
6. Որոշումը չի կարող GREEN համարվել, եթե դրա պահանջած implementation-ը կամ validation-ը իրականում չի կատարվել։
7. Հայերեն և անգլերեն տարբերակները ՊԵՏՔ Է ունենան հավասար իմաստ։

---

## Որոշումների գրանցամատյան

Ստորև բերված ընդունված որոշումները հաշտեցնում են նախկին D-001..D-006 գրանցամատյանը և D-001..D-008 canonical ցանկը մեկ, ոչ-հակասական հավաքածուի մեջ։ ID-ները հետևում են canonical D-001..D-008 համարակալմանը. յուրաքանչյուր գրառում պահում է մեկ, առանձին որոշում։

### D-001 — BroPS-ը անձնական AI օպերացիոն համակարգ է

**Վիճակ.** Locked / Փակված

BroPS-ը միասնական, անձնական AI օպերացիոն միջավայր է, ոչ թե ընդհանուր dashboard կամ պարզ chat հավելված։

### D-002 — Bro-ն առաջնային օպերատորն է

**Վիճակ.** Approved / Հաստատված

Gev-ը հիմնականում փոխազդում է Bro-ի հետ։ Bro-ն առաջնային օպերատորն ու orchestrator-ն է՝ համակարգելով գործիքները, նախագծերն ու մասնագետ agent-ները։

### D-003 — Group Chat-ը առաջնակարգ core workspace է

**Վիճակ.** Approved / Հաստատված

Group Chat-ը multi-agent համագործակցության core workspace է և պետք է աջակցի task-երին, որոշումներին, հաստատումներին, ֆայլերին, room context-ին և ամփոփումներին։

### D-004 — Command-first և local-first ըստ լռելյայնի

**Վիճակ.** Approved / Հաստատված

Համակարգը իր փոխազդեցության մոդելով և architecture-ով ըստ լռելյայնի command-first և local-first է։

### D-005 — Վերահսկվող ինքնավարություն՝ հաստատման դարպասներով

**Վիճակ.** Approved / Հաստատված

Agent-ները գործում են միայն հստակ scope-ի ներսում։ Ռիսկային, կործանարար, արտաքին, անշրջելի, ֆինանսական, security-զգայուն կամ այլ բարձր ազդեցությամբ գործողությունները պահանջում են Owner-ի հստակ հաստատում։

### D-006 — Repository-ն կամ կառավարվող տվյալների մոդելը canonical է

**Վիճակ.** Approved / Հաստատված

Canonical ճշմարտությունն ապրում է repository-ում կամ կառավարվող տվյալների մոդելում, ոչ միայն chat-ում։ Ընդունված product և architecture որոշումները պետք է գրանցվեն repository documentation-ում. միայն chat-ը canonical ապացույց չէ։

### D-007 — Հայերենն ու անգլերենը ունեն հավասար product կարգավիճակ

**Վիճակ.** Superseded by D-009 / Փոխարինված D-009-ով (միայն լեզուների քանակի մասով)

Հայերենն ու անգլերենը ունեն հավասար, առաջնակարգ product կարգավիճակ։ Այս որոշումը մնում է ուժի մեջ հավասար-կարգավիճակի սկզբունքի մասով. դրա նախկին երկլեզու (միայն HY/EN) ձևակերպումը փոխարինվում է D-009-ով, որը փակում է եռալեզու շրջանակ (HY/EN/RU)։

### D-008 — Իրականացումը հետևում է վավերացված ձևավորմանն ու հստակ contract-ներին

**Վիճակ.** Approved / Հաստատված

Product-ը, UX-ը և architecture-ը ձևավորվում ու վավերացվում են սերվերի/Debian deployment-ի որոշումներից առաջ։ Իրականացումը սկսվում է միայն հստակ, versioned contract-ների դեմ, և implementation status-ը երբեք չպետք է շփոթվի specification status-ի հետ։

### D-009 — Եռալեզու product շրջանակ (հայերեն, անգլերեն, ռուսերեն)

**Վիճակ.** Approved / Հաստատված

- **Որոշում.** BroPS-ը աջակցում է երեք առաջնակարգ runtime լեզուների՝ HY / EN / RU։
- **Համատեքստ.** Նախկին փաստաթղթերը նշում էին երկլեզու HY/EN, մինչդեռ `DESIGN_SYSTEM.md`-ը, `LOCALIZATION_AND_THEMES`-ը և վերջին երկու commit-ները փակել էին եռալեզու շրջանակ։ Սա լուծեց հիմքում առկա իրական հակասությունը։
- **Հետևանք.** Փոխարինում է D-007-ի երկլեզու ձևակերպումը։ Բոլոր փաստաթղթերը պետք է նշեն HY/EN/RU։
- **Փոխարինում է.** D-007 (միայն ձևակերպումը / լեզուների քանակը)։

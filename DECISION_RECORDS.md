# BroPS Decision Records / BroPS որոշումների գրանցամատյան

Այս ֆայլը սահմանում է որոշումների canonical ձևաչափը։ Ընդունված product և architecture որոշումները գրանցվում են `DECISIONS.md`-ում կամ առանձին ADR ֆայլերում՝ այս contract-ով։

This file defines the canonical decision format. Accepted product and architecture decisions are recorded in `DECISIONS.md` or individual ADR files using this contract.

## Status values / Վիճակներ

- Proposed / Առաջարկված
- Approved / Հաստատված
- Implementing / Իրականացվում է
- Locked / Փակված
- Superseded / Փոխարինված
- Rejected / Մերժված

## Required record / Պարտադիր գրառում

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

## Decision rules / Որոշումների կանոններ

### Հայերեն

1. Յուրաքանչյուր նշանակալի product, architecture, security կամ governance փոփոխություն ՊԵՏՔ Է ունենա decision ID։
2. Proposed որոշումը canonical mandate չէ։
3. Approved որոշումը թույլատրում է իրականացումը, բայց դեռ LOCKED չէ։
4. LOCKED որոշման փոփոխությունը պահանջում է նոր decision record, որը հստակ նշում է supersession-ը։
5. Chat-ում տրված համաձայնությունը ՊԵՏՔ Է փոխանցվի repository, որպեսզի դառնա canonical։
6. Որոշումը չի կարող GREEN համարվել, եթե դրա պահանջած implementation-ը կամ validation-ը իրականում չի կատարվել։
7. Հայերեն և անգլերեն տարբերակները ՊԵՏՔ Է ունենան հավասար իմաստ։

### English

1. Every significant product, architecture, security, or governance change MUST have a decision ID.
2. A Proposed decision is not a canonical mandate.
3. An Approved decision authorizes implementation but is not yet LOCKED.
4. Changing a LOCKED decision requires a new decision record that explicitly identifies the supersession.
5. Agreement given in chat MUST be transferred into the repository to become canonical.
6. A decision cannot be considered GREEN when its required implementation or validation has not actually occurred.
7. Armenian and English versions MUST carry equal meaning.

## Initial canonical decisions / Սկզբնական canonical որոշումներ

- D-001 — BroPS is a personal AI Operating System, not a generic dashboard.
- D-002 — Bro is the primary operator and orchestrator.
- D-003 — Group Chat is a first-class core workspace.
- D-004 — The system is command-first and local-first by default.
- D-005 — High-impact actions require explicit Owner approval.
- D-006 — Canonical truth lives in the repository or governed data model, not only in chat.
- D-007 — Armenian and English have equal product status.
- D-008 — Implementation begins only against explicit, versioned contracts; implementation status must never be confused with specification status.

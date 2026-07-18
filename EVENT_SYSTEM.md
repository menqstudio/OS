# Event System / Իրադարձությունների համակարգ

## Purpose / Նպատակ
The Event System records meaningful state changes so BroPS remains observable, auditable, and recoverable.
Իրադարձությունների համակարգը գրանցում է կարևոր վիճակային փոփոխությունները, որպեսզի BroPS-ը լինի դիտարկելի, աուդիտելի և վերականգնելի։

## Event Shape / Իրադարձության կառուցվածք
Every event MUST include:
Յուրաքանչյուր իրադարձություն ՊԵՏՔ Է ներառի՝

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

## Core Event Families / Հիմնական իրադարձությունների ընտանիքներ
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

## Rules / Կանոններ
1. Events are append-only evidence. Իրադարձությունները append-only ապացույց են։
2. State views MAY be rebuilt from events where designed. Նախատեսված դեպքերում վիճակային պատկերները ԿԱՐՈՂ ԵՆ վերակառուցվել իրադարձություններից։
3. Sensitive payloads MUST be minimized or referenced securely. Զգայուն payload-ները ՊԵՏՔ Է նվազեցվեն կամ անվտանգ հղվեն։
4. Failed and denied actions MUST also emit events. Ձախողված և մերժված գործողությունները նույնպես ՊԵՏՔ Է իրադարձություն ստեղծեն։
5. Correlated work MUST share a correlation identifier. Կապակցված աշխատանքը ՊԵՏՔ Է ունենա ընդհանուր correlation identifier։
6. Events MUST NOT silently rewrite history. Իրադարձությունները ՉՊԵՏՔ Է լուռ վերագրեն պատմությունը։

## Delivery Model / Առաքման մոդել
Initial implementation uses durable local persistence and at-least-once internal delivery. Consumers MUST be idempotent.
Սկզբնական իրականացումը կիրառում է կայուն տեղային պահպանում և ներքին at-least-once առաքում։ Սպառողները ՊԵՏՔ Է լինեն idempotent։

## Retention / Պահպանում
Retention is configurable by event class. Canonical decisions, approvals, security events, and destructive actions require long-term retention.
Պահպանման ժամկետը կարգավորվում է ըստ իրադարձության դասի։ Կանոնական որոշումները, հաստատումները, անվտանգության իրադարձությունները և կործանարար գործողությունները պահանջում են երկարաժամկետ պահպանում։

## Status / Կարգավիճակ
Specification baseline — not yet runtime-validated or Locked.
Specification baseline — դեռ runtime-ով չստուգված և Locked չէ։

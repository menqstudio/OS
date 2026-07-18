# Memory Engine / Հիշողության շարժիչ

## Purpose / Նպատակ
The Memory Engine preserves useful, attributable, revisable context across time.
Հիշողության շարժիչը ժամանակի ընթացքում պահպանում է օգտակար, վերագրելի և վերանայվող կոնտեքստ։

## Memory Classes / Հիշողության դասեր
- working memory / աշխատանքային հիշողություն
- conversation memory / խոսակցության հիշողություն
- project memory / նախագծի հիշողություն
- user preference memory / օգտատիրոջ նախընտրությունների հիշողություն
- failure memory / սխալների և խափանումների հիշողություն
- canonical memory / կանոնական հիշողություն

## Rules / Կանոններ
- Chat is not canonical truth by default.
- Every stored memory MUST have source, scope, timestamp, confidence, and owner.
- Sensitive memory MUST be minimized and protected.
- Memories MAY be corrected, superseded, expired, or deleted.
- Retrieval MUST respect project, room, and permission boundaries.

## Write Flow / Գրման հոսք
candidate → classify → deduplicate → verify source → approve policy → persist → index

## Retrieval Flow / Վերցման հոսք
intent → scope filter → permission filter → relevance ranking → freshness check → context injection

## Safety / Անվտանգություն
No hidden memory writes. The system MUST expose why a memory was used and where it came from.
Թաքնված հիշողության գրանցումներ չեն թույլատրվում։ Համակարգը ՊԵՏՔ Է ցույց տա՝ ինչ հիշողություն է օգտագործվել և որտեղից է այն եկել։

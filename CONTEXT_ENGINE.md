# Context Engine / Կոնտեքստի շարժիչ

## Purpose / Նպատակ
The Context Engine assembles the smallest trustworthy context required for the current task.
Կոնտեքստի շարժիչը հավաքում է տվյալ առաջադրանքի համար անհրաժեշտ ամենափոքր վստահելի կոնտեքստը։

## Context layers / Կոնտեքստի շերտեր
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

## Selection rules / Ընտրության կանոններ
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

## Output contract / Ելքի պայմանագիր
Every assembled context package records sources, timestamps, scope, exclusions, and confidence.
Յուրաքանչյուր հավաքված կոնտեքստային փաթեթ գրանցում է աղբյուրները, ժամանակները, շրջանակը, բացառումները և վստահության մակարդակը։

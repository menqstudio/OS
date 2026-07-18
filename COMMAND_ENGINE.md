# Command Engine / Հրամանների շարժիչ

## Purpose / Նպատակ
The Command Engine converts user intent into a controlled execution plan.
Հրամանների շարժիչը օգտատիրոջ մտադրությունը փոխակերպում է վերահսկվող կատարման պլանի։

## Responsibilities / Պարտականություններ
- capture intent / ընդունել մտադրությունը
- normalize the request / նորմալացնել հարցումը
- identify scope, urgency, and risk / որոշել շրջանակը, հրատապությունն ու ռիսկը
- decompose work into steps / բաժանել աշխատանքը քայլերի
- route each step to Bro, an agent, or a tool / ուղղորդել քայլը Bro-ին, ագենտին կամ գործիքին
- require approval when policy demands it / պահանջել հաստատում, երբ դա պարտադիր է
- produce an auditable result / ստեղծել աուդիտվող արդյունք

## Command lifecycle / Հրամանի կյանքի ցիկլ
`received -> understood -> planned -> approved_if_needed -> executing -> verified -> completed | failed | cancelled`

## Required command fields / Պարտադիր դաշտեր
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

## Core laws / Հիմնական օրենքներ
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

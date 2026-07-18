# Multi-Agent Runtime / Բազմաագենտ Runtime

## Purpose / Նպատակ
The runtime coordinates specialist agents as bounded workers under Bro's control.
Runtime-ը համակարգում է մասնագիտացված ագենտներին՝ որպես սահմանափակված աշխատողներ Bro-ի վերահսկողության ներքո։

## Agent contract / Ագենտի պայմանագիր
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

## Execution model / Կատարման մոդել
`assigned -> accepted -> running -> blocked | completed | failed | cancelled`

## Runtime laws / Runtime օրենքներ
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

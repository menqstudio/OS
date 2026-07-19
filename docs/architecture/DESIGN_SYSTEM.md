# MenQ Studio Design Standards

**Purpose:** Define the single canonical visual, motion, localization, theming, and accessibility standard for all MenQ Studio product surfaces.
**Scope:** Every user-facing surface — product shell, screens, components, chat/agent surfaces, notifications, and states — across all product UIs. Product UIs inherit from this document. They may extend it, but they may never replace or contradict it.
**Owner:** Gev
**Related:** [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md) · [product/SCREEN_INVENTORY.md](../product/SCREEN_INVENTORY.md) · [product/NAVIGATION.md](../product/NAVIGATION.md) · [ARCHITECTURE.md](ARCHITECTURE.md)
**Last updated:** 2026-07-19

This is THE only design source. When any product UI, spec, or component appears to conflict with this document, this document wins.

---

## Visual direction

Premium, calm, intelligent, technical, slightly futuristic, and human. The product must not look like a generic admin template, and it must never feel heavy or toy-like.

## Core principles

- Dark and Light themes are mandatory, first-class, and feature-complete.
- Armenian (`hy`), English (`en`), and Russian (`ru`) language parity is mandatory; all three are first-class.
- Token-based styling; no arbitrary hard-coded values and no hard-coded theme colors in production UI.
- Strong information hierarchy.
- Spacious but efficient layouts.
- Motion communicates state, not decoration.
- Accessible contrast and keyboard navigation.
- Responsive desktop-first design.

## Product shell

- Collapsible left navigation.
- Global command palette.
- Persistent Bro command access.
- Main workspace.
- Optional right context drawer.
- Status and notification surfaces.
- Runtime language switcher: HY / EN / RU.
- Runtime theme switcher: Dark / Light.

## Component families

Button, input, command composer, card, panel, table, board, chat message, thread, room list, agent card, task card, decision card, approval card, file row, badge, status indicator, modal, drawer, toast, empty state, skeleton, chart, timeline.

## Chat identity

Human, Bro, and specialist-agent messages must be visually distinct without becoming noisy. Agent status, scope, and execution state must be visible near the message.

---

## Motion

- Standard transition: 160–240ms.
- Data entry animation: 600–900ms.
- KPI count-up: about 800ms.
- Motion communicates state, not decoration.
- No motion may hide execution state or approval requirements.

### Reduced motion

Respect the user's reduced-motion setting. When reduced motion is requested, replace animated transitions with immediate state changes while preserving all information and interaction states. Reduced-motion support is mandatory in both themes.

---

## Localization

MenQ Studio MUST support three complete, first-class runtime languages:

- Armenian (`hy`)
- English (`en`)
- Russian (`ru`)

No language may be treated as a shortened or partial translation, and no language may contain abbreviated, missing, placeholder, machine-garbled, or lower-quality content. All three languages are equal in coverage and quality.

### Runtime language switching

Language switching MUST:

- work without restarting the application;
- update the current screen immediately;
- preserve navigation state, open drawers, filters, and unsaved form values;
- persist the selected language per user profile;
- fall back safely to English only when a translation key is genuinely missing;
- visibly report missing translation keys in development mode.

### Translation coverage

Every user-facing string MUST exist in Armenian, English, and Russian, including:

- navigation;
- buttons and forms;
- chat and group chat surfaces;
- agent states;
- tasks, projects, decisions, approvals, and automation states;
- notifications and activity;
- validation, errors, warnings, and confirmations;
- empty, loading, offline, and permission-denied states;
- accessibility labels;
- dates, times, numbers, pluralization, and relative-time formatting.

### Text direction and layout

All three supported languages use left-to-right layout. Components MUST tolerate text expansion and differing word lengths across languages without clipping or layout breakage.

---

## Themes

MenQ Studio MUST support:

- Dark mode
- Light mode

Both themes are first-class and feature-complete. Dark and Light modes MUST expose the same functionality, hierarchy, readability, interaction states, charts, code blocks, dialogs, and accessibility quality.

### Runtime theme switching

Theme switching MUST:

- work without restarting the application;
- update every active surface immediately;
- persist per user profile;
- support System, Dark, and Light preference values, while Dark and Light remain the actual rendered themes;
- preserve current application state.

### Semantic tokens

Themes MUST be implemented through semantic design tokens rather than component-specific hard-coded colors, including:

- background and surface hierarchy;
- text hierarchy;
- borders and separators;
- primary, secondary, and destructive actions;
- success, warning, danger, and information states;
- focus, hover, pressed, selected, disabled, and loading states;
- charts, code blocks, diff views, chat identities, and agent status.

**No production component may hard-code theme colors.**

---

## Accessibility

Both themes MUST maintain:

- readable contrast;
- visible focus indicators;
- distinguishable interactive states;
- full keyboard navigation;
- reduced-motion support.

Accessibility labels MUST be fully translated across Armenian, English, and Russian.

---

## Acceptance gate

A feature is not complete until it has been verified in all six combinations of language and theme:

1. Armenian (HY) + Dark
2. Armenian (HY) + Light
3. Russian (RU) + Dark
4. Russian (RU) + Light
5. English (EN) + Dark
6. English (EN) + Light

Each combination MUST show complete, high-quality translations, correct semantic-token theming, intact layout without clipping, working runtime language and theme switching, and full accessibility.

---

# Հայերեն

MenQ Studio-ի դիզայնի ստանդարտները։ Ապրանքը պետք է լինի premium, հանգիստ, խելացի, տեխնոլոգիական և փոքր-ինչ futuristic, բայց ոչ ծանր կամ խաղային։ Production UI-ն կառուցվում է semantic token-ներով՝ առանց կոշտ կոդավորված գույների, ամբողջական accessibility-ով և երեք հավասարազոր, առաջնային լեզուներով՝ հայերեն (`hy`), անգլերեն (`en`) և ռուսերեն (`ru`)։ Լեզվի փոխարկումն աշխատում է runtime-ում՝ առանց հավելվածը վերագործարկելու։

Dark և Light ռեժիմները պարտադիր են և առաջնային՝ նույն հնարավորություններով ու որակով, փոխարկվում են runtime-ում և կիրառվում semantic token-ների միջոցով։ Անիմացիաները փոխանցում են վիճակ, ոչ թե դեկորացիա (ստանդարտ անցում՝ 160–240ms, տվյալների մուտք՝ 600–900ms, KPI հաշվարկ՝ ~800ms), և reduced-motion-ը պարտադիր է։ Ֆունկցիան ավարտված չէ, քանի դեռ ստուգված չէ վեց համակցություններով՝ HY/RU/EN × Dark/Light։ Սա դիզայնի միակ աղբյուրն է. ապրանքային UI-ները ժառանգում են այն և կարող են ընդլայնել, բայց երբեք չեն կարող փոխարինել այն։

---

# Русский

Стандарты дизайна MenQ Studio. Продукт должен быть премиальным, спокойным, интеллектуальным, технологичным, слегка футуристичным и человечным, но не тяжёлым и не игрушечным. Production UI строится на семантических токенах без жёстко заданных цветов тем, с полной поддержкой доступности и тремя равноправными первоклассными языками: армянский (`hy`), английский (`en`) и русский (`ru`). Переключение языка работает во время выполнения без перезапуска приложения.

Тёмная и светлая темы обязательны и первоклассны — с одинаковой функциональностью и качеством, переключаются во время выполнения и реализуются через семантические токены. Анимация передаёт состояние, а не украшение (стандартный переход 160–240ms, ввод данных 600–900ms, счётчик KPI ~800ms), поддержка reduced-motion обязательна. Функция не завершена, пока не проверена во всех шести сочетаниях: HY/RU/EN × Dark/Light. Это единственный источник дизайна: продуктовые UI наследуют его и могут расширять, но никогда не заменять.

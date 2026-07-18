# BroPS Localization and Themes / Լոկալիզացիա և թեմաներ / Локализация и темы

Status: Draft canonical

## Supported Languages / Աջակցվող լեզուներ / Поддерживаемые языки

BroPS MUST support three complete runtime languages:

- Armenian (`hy`)
- English (`en`)
- Russian (`ru`)

All three languages are first-class. No language may contain abbreviated, missing, placeholder, machine-garbled, or lower-quality content.

BroPS-ը ՊԵՏՔ Է ամբողջությամբ աշխատի երեք լեզվով՝ հայերեն, անգլերեն և ռուսերեն։ Բոլոր երեք լեզուները հավասարազոր են։

BroPS ДОЛЖЕН полностью поддерживать армянский, английский и русский языки. Все три языка равноправны.

## Runtime Switching

Language switching MUST:

- work without restarting the application;
- update the current screen immediately;
- preserve navigation state, open drawers, filters, and unsaved form values;
- persist the selected language per user profile;
- fall back safely to English only when a translation key is genuinely missing;
- visibly report missing translation keys in development mode.

## Translation Coverage

Translations MUST cover:

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

## Text Direction and Layout

All supported languages use left-to-right layout. Components MUST tolerate text expansion and different word lengths without clipping or layout breakage.

## Supported Themes / Աջակցվող թեմաներ / Поддерживаемые темы

BroPS MUST support:

- Dark mode
- Light mode

Both themes are first-class and feature-complete.

## Runtime Theme Switching

Theme switching MUST:

- work without restarting the application;
- update every active surface immediately;
- persist per user profile;
- support System, Dark, and Light preference values, while Dark and Light remain the actual rendered themes;
- preserve current application state.

## Semantic Tokens

Themes MUST be implemented through semantic tokens, including:

- background and surface hierarchy;
- text hierarchy;
- borders and separators;
- primary, secondary, and destructive actions;
- success, warning, danger, and information states;
- focus, hover, pressed, selected, disabled, and loading states;
- charts, code blocks, diff views, chat identities, and agent status.

No production component may hard-code theme colors.

## Accessibility

Both themes MUST maintain readable contrast, visible focus indicators, distinguishable interactive states, and reduced-motion support.

## Acceptance Gate

A feature is not complete until it has been verified in all six combinations:

1. Armenian + Dark
2. Armenian + Light
3. English + Dark
4. English + Light
5. Russian + Dark
6. Russian + Light

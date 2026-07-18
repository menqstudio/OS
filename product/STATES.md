- **Purpose:** Define the single canonical set of UI state patterns that every BroPS screen and surface inherits, so state behavior is consistent, honest, and reusable across the product.
- **Scope:** Phase 1 UX. The ten canonical states (loading, empty, populated, error, offline, permission-denied, blocked, awaiting-approval, destructive-confirmation, success) plus the rules and mappings that govern them. Trilingual product surface (HY/EN/RU) in Dark and Light.
- **Owner:** Gev.
- **Related:** [SCREEN_INVENTORY.md](SCREEN_INVENTORY.md), [../DESIGN_SYSTEM.md](../DESIGN_SYSTEM.md), [INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md).
- **Last updated:** 2026-07-19.

# BroPS Canonical UI State Patterns / Ինտերֆեյսի վիճակների կանոնական օրինաչափություններ

Status: Draft canonical

Every screen and surface listed in [SCREEN_INVENTORY.md](SCREEN_INVENTORY.md) inherits these patterns. A screen may extend a pattern for its content, but it may never replace, contradict, or weaken it. When a screen conflicts with this document, this document wins; when this document conflicts with [../DESIGN_SYSTEM.md](../DESIGN_SYSTEM.md), the Design System wins.

All visual treatment below is expressed through the semantic token families defined in the Design System (background/surface hierarchy, text hierarchy, borders, primary/secondary/destructive actions, success/warning/danger/information states, and focus/hover/pressed/selected/disabled/loading states). **No state may hard-code a theme color.**

---

## Global rules for all states

These rules bind every state and every screen. They are not optional.

1. **No state may hide execution status, approval status, ownership, failure, or uncertainty.** If work is running, waiting, blocked, failed, or unverified, the state must say so in plain language. Silence, spinners-without-context, and optimistic "done" claims are prohibited.
2. **Truth over comfort.** A state must never present an ambiguous or unverified result as success. Uncertainty is shown as uncertainty (see `blocked` and `error`), never smoothed over.
3. **Ownership is always visible where it exists.** When a screen shows work items (tasks, agents, approvals, decisions, runs), the responsible owner or agent is named in every state, including loading placeholders and error states.
4. **Every state exists in all six combinations.** Each state must be complete and high-quality in HY/RU/EN × Dark/Light. This matches the Design System acceptance gate; a state is not done until verified in all six.
5. **Semantic tokens only.** Status color, surface, border, and text all come from semantic tokens. Success is `state-success`, warning is `state-warning`, danger/failure is `state-danger`, informational is `state-info`. Never a raw hex or theme-specific literal.
6. **Reduced motion is mandatory.** When the user requests reduced motion, animated transitions are replaced by immediate state changes. No information, affordance, or status indicator may be lost in reduced-motion mode. Motion communicates state; it is never the only carrier of state — every animated cue also has a static, text, or iconographic equivalent.
7. **Motion may never mask state.** Transitions must not delay, obscure, or soften execution status or approval requirements (per Design System motion rules). A skeleton or fade may never outlive the data it stands in for.
8. **Keyboard and focus.** Every actionable element in every state is reachable by keyboard, has a visible focus indicator, and exposes a translated accessibility label in HY/EN/RU.
9. **Localized microcopy.** Every state string — including counts, relative times, error causes, and confirmation text — exists in all three languages with equal meaning and quality. English is a fallback only for a genuinely missing key.

---

## Canonical patterns

Each pattern below is the reusable definition. Screens supply the content; the behavior is fixed.

### 1. Loading / Բեռնում

- **When it applies:** Data or a view is being fetched or computed and cannot yet be shown. Distinct from `blocked` (which is waiting on a condition, not on data transport).
- **What the user sees:**
  - **Skeleton** for structured, predictable layouts (tables, boards, cards, chat threads, drawers) where the final shape is known. Skeletons mirror the real layout's structure and density.
  - **Spinner / progress** for atomic or unpredictable operations (a single action resolving, a command executing, an unknown-length result). Long or multi-step operations (agent runs, executions) show determinate progress or a live step label, never a bare spinner.
  - Loading never blanks ownership or execution context: an in-progress agent run shows the agent name and current step while loading its output.
- **Allowed actions:** Cancel where the operation is cancelable; navigate away; nothing that would act on not-yet-loaded data. Cancel must be explicit, not implied by navigation.
- **Rule of thumb:** Known shape → skeleton. Unknown shape or single action → spinner. Work that executes on the user's behalf → determinate progress with a step label.
- **Accessibility / motion:** Loading regions expose `aria-busy` and a translated "Loading…" label. Skeleton shimmer and spinner rotation are decorative and are disabled under reduced motion, replaced by a static "Loading…" label and a still placeholder. Focus is not stolen; it stays where the user left it until content is ready.

### 2. Empty / Դատարկ

Three distinct sub-patterns — never collapse them into one generic "No data".

- **First-run empty (nothing exists yet):** Explains what this surface is for and offers the primary creation action. Encouraging, not apologetic. Example primary action: "Create your first project".
- **No-results empty (a collection is genuinely empty):** States that nothing exists in this scope and offers the creation or import path. Distinct from a failed load — an empty collection is a success, not an error.
- **Filtered-empty (search/filters excluded everything):** States that the current filter or query matched nothing, echoes the active filters/query, and offers "Clear filters" / "Reset search" as the primary action. Never implies the underlying data is empty.
- **What the user sees:** A calm empty-state block (icon or illustration optional), one-line explanation, and a single clear primary action. Tone differs by sub-pattern (invitation vs. neutral vs. corrective).
- **Allowed actions:** The primary create/import/clear action; secondary "Learn more" where useful. Filtered-empty always offers a path back to a populated view.
- **Accessibility / motion:** Empty block is announced to assistive tech as a status, not an error. Entrance uses the standard 160–240ms transition; under reduced motion it appears immediately.

### 3. Populated / Լցված

- **When it applies:** Real content is present and current. The default working state.
- **What the user sees:** The screen's actual content with full information hierarchy — content, ownership, and live status all visible. For any item that carries execution or approval status (agent runs, tasks, automations, approvals), that status is shown inline on the item, not hidden behind a click.
- **Allowed actions:** The screen's full action set, gated by permission. Actions the user cannot perform appear disabled with a reason on hover/focus (see `permission-denied`), never silently absent.
- **Accessibility / motion:** New or changed rows/cards may use the data-entry animation (600–900ms) or KPI count-up (~800ms); under reduced motion they appear in final state instantly. Live status changes are announced politely and never depend on color alone (icon + label + token).

### 4. Error / Սխալ

Two severities — the treatment differs.

- **Recoverable error:** One operation or region failed but the screen is still usable. Shown as an inline error on the affected region/card/row using `state-danger`, with a plain-language cause and a **Retry** as primary action. The rest of the screen stays interactive.
- **Fatal error:** The whole screen or flow cannot continue. Shown as a full-surface error state with a plain-language cause, a **Retry / Reload** primary action, and a safe secondary exit (back / go home). Never a blank screen and never a raw stack trace as the primary message.
- **What the user sees:** What failed, why (in the user's language), and what they can do next. Technical detail is available on demand ("Details" / execution log link), never as the headline.
- **Allowed actions:** Retry (primary), view details / open execution log, report, and a safe exit for fatal errors.
- **Rule:** An error never masquerades as any other state. A failed load is `error`, not `empty`. A partial or unverified result is `error` or `blocked`, never `success`.
- **Accessibility / motion:** Errors are announced assertively to assistive tech. No shake/flash that conveys meaning by motion alone; the `state-danger` token plus an icon and text carry the meaning. Reduced motion removes any attention animation while keeping the full message.

### 5. Offline / Անցանց

- **When it applies:** The client has lost connectivity, or a required service is unreachable, so live data and actions cannot be trusted.
- **What the user sees:** A persistent, non-blocking offline indicator on the shell status surface, plus per-region treatment: cached content is clearly labeled "Offline — last updated {relative time}" and write actions are disabled with an offline reason. The product never pretends stale data is live.
- **Allowed actions:** Read cached content (clearly marked stale); retry/reconnect; queue-safe actions only where BroPS explicitly supports offline queuing (and then the queued/pending status is visible). Destructive or execution actions are disabled offline.
- **Accessibility / motion:** Offline status is announced once on transition and remains readable as text (not color-only). Reconnection restores live state with the standard transition; under reduced motion the swap is immediate. Ownership and last-known execution status remain visible on cached items.

### 6. Permission-denied / Թույլտվությունը մերժված է

- **When it applies:** The user is authenticated but not authorized for this surface, item, or action.
- **What the user sees:** For a whole surface — a clear "You don't have access" state explaining what is restricted and how to request access, with the owner/authority named where known. For a single action — the control is visible but disabled, with a translated reason on hover/focus. Denied actions are never silently hidden; the user must be able to see that a capability exists and that they lack it.
- **Allowed actions:** Request access / contact owner; navigate away. No action that the permission forbids is executable.
- **Accessibility / motion:** Disabled controls use the `disabled` token state and expose an accessible name plus the denial reason. No motion. The reason text is fully localized (HY/EN/RU).

### 7. Blocked / Արգելափակված

- **When it applies:** The screen or action cannot proceed because an external condition is unmet — a missing prerequisite, an unfinished upstream step, an unmet dependency, or an unverified/uncertain result. Distinct from `error` (something failed) and `permission-denied` (not authorized).
- **What the user sees:** A blocked state using `state-warning`, naming the exact blocker ("Waiting on: {dependency}"), who or what must resolve it, and — where known — what will unblock it. Uncertainty is surfaced here honestly: if a result cannot be verified, the screen says so rather than showing a false success.
- **Allowed actions:** Go to the blocker (deep link to the upstream item), refresh/re-check status, request help. The blocked action itself stays disabled until the condition clears.
- **Accessibility / motion:** Announced politely as a status with the blocker named in text. `state-warning` token plus icon and label, never color alone. No looping animation; status refresh follows the standard transition, immediate under reduced motion.

### 8. Awaiting-approval / Սպասում է հաստատման

- **When it applies:** An action or execution is paused pending a required approval (per the Approvals workspace and Approval drawer). Core to BroPS's human-in-the-loop guarantee.
- **What the user sees:** A prominent pending-approval state on the affected item and, for the approver, in the Approvals surface. It names what is being requested, the requesting agent/owner, the scope of the pending action, and the current approval status. Execution is visibly held — never quietly proceeding. Approval status is never hidden behind a click.
- **Allowed actions:** For the approver — Approve / Reject with a reason (Approve is primary but must be deliberate). For the requester/others — view request, add context, cancel the request. The underlying action cannot execute until approved.
- **Accessibility / motion:** Pending status is announced and persistently visible as text plus an `state-info`/pending token. No motion that implies progress (nothing is progressing — it is waiting). Reduced motion: immediate. Ownership of both requester and approver is shown.

### 9. Destructive-confirmation / Կործանարար գործողության հաստատում

- **When it applies:** Before any irreversible or high-impact action (delete, revoke, stop a run, remove access, purge).
- **What the user sees:** A modal or inline confirmation naming the exact object and the exact consequence in plain language ("This permanently deletes {name}. This cannot be undone."). The confirm control uses the `action-destructive` token and is clearly separated from cancel. For the highest-impact actions, confirmation requires an explicit match step (type the name) so it cannot be triggered by reflex.
- **Allowed actions:** Confirm (destructive, styled distinctly) or Cancel (default/safe, focused by default). Cancel is always the low-friction path.
- **Accessibility / motion:** Focus moves to the safe (Cancel) control on open; focus is trapped within the dialog; Escape cancels. The dialog is announced with its full consequence text. Entrance uses the standard transition; under reduced motion it appears immediately with no fade. Danger is carried by the `action-destructive` token, an icon, and the text — never color alone.

### 10. Success / Հաջողություն

- **When it applies:** An action completed and the result is verified. Success is only shown for outcomes that are actually confirmed — a not-yet-verified or partial result uses `blocked` or `error`, never `success`.
- **What the user sees:** A confirmation that states specifically what succeeded (not a generic "Done"), using `state-success`. Transient outcomes use a toast; state-changing outcomes also update the underlying view so the success is reflected in the content, not only in a disappearing message. Where relevant, a link to the result or execution log is offered.
- **Allowed actions:** Continue, undo where the action is reversible, view result / open execution log, dismiss.
- **Accessibility / motion:** Success is announced politely with a translated message. Toasts persist long enough to read, pause on hover/focus, and are dismissible; they never auto-hide critical confirmation before it can be read. Success animation is disabled under reduced motion, replaced by an immediate `state-success` indicator plus text.

---

## State → trigger → treatment → action map

| State | Trigger | Primary UI treatment | Primary action |
| --- | --- | --- | --- |
| Loading | Data/view fetching or computing | Skeleton (known shape) or spinner/determinate progress (atomic/long op), ownership kept visible | Cancel (if cancelable) |
| Empty | Scope has no content | First-run / no-results / filtered-empty block, tone per sub-type | Create / Import / Clear filters |
| Populated | Current content present | Full content with inline ownership + live status | Screen's permitted actions |
| Error | Operation failed | Inline (recoverable) or full-surface (fatal) `state-danger` with plain-language cause | Retry / Reload |
| Offline | Connectivity or service lost | Persistent offline indicator; cached content labeled stale; writes disabled | Reconnect / Retry |
| Permission-denied | Authenticated but not authorized | Access-restricted surface, or visible disabled control with reason | Request access |
| Blocked | Unmet prerequisite / dependency / uncertainty | `state-warning` block naming the blocker and resolver | Go to blocker / Re-check |
| Awaiting-approval | Action paused for required approval | Prominent pending state naming request, scope, requester, status | Approve / Reject (approver) |
| Destructive-confirmation | Before irreversible/high-impact action | Confirmation naming object + consequence, `action-destructive` confirm | Confirm or Cancel (safe default) |
| Success | Action completed and verified | `state-success` confirmation + underlying view updated | Continue / Undo / View result |

---

## Trilingual state microcopy reference

Canonical short labels every screen reuses. Equal meaning and quality in all three languages; expansion-tolerant per the Design System.

| State | English (en) | Հայերեն (hy) | Русский (ru) |
| --- | --- | --- | --- |
| Loading | Loading… | Բեռնվում է… | Загрузка… |
| Empty (first-run) | Nothing here yet | Դեռ ոչինչ չկա | Пока ничего нет |
| Empty (no results) | No items | Տարրեր չկան | Нет элементов |
| Empty (filtered) | No matches — adjust filters | Համընկնումներ չկան — փոխեք զտիչները | Нет совпадений — измените фильтры |
| Error (recoverable) | Something went wrong. Retry? | Ինչ-որ բան սխալ գնաց։ Կրկնե՞լ | Что-то пошло не так. Повторить? |
| Error (fatal) | This screen can't load | Այս էկրանը չի բեռնվում | Этот экран не загружается |
| Offline | Offline — showing cached data | Անցանց — ցուցադրվում են պահված տվյալները | Офлайн — показаны кэшированные данные |
| Permission-denied | You don't have access | Դուք մուտք չունեք | У вас нет доступа |
| Blocked | Blocked — waiting on {blocker} | Արգելափակված է — սպասում է {blocker}-ին | Заблокировано — ожидает {blocker} |
| Awaiting-approval | Awaiting approval | Սպասում է հաստատման | Ожидает подтверждения |
| Destructive-confirmation | This can't be undone | Սա հնարավոր չէ հետարկել | Это нельзя отменить |
| Success | Done | Պատրաստ է | Готово |

---

# Հայերեն

Կարգավիճակ: Նախնական կանոնական

[SCREEN_INVENTORY.md](SCREEN_INVENTORY.md)-ում թվարկված յուրաքանչյուր էկրան և մակերես ժառանգում է այս օրինաչափությունները։ Էկրանը կարող է ընդլայնել օրինաչափությունն իր բովանդակության համար, բայց երբեք չի կարող փոխարինել, հակասել կամ թուլացնել այն։ Երբ էկրանը հակասում է այս փաստաթղթին՝ հաղթում է այս փաստաթուղթը. երբ այս փաստաթուղթը հակասում է [../DESIGN_SYSTEM.md](../DESIGN_SYSTEM.md)-ին՝ հաղթում է Design System-ը։

Ամբողջ վիզուալ մշակումը արտահայտվում է Design System-ի semantic token ընտանիքներով (ֆոն/մակերես, տեքստի հիերարխիա, եզրագծեր, primary/secondary/destructive գործողություններ և success/warning/danger/information վիճակներ)։ **Ոչ մի վիճակ չի կարող կոշտ կոդավորել թեմայի գույն։**

## Ընդհանուր կանոններ բոլոր վիճակների համար

1. **Ոչ մի վիճակ չի կարող թաքցնել կատարման կարգավիճակը, հաստատման կարգավիճակը, սեփականությունը, ձախողումը կամ անորոշությունը։** Եթե աշխատանքը ընթանում է, սպասում է, արգելափակված է, ձախողվել է կամ չի ստուգվել՝ վիճակը պետք է դա ասի պարզ լեզվով։ Լռությունը, առանց համատեքստի spinner-ները և չափազանց լավատեսական «պատրաստ է» հայտարարությունները արգելված են։
2. **Ճշմարտությունը՝ հարմարավետությունից առաջ։** Վիճակը երբեք չի ներկայացնում անորոշ կամ չստուգված արդյունքը որպես հաջողություն։ Անորոշությունը ցուցադրվում է որպես անորոշություն (տես `blocked` և `error`)։
3. **Սեփականությունը միշտ տեսանելի է, երբ այն կա։** Աշխատանքային տարրեր ցուցադրող էկրանում պատասխանատու սեփականատերը կամ ագենտը նշվում է ամեն վիճակում, ներառյալ loading-ը և error-ը։
4. **Ամեն վիճակ գոյություն ունի բոլոր վեց համակցություններում։** Յուրաքանչյուր վիճակ պետք է լինի ամբողջական և բարձրորակ HY/RU/EN × Dark/Light-ում՝ համաձայն Design System-ի ընդունման դարպասի։
5. **Միայն semantic token-ներ։** Success՝ `state-success`, warning՝ `state-warning`, danger/ձախողում՝ `state-danger`, informational՝ `state-info`։ Երբեք raw hex կամ թեմա-կախյալ լիտերալ։
6. **Reduced-motion-ը պարտադիր է։** Երբ օգտատերը պահանջում է reduced motion, անիմացիաները փոխարինվում են ակնթարթային փոփոխություններով՝ առանց տեղեկատվության կամ կարգավիճակի կորստի։ Անիմացիան երբեք վիճակի միակ կրողը չէ։
7. **Անիմացիան երբեք չի քողարկում վիճակը։** Անցումները չեն ուշացնում կամ մթագնում կատարման կամ հաստատման կարգավիճակը։
8. **Ստեղնաշար և ֆոկուս։** Ամեն վիճակի ամեն գործող տարր հասանելի է ստեղնաշարով, ունի տեսանելի ֆոկուսի ցուցիչ և թարգմանված accessibility պիտակ HY/EN/RU-ով։
9. **Տեղայնացված microcopy։** Ամեն վիճակի տողը գոյություն ունի բոլոր երեք լեզուներով՝ հավասար իմաստով և որակով։ Անգլերենը միայն fallback է իսկապես բացակայող բանալու համար։

## Կանոնական օրինաչափություններ

1. **Loading / Բեռնում** — Տվյալները դեռ բեռնվում են։ Հայտնի կառուցվածք → skeleton; ատոմային կամ երկար գործողություն → spinner/դետերմինիստիկ առաջընթաց քայլի պիտակով։ Ագենտի ընթացիկ քայլն ու անունը մնում են տեսանելի։ Թույլատրելի՝ Cancel (եթե հնարավոր է)։ `aria-busy` + թարգմանված «Բեռնվում է…»; reduced motion-ում՝ ստատիկ պիտակ, ֆոկուսը չի գողացվում։
2. **Empty / Դատարկ** — Երեք ենթատեսակ՝ առաջին անգամ (հրավեր և ստեղծման գործողություն), արդյունք չկա (դատարկ հավաքածու, ոչ սխալ), զտված-դատարկ (զտիչը ոչինչ չգտավ, առաջարկվում է «Մաքրել զտիչները»)։ Հայտարարվում է որպես status, ոչ error; մուտքը՝ 160–240ms, reduced motion-ում՝ ակնթարթ։
3. **Populated / Լցված** — Իրական, արդի բովանդակություն ամբողջական հիերարխիայով; կատարման/հաստատման կարգավիճակը ցուցադրվում է inline՝ տարրի վրա։ Գործողությունները սահմանափակվում են թույլտվությամբ։ Data-entry անիմացիա (600–900ms) / KPI count-up (~800ms), reduced motion-ում՝ վերջնական վիճակ անմիջապես; գույնը երբեք միակ ազդանշանը չէ։
4. **Error / Սխալ** — Վերականգնվող՝ inline `state-danger` + Retry, մնացած էկրանը մնում է աշխատունակ; ֆատալ՝ ամբողջ մակերես Retry/Reload + անվտանգ ելք։ Ցույց է տալիս ինչ ձախողվեց, ինչու և հաջորդ քայլը; ոչ մի raw stack trace որպես գլխավոր հաղորդագրություն։ Հայտարարվում է assertive; սխալը երբեք չի ձևանում այլ վիճակ։
5. **Offline / Անցանց** — Կայուն offline ցուցիչ shell-ի status մակերեսին; պահված բովանդակությունը նշվում է «Անցանց — վերջին թարմացում {ժամանակ}», գրելու գործողությունները անջատված են։ Stale տվյալը երբեք չի ներկայացվում որպես live։ Reconnect-ը վերականգնում է live վիճակը։
6. **Permission-denied / Թույլտվությունը մերժված է** — Ամբողջ մակերես՝ «Դուք մուտք չունեք» բացատրությամբ և access-ի հայցի ուղով; առանձին գործողություն՝ տեսանելի, բայց անջատված վերահսկիչ՝ պատճառով։ Մերժված գործողությունը երբեք լուռ չի թաքցվում։ `disabled` token + accessible անուն, ամբողջությամբ տեղայնացված։
7. **Blocked / Արգելափակված** — Արտաքին պայման չի բավարարվել (prerequisite, upstream քայլ, կախվածություն կամ չստուգված արդյունք)։ `state-warning` բլոկ, որ նշում է ճշգրիտ blocker-ը և ով պետք է լուծի; անորոշությունը ազնվորեն ցուցադրվում է։ Թույլատրելի՝ գնալ blocker-ին, կրկին ստուգել։ Տարբերվում է `error`-ից և `permission-denied`-ից։
8. **Awaiting-approval / Սպասում է հաստատման** — Գործողությունը կասեցված է պարտադիր հաստատման համար։ Ցուցադրվում է ինչ է հայցվում, հայցող ագենտ/սեփականատեր, scope և կարգավիճակ; կատարումը տեսանելիորեն պահված է, ոչ լուռ ընթացող։ Հաստատողի համար՝ Approve/Reject պատճառով։ Հաստատման կարգավիճակը երբեք թաքցված չէ։
9. **Destructive-confirmation / Կործանարար գործողության հաստատում** — Անշրջելի գործողությունից առաջ՝ հաստատում, որ նշում է ճշգրիտ օբյեկտն ու հետևանքը («Սա մշտապես ջնջում է {name}։ Հնարավոր չէ հետարկել»)։ Confirm-ը՝ `action-destructive` token, Cancel-ը՝ լռելյայն ֆոկուսում; ամենաբարձր ազդեցության դեպքում՝ անվան մուտքագրում։ Escape-ը չեղարկում է, ֆոկուսը թակարդված է։
10. **Success / Հաջողություն** — Գործողությունն ավարտվել է և ստուգված է; չստուգված/մասնակի արդյունքն օգտագործում է `blocked` կամ `error`, ոչ `success`։ Հատուկ ասում է ինչ հաջողվեց (ոչ ընդհանուր «Done»), `state-success`; state-փոփոխող արդյունքը թարմացնում է նաև հիմքում ընկած տեսքը։ Toast-երը բավական երկար են կարդալու համար, դադարում են hover-ի ժամանակ; reduced motion-ում՝ ակնթարթ ցուցիչ + տեքստ։

## Վիճակ → գործարկիչ → մշակում → գործողություն

| Վիճակ | Գործարկիչ | Հիմնական UI մշակում | Հիմնական գործողություն |
| --- | --- | --- | --- |
| Loading | Տվյալ/տեսք բեռնվում է | Skeleton (հայտնի ձև) կամ spinner/առաջընթաց, սեփականությունը տեսանելի | Cancel (եթե հնարավոր է) |
| Empty | Scope-ը դատարկ է | Առաջին անգամ / արդյունք չկա / զտված-դատարկ բլոկ | Ստեղծել / Ներմուծել / Մաքրել զտիչները |
| Populated | Առկա բովանդակություն | Ամբողջ բովանդակություն inline սեփականությամբ և կարգավիճակով | Էկրանի թույլատրված գործողությունները |
| Error | Գործողությունը ձախողվեց | Inline (վերականգնվող) կամ ամբողջ մակերես (ֆատալ) `state-danger` | Retry / Reload |
| Offline | Կապ/ծառայություն կորավ | Կայուն offline ցուցիչ; պահված բովանդակությունը՝ stale, գրելը անջատված | Reconnect / Retry |
| Permission-denied | Վավերացված, բայց ոչ լիազորված | Access-restricted մակերես կամ անջատված վերահսկիչ պատճառով | Հայցել access |
| Blocked | Չբավարարված պայման / կախվածություն / անորոշություն | `state-warning` բլոկ blocker-ի և լուծողի անունով | Գնալ blocker-ին / Կրկին ստուգել |
| Awaiting-approval | Կասեցված պարտադիր հաստատման համար | Ցայտուն pending վիճակ՝ հայց, scope, հայցող, կարգավիճակ | Approve / Reject (հաստատող) |
| Destructive-confirmation | Անշրջելի գործողությունից առաջ | Հաստատում՝ օբյեկտ + հետևանք, `action-destructive` confirm | Confirm կամ Cancel (անվտանգ լռելյայն) |
| Success | Գործողությունն ավարտվեց և ստուգվեց | `state-success` հաստատում + թարմացված տեսք | Continue / Undo / Դիտել արդյունքը |

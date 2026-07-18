- **Purpose:** Define the canonical desktop information architecture for BroPS — the app shell regions, their responsibilities, persistence rules, routing model, keyboard model, layering, and the mapping of every screen into the four navigation sections. This is the Phase 1 UX structural contract that all screen and component specs inherit from.
- **Scope:** Desktop-first app shell and structural UX. Trilingual product runtime (HY/EN/RU). Visual, motion, and theming rules are owned by [../DESIGN_SYSTEM.md](../DESIGN_SYSTEM.md); this document must never contradict it. Screen-level state and content are owned by the individual screen specs.
- **Owner:** Gev.
- **Related:** [../DESIGN_SYSTEM.md](../DESIGN_SYSTEM.md), [NAVIGATION.md](NAVIGATION.md), [SCREEN_INVENTORY.md](SCREEN_INVENTORY.md), [../ARCHITECTURE.md](../ARCHITECTURE.md).
- **Last updated:** 2026-07-19.

# BroPS Information Architecture

Status: Draft canonical.

BroPS presents thirteen backend domains ([../ARCHITECTURE.md](../ARCHITECTURE.md)) as one unified AI Operating System. The app shell is the single, always-present frame that hosts every screen. The sidebar is a projection of the system, not the system itself ([NAVIGATION.md](NAVIGATION.md)); this document defines the frame that holds that projection.

## 1. App shell regions

The shell is a fixed grid of six regions. All screens render inside `MainWorkspace`; nothing else in the shell is owned by a screen.

```
┌──────────────────────────────────────────────────────────────────────┐
│ TopBar (fixed, 56px)                                                   │
├───────────┬──────────────────────────────────────────┬───────────────┤
│           │                                          │               │
│  LeftNav  │            MainWorkspace                 │  RightDrawer  │
│  (rail /  │            (scroll owner)                │  (optional,   │
│  expanded)│                                          │   context)    │
│           │                                          │               │
├───────────┴──────────────────────────────────────────┴───────────────┤
│ StatusBar (fixed, 28px) + overlay surfaces (toasts, palette, Ask Bro) │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.1 LeftNav — left navigation (collapsible)

- Holds the four sidebar sections in fixed order: **Core, Intelligence, Operations, System** ([NAVIGATION.md](NAVIGATION.md)).
- Two width states: **expanded** (`260px`, icon + label + section headers) and **rail** (`64px`, icon-only, section headers become dividers, labels move to hover tooltips).
- Top of nav: workspace/product identity + a **Pin** zone for user-pinned items. Bottom of nav: current user avatar, presence, and the collapse toggle.
- Active route is highlighted with the `selected` semantic state; a section auto-expands to reveal the active item.
- Items may be pinned, reordered, or hidden by the user without changing routes or the domain model (Navigation law).

### 1.2 TopBar — top bar

Left to right:

1. **LeftNav collapse toggle** + optional breadcrumb of the current workspace/object.
2. **Global search** — an inline input that opens the search surface; typing `/` from anywhere focuses it.
3. **Command palette trigger** — a button labeled with the `Ctrl/Cmd+K` hint that opens the palette.
4. **Language switch — HY / EN / RU** — segmented control; switches at runtime with no reload, preserving navigation, drawers, filters, and unsaved form values (DESIGN_SYSTEM localization law).
5. **Theme switch — Dark / Light** — reflects System/Dark/Light preference, applies immediately to every surface.
6. **Notifications** — bell with unread count; opens the Notification center as a RightDrawer surface.
7. **Approvals badge** — a distinct, always-visible indicator of pending approvals; opens the Approval drawer. Kept separate from notifications because approvals gate execution and carry authority ([../ARCHITECTURE.md](../ARCHITECTURE.md) execution model).

### 1.3 MainWorkspace

- The only vertically scrolling region; the shell frame itself never scrolls.
- Renders exactly one active screen from the [SCREEN_INVENTORY.md](SCREEN_INVENTORY.md). Screens own their own internal layout, sub-navigation (e.g. project tabs, task views), and all eight required states (loading, empty, populated, error, offline, permission-denied, destructive-confirmation, success).

### 1.4 RightDrawer — optional right context drawer

- A single, reusable right-side container that hosts one context surface at a time: **Agent drawer, Project drawer, Task drawer, Approval drawer, Notification center, Context inspector, File preview, Execution log** ([SCREEN_INVENTORY.md](SCREEN_INVENTORY.md) Global Surfaces).
- Default width `380px`, user-resizable within `320–560px`. Opened by object links, TopBar actions, or deep links.
- Shows detail/inspection **alongside** the workspace; it never replaces the current screen (that is what routing does). Opening a drawer does not lose workspace context.

### 1.5 Persistent Bro command access — Ask Bro

- **Ask Bro** is reachable from every screen and every state (DESIGN_SYSTEM: "Persistent Bro command access").
- Access points: a persistent composer affordance anchored bottom-right of the shell, the palette (`>` command mode), and the global shortcut. It opens as an overlay composer/panel, above the workspace and drawer, so Gev can state intent without leaving the current context ([../ARCHITECTURE.md](../ARCHITECTURE.md): "Gev states intent").
- The Command workspace (SCREEN_INVENTORY #2) is the full-screen home of this surface; Ask Bro is its always-available overlay projection.

### 1.6 StatusBar and notification surfaces

- **StatusBar** (bottom, 28px): system health, active-agent count, execution/connectivity status (online/offline), current mode, and a compact language/theme readout. Non-blocking.
- **Toasts**: transient success/error/info, top-right stack, auto-dismiss per DESIGN_SYSTEM motion; never carry approval or destructive-confirmation decisions.
- **Notification center**: the durable list, opened in RightDrawer.

## 2. Region responsibilities — persist vs reset on navigation

"Navigation" = changing the active route in MainWorkspace. Persistence follows the state layers in [../ARCHITECTURE.md](../ARCHITECTURE.md) (conversation, workspace, canonical, evidence, memory).

| Region / state | Persists across navigation | Resets on navigation |
| --- | --- | --- |
| LeftNav expanded/rail, pins, section expansion | Yes (memory/profile) | No |
| Language and theme | Yes (per-profile, memory) | No |
| Ask Bro / conversation context | Yes (conversation state) | No |
| Approvals badge, Notification unread count | Yes (canonical/live) | No |
| RightDrawer open surface + target object | Yes **if addressed in the route**; otherwise closes | Closes when not part of the new route |
| MainWorkspace scroll position | No (restored only on back/forward) | Yes |
| Screen-local filters, sort, tabs, selection | Per-screen: restored on back/forward via route params; otherwise reset | Yes, on forward navigation to a new object |
| Unsaved form values | Preserved across **language/theme** switch; guarded by a discard confirmation on route change | Prompt-guarded |

Rule: never silently discard unsaved edits or an in-progress Ask Bro turn on navigation; require an explicit destructive-confirmation state (DESIGN_SYSTEM / SCREEN_INVENTORY).

## 3. Responsive and desktop breakpoints

Desktop-first (DESIGN_SYSTEM). Breakpoints govern shell collapse, not content redesign.

| Breakpoint | Range | LeftNav | RightDrawer | Notes |
| --- | --- | --- | --- | --- |
| `xl` | ≥ 1440px | Expanded | Docked, pushes workspace | Full three-column shell |
| `lg` | 1200–1439px | Expanded | Docked, pushes workspace | Default target |
| `md` | 1024–1199px | Rail (auto) | **Overlay** above workspace with scrim | Drawer floats, does not shrink workspace |
| `sm` | 768–1023px | Rail, expands as temporary overlay on hover/focus | Overlay full-height, up to 90vw | Compact desktop / split window |
| `xs` | < 768px | Collapsed to overlay drawer (hamburger) | Overlay full-width | Lower bound; below spec target, must not break |

Collapse behavior:

- LeftNav auto-collapses to rail at `md` and narrower; the user's manual expand/collapse choice always overrides the auto default until they clear it.
- At `md` and below, RightDrawer switches from **docked** (reflows workspace) to **overlay** (scrim, dismiss on scrim click or `Esc`).
- The shell never produces horizontal scroll; overflowing tables, boards, and timelines scroll inside their own containers.

## 4. Deep-linking and routing model

Every workspace, object, and drawer state is a first-class, shareable URL. This is mandatory: reload and share must restore the same view.

### 4.1 Route shape

```
/{workspace}/{objectType?}/{objectId?}/{subview?}?{query}#{anchor}
```

- **Workspace segment** — one per sidebar item: `home`, `command`, `chat`, `projects`, `tasks`, `agents`, `knowledge`, `memory`, `decisions`, `research`, `library`, `calendar`, `automations`, `approvals`, `activity`, `notifications`, `files`, `integrations`, `analytics`, `security`, `settings`.
- **Objects are addressable** — `project | task | room | thread | decision | approval | agent | file | knowledge | memory | automation | integration` each resolve by id, e.g. `/projects/project/PRJ-142/tasks`, `/chat/room/ROOM-9/thread/TH-3`, `/decisions/decision/DEC-58`.
- **Sub-view segment** — screen-local tabs and views: project tabs (`overview | chat | tasks | files | knowledge | decisions | agents | timeline | activity | settings`, per [NAVIGATION.md](NAVIGATION.md)); task views (`inbox | today | assigned-me | assigned-agents | waiting-approval | blocked | recurring | completed`).

### 4.2 Drawer and inspector state in the route

The RightDrawer is addressable via query params so it survives reload and share:

- `?drawer={agent|project|task|approval|notifications|inspector|file|log}&drawerId={id}` opens the corresponding surface over the current workspace.
- `?panel=ask-bro&thread={id}` restores the Ask Bro overlay and its conversation thread.
- Filters, sort, search, and pagination are query params (`?q=&status=&sort=&page=`) so a filtered list is shareable and back/forward-safe.

### 4.3 Resolution and guards

- Unknown/permission-denied object ids resolve to the screen's `permission-denied` or `error` state, never a blank frame.
- Language and theme are **not** in the path; they are profile state carried across all routes.
- Back/forward restores workspace scroll, screen-local filters, and drawer state from history entries.

## 5. Keyboard model

Full keyboard navigation is mandatory (DESIGN_SYSTEM accessibility). All shortcuts are localized in their labels but bound to physical keys.

### 5.1 Global shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl/Cmd+K` | Open **command palette** |
| `Ctrl/Cmd+J` | Open/focus **Ask Bro** composer |
| `/` | Focus **global search** |
| `Ctrl/Cmd+\` | Toggle LeftNav expanded/rail |
| `Ctrl/Cmd+.` | Toggle RightDrawer open/close |
| `Ctrl/Cmd+1..4` | Jump to section (Core / Intelligence / Operations / System) |
| `g` then `h/c/p/t/a` | Go to Home / Chat / Projects / Tasks / Agents (chord) |
| `Ctrl/Cmd+Shift+A` | Open Approvals |
| `Ctrl/Cmd+Shift+N` | Open Notifications |
| `Ctrl/Cmd+B` | Toggle theme Dark/Light |
| `?` | Open keyboard-shortcut help overlay |

### 5.2 Command palette (`Ctrl/Cmd+K`)

- Unified entry: navigation ("go to…"), object search, and actions/commands. A leading `>` forces **command/Ask Bro** mode; `#` scopes to objects; plain text is fuzzy navigation + search.
- Results grouped by section and object type; results are localized; `Enter` executes, `Cmd/Ctrl+Enter` opens the target in the RightDrawer instead of navigating.
- Fully keyboard-driven: arrow keys move, `Esc` closes and returns focus to the prior element.

### 5.3 Focus order and Escape/back

- Tab order: **skip-to-content link → TopBar (search, palette, language, theme, notifications, approvals) → LeftNav → MainWorkspace → RightDrawer → StatusBar.** A "skip to main workspace" link is the first focusable element.
- Focus is trapped inside the topmost modal or overlay palette while open; drawers do not trap focus but are fully tabbable.
- **Escape law:** `Esc` dismisses the topmost layer only, in z-order — toast/palette → Ask Bro overlay → modal → drawer — one layer per press. When no overlay is open, `Esc` clears the active search/selection; it never navigates away.
- **Back** (browser/`Alt+←`) changes the route only and respects the section 2 persistence rules and unsaved-edit guard.

## 6. Layering and z-order

One coherent stack. Higher layers receive input; lower layers are inert while a blocking layer is open.

| z-band | Layer | Blocking | Can stack |
| --- | --- | --- | --- |
| 0 | Shell frame + MainWorkspace | — | base |
| 10 | LeftNav / RightDrawer (docked) | No | with base |
| 20 | RightDrawer (overlay, `md`↓) + scrim | Soft (scrim dismiss) | over base only |
| 30 | Ask Bro overlay composer | No (non-blocking) | over workspace + drawer |
| 40 | Command palette / global search overlay | Soft | over all above; closes Ask Bro focus |
| 50 | Modal dialog (incl. destructive-confirmation, approvals-with-authority) | **Yes** (focus-trapped, scrim) | one at a time |
| 60 | Toasts / system alerts | No | always on top, never block input |

Stacking rules:

- **Only one modal at a time.** A modal supersedes and visually suppresses palette, Ask Bro, and drawers; opening a modal closes the palette.
- **Drawers do not stack**; requesting a second drawer surface replaces the current one in the single RightDrawer.
- **Toasts never carry decisions** — anything requiring authority or confirmation is a modal (approval, destructive action).
- Palette and Ask Bro are mutually exclusive for focus; the palette takes precedence when both are triggered.

## 7. The 22 screens across the four nav sections

Every screen in [SCREEN_INVENTORY.md](SCREEN_INVENTORY.md) maps to exactly one section. **Command** (#2) is the full-screen home of the persistent Bro access surface; **Group Chat** (#4) is a mode of Chat. Both remain routable workspaces while also surfacing as shell affordances.

### Core (7) — where work originates and is conducted
| # | Screen | Route |
| --- | --- | --- |
| 1 | Home | `/home` |
| 2 | Command | `/command` |
| 3 | Chat | `/chat` |
| 4 | Group Chat | `/chat/room/{id}` (group mode) |
| 5 | Projects | `/projects` |
| 6 | Tasks | `/tasks` |
| 7 | Agents | `/agents` |

### Intelligence (5) — durable knowledge and reasoning
| # | Screen | Route |
| --- | --- | --- |
| 8 | Knowledge | `/knowledge` |
| 9 | Memory | `/memory` |
| 10 | Decisions | `/decisions` |
| 11 | Research | `/research` |
| 12 | Library | `/library` |

### Operations (5) — time, execution flow, and gates
| # | Screen | Route |
| --- | --- | --- |
| 13 | Calendar | `/calendar` |
| 14 | Automations | `/automations` |
| 15 | Approvals | `/approvals` |
| 16 | Activity | `/activity` |
| 17 | Notifications | `/notifications` |

### System (5) — sources, connections, and governance
| # | Screen | Route |
| --- | --- | --- |
| 18 | Files | `/files` |
| 19 | Integrations | `/integrations` |
| 20 | Analytics | `/analytics` |
| 21 | Security | `/security` |
| 22 | Settings | `/settings` |

This mapping equals the [NAVIGATION.md](NAVIGATION.md) sidebar (20 sidebar items) plus the two nested surfaces (Command, Group Chat), for all 22 inventoried screens.

---

# Հայերեն

- **Նպատակ:** Սահմանել BroPS-ի desktop-ի կանոնական ինֆորմացիոն ճարտարապետությունը՝ app shell-ի տարածքները, դրանց պատասխանատվությունը, պահպանման կանոնները, routing-ի մոդելը, ստեղնաշարի մոդելը, շերտավորումը և բոլոր էկրանների բաշխումը չորս նավիգացիոն բաժինների միջև։ Սա Phase 1 UX-ի կառուցվածքային պայմանագիրն է, որից ժառանգում են բոլոր էկրանների ու կոմպոնենտների սպեցիֆիկացիաները։
- **Շրջանակ:** Desktop-first app shell և կառուցվածքային UX։ Trilingual runtime (HY/EN/RU)։ Visual, motion և theming կանոնները պատկանում են [../DESIGN_SYSTEM.md](../DESIGN_SYSTEM.md)-ին. այս փաստաթուղթը երբեք չի հակասում դրան։
- **Սեփականատեր:** Gev.
- **Առնչվող:** [../DESIGN_SYSTEM.md](../DESIGN_SYSTEM.md), [NAVIGATION.md](NAVIGATION.md), [SCREEN_INVENTORY.md](SCREEN_INVENTORY.md), [../ARCHITECTURE.md](../ARCHITECTURE.md)։
- **Վերջին թարմացում:** 2026-07-19։

Կարգավիճակ՝ Draft canonical.

BroPS-ն օգտագործողին ներկայացնում է տասներեք backend domain-ները ([../ARCHITECTURE.md](../ARCHITECTURE.md)) որպես մեկ միասնական AI Operating System։ App shell-ը միակ, մշտապես առկա շրջանակն է, որը պահում է յուրաքանչյուր էկրան։ Sidebar-ը համակարգի projection-ն է, ոչ թե ինքը համակարգը ([NAVIGATION.md](NAVIGATION.md))։

## 1. App shell-ի տարածքները

Shell-ը վեց տարածքից բաղկացած ֆիքսված grid է։ Բոլոր էկրանները ցուցադրվում են `MainWorkspace`-ի ներսում. shell-ի մնացած ոչինչ էկրանին չի պատկանում։

### 1.1 LeftNav — ձախ նավիգացիա (ծալովի)

- Պահում է չորս բաժինները ֆիքսված հերթականությամբ՝ **Core, Intelligence, Operations, System**։
- Երկու լայնության վիճակ՝ **expanded** (`260px`՝ icon + label + բաժնի վերնագրեր) և **rail** (`64px`՝ միայն icon, label-ները՝ hover tooltip-ով)։
- Վերևում՝ product identity և **Pin** գոտի, ներքևում՝ օգտատիրոջ avatar, presence և collapse կոճակ։
- Active route-ը նշվում է `selected` semantic վիճակով. active-ը պարունակող բաժինը ավտոմատ բացվում է։
- Item-երը կարող են pin-վել, վերադասավորվել կամ թաքցվել՝ առանց route-երը կամ domain մոդելը փոխելու։

### 1.2 TopBar — վերին վահանակ

Ձախից աջ՝ (1) LeftNav collapse toggle + breadcrumb, (2) **Global search** (`/`-ը ֆոկուսավորում է), (3) **Command palette trigger** (`Ctrl/Cmd+K`), (4) **Լեզվի փոխարկիչ HY / EN / RU** (runtime, առանց reload, պահպանելով նավիգացիան, drawer-ները, ֆիլտրերը և չպահված ձևերի արժեքները), (5) **Theme փոխարկիչ Dark / Light** (անմիջապես կիրառվում է բոլոր surface-երին), (6) **Notifications** (unread count, բացում է Notification center-ը RightDrawer-ում), (7) **Approvals badge** (միշտ տեսանելի ցուցիչ. approval-ները gate են անում execution-ը և կրում են authority, ուստի առանձնացված են notification-ներից)։

### 1.3 MainWorkspace

- Միակ ուղղահայաց scroll անող տարածքը. shell-ի շրջանակն ինքը երբեք չի scroll անում։
- Ցուցադրում է ճիշտ մեկ ակտիվ էկրան [SCREEN_INVENTORY.md](SCREEN_INVENTORY.md)-ից՝ իր ներքին layout-ով, sub-navigation-ով և ութ պարտադիր վիճակներով (loading, empty, populated, error, offline, permission-denied, destructive-confirmation, success)։

### 1.4 RightDrawer — ընտրովի աջ context drawer

- Մեկ վերօգտագործվող աջ container, որը միաժամանակ պահում է մեկ context surface՝ **Agent, Project, Task, Approval drawer, Notification center, Context inspector, File preview, Execution log**։
- Լռելյայն լայնությունը `380px`, չափափոխելի `320–560px` միջակայքում։ Բացվում է object link-երով, TopBar գործողություններով կամ deep link-երով։ Երբեք չի փոխարինում ընթացիկ էկրանին. context-ը չի կորչում։

### 1.5 Bro-ի մշտական հասանելիություն — Ask Bro

- **Ask Bro**-ն հասանելի է յուրաքանչյուր էկրանից և վիճակից (DESIGN_SYSTEM՝ «Persistent Bro command access»)։
- Մուտքի կետեր՝ shell-ի ներքև-աջ մշտական composer, palette-ի `>` command mode և global shortcut։ Բացվում է overlay-ով՝ workspace-ի և drawer-ի վրայից, որպեսզի Gev-ը կարողանա intent հայտնել՝ առանց context-ը լքելու։
- Command workspace-ը (SCREEN_INVENTORY #2) այս surface-ի լիաէկրան տունն է, Ask Bro-ն՝ դրա միշտ հասանելի overlay projection-ը։

### 1.6 StatusBar և notification surface-եր

- **StatusBar** (ներքև, 28px)՝ system health, ակտիվ agent-ների քանակ, execution/կապի վիճակ (online/offline), ընթացիկ mode, language/theme համառոտ ցուցում։ Չի արգելափակում։
- **Toast-եր**՝ անցողիկ success/error/info, վերև-աջ, երբեք չեն կրում approval կամ destructive որոշում։
- **Notification center**՝ մշտական ցանկը RightDrawer-ում։

## 2. Տարածքների պատասխանատվությունը — պահպանվում է vs զրոյացվում է նավիգացիայի ժամանակ

«Նավիգացիա» = MainWorkspace-ի ակտիվ route-ի փոփոխություն։ Պահպանումը հետևում է [../ARCHITECTURE.md](../ARCHITECTURE.md)-ի state շերտերին։

| Տարածք / վիճակ | Պահպանվում է | Զրոյացվում է |
| --- | --- | --- |
| LeftNav expanded/rail, pin-եր, բաժնի բացվածություն | Այո (memory/profile) | Ոչ |
| Լեզու և theme | Այո (per-profile) | Ոչ |
| Ask Bro / conversation context | Այո (conversation state) | Ոչ |
| Approvals badge, Notification unread | Այո (canonical/live) | Ոչ |
| RightDrawer բացված surface + object | Այո՝ **եթե route-ում է**, այլապես փակվում է | Փակվում է |
| MainWorkspace scroll դիրք | Ոչ (միայն back/forward-ով) | Այո |
| Էկրանի ֆիլտրեր, sort, tab, ընտրություն | Ըստ էկրանի՝ back/forward-ով վերականգնվում է route param-երից | Այո՝ նոր object-ի անցնելիս |
| Չպահված ձևերի արժեքներ | Պահպանվում են **language/theme** փոխարկման ժամանակ. route փոփոխությունը պաշտպանված է discard confirmation-ով | Prompt-ով պաշտպանված |

Կանոն՝ երբեք լուռ չկորցնել չպահված խմբագրումները կամ ընթացիկ Ask Bro turn-ը. պահանջվում է բացահայտ destructive-confirmation վիճակ։

## 3. Responsive և desktop breakpoint-եր

Desktop-first (DESIGN_SYSTEM)։ Breakpoint-երը կառավարում են shell-ի collapse-ը, ոչ թե բովանդակության վերաձևումը։

| Breakpoint | Միջակայք | LeftNav | RightDrawer |
| --- | --- | --- | --- |
| `xl` | ≥ 1440px | Expanded | Docked, հրում է workspace-ը |
| `lg` | 1200–1439px | Expanded | Docked |
| `md` | 1024–1199px | Rail (auto) | **Overlay** scrim-ով |
| `sm` | 768–1023px | Rail, hover/focus-ով ժամանակավոր overlay | Overlay, մինչև 90vw |
| `xs` | < 768px | Hamburger overlay | Overlay full-width |

Collapse վարքագիծ՝ LeftNav-ը `md`-ից ցածր ավտոմատ դառնում է rail, բայց օգտատիրոջ ձեռքով ընտրությունը գերակայում է. `md`-ից ցածր RightDrawer-ը docked-ից անցնում է overlay (scrim, `Esc`-ով dismiss)։ Shell-ը երբեք չի տալիս հորիզոնական scroll. աղյուսակները, board-ները և timeline-ները scroll են անում իրենց container-ի ներսում։

## 4. Deep-linking և routing մոդել

Յուրաքանչյուր workspace, object և drawer վիճակ առաջնային, կիսվող URL է. reload-ը և share-ը պետք է վերականգնեն նույն view-ն։

### 4.1 Route-ի ձևը

```
/{workspace}/{objectType?}/{objectId?}/{subview?}?{query}#{anchor}
```

- **Workspace հատված**՝ մեկը յուրաքանչյուր sidebar item-ի համար (`home … settings`)։
- **Object-երը հասցեավորելի են**՝ `project | task | room | thread | decision | approval | agent | file | knowledge | memory | automation | integration`, օրինակ՝ `/projects/project/PRJ-142/tasks`, `/chat/room/ROOM-9/thread/TH-3`։
- **Sub-view հատված**՝ project tab-եր (`overview … settings`) և task view-եր (`inbox … completed`) ըստ [NAVIGATION.md](NAVIGATION.md)-ի։

### 4.2 Drawer և inspector-ի վիճակը route-ում

- `?drawer={agent|project|task|approval|notifications|inspector|file|log}&drawerId={id}`՝ բացում է համապատասխան surface-ը ընթացիկ workspace-ի վրայից։
- `?panel=ask-bro&thread={id}`՝ վերականգնում է Ask Bro overlay-ն ու իր thread-ը։
- Ֆիլտր, sort, search, pagination՝ query param-եր (`?q=&status=&sort=&page=`), որպեսզի ֆիլտրված ցանկը կիսվող և back/forward-ապահով լինի։

### 4.3 Resolution և guard-եր

- Անհայտ կամ permission-denied object id-ները տանում են էկրանի `permission-denied` կամ `error` վիճակին, ոչ երբեք դատարկ շրջանակի։
- Լեզուն և theme-ը path-ում չեն. դրանք profile state են՝ կրվող բոլոր route-երով։
- Back/forward-ը վերականգնում է scroll-ը, էկրանի ֆիլտրերը և drawer-ի վիճակը history-ից։

## 5. Ստեղնաշարի մոդել

Լիարժեք keyboard navigation-ը պարտադիր է (DESIGN_SYSTEM accessibility)։

### 5.1 Global shortcut-եր

| Shortcut | Գործողություն |
| --- | --- |
| `Ctrl/Cmd+K` | Բացել **command palette** |
| `Ctrl/Cmd+J` | Ֆոկուսավորել **Ask Bro** |
| `/` | Ֆոկուսավորել **global search** |
| `Ctrl/Cmd+\` | LeftNav expanded/rail |
| `Ctrl/Cmd+.` | RightDrawer open/close |
| `Ctrl/Cmd+1..4` | Անցնել բաժին (Core / Intelligence / Operations / System) |
| `g` ապա `h/c/p/t/a` | Home / Chat / Projects / Tasks / Agents (chord) |
| `Ctrl/Cmd+Shift+A` | Բացել Approvals |
| `Ctrl/Cmd+Shift+N` | Բացել Notifications |
| `Ctrl/Cmd+B` | Փոխարկել theme Dark/Light |
| `?` | Shortcut help overlay |

### 5.2 Command palette (`Ctrl/Cmd+K`)

- Միասնական մուտք՝ navigation, object search և action/command։ Առաջատար `>`-ը ստիպում է **command/Ask Bro** mode, `#`-ը scope անում է object-երին, պարզ տեքստը fuzzy navigation + search է։
- Արդյունքները խմբավորված են ըստ բաժնի ու object տեսակի և localized են. `Enter`՝ execute, `Cmd/Ctrl+Enter`՝ բացել RightDrawer-ում՝ առանց navigate անելու։ Ամբողջովին keyboard-driven, `Esc`-ը փակում է և ֆոկուսը վերադարձնում։

### 5.3 Focus order և Escape/back

- Tab հերթականություն՝ **skip-to-content → TopBar (search, palette, language, theme, notifications, approvals) → LeftNav → MainWorkspace → RightDrawer → StatusBar**։ Առաջին focus-ելի տարրը «skip to main workspace» link-ն է։
- Ֆոկուսը թակարդված է վերին modal-ի կամ palette overlay-ի ներսում. drawer-ները թակարդ չեն, բայց լիովին tabbable են։
- **Escape կանոն**՝ `Esc`-ը dismiss է անում միայն ամենավերին շերտը z-order-ով (toast/palette → Ask Bro → modal → drawer)՝ մեկ սեղմումին մեկ շերտ։ Overlay չլինելիս `Esc`-ը մաքրում է ակտիվ search/ընտրությունը. երբեք չի navigate անում։
- **Back** (`Alt+←`)՝ փոխում է միայն route-ը՝ հարգելով բաժին 2-ի պահպանման կանոնները և չպահված խմբագրման guard-ը։

## 6. Շերտավորում և z-order

| z-band | Շերտ | Արգելափակող | Կարող է stack անել |
| --- | --- | --- | --- |
| 0 | Shell + MainWorkspace | — | base |
| 10 | LeftNav / RightDrawer (docked) | Ոչ | base-ի հետ |
| 20 | RightDrawer (overlay) + scrim | Մեղմ | միայն base-ի վրա |
| 30 | Ask Bro overlay | Ոչ | workspace + drawer-ի վրա |
| 40 | Command palette / global search | Մեղմ | վերևից. փակում է Ask Bro ֆոկուսը |
| 50 | Modal (destructive-confirmation, authority approval) | **Այո** (focus-trap, scrim) | մեկը միանգամից |
| 60 | Toast / system alert | Ոչ | միշտ վերևում, չեն արգելափակում |

Կանոններ՝ **միանգամից միայն մեկ modal**. modal-ը գերակայում է palette-ին, Ask Bro-ին ու drawer-ներին և բացվելիս փակում է palette-ը։ **Drawer-ները չեն stack անում**. երկրորդ surface-ը փոխարինում է ընթացիկին միակ RightDrawer-ում։ **Toast-երը երբեք որոշում չեն կրում**. authority կամ confirmation պահանջողը modal է։ Palette-ը և Ask Bro-ն ֆոկուսի համար փոխբացառող են. palette-ը գերակայում է։

## 7. 22 էկրանները չորս նավիգացիոն բաժիններում

[SCREEN_INVENTORY.md](SCREEN_INVENTORY.md)-ի յուրաքանչյուր էկրան պատկանում է ճիշտ մեկ բաժնի։ **Command**-ը (#2) persistent Bro surface-ի լիաէկրան տունն է, **Group Chat**-ը (#4)՝ Chat-ի mode։ Երկուսն էլ routable workspace են և միաժամանակ shell affordance։

### Core (7) — որտեղ ծնվում և վարվում է աշխատանքը
Home `/home`, Command `/command`, Chat `/chat`, Group Chat `/chat/room/{id}` (group mode), Projects `/projects`, Tasks `/tasks`, Agents `/agents`։

### Intelligence (5) — մշտական գիտելիք և դատողություն
Knowledge `/knowledge`, Memory `/memory`, Decisions `/decisions`, Research `/research`, Library `/library`։

### Operations (5) — ժամանակ, execution flow և gate-եր
Calendar `/calendar`, Automations `/automations`, Approvals `/approvals`, Activity `/activity`, Notifications `/notifications`։

### System (5) — աղբյուրներ, կապեր և կառավարում
Files `/files`, Integrations `/integrations`, Analytics `/analytics`, Security `/security`, Settings `/settings`։

Այս բաշխումը հավասար է [NAVIGATION.md](NAVIGATION.md)-ի sidebar-ին (20 item) գումարած երկու nested surface-երը (Command, Group Chat)՝ ընդամենը 22 inventoried էկրան։

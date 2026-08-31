# BroPS Desktop — Design System Reference

Canonical reference for the BroPS desktop UI (Phase-4 roadmap deliverable). It
documents the design tokens, the shared component library, the standard states,
and the accessibility and theming rules that every screen must follow.

Source of truth in code:

- `apps/desktop/src/theme/tokens.css` — CSS custom-property tokens.
- `apps/desktop/src/components/ui.tsx` + `ui.css` — the component library.
- `apps/desktop/src/components/charts/Chart.tsx` + `geometry.ts` — the chart
  primitives (`Beatline`, `StripChart`, `BarChart`) and their pure geometry.
- `apps/desktop/src/domain/enums.ts` — the `Tone` type and `statusTone` map.

## 1. Overview

The design system is a set of **CSS custom properties (design tokens)** — there
is **no CSS-in-JS** and no runtime styling library. Components declare semantic
class names (`.card`, `.btn`, `.badge`, …) in `ui.css`, and those classes resolve
their values from tokens. Nothing hard-codes a color; every color, space, radius,
shadow and duration is a `var(--menq-*)` / `var(--brops-*)` lookup.

Two token layers exist:

- **`--menq-*`** — the MenQ foundation scale and semantic palette (the raw
  values). Marked *provisional* in `tokens.css` pending the canonical MenQ source.
- **`--brops-*`** — BroPS semantic aliases that resolve back to `--menq-*`
  (e.g. `--brops-surface: var(--menq-color-surface)`). Components prefer the
  `--brops-*` aliases so the app has one indirection point over the foundation.

**Theming.** The default `:root` block defines the **light** theme; the
**dark** theme is applied as an override selector `:root[data-theme="dark"]` on
the `<html>` element. Only the semantic color tokens are re-declared for dark —
spacing, radii, fonts, shadows and motion are theme-independent. The `Theme`
type (`enums.ts`) is `'dark' | 'light'`.

## 2. Design tokens

### Colors — semantic palette (light default / dark override)

| Token | Role | Light (`:root`) | Dark (`[data-theme="dark"]`) |
| --- | --- | --- | --- |
| `--menq-color-bg` | App background | `#f5f6f8` | `#0c0e13` |
| `--menq-color-surface` | Card / panel surface | `#ffffff` | `#14171f` |
| `--menq-color-elevated` | Modals, popups, toasts | `#ffffff` | `#1b1f2a` |
| `--menq-color-text` | Primary ink | `#10131a` | `#eef1f6` |
| `--menq-color-muted` | Secondary / muted ink | `#5b6473` | `#98a2b3` |
| `--menq-color-border` | Borders / dividers | `#e2e5ea` | `#262b37` |
| `--menq-color-accent` | Brand accent | `#3d5afe` | `#7c8dff` |
| `--menq-color-accent-text` | Ink on accent fill | `#ffffff` | `#0c0e13` |
| `--menq-color-success` | Success tone | `#1f9d55` | `#4ade80` |
| `--menq-color-warning` | Warning tone | `#c77700` | `#f0b23a` |
| `--menq-color-danger` | Danger / error tone | `#d1435b` | `#f2708a` |
| `--menq-color-info` | Info tone | `#2a7de1` | `#6cb2ff` |
| `--menq-color-focus` | Focus ring color | `#3d5afe` | `#7c8dff` |
| `--menq-color-hover` | Hover wash | `rgba(61,90,254,0.08)` | `rgba(124,141,255,0.12)` |
| `--menq-color-selected` | Selected wash | `rgba(61,90,254,0.12)` | `rgba(124,141,255,0.18)` |

BroPS aliases: `--brops-bg`, `--brops-surface`, `--brops-elevated`,
`--brops-text`, `--brops-muted`, `--brops-border`, `--brops-accent`,
`--brops-accent-text`, plus `--brops-command-surface` (→ elevated) and
`--brops-agent-card-radius` (→ card radius).

### Spacing scale (theme-independent)

| Token | Value | | Token | Value |
| --- | --- | --- | --- | --- |
| `--menq-space-1` | `4px` | | `--menq-space-5` | `24px` |
| `--menq-space-2` | `8px` | | `--menq-space-6` | `32px` |
| `--menq-space-3` | `12px` | | `--menq-space-7` | `48px` |
| `--menq-space-4` | `16px` | | | |

### Radii

| Token | Value | Use |
| --- | --- | --- |
| `--menq-radius-sm` | `6px` | Small chips, inline action buttons |
| `--menq-radius-md` | `10px` | Buttons, inputs, most surfaces |
| `--menq-radius-card` | `14px` | Cards, modals, kanban columns |
| `--menq-radius-pill` | `999px` | Badges, bar-chart tracks |

### Typography

| Token | Value |
| --- | --- |
| `--menq-font-sans` | `"Inter", "Segoe UI", system-ui, -apple-system, "Noto Sans Armenian", sans-serif` |
| `--menq-font-mono` | `"JetBrains Mono", "Cascadia Code", ui-monospace, monospace` |

The Armenian fallback (`Noto Sans Armenian`) supports the `hy` locale
(`Lang = 'hy' | 'en' | 'ru'`).

### Shadows

| Token | Value | Use |
| --- | --- | --- |
| `--menq-shadow-1` | `0 1px 2px rgba(0,0,0,0.18)` | Subtle raise |
| `--menq-shadow-2` | `0 8px 28px rgba(0,0,0,0.28)` | Modals, popups, toasts |

### Motion

| Token | Value | Use |
| --- | --- | --- |
| `--menq-motion-fast` | `160ms` | Hover/border transitions, toast-in |
| `--menq-motion-med` | `240ms` | Bar-fill width, larger transitions |

All animated CSS is wrapped so that `@media (prefers-reduced-motion: reduce)`
disables it (typing dots, streaming caret, toast entrance, bar-fill, etc.).

## 3. Components

Exported from `apps/desktop/src/components/ui.tsx`. Each renders a semantic class
defined in `ui.css`; none accepts inline color styling.

| Component | Props | Renders |
| --- | --- | --- |
| `Card` | `children`, `className?`, `style?` | `.card` surface (border + `radius-card` + `space-5` padding). |
| `Panel` | `title?`, `actions?`, `children` | `Card` wrapping a `.panel` with an optional `.panel-head` (title + actions). |
| `PageHeader` | `title`, `subtitle?`, `actions?` | Top-of-page `.page-header` with `.page-title` / `.page-subtitle`. |
| `Button` | `variant?`, `small?`, `onClick?`, `title?`, `type?`, `disabled?` | `.btn`; variants `default`, `primary`, `danger`, `ghost`; `small` → `.btn--sm`. Disabled is dimmed (`opacity 0.5`). |
| `Badge` | `tone?: Tone`, `children` | `.badge.badge--<tone>` pill with a leading dot. Default tone `neutral`. |
| `StatusPill` | `status: string` | Maps `status` through `statusTone` → `Badge`; underscores become spaces. |
| `EmptyState` | `title`, `hint?`, `glyph?` (default `◍`) | Centered `.empty` block with glyph, title, muted hint. |
| `Avatar` | `name` | `.avatar` circle with the uppercased first initial. |
| `Field` | `label`, `children` | Stacked `.field` with an uppercase `.field-label` (read-only display pair). |
| `Skeleton` | `rows?` (default 3) | `aria-busy` stack of shimmer `.skeleton` bars — the loading placeholder. |
| `ErrorState` | `message`, `onRetry?`, `retryLabel?` | Danger-glyph `.empty` with message + optional retry `Button`. Falls back to a calm offline `EmptyState` when no backend is present. |
| `Async<T>` | `state`, `emptyTitle?`, `emptyHint?`, `children(data)` | The uniform loading/error/empty/populated wrapper around a list command (see §4). |
| `FormRow` | `label`, `children` | `<label>.form-row` with a `.field-label` — the standard form field wrapper. |
| `Input` | native input attrs + `ref?` | `.input`. |
| `Textarea` | native textarea attrs | `.textarea` (min-height, vertical resize). |
| `Select` | native select attrs | `.select`. |
| `Modal` | `title`, `onClose`, `children` | `.modal-scrim` + `.modal` dialog (`role="dialog"`, `aria-modal="true"`); scrim click closes, inner click is stopped. |
| `ConfirmDialog` | `title`, `message`, `confirmLabel`, `cancelLabel`, `onConfirm`, `onCancel` | `Modal` with a `ghost` cancel + `danger` confirm — the second step before any destructive action. |

Not a component but shared: `.badge` inside a calendar event, `.board-*`
(kanban), `.chat-*`, `.bar-chart`, `.toast*`, `.offline-banner` classes are all
defined in `ui.css` and consume the same tokens.

### 3.1 Phase-4 library primitives (G1–G9)

Reusable primitives added in Phase-4. Each is presentational and locale-neutral
(labels are passed in as props, so none call `useApp()` or touch the IPC layer),
each renders classes in `ui.css` (charts in `components/charts/`), and each
covers the standard §D concerns — role/aria, keyboard, non-color signal, and
`prefers-reduced-motion`.

Two chart primitives cover the interactive/static split: **`Beatline`** is a
static image with a text equivalent; **`StripChart`** is its live, keyboard-driven
sibling. **`BarChart`** covers horizontal-magnitude comparison. All three draw
from the same pure geometry (`components/charts/geometry.ts`) and share the
single-accent + summary + `<details>`-table accessibility contract — color is
never the signal.

| Primitive | Import | Props (key) | States / keyboard / aria / reduced-motion |
| --- | --- | --- | --- |
| **`DataTable<T>`** (G1) | `components/ui` | `columns: Column<T>[]`, `rows`, `rowKey`, `caption`, `loading?`, `emptyTitle?`/`emptyHint?`/`emptyGlyph?`, `onActivateRow?`, `skeletonRows?` | Native `<table role="table">` with `<caption>` + `<th scope="col">`. **States:** `loading` → `aria-busy` skeleton rows; `rows.length === 0` → `EmptyState`; else data rows. **Keyboard:** roving `tabindex` on rows — Up/Down move focus, Home/End jump, Enter/Space activate (when `onActivateRow`). **Non-color:** `numeric` columns right-align with tabular-nums (layout signal, not hue). **Motion:** none. |
| **`Drawer`** (G2) | `components/ui` | `title`, `onClose`, `side?='right'`, `children`, `footer?` | Mirrors `Modal`: `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, scrim-click closes, inner click stopped. **Keyboard:** Esc closes; Tab is trapped inside; initial focus lands on the first focusable; focus is restored to the opener on unmount. **Motion:** slide-in from the edge, disabled under reduced-motion. |
| **`Rail`** / **`RailSection`** (G3) | `components/ui` | `Rail`: `label`, `side?='left'`, `actions?`, `variant?='complementary'\|'panel'`, `children`. `RailSection`: `title`, `children` | Promotes the context/command/group-rail pattern; compose `RailSection` for titled sub-groups. **Two renderings:** `variant='complementary'` (default) → a landmark `<aside role="complementary">` with an accessible name and an uppercase rail header, for a rail that should be a navigable landmark; `variant='panel'` → the **same markup as `Panel`** (a `.card` > `.panel` with `label` as `.panel-title`, `space-5` padding, **no** landmark role) so a list/rail can adopt the rail model without adding a second `complementary` landmark or changing padding (used by the conversation list and the command run list). **Motion:** none. |
| **`TileGroup`** / **`StatTile`** (G4) | `components/ui` | `TileGroup`: `label`, `children`. `StatTile`: `glyph`, `value`, `label`, `hint?`, `countUp?`, `onActivate?` | Promotes Home's bespoke `.stat` tile (Home now renders its four workspace counts as a `TileGroup` of activating `StatTile`s). **Keyboard:** inside a `TileGroup`, arrow keys (both axes) + Home/End rove focus with a single tab stop; a `StatTile` with `onActivate` is a `<button>` with a trailing "→". **Non-color:** glyph + label carry meaning. **Motion:** optional integer count-up on a numeric `value`, snapped to the final value under reduced-motion. |
| **`Mark`** / **`LiveMark`** (G5) | `components/ui` | `Mark`: `word?='Br·PS'`, `sub?`, `glyph?='B'`, `responsive?=false`. `LiveMark`: `state?='live'\|'connecting'\|'offline'`, `label?`, `word?` | The "Br·PS" brand wordmark, extracted from the Shell (which now renders it). **Responsive:** with `responsive`, the text (word + sub) is hidden at **≤900px** — mirroring the collapsed-sidebar label rule — leaving only the square glyph, which keeps a `title` so the collapsed mark stays identifiable. **Non-color:** `LiveMark` shows a state word ("Live"/"Connecting"/"Offline") next to its dot; color only echoes it. **Motion:** the live dot pulses only in `state="live"`, disabled under reduced-motion (`livemark--still`). |
| **`InlineAlert`** (G6) | `components/ui` | `tone?='info'\|'success'\|'warning'\|'danger'`, `title?`, `children?`, `glyph?` | Inline notice strip. **Aria:** `danger` → `role="alert"` (assertive); calmer tones → `role="status"` (polite). **Non-color:** a leading glyph (`ℹ`/`✓`/`⚠`) carries the tone plus a left-border accent. **Motion:** none. |
| **`Beatline`** (G7) | `components/charts/Chart` | `data: BeatPoint[]`, `caption`, `summary?`, `unit?`, `height?`, `loading?`, `emptyTitle?`/`emptyHint?`, `valueHeader?`/`labelHeader?`, `showDots?` | Accessible **static** deterministic line/beatline chart (geometry in `components/charts/geometry.ts` — `buildECG`, `buildLinePath`, `pointCoords`, `ringPositions`, all pure). **States:** `loading` → `aria-busy` skeleton; empty `data` → `EmptyState`; else the plot. **Aria:** `<svg role="img">` labelled by a visible one-line `summary`; a `<details>` data-table fallback lists every point as text. **Non-color:** one accent stroke; meaning lives in the summary + table. **Motion:** the draw-on animation is disabled under reduced-motion. |
| **`StripChart`** (G8) | `components/charts/Chart` | `points: StripPoint[]`, `selected`, `opened?`, `frozen?`, `sweep?`, `plot?`, `beats?`, `ariaLabel`, `onSelect`, `onOpen`, `onToggleFreeze`, `onCloseOpened` | The **interactive** beatline/strip (Activity's ECG). A deterministic ECG trace (decorative, `aria-hidden`) overlaid with one roving-focus "blip" `<button>` per point, plus a freeze/select affordance. **Fully controlled** — the page owns `selected`/`opened`/`frozen` (to drive a detail panel, live region and vitals); the primitive owns the geometry, the roving `tabindex` and the keyboard model. **Keyboard** (on the focusable `role="group"` strip): ←↑/→↓ scrub selection (clamped, no wrap), Home/End first/last, **Enter** opens the selected blip (`onOpen`), **Space** toggles freeze (`onToggleFreeze`), **Esc** closes an open detail (`onCloseOpened`). **Non-color:** each blip carries a text `label` (aria-label + title); selection and open state expose `aria-pressed` + a shape/scale change, not hue. **Motion:** the sweep, the blip reveal and the dot transitions are disabled under reduced-motion. |
| **`BarChart`** (G9) | `components/charts/Chart` | `data: BarDatum[]`, `caption`, `summary?`, `unit?`, `hidden?`, `onToggle?`, `legendLabel?`/`showLabel?`/`hideLabel?`/`hiddenWord?`, `allHiddenNote?`, `totalLabel?`, `nodeHeader?`/`valueHeader?`/`shareHeader?`, `tableToggle?`, `showTable?` | Accessible **horizontal** bar chart (Analytics' distribution plot). One accent fill per bar with its value + share% of the visible total, a running total, and — when `onToggle` is given — a focusable legend whose items toggle series on/off (controlled via the `hidden` set). **States:** all series hidden → `allHiddenNote`; else the bars. **Aria:** the `.bar-chart` figure is `role="img"` labelled by a visible one-line `summary` (auto-generated in English, overridable); a `<details>` data-table fallback lists every series (value + share, "hidden" marked) as text. **Non-color:** the legend button's `aria-pressed` + a struck-through label mark a hidden series; every bar shows value + share% as text. **Motion:** the staggered bar entrance is disabled under reduced-motion. |

#### Intentionally bespoke: the Agents lattice

The Agents "live network" lattice (`features/Agents.tsx`) is **deliberately not**
extracted into a general radial/lattice chart primitive, and this is the
documented exception to "refactor every page onto a primitive." A faithful
primitive would have to absorb the page's whole interaction surface — a central
conductor hub, per-agent phase state with distinct suspend/interrupt animations,
governance link strokes streaming from hub to node, a roving-focus node ring wired
to a dossier panel, and the honest "telemetry pending" states. Generalizing all of
that would produce a one-consumer abstraction with a dozen slots and callbacks —
a contrived primitive that is harder to read than the bespoke component. So the
**stateful lattice stays bespoke**; what *is* genuinely reusable — the
deterministic ring geometry — was extracted to `ringPositions(n)` in
`components/charts/geometry.ts` (pure, tested) and is consumed by the page. That
keeps the shared, testable part in the library without forcing a bad abstraction.

### `usePrefersReducedMotion()` — the one export this page had not documented

The library ships 28 exports and this catalogue described 27. The missing one was the hook that
implements §C.1's *"every component honors `prefers-reduced-motion`"* — which is the wrong export
to leave undocumented, because a component author who does not know it exists writes the media
query again, or, more often, does not.

```tsx
const reduced = usePrefersReducedMotion();
// … the value drives BEHAVIOUR, not just CSS:
const shown = useCountUp(total, reduced);      // reduced → jump to the number, do not animate to it
<div className={`reactor${executing && !reduced ? ' dispatching' : ''}`} />
```

Use it when the motion is **produced in JavaScript** — a count-up, a `requestAnimationFrame` loop,
a class toggled while something streams. Use a `@media (prefers-reduced-motion: reduce)` block when
the motion is **declared in CSS**. Both are required and neither replaces the other: a CSS media
query cannot stop a `setInterval` from re-rendering, and the hook cannot reach a keyframe.

It subscribes to the media query rather than reading it once, so a user who changes the system
setting while the app is open gets the change immediately — the same reason the theme follows
`prefers-color-scheme` live.

**Reduced motion does not mean no feedback.** §C.1 says *"disable drift/ember/reveal animations,
keep opacity state changes"*: the surface must still show that something happened, it just must not
move to say so.

### Tones and the `statusTone` map

`Tone` (`enums.ts`) = `'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info'`.
Each maps to a `.badge--<tone>` rule: `neutral` uses muted ink on a hover wash,
`accent` uses the accent color on the selected wash, and `success` / `warning` /
`danger` / `info` use their semantic color over a 14% `color-mix` tint of that
same color.

`StatusPill` never picks a color directly — it looks the raw domain status up in
`statusTone` (falling back to `neutral`) and hands the resulting tone to `Badge`.
Representative mappings:

- `active`, `running`, `working`, `thinking`, `planning` → **accent**
- `done`, `completed`, `succeeded`, `approved`, `connected` → **success**
- `review`, `paused`, `awaiting_approval`, `pending`, `medium`, `high` → **warning**
- `blocked`, `failed`, `rejected`, `critical`, `error` → **danger**
- `observing`, `info` → **info**
- `inbox`, `planned`, `idle`, `offline`, `queued`, `cancelled`, `expired` → **neutral**

This gives every enum (`TaskStatus`, `AgentStatus`, `RunStatus`,
`ApprovalStatus`, `RiskLevel`, `Priority`, `Severity`, integration statuses) a
consistent color without any feature choosing colors itself.

## 4. States

Every data screen renders one of a small, fixed set of states. `Async<T>` is the
canonical dispatcher and should wrap any list command:

1. **Loading** — `state.loading && data === null` → `<Skeleton rows={4} />`
   (`aria-busy`), never a spinner or layout jump.
2. **Error** — `state.error` → `<ErrorState>` with the message and a retry
   button (`onRetry`). Permission-denied errors are prefixed with a translated
   "permission denied" label. When there is no desktop backend at all (browser
   preview), both `Async` and `ErrorState` degrade to a **calm offline**
   `EmptyState` (glyph `◍`) instead of the alarming red error.
3. **Empty** — resolved list of length 0 → `<EmptyState>` with `emptyTitle` /
   `emptyHint`.
4. **Populated** — `children(data)` renders the real content.

**Blocked (governance state).** `blocked` is a first-class domain status across
`TaskStatus`, `ProjectStatus`, and `AgentStatus`, and maps to the **danger**
tone. It is not a component state but a governance concept from the roadmap: an
item halted awaiting approval or unmet dependency. It surfaces through
`StatusPill status="blocked"` (a danger pill) and, for approvals, through the
A3 `ConfirmDialog` gate that blocks destructive actions behind a deliberate
second confirmation.

## 5. Accessibility & theming rules

- **Theme switching** is driven solely by the `data-theme` attribute on the
  `<html>` element. `:root` is light; `:root[data-theme="dark"]` overrides the
  semantic colors for dark. Never fork components per theme — set the attribute
  and let tokens cascade.
- **Reduced motion:** every animation is guarded by
  `@media (prefers-reduced-motion: reduce)`, which disables typing dots, the
  streaming caret, toast entrance, and bar-fill transitions. Any new animation
  MUST add the same guard.
- **Contrast:** the semantic ink/surface pairs are chosen for WCAG **AA** in
  both themes; tones are used as color *plus* a shape/label (badges carry text
  and a dot, pills carry the status word) so meaning never relies on color alone.
- **Keyboard & focus:** `Modal` sets `role="dialog"` + `aria-modal="true"`;
  interactive rows expose actions on `:hover` **and** `:focus-within` so
  keyboard users reach them; `--menq-color-focus` is reserved for focus
  affordances; `Skeleton` marks loading regions `aria-busy`.

## 6. How to use

- **Reuse, don't rebuild.** Compose screens from the components in `ui.tsx`
  (`PageHeader`, `Card`/`Panel`, `Button`, `Badge`/`StatusPill`, `Async`,
  `Modal`, `FormRow` + `Input`/`Select`/`Textarea`). See `features/Approvals.tsx`
  and `features/Tasks.tsx` for canonical composition.
- **Consume tokens via classes — never inline colors.** Reach for a semantic
  class first; if you must write CSS, resolve values from `var(--brops-*)` /
  `var(--menq-*)`. Do not hard-code hex colors, pixel spacing, radii, or
  durations — add or reuse a token instead.
- **Status → color goes through `statusTone`.** To color a domain value, render
  `<StatusPill>` (or `<Badge tone={statusTone[value]}>`); do not choose a tone
  inline. To add a new status, extend `statusTone` in `enums.ts` so the whole app
  stays consistent.
- **New tokens land in `tokens.css`** under the appropriate layer (`--menq-*`
  foundation, then a `--brops-*` alias if the app needs an indirection point),
  and dark values go in the `:root[data-theme="dark"]` block.

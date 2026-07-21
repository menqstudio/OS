# BroPS Desktop — Design System Reference

Canonical reference for the BroPS desktop UI (Phase-4 roadmap deliverable). It
documents the design tokens, the shared component library, the standard states,
and the accessibility and theming rules that every screen must follow.

Source of truth in code:

- `apps/desktop/src/theme/tokens.css` — CSS custom-property tokens.
- `apps/desktop/src/components/ui.tsx` + `ui.css` — the component library.
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

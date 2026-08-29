## Phase 4 — UI/UX System · UI/UX Համակարգ

**Objective.** Promote the design system from tokens-in-a-doc to a **real component library** and apply it
across the cockpit, then ship the observability pages (`activity`, `analytics`, `library`) so the product
looks and behaves like `brops-aios.html` — consistently, accessibly, in light and dark, with motion.

**Scope.** In: the reusable component set (surfaces, buttons, pills/marks, tiles, tables, charts,
skeletons, toasts, modals, rails), the theming layer, the motion system, the a11y baseline, and three
pages (`activity`, `analytics`, `library`). Out: domain data that later phases own (this phase renders
system/telemetry data already available).

**Architecture.** A `packages/ui` (or `apps/desktop/src/ui`) component library consuming §C.1 tokens as
CSS variables; a theme provider (dark default, light parity); a motion utility honoring
`prefers-reduced-motion`; a charting primitive (reproducing the prototype's `plot`/`beatline`/`sweep`
canvas visuals). Every Phase-3 page is refactored onto these components (no bespoke one-offs).

**UI/UX work.** The system itself is the deliverable, plus three pages:
- **Component library.** Surfaces (`surface`/`cut`/`hud`/`soft`), marks (`mark live`), pills, tiles,
- **`activity` ♥ Զարկերակ.** Components: ECG strip (`paBeatline`/`buildECG`), vitals readout (system pulse,
- **`analytics` ◈ Վերլուծություն.** Components: live deck (`anLive`/`anDeck`), distribution-by-node
- **`library` ❑ Դարան.** Components: the component/prompt/pattern catalog with live previews, search,

**Backend work.** Minimal desktop backend: telemetry/analytics read IPC (aggregates from the engine),
library store CRUD. Most work is frontend (component library + theming + charts).

**Contracts / schemas.** No new cross-boundary contract. Define **internal** component prop contracts +
a `theme-tokens` source of truth (generated from §C.1) so tokens never drift between doc and code.

**Data models.** Desktop: `library_item`, `telemetry_snapshot` (cache). Engine analytics remain
authoritative; the desktop caches for display.

**Dependencies.** Phase 3 (shell + token stylesheet). Runs in parallel with Phase 5 (§E) — disjoint pages
+ stores; reconcile only the shared shell/nav.

**Security gates.** Presentational phase, but the `blocked` state and any action that crosses the wall
still route through the governed path. No telemetry leaves the machine (local-only), consistent with the
engine's local-first posture.

**Tests.** Component unit tests (states + a11y via jest-axe/testing-library); visual/interaction tests
for the three pages; reduced-motion snapshot; contrast assertion for every token pair on `--bg`/`--surface`.

**CI requirements.** Frontend leg runs component + page tests + an a11y assertion gate; `npm run build`
green. A contrast/token-drift check (generated tokens match §C.1) runs in CI.

**Documentation updates.** A `docs/DESIGN_SYSTEM.md` (component catalog + tokens + motion + a11y rules);
update this phase's specs; `PROJECT_STATE.md`.

**Acceptance criteria.** Every Phase-3 page is refactored onto the shared library; `activity`,
`analytics`, `library` shipped to full §D; light+dark parity; reduced-motion honored; a11y gate green.

**Merge gate.** a11y gate green; token-drift check green; Architect design review; Owner approval.

**Stop conditions.** If a page needs bespoke CSS that bypasses the token system → stop, extend the system
instead. If a chart encodes meaning in color alone → stop, add a non-color signal (§dataviz).

> **⚖ Phase 4 was CHECKED AGAINST THE CODE before anything was built (2026-08-16),** the same
> way Phases 2 and 3 were. Most of it already existed. What verification is for is the part that
> did not, and this phase was swept along **four §D dimensions** rather than read page by page:
>
> | sweep | pages | real gaps |
> |---|---|---|
> | **Keyboard** | 22 | 1 — `automations` declared `/` and had no handler |
> | **States** | 22 | 1 — `command` rendered a governed REFUSAL identically to a dropped connection |
> | **A11y** | 21 | 2 — `tasks` lanes were bare `<div>`s, `command`'s trace had `aria-live` without `role=log` |
> | **Motion** | 14 | 0 |
>
> Two more were found by reading the pages the phase actually owns: **`analytics` had no scrubber
> at all**, and **`library`'s `Enter` did nothing while looking as though it did**. Six real
> defects, every one of them user-facing, none of them visible from a status board.
>
> Three pages flagged by the sweeps were **false positives, checked rather than trusted**: `group`
> inherits its keymap from `Conversations`, `activity`'s `Space`/`←→`/`Enter` live in the
> `StripChart` primitive, and `command`'s loading/error/empty come from the shared `Async`. A page
> that looks empty in its own file is not the same as a page that does nothing.

**Definition of Done.**
- [x] Component library with full §D state/keyboard/aria/reduced-motion coverage + usage docs. — **28 exports** in `components/ui.tsx` (`Async` · `Button` · `Card` · `ConfirmDialog` · `DataTable` · `Drawer` · `EmptyState` · `ErrorState` · `Modal` · `Panel` · `Rail` · `Skeleton` · `StatTile` · `StatusPill` · `TileGroup` · …), each documented in [`docs/DESIGN_SYSTEM.md`](docs/DESIGN_SYSTEM.md) §3.1. `Drawer` and `Modal` carry the full dialog contract (focus trap, initial focus, restoration, `Esc`); `Async` is the one place loading/error/empty are decided, which is why three pages that looked stateless are not. The a11y pass covers the primitives **and**, since 2026-08-16, the pages.
- [x] Theme provider (dark default + light parity); generated tokens match §C.1 (drift check green). — **measured, not assumed**: `aios.css`'s base `:root` declares 72 custom properties and `:root[data-theme="light"]` overrides **42** — every colour. The 30 it does not override are spacing, radii, type scale, fonts and motion, which are theme-independent by definition and would be a bug to fork. `check_token_parity` (tokens.ts ↔ tokens.css), `check_contrast` (24 pairs, **both** themes) and `check_c1_tokens` (42 §C.1 tokens + no undeclared `var()` + a monotonic spacing ladder in every tier) all gate this in CI.
- [x] `activity`, `analytics`, `library` pages shipped to full §D. — `activity`: ECG strip, vitals from real events only, `Space`/`←→`/`Enter` in `StripChart`. `analytics`: the **scrubber §D asks for**, built as an ARIA slider over the RANK cut-off rather than a timeline, because the engine exposes one all-time aggregate with no time dimension and this page refuses to invent an axis in three other panels. `library`: `/`, arrows, and `Enter` that now **opens** — it used to fire an `onClick` that re-selected the already-selected row while the preview it should open had no tab stop at all.
- [x] All Phase-3 pages refactored onto the library. — **25 of 28** feature modules import `components/ui`. The three that do not are named and reasoned: `Chat.tsx` is a 20-line delegate to `Conversations`, `writeRecord.tsx` is a helper rather than a page, and `Agents.tsx`'s stateful lattice is the **documented exception** in §3.1 — generalising it would produce a one-consumer abstraction with a dozen slots, so only the deterministic ring geometry was extracted (`charts/geometry.ts`, pure and tested).
- [x] `docs/DESIGN_SYSTEM.md` + `PROJECT_STATE.md` synced. — the catalogue described **27 of 28** exports; the missing one was `usePrefersReducedMotion`, which is the hook implementing §C.1's own reduced-motion rule. Documented now, with the distinction that matters: the hook is for motion produced in **JavaScript** (a count-up, an rAF loop), the media query for motion declared in **CSS**, and neither replaces the other.

**Task checklist.**
- [x] Build the component library (surfaces, marks, pills, tiles, tables, skeleton, toast, modal, rails). — see DoD row 1.
- [x] Theme provider + generated `theme-tokens` + CI token-drift/contrast check. — see DoD row 2; three gates, not one.
- [x] Charting primitive (plot/beatline/sweep) with accessible summaries + table fallback. — `components/charts/Chart.tsx`: `role="img"` labelled by a generated one-line summary, a `<details>` **data-table fallback** on every chart, a focusable legend, and share percentages on each row. §dataviz honoured — *"colour is never the signal"*: the line is one accent stroke, every blip carries a text label, and every table row states label **and** value.
- [x] `activity` page per §D (ECG + vitals + scrub/freeze). — keyboard scrub lives in `StripChart` with its own tests; every vital is derived from the real events array and the ones with no backing signal say so rather than showing a number.
- [x] `analytics` page per §D (distribution + autonomy/channel splits + scrubber). — the splits render **honest empties naming the missing engine aggregate**; the distribution and the scrubber are real.
- [x] `library` page per §D (catalog + search + previews). — see DoD row 3.
- [x] Refactor Phase-3 pages onto the library; author `docs/DESIGN_SYSTEM.md`. — see DoD rows 4 and 5.

---

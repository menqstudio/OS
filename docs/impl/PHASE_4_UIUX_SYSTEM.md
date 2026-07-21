# Phase 4 — UI/UX System · Implementation Spec

> ⚠️ **PROPOSAL — NOT EXECUTION AUTHORITY.** This spec is a *proposal* for review, not canonical.
> It does NOT authorize execution. Its architecture / trust / contract decisions are **§I controlled
> changes** requiring Architect audit + Owner approval before any build, and are **superseded where they
> conflict with the Challenger-Deep audit** (round 1) — esp. the receipt/sidecar/provider findings.


> Execution blueprint for `MASTER_EXECUTION_ROADMAP.md` §"Phase 4 — UI/UX System" (roadmap
> lines 718–804). Grounded in the code as it stands on `main`. Read this together with
> `docs/DESIGN_SYSTEM.md` (the current design-system reference) before starting. This is a
> build plan, not a change to the plan — nothing here alters architecture, trust boundary,
> security, or execution order (no §I event).

## 1. Objective & current state

**Roadmap intent.** Promote the design system from "tokens in a doc" to a *maintained component
library* applied across the cockpit, add the theming/motion/a11y/charting layers it is still
missing, wire a token-drift check into CI, and ship three observability pages — `activity`,
`analytics`, `library` — to full §D spec, on real (local) telemetry.

**What already exists (do NOT rebuild):**

- A real component library at `apps/desktop/src/components/ui.tsx` (+ `ui.css`): `Card`, `Panel`,
  `PageHeader`, `Button`, `Badge`, `StatusPill`, `EmptyState`, `Avatar`, `Field`, `Skeleton`,
  `ErrorState`, `Async<T>`, `FormRow`, `Input`, `Textarea`, `Select`, `Modal`, `ConfirmDialog`.
- The token layer: `apps/desktop/src/theme/tokens.css` — `--menq-*` foundation + `--brops-*`
  aliases, light `:root` default + `:root[data-theme="dark"]` override. Theme is driven by the
  `data-theme` attribute set in `app/store.tsx:72-75`.
- The tone system: `Tone` + `statusTone` in `domain/enums.ts:28-47`; `blocked` already maps to
  `danger`. `StatusPill` (`ui.tsx:51-54`) is the single status→color path.
- `docs/DESIGN_SYSTEM.md` already documents all of the above as the canonical reference.
- `activity` and `analytics` pages exist as thin real screens:
  `features/Activity.tsx` (lists `ActivityEvent[]` via `desktop.listActivity()`),
  `features/Analytics.tsx` (renders `Metric[]` from `desktop.getAnalytics()` as `MetricBars`).

**What is missing / mock (the actual Phase-4 work):**

1. `features/Library.tsx` **does not exist** (not in `features/registry.tsx:1-48`); `library`
   route falls through to `<Generic>`. It must be created.
2. No **charting primitive**. `Analytics.tsx:12-30` hand-rolls a CSS bar chart (`.bar-chart`);
   there is no reusable chart component, no ECG/beatline/sweep, no accessible-summary/table
   fallback (roadmap line 800; DESIGN_SYSTEM.md has no chart section).
3. No **motion tokens**. `tokens.css:23-24` has only `--menq-motion-fast/-med`; the roadmap's
   §C.1 motion set (`--spring`, `--enter`, `--stagger`, live-pulse) is absent, and there is no
   `reveal`/stagger utility. `prefers-reduced-motion` is honored in `ui.css` per-animation but
   there is no shared motion layer.
4. No **skeleton variety** beyond the flat `Skeleton` bar stack (`ui.tsx:79-87`) — no shimmer,
   no staggered reveal.
5. No **a11y gate** and no **token-drift/contrast check** in CI. Tokens live only in `tokens.css`;
   nothing asserts they match §C.1 or meet AA.
6. No **live telemetry**. `desktop.getAnalytics()` returns static `COUNT(*)` aggregates
   (`repo.rs:1447-1466`, `metrics()`); `list_activity` returns stored `audit_events` rows
   (`repo.rs` `security`/activity readers). There is no vitals stream, no ECG feed, no
   distribution-by-node/autonomy/channel split data.

## 2. Phase 4 specifics

### 2a. Formalize the component library into a maintained system

Extend `ui.tsx`/`ui.css` (keep the existing exports API-stable) with the primitives the roadmap
names (lines 736–738) and DESIGN_SYSTEM.md does not yet document:

| New primitive | Renders / role | Notes |
|---|---|---|
| `Tile` | KPI/stat tile (`.tile`) — big value + label + optional delta/spark | Replaces the ad-hoc `grid-3` cards in `Analytics.tsx:46-55`. |
| `DataTable<T>` | Sortable, keyboard-navigable table (`role=table`, arrow nav) | For analytics/library rows; not yet present. |
| `Chart` | Accessible charting primitive (see 2b) | New. |
| `SkeletonBlock` / `reveal` | Shimmer + staggered enter (`reveal` + `--stagger`) | Upgrade of `Skeleton`; add shimmer keyframe guarded by reduced-motion. |
| `Toast` / `InlineAlert` | Already partly in `ui.css` (`.toast*`) + `components/toast.tsx` | Formalize an exported `InlineAlert` for error/blocked rows. |
| `Drawer` | Side drawer variant of `Modal` (`role=dialog`) | For detail panes (activity beat detail, library preview). |
| `Rail` | `ctx-rail` / `cmd-rail` shell used by chat + later phases | Extract from chat markup. |
| `BlockedState` | First-class governance-denied panel: gate reason + lawful next step | New — §D "blocked" is currently only a `StatusPill status="blocked"` (DESIGN_SYSTEM.md §4). Make it a component so every wall-crossing page reuses it. |

Each primitive ships: all §D states where applicable, keyboard path, `aria-*`, a reduced-motion
variant, and a usage entry appended to `docs/DESIGN_SYSTEM.md` §3. Define **internal prop
contracts** (TypeScript interfaces co-located in `ui.tsx`) — no new cross-boundary contract
(roadmap line 760).

### 2b. Charting primitive (accessible-by-construction)

New `apps/desktop/src/components/chart.tsx` (+ `chart.css`). One `<Chart>` component with
variants `bars` | `line` | `beatline` (ECG) | `sweep`, driven by a typed `ChartSeries[]` model.
Hard requirements (roadmap lines 749–751, stop-condition line 788; load the `dataviz` skill):

- Every chart renders an accessible **summary** (`<figcaption>`/`aria-label`) **and** a visually
  hidden **`DataTable` fallback** of the same data.
- Color is never the only signal: series carry a shape/label/pattern too. Colors resolve from
  semantic tokens only (`--brops-accent`, `--menq-color-*`), never hard-coded.
- Motion (series enter, ECG pulse, sweep) uses the new motion tokens (2c) and is disabled under
  `prefers-reduced-motion`.
- Canvas or SVG is fine; if canvas, mirror the data into the DOM table for a11y + tests.

### 2c. Motion tokens + a theme/motion layer

Add to `tokens.css:23-24` (theme-independent block), sourced from roadmap §C.1 (line 142):

```css
--menq-motion-spring: cubic-bezier(.16, 1, .3, 1);
--menq-motion-enter: 640ms;
--menq-motion-stagger: 52ms;
--menq-motion-pulse: 1200ms;   /* live-data heartbeat */
```

Keep the existing `--menq-color-*`/`--brops-*` names (they are the real, shipped tokens);
DESIGN_SYSTEM.md documents `--menq-motion-fast 160ms` / `--menq-motion-med 240ms` — **reconcile**
the roadmap §C.1 values (`--fast 130ms`, `--slow 220ms`) into the doc rather than forking: the
**code tokens win** (DESIGN_SYSTEM.md line 99-102) and §C.1 is marked *Derived* (roadmap line 322).
Record any numeric reconciliation in DESIGN_SYSTEM.md §2 Motion. Add a `reveal`/stagger utility
class in `ui.css`, one `@media (prefers-reduced-motion: reduce)` guard covering it (mirror the
existing guards; DESIGN_SYSTEM.md §5).

### 2d. Token-drift + contrast CI check

New `apps/desktop/scripts/check-tokens.mjs` (run in the frontend CI leg): parse `tokens.css`,
assert (a) the token *names* the app relies on are present in both `:root` and
`:root[data-theme="dark"]`; (b) every ink/surface pair (`--menq-color-text` on `--menq-color-bg`
and on `--menq-color-surface`, plus each semantic tone) meets WCAG **AA** contrast in both themes
(compute the ratio in-script, no network); (c) DESIGN_SYSTEM.md §2's documented values match the
CSS (drift check — roadmap line 785, 799). Fail the build on any miss. Wire it into
`apps/desktop/package.json` scripts and the CI frontend leg (roadmap §B.4).

### 2e. Wire activity / analytics / library to real telemetry data (what IPC)

Today's data is thin (see §1.6). Add a small read-only telemetry surface — **local-only, no data
leaves the machine** (roadmap line 770). Two options, pick per the stop-condition rule (never
bespoke bypass): (1) extend the existing Rust command layer, or (2) add a `telemetry_snapshot`
cache table.

**New/extended Rust commands** (in `apps/desktop/src-tauri/src/commands.rs`, registered in
`src-tauri/src/lib.rs:63` `generate_handler!`, backed by `core/src/repo.rs`):

- `get_vitals() -> Vitals` — `{ systemPulse, avgResponseMs, networkLoad, errorRate, sampledAt }`,
  computed from `runs`, `messages`, `audit_events`, `approvals` (all existing tables). Feeds
  `activity` vitals readout.
- `stream_vitals(onEvent: Channel<Vitals>)` — periodic push for the live ECG strip (mirror the
  existing `Channel` pattern in `desktop.ts:124-128`, `streamReply` at `desktop.ts:162-167`).
  Server-tick every ~1s; the UI honors reduced-motion by falling back to a static readout.
- `get_analytics_breakdown() -> AnalyticsBreakdown` — distribution-by-node, autonomy split,
  channel split (roadmap line 750). Compute from `messages.role`/`author`, `runs`, `activity`.
  Extends `get_analytics` (`repo.rs metrics()` line 1447) rather than replacing it.
- `list_library_items() / create_library_item() / delete_library_item()` — desktop library store
  (see §3). `library` also reads the engine skill registry (roadmap line 755); that is a **read**
  and, if it needs a bridge/engine call, it is out-of-scope-for-now (render local items first,
  gate skill-registry read behind a follow-up — do not add an engine call in this phase without
  the §G.2 contract/audit path).

**Refresh model.** `activity` = live push (`stream_vitals`) + reload on focus; `analytics` =
pull on mount + manual refresh; `library` = pull + search-as-you-type (mirror `Knowledge.tsx:64`).

### 2f. Refactor Phase-3 pages onto the library

Every existing screen must compose only library primitives — no bespoke inline CSS (roadmap DoD
line 794, stop-condition 787). Concretely: replace `Analytics.tsx:46-55`'s inline
`{fontSize:30}` stat cards with `Tile`, and `MetricBars` with `Chart variant="bars"`. Audit all
`features/*.tsx` for hard-coded `style={{color/fontSize/padding}}` and move them to tokens/classes.

## 3. Data models / contracts

No new **cross-boundary** contract (roadmap line 760). New **local** shapes only:

- TS (`domain/entities.ts`): `Vitals`, `AnalyticsBreakdown`, `LibraryItem`, `NewLibraryItem`,
  `ChartSeries` (UI-only). Mirror Rust structs, camelCase (per `entities.ts:1-3`).
- Rust (`core/src/domain.rs`): matching structs; `Metric` (line 230 in entities) stays.
- SQLite: new migration `0012_library.sql` (forward-only; bump `SCHEMA_VERSION` in
  `core/src/db.rs:18` to 12, add to the `migrate` array `db.rs:65-77`):

```sql
CREATE TABLE IF NOT EXISTS library_items (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL DEFAULT 'component',   -- component | prompt | pattern
    title      TEXT NOT NULL,
    body       TEXT NOT NULL DEFAULT '',
    tags       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

Optionally add `library_items` to the FTS `search_index` (mirror the `knowledge_notes` triggers
in `0010_search_fts.sql:57-66`) so `library` search and global `search_all` cover it. A
`telemetry_snapshot` cache table is optional (roadmap line 763) — only add it if vitals need
persistence across restarts; otherwise compute on demand.

## 4. UI wiring & states (§D per page)

**`activity` ♥ Զարկերակ** (`features/Activity.tsx` — extend). Components: ECG strip (`Chart
variant="beatline"`), vitals `Tile` row (system pulse / avg response / network load / error rate),
per-event blip markers, freeze/plot/sweep controls. States: `default`(live via `stream_vitals`),
`loading`(strip skeleton), `empty`("no activity yet"), `error`(stream lost → `ErrorState`+retry),
`blocked`(`BlockedState`). Motion: `--menq-motion-pulse` heartbeat, count-up on vitals, blip
`reveal`+`--stagger`; all reduced-motion-guarded. Keyboard: `Space` freeze, `←/→` scrub blips,
`Enter` open a beat's detail (`Drawer`). A11y: strip carries a text-equivalent live region
(`aria-live=polite`, e.g. "system pulse 70/min"); blips are `<button>`s with HY labels.

**`analytics` ◈ Վերլուծություն** (`features/Analytics.tsx` — extend). Components: live deck of
`Tile`s, distribution `Chart`, autonomy split, channel split, scrubber (`role=slider`, arrow
keys). Keep the current `Async`+`getAnalytics` path; add `get_analytics_breakdown`. States: reuse
`Async` (loading/error/empty/populated, `ui.tsx:108-134`); add `empty`(no range) and `blocked`.
A11y: every chart has an accessible summary + `DataTable` fallback (2b).

**`library` ❑ Դարան** (`features/Library.tsx` — **create**; register in
`features/registry.tsx:27-48` under `library:`). Components: catalog grid of `LibraryItem`
previews, `/`-focus search (mirror `Knowledge.tsx:106-112`), filter chips (`kind`), live preview
`Drawer`. States via `Async`: `empty`("nothing saved") **distinct from** filtered-empty (roadmap
line 756 — pass a different `emptyTitle`/`emptyHint` when a query is active vs not, matching the
"nothing yet" vs "filtered to nothing" §D rule). Keyboard: `/` focus, arrow-navigate results,
`Enter` open. A11y: results `role=list`, previews labeled.

All three inherit the app-shell chrome from Phase 3; reconcile only the shared `#nav`/stage seam
(roadmap §E parallelization note — Phase 4 and Phase 5 run concurrently).

## 5. Exact files to touch

Create:
- `apps/desktop/src/features/Library.tsx`
- `apps/desktop/src/components/chart.tsx` + `chart.css`
- `apps/desktop/scripts/check-tokens.mjs`
- `apps/desktop/src-tauri/core/schema/0012_library.sql`
- tests (see §6)

Edit:
- `apps/desktop/src/components/ui.tsx` + `ui.css` (new primitives: `Tile`, `DataTable`, `Drawer`,
  `Rail`, `BlockedState`, upgraded `Skeleton`/`reveal`, `InlineAlert`)
- `apps/desktop/src/theme/tokens.css` (motion tokens `2c`)
- `apps/desktop/src/features/Activity.tsx`, `Analytics.tsx` (charts/tiles/telemetry)
- `apps/desktop/src/features/registry.tsx` (add `library`)
- `apps/desktop/src/services/desktop.ts` (new IPC: `get_vitals`, `stream_vitals`,
  `get_analytics_breakdown`, `list_library_items`, `create_library_item`, `delete_library_item`)
- `apps/desktop/src/domain/entities.ts` (new TS shapes)
- `apps/desktop/src-tauri/src/commands.rs` (new `#[tauri::command]`s) +
  `src-tauri/src/lib.rs:63` (register in `generate_handler!`)
- `apps/desktop/src-tauri/core/src/repo.rs` (`vitals()`, `analytics_breakdown()`, library CRUD),
  `core/src/domain.rs` (structs), `core/src/db.rs:18,65-77` (bump `SCHEMA_VERSION` → 12)
- `docs/DESIGN_SYSTEM.md` (new primitives §3, chart section, motion reconciliation §2), `PROJECT_STATE.md`

## 6. Tests & acceptance

- **Component unit tests** (`apps/desktop/src/components/*.test.tsx`, testing-library +
  jest-axe): every primitive's states + a11y; assert `BlockedState` shows a reason + next step.
- **Chart a11y test:** summary + table fallback present; a reduced-motion snapshot; assert no
  series relies on color alone.
- **Page tests:** `Activity`/`Analytics`/`Library` render all §D states (loading/empty/error/
  blocked); library distinguishes empty vs filtered-empty.
- **Token-drift/contrast:** `check-tokens.mjs` runs green in CI; add a failing-fixture test that
  it *catches* a drift (a token removed from the dark block) and an AA violation.
- **Rust:** `cargo test -p brops-core` covers `vitals()`, `analytics_breakdown()`, library CRUD
  + the `0012` migration (mirror existing repo tests); keep 29+ green.
- **Acceptance (roadmap 782–785, DoD 790–795):** all Phase-3 pages compose only library
  primitives; `activity`/`analytics`/`library` shipped to full §D; light+dark parity; reduced
  motion honored; a11y gate + token-drift check green in CI; Architect design review; Owner
  approval. Verify with `cd apps/desktop && npm ci && npm run build` (tsc + vite) and the Rust
  legs (§B.4). No `git push`/merge — hand Gev the commands (§B.5).

## 7. Security notes

Presentational phase, but: (a) the `blocked` state and any action crossing the wall still route
through the governed path (Phase 1 `bridge.*`); `BlockedState` surfaces the engine verdict reason
and offers the lawful next step (request approval) — never a local override. (b) Telemetry is
**local-only** — no vitals/analytics leave the machine (consistent with `ai.rs` local-first
posture and roadmap line 770). (c) No new secret/key/lease handling — this phase touches no
`engine/` security code; if a chart or telemetry need pressures an engine change, **stop** and
raise it as a separate audited engine task (§G.2, roadmap stop-conditions). (d) The token-drift
check is defense against silent visual/contrast regressions, not a security control, but keep it
network-free (no external contrast API) to preserve the offline posture.

## 8. Dependencies / open questions

- **Depends on Phase 3** (shell + token stylesheet + routing). Phase 3 is not yet merged
  (roadmap phase board: P3 ⏳ blocked on P1/P2). If P3's shell isn't present when this starts,
  the three pages can still be built against the existing `features/registry.tsx` + `ui.tsx` and
  reconciled onto the shell seam later — but the refactor-all-pages DoD (line 794) needs P3's
  shell. Flag if starting ahead of P3.
- **Runs parallel to Phase 5** (roadmap §E) — disjoint pages/stores; only the `#nav` seam is
  shared. Coordinate the migration number (`0012` here vs Phase 5's `0012`/`0013`) so two agents
  don't collide on `SCHEMA_VERSION` — claim the next free integer in `TASKS.md` first (§B.2).
- **Open:** does `library` read the engine **skill registry** now, or defer? Reading it is a
  cross-boundary call; recommend shipping the local library store first and gating the
  skill-registry read behind a follow-up task with the §G.2 contract/audit path.
- **Open:** exact numeric reconciliation of motion durations (§C.1 `130/220ms` vs code
  `160/240ms`) — pick code values, update the doc, note it; this is editorial (not a §I event).
- **Open:** live `stream_vitals` tick rate and battery/perf budget — pick a conservative default
  (~1s, pausable via freeze), confirm in review.

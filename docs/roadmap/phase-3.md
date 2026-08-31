## Phase 3 — Desktop Integration · Desktop-ի ինտեգրում

**Objective.** Stand up the real cockpit shell wired to the governed engine: the app frame (side nav +
stage + command dock), the `home` overview, governed `chat`, and `settings` — so the owner opens one app
whose core loop (talk to Bro → governed turn → verified result) works end-to-end.

**Scope.** In: the app shell (`.app`/`.side`/`#nav`/`.stage`), the global command dock (`cmd-dock`,
⌘K), routing across the 22-page registry, and three core pages (`home`, `chat`, `settings`) fully wired.
Out: the domain pages owned by later phases (they get placeholder routes now).

**Architecture.** React/TS webview in Tauri; Rust backend owns IPC + the bridge call from Phase 1. The
shell is the cross-cutting chrome every later page mounts into; the command dock routes to any page and
issues governed actions through the bridge. Begins the `contracts/` dedupe (shared shapes referenced,
not yet moved).

**UI/UX work.** Full §D specs for the shell + three pages:
- **App shell.** Components: brand (`.brand` `Br·PS` live mark), `#nav` (22-entry icon+label rail), `.stage`
- **`home` ⌂ Ամփոփում (Overview).** Components: summary tiles (system pulse, pending approvals count,
- **`chat` ✦ Զրույց Bro-ի հետ (governed).** Components: thread (`thread`), composer (`composer`/`compInput`),
- **`settings` ⚙ Կարգավորումներ.** Components: sections (provider, appearance/theme, governance sidecar

**Backend work.** Rust: route registry + IPC wiring; the governed chat command calling the Phase-1
adapter; settings persistence; theme. Frontend: the shell, router, three pages, design-token stylesheet
(reproducing §C.1). Placeholder routes for phases 2/4–9 pages.

**Contracts / schemas.** Reuse Phase-1 `bridge.*`. Begin `contracts/` dedupe: reference (do not yet
relocate) `execution-lease`/`approval`/`task-contract`/`mode-grant`; record the migration plan for the
final dedupe milestone.

**Data models.** Desktop SQLite: `conversation`, `message` (with `receipt_id`, `verified`), `setting`,
`route_state`. Product/UI state only; security truth stays in the engine.

**Dependencies.** Phase 1 (governed chat) + Phase 2 (governance surfaces reachable from the shell).

**Security gates.** Governed chat uses the fail-closed, verified-receipt-mandatory path (no verified
receipt ⇒ no message body). Settings can enable the governed provider but never holds keys/leases. The
shell exposes the Phase-2 `blocked` states wherever an action crosses the wall.

**Tests.** Frontend: shell routing, `⌘K` dock, three pages' state coverage (incl. `blocked`). Rust:
governed chat command returns fail-closed on missing receipt; settings persist/restore. Cockpit suites +
Phase-1 bridge tests stay green.

**CI requirements.** Frontend leg runs the new UI tests; `npm run build` (tsc + vite) green; `cargo
check` on the app crate green. Keep all Phase-0/1 legs green.

**Documentation updates.** `docs/ARCHITECTURE.md` (shell + governed chat loop), `README` screenshot/flow
if visuals change, this phase's specs, `PROJECT_STATE.md`, and the `contracts/` dedupe plan note.

**Acceptance criteria.** Owner opens the app → navigates the 22-page rail → talks to Bro → gets a
**verified** governed reply (or a legible fail-closed `blocked` state) → sees settings/theme persist.
All shell + three-page §D states implemented. Build green.

**Merge gate.** Governed chat proven fail-closed + verified; shell a11y (keyboard + aria) reviewed;
Architect confirms no security regression; Owner approval.

**Stop conditions.** If governed chat cannot produce a verified receipt in the desktop deployment →
stop, resolve trust-root provisioning with Owner (do not fall back to ungoverned by default). If shell
work pressures an engine change → audited task.

> **⚖ Phase 3 was CHECKED AGAINST THE CODE before anything was built (2026-08-15),** the same way
> Phase 2 was, and under the committed exemption in `config/roadmap-order-exemptions.json` — Phase 1
> and Phase 2 are both held by the Owner's production gate, so 3 is the first phase with buildable
> work. The shell, the router, all 23 routes and the three core pages **already existed**. So the
> first act was verification, and it earned its keep: **two live defects nothing could see.**
>
> 1. **`--s7` and `--s9` were never declared**, on a ladder documented as `--s1..--s10`, while
>    `padding:var(--s7) var(--s5)` shipped on the Agents and Automations empty states. An undeclared
>    custom property makes the whole declaration invalid at computed-value time, so **those panels
>    rendered with no padding at all.** §C.1 listed eight values for a ten-name range, which is why
>    the gap read as deliberate to everyone who checked. Six more bare `var()` references were
>    dropping their declarations the same way and now carry their base state as a fallback.
> 2. **The `cmd-dock` was a modal the keyboard could walk out of.** No `role="dialog"`, so a screen
>    reader announced nothing; no focus trap, so `Tab` left the palette while a scrim still covered
>    the page; no focus restoration; no `aria-activedescendant`, so the active row was a CSS class
>    and nothing more. §D nominates this surface as the keyboard route to all 23 pages, which makes
>    a keyboard-only owner its primary user and made it the surface that served them worst.
>
> Both fixed, both mutation-verified, and `tools/check_c1_tokens.py` now holds the stylesheet to
> §C.1 — 42 tokens — and refuses a bare `var()` that nothing declares. Restoring the `--s7` bug
> turns that gate RED, so the check catches the defect that created it.

**Definition of Done.**
- [x] App shell (nav + stage + `⌘K` dock) with full routing across all 23 registry entries. — `Shell.tsx` (brand · grouped `#nav` with roving tabindex + `aria-current=page` · `main tabindex=-1` · skip link in `App.tsx` · off-canvas drawer under 860px), `routes.tsx` (a **total** `Record<RouteId, …>`, so a route id without a page is a compile error; lazy chunks; a route-level error boundary that prints the real thrown value; focus moved into the new page's heading on every navigation). `CommandPalette.tsx` is the `cmd-dock`: ⌘K/Ctrl+K, ARIA combobox owning a listbox, `aria-activedescendant`, `Tab` trap, focus restored to the opener, ↑/↓/Home/End/Enter/Esc. **Both of the last two were refuted as stated by the fifth audit and are true now, not then:** the trap was bound to the input alone, so one click on the panel's padding blurred to `<body>` and the next `Tab` escaped behind the scrim (`A-02`, found with trusted browser input — jsdom's tab model cannot see it); and the restore chased a node the route change had already unmounted, a silent no-op on the palette's primary path (`A-03`). The trap is now a mousedown guard plus a document-level handler, and the restore refuses a detached opener. **23**, not 22 — `bridge` became its own route when it stopped being reachable only from inside `decisions`.
- [x] `home`, `chat` (governed), `settings` built to full §D spec incl. `blocked`. — `Home.tsx` 562 · `Conversations.tsx` 1053 (which `Chat.tsx` renders as `kind="direct"`, so the delegation surface sits inside the workspace that owns the conversation) · `Settings.tsx` 433. Each carries the real §D state set — `Skeleton`/`EmptyState`/`ErrorState`, `blocked`, `aria-live` — against the real IPC with no fixture layer behind it: outside Tauri every call rejects and each panel renders its own error state.
- [x] Design-token stylesheet reproducing §C.1; `prefers-reduced-motion` honored. — **now checked, not asserted**: `tools/check_c1_tokens.py` reads §C.1 out of this file and holds `aios.css`'s `:root` to all 42 tokens, positional rows (type scale · radii · spacing) matched by order, with a row whose value count disagrees with its token-name range treated as an **error** rather than a partial read. `prefers-reduced-motion` is honoured globally (`aios.css`) and again per page. `check_token_parity` compares a *different* pair of files for a *different* set of names and never covered this ladder.
- [x] Governed chat fail-closed + verified-receipt-mandatory, badge shown. — `receiptBadge()` maps only the backend's own vocabulary and **fails closed on everything else**: `trusted_verified` → green, `demonstration_*` → info, `development_untrusted` → warning, and any unrecognised value gets **no badge**, never a promotion. A `blocked` governed turn persists no message at all — it raises a turn-level notice carrying the engine's reason (`Conversations.tsx`), so there is no body to badge. Covered by `Conversations.verified.test.tsx`.
- [x] `contracts/` dedupe plan recorded; docs + `PROJECT_STATE.md` synced. — [`docs/design/CONTRACTS_DEDUPE_PLAN.md`](docs/design/CONTRACTS_DEDUPE_PLAN.md), measured rather than recalled: **four** schema homes, not two, and **no duplicated schema file exists anywhere in the tree**. The real drift is a Python schema and a hand-written Rust type bound by nothing but a doc comment — so the milestone's first step is a **binding gate**, not a move. It also records that `approval`, named as canonical by both `contracts/README.md` and this phase's Contracts row, **does not exist** — the same absence Phase 2 found from the other end (`T-021`).

**Task checklist.**
- [x] Build the app shell + router + `#nav` (23 entries) + `cmd-dock` (`⌘K`). — see DoD row 1; the palette got its **first tests** in the same change (9, six mutants killed).
- [x] Ship the design-token stylesheet (colors/type/space/motion) from §C.1. — and the two missing rungs of the spacing ladder, which is what made this row worth re-checking instead of ticking.
- [x] `home` overview page per §D (incl. first-run empty state). — `Home.tsx`; the first-run state is `EmptyState` plus the `Onboarding` overlay mounted in `App.tsx`.
- [x] `chat` page wired to the Phase-1 governed turn + receipt badge, all §D states. — see DoD row 4.
- [x] `settings` page (provider toggle, theme, sidecar config, about) per §D. — `Settings.tsx`; theme and language also live in the shell footer, so neither requires leaving the page you are on.
- [x] Placeholder routes for phase-2/4–9 pages; a11y keyboard pass on the shell. — there are **no placeholders left**: all 23 routes resolve to real pages. `Generic.tsx` was described here as "unreachable", and it was not: `openEntity` took `ent.route as RouteId` — a **cast over a backend-supplied string** — so a search result naming an unknown route rendered the placeholder (`A-08`, fifth audit). A cast is a promise to the compiler, not a check on the value. Both entry points validate now, the way `routeFromHash` always did. The a11y pass is the `cmd-dock` work above plus the existing roving-tabindex rail, and it is pinned by tests rather than by having been performed once.

---

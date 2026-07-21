# Phase 3 — Desktop Integration · Implementation Spec

> Execution blueprint for `MASTER_EXECUTION_ROADMAP.md` §"Phase 3 — Desktop Integration"
> (roadmap lines 624–714). Grounded in the code as it stands on `main`. This is a build plan,
> not a change to the plan — nothing here alters architecture, trust boundary, security, or
> execution order (no §I event). The one security-critical seam (flowing a *verified* receipt
> into a rendered message) is called out for Architect audit in §7.

---

## 1. Objective & current state

**Roadmap intent.** Stand up the real cockpit shell wired to the governed engine: app frame (side
nav + stage + command dock), `home` overview, governed `chat`, and `settings` — so the owner opens
one app whose core loop (talk to Bro → governed turn → **verified** result) works end to end, with
`blocked` states wherever an action crosses the wall.

**What already exists (do NOT rebuild — this phase is mostly *wiring + hardening*):**

- **App shell is built.** `components/Shell.tsx` renders the sidebar (brand + `NAV` groups),
  topbar (search button, lang select, theme toggle, approvals/notifications badges with real
  counts, `Shell.tsx:14-17`), and the `.content` stage. `App.tsx:8-20` composes Shell +
  `<Screen route={route}>` + `CommandPalette` + `Toaster`.
- **Routing is built.** `app/nav.ts` declares all 22 `RouteId`s + `NAV` groups; `app/store.tsx`
  owns `route`/`setRoute`/`openEntity`/`focus` (deep-link) and theme/lang/`governedEngine`
  persisted to `localStorage`. `features/registry.tsx:27-53` maps routes → components, falling
  through to `<Generic>` for unbuilt pages (so "placeholder routes" already exist).
- **Command palette exists** (`components/CommandPalette.tsx`), opened via `setPaletteOpen`
  (`Shell.tsx:48`).
- **Three core pages exist as real screens:** `features/Home.tsx` (Ask-Bro via `streamAsk` +
  priorities/approvals/agents/projects panels), `features/Chat.tsx` → `Conversations.tsx`
  (`kind="direct"`), `features/Settings.tsx` (theme, language, **governed-engine toggle** —
  `Settings.tsx:42-57`, backed by `store.tsx:28-31,61,84-87`).
- **Governed chat backend is built (Phase 1 slice 2).** `ai.rs` has `Provider::GovernedEngine`
  (`ai.rs:260-265, 294-336`), `governed_engine()` subprocess (`ai.rs:1097-1163`),
  `governed_request()` (`ai.rs:1039-1050`), and `interpret_bridge_result()` — the fail-closed,
  VERIFIED-receipt-mandatory guard (`ai.rs:1064-1090`). `generate`/`generate_stream`
  (`ai.rs:447-491`) already dispatch to it.
- **The receipt badge UI is built.** `Message.receipt?: 'verified' | 'blocked' | null`
  (`entities.ts:104-115`) and `Conversations.tsx:182-186` already render a `Badge` (success/danger)
  from it.

**What is missing / mock (the actual Phase-3 work):**

1. **Receipt-plumbing is broken end to end.** `ai.rs::interpret_bridge_result` verifies the receipt
   but then **discards it** — `governed_engine` returns only `Result<String>` (`ai.rs:1163`), so the
   `verified` flag and receipt id never leave the AI layer. `stream_reply`/`reply_in_conversation`
   (`commands.rs:487-549, 769-801`) persist the reply as a plain `agent` message with **no receipt**.
   `repo::chat::post_message` has no `receipt` column. So `Message.receipt` is *always* null and the
   badge never lights. **This is the core Phase-3 deliverable** (roadmap line 654, 703-705).
2. **The Settings toggle is inert.** `governedEngine` (store) records *intent* only; live routing is
   driven by env (`BROPS_AI_PROVIDER=governed-engine` + `BROPS_ALLOW_GOVERNED_ENGINE=1`,
   `ai.rs:312-324`). The toggle does not change the provider (roadmap wants the toggle to be the
   control surface; today it is a preference the backend ignores — see §8 open question).
3. **No `blocked` state on chat** when the governed provider is on but the sidecar is down/fail-closed.
   Today a governed failure surfaces as a generic `replyError` string (`Conversations.tsx:209-211`),
   not the §D `blocked` panel with the fail-closed reason + lawful next step.
4. **Shell a11y/keyboard gaps** vs §D (roadmap lines 640-646): nav buttons are not `aria-current=page`;
   `<main>` is not focused on route change (no `tabindex=-1`); no `⌘K` binding is documented; no
   page hotkeys; the sidebar does not collapse to icons <1024.
5. **`settings` lacks** the governance-sidecar config section + about (`MENQ OS v0.9`) + `blocked`
   (misconfigured) guidance (roadmap lines 660-661).

---

## 2. Backend / IPC to build

The core work is **plumbing the receipt through**, not new providers. Data flow of one governed turn:

```
Chat composer ─▶ desktop.streamReply(convId)         (services/desktop.ts:162-167)
   ▶ commands.rs::stream_reply
       ▶ ai::generate_stream(system, history, on_delta)         (ai.rs:463-491)
           ▶ Provider::GovernedEngine ▶ governed_engine()       (ai.rs:1097-1163)
               ▶ spawn bridge/engine_sidecar.py (stdin task-request → stdout bridge.result)
               ▶ interpret_bridge_result()  ── ok && receipt.verified ⇒ reply, else fail-closed
   ◀ reply text  ─────── PLUS the receipt verdict (NEW: no longer discarded)
   ▶ repo::chat::post_message(role=agent, body, receipt)        (NEW receipt column)
   ▶ StreamEvent::Done { message{ receipt } }  ─▶ badge lights   (Conversations.tsx:182)
```

**Changes:**

- **`ai.rs`** — introduce a small return type so the verdict survives:
  ```rust
  pub struct Generated { pub text: String, pub receipt: Option<ReceiptTag> }
  pub enum ReceiptTag { Verified, Blocked }   // maps 1:1 to Message.receipt
  ```
  `governed_engine` returns `Generated { text, receipt: Some(Verified) }` on the ok+verified path and
  surfaces `Blocked` (not a bare Err) when `interpret_bridge_result` fails closed so the UI can show
  the §D `blocked` state. The three non-governed providers return `receipt: None` (ungoverned turns
  carry no badge — matches `entities.ts:111-114`). `generate`/`generate_stream` return `Generated`.
- **`commands.rs`** — `stream_reply` (and `reply_in_conversation`) thread `Generated.receipt` into
  `NewMessage`/`post_message`; on a `Blocked` verdict emit a terminal `StreamEvent::Error` **carrying
  the fail-closed reason** (or a new `StreamEvent::Blocked { reason }` variant, `commands.rs:474-480`)
  so chat renders `blocked`, not a generic error, and **no result body is shown** (contract).
- **`brops-core`** — add a nullable `receipt` column to the `message` table (migration in
  `db::open`) and to `NewMessage`/`Message` (`src-tauri/core/src/domain.rs`) + `repo::chat::post_message`.
  Values constrained to `verified` | `blocked` | NULL.
- **Settings ↔ provider (see §8):** either (a) leave env-driven and make the toggle reflect
  `ai_status().provider` read-only, or (b) add a `set_ai_provider` command persisting to a `setting`
  row that `ai::resolve()` consults. Recommendation: (a) for this phase (no new secret path), (b) is a
  larger surface. Decide with Architect.

No new engine or bridge code — the governed path already exists and fails closed.

---

## 3. Data models / contracts

- **`Message.receipt`** (`entities.ts:104-115`) — already declared `'verified' | 'blocked' | null`.
  Backend now populates it. No TS change needed beyond ensuring `normalizeMessage`
  (`desktop.ts:30-32`) preserves it (it spreads `...m`, so it already does).
- **`StreamEvent`** (`desktop.ts:177-180` / `commands.rs:474-480`) — optionally add
  `{ type: 'blocked'; reason: string }` so the fail-closed governed state is distinct from a provider
  error. Update the `Conversations.tsx` stream handler (`Conversations.tsx:134-138`) to match.
- **Reused Phase-1 contracts:** `bridge/contracts/task-request.schema.json` +
  `bridge-result.schema.json` (unchanged). The receipt id itself lives in the engine ledger; the
  desktop stores only the `verified`/`blocked` **tag** alongside the turn (roadmap lines 478-479,
  671) — product state only, no security truth crosses.
- **`contracts/` dedupe (roadmap lines 668-670, 706):** *record the plan only* — reference (do not
  relocate) `execution-lease`/`approval`/`task-contract`/`mode-grant`; add the migration note.

---

## 4. UI wiring

| Surface (file) | Wire / harden | States to implement |
|---|---|---|
| **App shell** (`Shell.tsx`) | add `aria-current={route===id?'page':undefined}` on nav buttons; `<main tabindex={-1}>` + focus on route change; sidebar collapse to icons `<1024`; document `⌘K` (bind in `CommandPalette`) | route `loading`/`error`(page failed to mount — wrap `<Screen>` in an error boundary)/`blocked` |
| **`home`** (`Home.tsx`) | already real; add first-run `empty` (welcome HY + "Talk to Bro" CTA) when all panels are empty; keep Ask-Bro | default / loading (`Async`) / empty(first-run) |
| **`chat`** (`Conversations.tsx`) | consume the new receipt tag → badge already renders (line 182); add the §D **`blocked`** panel from the governed fail-closed reason (replace the generic hint at `Conversations.tsx:209-211`); keep `pwThink`/typing pulse | default / loading(turn running) / empty(first message) / error(turn failed) / **blocked**(governed on + sidecar down → reason, **no body**) |
| **`settings`** (`Settings.tsx`) | add a **governance sidecar** section (status from `ai_status()`, `ai.rs:432-439`) + **about** (`MENQ OS v0.9`) + `blocked`(misconfigured) guidance; keep theme/lang/governed toggle | default / blocked(sidecar misconfigured → guidance) |

Keyboard/a11y per §D (roadmap lines 640-661): chat `Enter` send / `Shift+Enter` newline / `@` mention
(already in `Conversations.tsx:84-102`) / `↑` edit last / `Esc` cancel run; thread `role=log
aria-live=polite`; badge announces verification (`aria-live`). Honor `prefers-reduced-motion` (theme
change respects it). Placeholder routes for phases 2/4–9 already handled by `<Generic>`.

**Honest handling when data isn't available yet:** the governed turn cannot produce a *live* verified
receipt without operator provisioning (`ai.rs:435-438` reports `ready:false`; the sidecar real mode
fails closed, `engine_sidecar.py:98-118`). So in the default deployment the badge path is exercised via
the self-test sidecar (`python bridge/engine_sidecar.py --self-test`) and the UI's `blocked` state is
the *expected* live state until provisioning lands. Do **not** fall back to ungoverned-as-verified —
an ungoverned turn carries `receipt:null` and no badge (contract: no verified receipt ⇒ no badge).

---

## 5. Exact files to touch

**Rust:**
- `apps/desktop/src-tauri/src/ai.rs` — `Generated`/`ReceiptTag`; `governed_engine` returns the tag;
  `generate`/`generate_stream` propagate it (`ai.rs:447-491, 1097-1163`).
- `apps/desktop/src-tauri/src/commands.rs` — thread the tag through `stream_reply` /
  `reply_in_conversation`; add `StreamEvent::Blocked` (`commands.rs:474-549, 769-801`).
- `apps/desktop/src-tauri/core/src/domain.rs` + `repo.rs` + `db.rs` — `message.receipt` column +
  `NewMessage`/`Message` field + migration + `post_message` write.

**TypeScript:**
- `apps/desktop/src/services/desktop.ts` — extend `StreamEvent` union (blocked); confirm receipt passes through.
- `apps/desktop/src/features/Conversations.tsx` — `blocked` panel + stream handler for the new variant.
- `apps/desktop/src/features/Settings.tsx` — sidecar-config + about + blocked sections.
- `apps/desktop/src/features/Home.tsx` — first-run empty state.
- `apps/desktop/src/components/Shell.tsx` — `aria-current`, `main` focus, responsive collapse, `⌘K`.
- `apps/desktop/src/i18n/en.ts` (+ `hy.ts`) — keys for blocked reasons, about, first-run, sidecar config.

**Docs (same-commit):** `docs/ARCHITECTURE.md` (shell + governed-chat loop), `PROJECT_STATE.md`,
`TASKS.md`, and the `contracts/` dedupe-plan note.

**Never touched here:** `engine/`, `bridge/engine_adapter.py`, `bridge/engine_sidecar.py`.

---

## 6. Tests & acceptance

**Tests (roadmap lines 680-685):**
- Rust: a governed chat turn returns fail-closed (`Blocked`, no body) on a missing/unverified receipt
  — extend the `ai.rs` tests (`ai.rs:1241-1340`) with an `interpret_bridge_result` case that yields
  `ReceiptTag::Blocked`; a `post_message` round-trip persists and restores `receipt`.
- Frontend: shell routing + `⌘K` dock; chat renders `verified` badge on a self-test turn and `blocked`
  on a fail-closed turn (no body shown); settings persist/restore theme + toggle.
- Keep green: `cargo test -p brops-core` (29), `cargo check` on the app crate, `npm run build`
  (tsc + vite), and the Phase-0/1 bridge legs (§B.4).

**Acceptance (roadmap lines 690-706):** owner opens the app → navigates the 22-page rail → talks to
Bro → gets a **verified** governed reply (badge lit) *or* a legible fail-closed `blocked` state
(no body) → sees theme/settings persist. All shell + three-page §D states implemented incl.
`blocked`. Build green.

---

## 7. Security notes

**Needs Architect audit (🛑 fail-closed chat gate, roadmap G.1 row "Phase 3"):**
- The **receipt-plumbing seam** — flowing a `verified` tag into a *rendered* message body. Audit that
  `Message.receipt='verified'` is set **only** when `ok && receipt.verified` (the same invariant
  `interpret_bridge_result` already enforces, `ai.rs:1064-1090`) and that a `Blocked`/unverified turn
  **never** renders a body (roadmap line 654, 677-678). A wrong tag would let an unverified turn
  masquerade as verified — exactly the failure the whole spine exists to refuse.
- The `message.receipt` column value domain must be closed (`verified`/`blocked`/NULL only); the
  webview must not be able to POST a `receipt` on a `post_message`/`post_user_message` call
  (`commands.rs:293-333`) — the tag is server-derived, never client-supplied.

**Safe (normal PR flow):** shell a11y/keyboard/responsive work, Home first-run copy, settings
about/theme, i18n keys, `contracts/` dedupe *plan note* (no relocation). Settings never holds
keys/leases (`ai.rs` reads secrets from env only, `ai.rs:11-20`).

**Invariants to preserve:** governed chat stays fail-closed + verified-receipt-mandatory (no verified
receipt ⇒ no body); the desktop holds no lease/key/env; the default non-governed provider paths stay
byte-for-byte unchanged (roadmap line 469-470).

---

## 8. Dependencies & open questions

- **Depends on Phase 1** (governed chat turn) — built — and **Phase 2** (governance surfaces reachable
  from the shell). The shell/pages can proceed now; the *live* verified badge depends on provisioning.
- **Owner (provisioning) — blocking for a live verified badge:** the sidecar real mode needs
  `BRO_KEYDIR`/`BRO_REGISTRY_ROOT`/`BRO_BINDING`/`BRO_REPOSITORY_ROOT`/`BRO_BUILDER_COMMAND`
  (`engine_sidecar.py:50-56`); until provisioned it fails closed (`engine_sidecar.py:114-118`). Ship
  with the self-test path proving the plumbing and the `blocked` state as the expected live state.
- **Architect (audit) — blocking:** the receipt-tag seam (§7) is a 🛑-adjacent security review; and the
  sidecar's real-mode **verifier swap** is an explicit Architect-audited follow-up
  (`engine_sidecar.py:25-33`) — the desktop badge can only show `verified` once that lands. Do not wire
  a fake verifier to light the badge.
- **Open question — the Settings toggle vs env routing:** should the toggle *control* the provider
  (needs a persisted `setting` + `ai::resolve()` reading it, option (b) in §2) or merely *reflect* the
  env-driven provider read-only (option (a))? Recommendation (a) for this phase — it adds no new
  control path over the wall; escalate (b) to the Architect if the owner wants in-app switching.
- **Stop condition (roadmap lines 697-699):** if governed chat cannot produce a verified receipt in
  the desktop deployment, **stop** and resolve trust-root provisioning with the Owner — do not fall
  back to ungoverned-by-default.

# BroPS Changelog

- **Purpose:** Record notable repository changes, most recent first.
- **Scope:** Documentation and, later, released application changes. Future work is in [ROADMAP.md](docs/ROADMAP.md).
- **Owner:** Gev.
- **Last updated:** 2026-07-22.

BroPS was intentionally recreated from zero; prior history is not part of this repository. Since the monorepo merge into `menqstudio/OS`, cockpit changes also flow through the OS-level security-remediation waves; the exact live state (branch/PR/blockers) is the root [`NEXT_CHAT.md`](../../NEXT_CHAT.md).

## 2026-07-22 — OS-monorepo security remediation (Waves 1–3a)

Closing the Challenger Deep audit's P0/P1 findings, on top of the merged desktop app. Enforced model: [SECURITY.md](SECURITY.md). Schema is now **v13** (migrations through 0013); `cargo test -p brops-core` GREEN (**69 tests**). All merged security PRs passed independent zero-trust re-audits.

- **Wave 1 — provider fail-closed** (T-012, PR #15 `15384cb`): no silent governed→ungoverned fallback; ungoverned only via `BROPS_ALLOW_UNGOVERNED=1`; honest 3-state provider status.
- **Wave 2a — webview message provenance** (T-013, PR #16 `d85dcba`): `post_message` roles restricted to `["user"]`; server-held answer via one-time `result_id`.
- **T-010 — Tauri capability boundary** (PR #19 `7d537c3`): deny-by-default manifest over all 65 commands; L2 hard-deletes denied; CI invariant `tools/check_capabilities.py`.
- **T-011 — durable approval + native confirmation** (PR #20/#21, merge `7638a64`): migrations 0012/0013; restart-safe self-approval; native-only approval; nonce compare-and-consume; atomic pre-dispatch execution claim; crash recovery; enforced single-instance lock.
- **Wave 3 — Receipt Protocol v1 design rev 4** (PR #23 `35a6ab5`): Ed25519 signed per-turn receipt, desktop = final verifier, fail-closed. Architect + Owner GREEN.
- **Wave 3a slice 1 — receipt protocol core** (`brops-core::receipt`), **PR #24 MERGED** (approved HEAD `c51031e`, merge commit `6c920d0`): RFC 8785 JCS, strict decode, verify-only `verify_strict`, type-state `parse→verify→bind→resolve_3a` chain, `IssuedRequest` request-hash recompute, private-field `ResolvedManifestKey`, `Wave3aTrustState` (no "Verified" variant). **Zero-trust GREEN** after three RED rounds (`a873501`/`aa4dc01`/`f5b6ffe`), CI 7/7 GREEN, 69 core tests. Slice 2 (storage/migration 0014) not started.

## 2026-07-19 — Security hardening (audit remediation)

Ten rounds of adversarial security review closed every finding; no Critical/High remained. The enforced model is documented in [SECURITY.md](SECURITY.md). Highlights:

- **Filesystem** confined to a `~/BroPS` root (override `BROPS_FILES_ROOT`), canonicalized (no traversal/symlink escape), with an always-on sensitive-path denylist; edits are regular-file-only, size-bounded, atomic, and permission-preserving.
- **AI subprocess** runs tool-free (`--tools ""`, `--strict-mcp-config`, `--setting-sources project`) in a unique owner-only sandbox; the transcript goes via stdin and the system prompt via a `0600` file — no confidential text in argv; absolute deadlines + byte caps; crash-residue sandboxes are swept by process-liveness.
- **Network:** Ollama is loopback-only unless `BROPS_ALLOW_REMOTE_OLLAMA=1` (+HTTPS); all outbound clients disable redirects.
- **Input** is size/role/count-validated before dispatch; **data at rest** is `0700`/`0600`; **CI actions** are SHA-pinned and gated on `clippy -D warnings` + a release build.
- Final audit pass fixes: one-shot subprocess stderr drain bounded by the deadline; Anthropic client no-redirect; broader secret denylist (tfstate/gitconfig/vault…); sandbox first-init race cleanup; agent-name sanitized before the system prompt; the approval gate is enforced in `set_step_status` (not just `advance`); transitive dependency-cycle detection; `LIKE` wildcard escaping; Approvals surface decision errors + A3 dual-confirm.

## 2026-07-19 — Phases 4–20: working desktop app

The app moved from a tested data core to a fully working desktop application — every navigation surface is backed by real Tauri commands over SQLite (the mock layer was deleted). Highlights, roughly in build order:

- **Backed screens (Phases 4–5):** projects/tasks CRUD, approvals, notifications, decisions/agents/activity, Chat + Group Chat, Knowledge + Memory, a `std::fs` Files browser, and Command→runs / Calendar→events / Automations / Integrations / Analytics / Security over real tables.
- **Live AI (Phases 7–9):** provider layer (`src-tauri/src/ai.rs`) defaulting to the local `claude` CLI (Gev's subscription, free) with token-by-token **streaming** over a Tauri `Channel`; Anthropic API + Ollama fallbacks. Markdown-rendered replies (dependency-free, XSS-safe renderer) and a live "Ask Bro" box.
- **Chat depth (Phases 10, 12):** pick the replying agent, group turns, `@mention` autocomplete, conversation delete/rename, live Markdown while streaming.
- **Execution + control (Phases 6, 13–14):** Command runs **actually execute** each step via the AI and persist results; **approvals actually gate** execution (approved→run, rejected→terminal, else pending + `awaiting_approval`); the run state machine and gating are transaction-safe and adversarially reviewed.
- **Operations UI (Phases 11, 15–18):** global search + command palette, toasts, "Save to chat", Tasks **kanban board** (drag), **Calendar** month view, **Analytics** charts.
- **Phase 19 — reach & editing:** command-palette **deep-links** (open the specific project/task/knowledge/conversation via a routing `focus` target), **Projects** detail/edit/status/tabs, and honest **offline / permission** states with a preview banner.
- **Phase 20 — completeness:** **Task dependencies** (blockers, self-edge + cycle guarded), **Files** text view/edit (`read_file`/`write_file`, 2 MB + binary guarded), and **full-text search via FTS5** (a `search_index` virtual table kept in sync by triggers; tokenized, prefix, multi-term, injection-safe).
- **Verification:** `cargo test -p brops-core` GREEN (**28 tests**), host lib test GREEN, `npm run build` GREEN, clippy clean, release binary builds, and CI (frontend + data-core + desktop-build) green. Schema at **v10**. A three-agent deep audit (backend / frontend / end-to-end runtime) found no critical or high-severity defects.

## 2026-07-19 — Phase 3 data core (SQLite) + Tauri scaffold

- Added `src-tauri/core` (`brops-core`): SQLite schema, forward-only migrations, and typed project/task/audit repositories. `cargo test -p brops-core` is GREEN (6 tests: migration idempotency, CRUD, foreign-key enforcement, validation, audit).
- Scaffolded the Tauri 2 host (`src-tauri/`): `AppState`, typed `#[tauri::command]` surface, `tauri.conf.json`, capabilities. The GUI binary build needs system webview libraries and is documented in `src-tauri/README.md` (not built in the authoring environment).

## 2026-07-19 — Phase 2 frontend prototype

- Running React + TypeScript + Vite prototype: app shell, command palette, all primary screens with mock data, trilingual HY/EN/RU switching, Dark/Light themes, semantic design tokens. `npm run build` is GREEN.
- Backend (Tauri/Rust/SQLite) deferred to Phase 3, marked as prototype rather than fake-working.

## 2026-07-19 — Reconciled implementation line

- Merged the `brops-v1-foundation-implementation` scaffold and deeper architecture docs (`docs/architecture/*`, `IMPLEMENTATION_EXECUTION_HANDOFF.md`, `MENQ_STUDIO_DESIGN_STANDARD_ADOPTION.md`) onto the canonicalized foundation without reintroducing the old flat docs.

## 2026-07-19 — Phase 1 UX architecture delivered

- Completed the Phase 1 UX flows (`product/`): information architecture, chat, project/task, decision/approval, agent, and remaining-workspace flows, plus canonical states. Roadmap Phase 1 exit condition met.

## 2026-07-19 — Foundation v1 Locked

- Marked Foundation v1 (Roadmap Phase 0) **Locked** after review, canonicalization, and the Phase 1 UX-architecture layer (decision D-010).
- Removed the transient `FOUNDATION_REVIEW.md` working artifact.

## 2026-07-19 — Phase 1 UX architecture

- Added `product/INFORMATION_ARCHITECTURE.md`, `product/CHAT_FLOWS.md`, `product/PROJECT_TASK_FLOWS.md`, `product/DECISION_APPROVAL_FLOWS.md`, and `product/STATES.md`.

## 2026-07-19 — Foundation canonicalized

- Consolidated 35 flat root documents into one source of truth per topic.
- Merged `MISSION` + `VISION` + `PRODUCT_SCOPE` into `PROJECT_CONTEXT.md`.
- Merged `PRINCIPLES` + `LAWS` into `PRINCIPLES.md` (laws keep IDs L-001..L-012).
- Merged `DECISIONS` + `DECISION_RECORDS` into `DECISIONS.md`.
- Merged `DESIGN_SYSTEM` + `LOCALIZATION_AND_THEMES` into `DESIGN_SYSTEM.md` (MenQ Studio Design Standards).
- Merged the orchestrator, multi-agent runtime, personas, the five engines, event system, tool execution, and approval model into `AI_RUNTIME.md`.
- Moved UX/product-surface specs into `product/` (NAVIGATION, SCREEN_INVENTORY, WORKSPACES, GROUP_CHAT, SEARCH_AND_COMMAND_PALETTE, USER_FLOWS).
- Retired `NEXT_CHAT.md`; added `CHANGELOG.md`.
- Added a documentation index and `Purpose/Scope/Owner/Related/Last updated` headers to canonical docs.
- Resolved the language-scope contradiction: the product is trilingual **HY/EN/RU** (decision D-009 supersedes the bilingual wording of D-007).

## Foundation v1 (Draft)

- Established product identity, mission, vision, scope, principles, and laws.
- Defined product architecture, the AI runtime model, navigation, first-class Group Chat, the agent model, and design direction.
- Recorded the initial accepted decisions and the phased roadmap.

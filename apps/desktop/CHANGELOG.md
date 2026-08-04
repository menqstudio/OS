# BroPS Changelog

- **Purpose:** Record notable repository changes, most recent first.
- **Scope:** Documentation and, later, released application changes. Future work is in [ROADMAP.md](docs/ROADMAP.md).
- **Owner:** Gev.
- **Last updated:** 2026-08-04.

BroPS was intentionally recreated from zero; prior history is not part of this repository. Since the monorepo merge into `menqstudio/OS`, cockpit changes also flow through the OS-level security-remediation waves; the exact live state (branch/PR/blockers) is the root [`NEXT_CHAT.md`](../../NEXT_CHAT.md).

## 2026-08-04 — production custody proven + Windows trust-chain audit + P0 fixes (PR #53, CI green)

- **Production custody proven (local, with the Owner):** the Owner ran the offline-root ceremony live —
  `win_provision` verified the offline seed against the TCB pin `3c83c2bc…` and signed the manifest offline;
  `win_live_turn` over real named pipes (3 servers + executor) reached
  `trusted_verified(production signer id brops-live-signer-1, epoch 2) production_verified=true bound=true` under the
  REAL production root. Honest graduation from demonstration custody. This is a LOCAL proof, **not** the
  shipped badge — `platform_governed_execution_supported()` stays false.
- **Builder-side adversarial audit** (Owner-designated; 5 fresh reviewers, each attacking one dimension). Verdict
  **NOT GREEN but central guarantee HOLDS** — no fresh production forgery is possible without the offline root;
  root custody, output→receipt binding, and the server-side peer-SID gate are sound. Full verdict:
  `win-live/proof/BUILDER_AUDIT_VERDICT_2026-08-04.md`. This is builder evidence, not the independent Architect
  verdict (still pending).
- **P0-2 fixed — pipe squat + broker impersonation:** the client now connects with
  `SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION` (a rogue server can only identify us, never impersonate the
  broker onward to the signer) and the server creates with `FILE_FLAG_FIRST_PIPE_INSTANCE` (a squatter of the
  trusted pipe name makes our create fail-closed). Owner re-ran the live-turn proof → still `trusted_verified`.
- **P0-1 corrected — anti-rollback honesty:** `FLOOR_SEED_HEX` is a public source constant, so the old
  "cannot forge floor.sig" claim was false. No fake verification was added; every false claim now states the
  reality (the floor signature is a corruption check; the real boundary is the deploy-dir OS write-ACL), with
  the real closure (ACL + per-deploy sealed floor key + TPM counter) specified in
  `WINDOWS_ANTIROLLBACK_HARDENING.md`.
- **Trust-UI honesty (dim-1 P2):** the self-test now carries an explicit `demonstration_custody` flag and a
  distinct "DEMONSTRATION CUSTODY" badge, so `production_verified` can never be read as production trust on its
  own.

## 2026-08-04 — comprehensive what's-left audit remediation (PR #53, CI green)

- **State-doc drift fixed (P1-5):** the canonical docs (`NEXT_CHAT`/`PROJECT_STATE`/`TASKS`/`config/current_state.json`) recorded a six-commit-stale branch head; the Coordination CI gate validates `status_tokens` verbatim, not the head SHA, so the drift was invisible. Head pointer + `shipped_this_cycle.range` refreshed and the post-pointer commits folded into the CURRENT block. Coordination gate GREEN.
- **Per-page smoke tests (P2-1):** the audit flagged ~19 feature pages with no dedicated test. Added focused smoke tests for the eight highest-risk / governance- and data-sensitive surfaces — **Approvals** (escalate never sends an engine command — the cardinal mirror-never-decide invariant; deny → real `reject_approval`), **Command** (real run ledger + step chain), **Files** (real `list_dir` mirror; no `read_file` until a file is opened), **Security** (honest "Integrity unverified", never a fabricated verified chain), **Notifications** (real store; Dismiss → real `mark_notification_read`), **Agents**, **Projects**, **Tasks**. Shared test infra now stubs `matchMedia` / `scrollIntoView` / `ResizeObserver` (all absent in jsdom). Full frontend suite: **19 files / 172 tests green**, `tsc --noEmit` clean.
- **Doc hygiene (P2-4):** `apps/desktop/docs/ROADMAP.md` given a banner pointing to the canonical repo-root `MASTER_EXECUTION_ROADMAP.md`.
- **Windows-broker hardening (P1-3, pure verifier):** `core/src/windows_broker.rs` `verify_startupinfo_handle_list` now rejects a **duplicate handle slot** (`DuplicateHandleSlot`). Previously a list that carried every slot 0..=6 *plus* a repeat (e.g. a second write end of the output pipe) passed, because each slot was only checked to be "present at least once" — a duplicate would have handed the contained executor an EXTRA inherited handle past the FD-count floor. The change only ever *adds* a rejection (strictly more fail-closed; no legitimate 7-handle list regresses) and is covered by a new unit test. The real syscall wiring (`CreateProcessAsUser` + restricted token + STARTUPINFOEX), CNG key custody, and the dedicated service account remain gated on a Windows session-0 test environment + a separate Architect audit before the shipped Windows gate can flip.
- **Deferred, on purpose:** the audit's P1-2 (consolidate the four copy-pasted governed blocks in `commands.rs`) and P0-1 (Wave-3a governed-accept author) are trust-critical refactors whose payoff is gated on the live-wiring that needs the sidecar/custody infra — not landed unreviewed. The shipped app stays fail-closed; no trust/gate semantics changed.

## 2026-08-04 — group chat, skill library, hardening, and the live-verified seam (PR #53, CI green)

- **Group chat, first-class** (schema **0017** `conversation_participants`, `SCHEMA_VERSION 17`): explicit room roster + a create-modal multi-select; the reply fan-out targets the roster, overridable by @mention; per-agent error isolation (one agent's failure no longer aborts the room); each transcript line keeps its speaker's name so a room isn't flattened to anonymous "assistant"; the system prompt names who's present.
- **Attribution hardening (independent review):** the author sanitizer strips `:` so a renderer name can't forge a second speaker into `history_sha256`; the reply's attributed author is resolved against the real agent list (unknown → Bro); the "In the room" rail shows the real roster, not every agent.
- **Skills:** all **42** `engine/skills/*/SKILL.md` rewritten to domain-grade guidance (v1.1.0) with the fail-closed Safety/Handoffs preserved.
- **Supply-chain:** patched the npm `undici` high advisory (7.29.0 override); the three new cryptography X.509/PKCS#7 advisories are waived with per-advisory notes (the engine uses only Ed25519 — a 50.0.0 bump broke the governance runtime).
- **Capability:** `open_window` + `cancel_reply` + the two participants commands declared across manifest/policy/capabilities (T-010 gate green, 76 commands).
- **Live-verified seam:** `proof::in_process_turn_output` lets the governed chain sign+bind a REAL reply (not a fixed demo string), fail-closed on empty. Custody stays the demonstration anchor; the desktop governed-live path + an honest "demonstration custody" badge and production custody (offline-root ceremony + running the sidecar) are the remaining operator-gated steps ([`src-tauri/win-live/WIRING_LIVE_TRUST.md`](src-tauri/win-live/WIRING_LIVE_TRUST.md)).
- Two independent audits (security/trust + correctness) with every finding fixed; the one latent P0 (Wave-3a governed-accept author) is annotated for the wiring. A GitHub Release (`brops-desktop-v0.1.0`) carries the Windows installer.

## 2026-08-03 — production custody, in-app agent, cockpit UX (branch `feat/windows-broker-machineproof`, not merged)

On top of the trust chain proven earlier, this cycle graduated custody and hardened the in-app experience. The branch is not merged to `main`, but a tagged **GitHub Release `brops-desktop-v0.1.0`** (published 2026-08-03, target `feat/windows-broker-machineproof`) ships the Windows installer (`BroPS_0.1.0_x64-setup.exe` + `BroPS_0.1.0_x64_en-US.msi`). Production `trusted_verified` for live turns stays fail-closed pending the operator's sidecar infrastructure ([`src-tauri/win-live/WIRING_LIVE_TRUST.md`](src-tauri/win-live/WIRING_LIVE_TRUST.md)); the shipped Windows governed gate (`platform_governed_execution_supported()`) stays false.

- **Production custody graduated** (`1bda438`, `4912d6c`): `win_gen_root` offline root-key ceremony + [`CUSTODY_CEREMONY.md`](src-tauri/win-live/CUSTODY_CEREMONY.md); `tcb::ROOT_PUBLIC_KEY_HEX` is now the operator's key whose private half is offline, with a SEPARATE compiled-in demonstration anchor for the in-process proof/tests (PinnedRoot made injectable in both resolvers). `win_provision` refuses a non-matching root (proven). Nothing in-tree can forge a production manifest.
- **In-app Bro → bounded coding agent with Bash** (`abc0d95`): file tools + Bash in acceptEdits, hard `--disallowedTools` deny-list (never push / delete / install). Owner-authorized.
- **Fixed the in-app "claude CLI timed out"** (`4008056`): the agent loaded the target repo's `.claude` (CLAUDE.md startup contract + a Stop hook) via `--setting-sources project`; switched to `--setting-sources ""` (no user/project hooks — tools/permission come from CLI flags) and gave the agent a 900s budget vs a chat's 180s.
- **Chat UX** (`4008056`): a Stop button (cancels the turn, keeps the partial via a per-conversation cancel registry + `cancel_reply`) and type-while-thinking (a follow-up sent mid-turn queues and auto-fires), both in direct and group chat.
- **Responsive + perf + windows** (`1c247f5`, `91f3ce8`): a hamburger nav drawer below 860px (the rail was previously stuck off-canvas) + a 1560px content cap for 4K; lighter ambient (aurora blur 52→34, pause-when-hidden, coalesced pointer layout reads); right-click **Open in new window** (`open_window`); route↔URL-hash sync so a new window / reload lands on the same view; Escape closes overlays.
- **Audit fixes (first pass)** (`d49f179`): 8 nav items showed the `generic.subtitle` "Prototype workspace" despite having real backed views → pointed at their real subtitles (+ new `research`/`library` subtitles ×3 languages); `Generic.tsx` strings moved under i18n and guarded against an unknown route; the two remaining Windows subprocess spawns (broker recorder, win-live executor) get `CREATE_NO_WINDOW`; human chat input now uses the hardened `post_user_message` (server fixes the role) instead of `post_message`.
- **Capability inventory (T-010 gate)** (`fbc95c0`): declared `cancel_reply` + `open_window` across the capability inventory so the new chat-Stop and open-in-new-window commands pass the deny-by-default boundary.
- **Supply-chain** (`5cd08a3`): patched `undici` to `7.29.0`, clearing the high-severity `npm audit` gate.
- **Every finding from two independent audits fixed** (`174f774`): closed all findings from two independent adversarial passes over this cycle's changes (the in-app agent, chat write path, capability declarations, and Windows spawns).
- **Group-chat speaker attribution** (`97483f2`): preserve each speaker's attribution in the model transcript so a multi-agent group chat reads correctly to the model.

## 2026-07-22 — OS-monorepo security remediation (Waves 1–3a)

Closing the Challenger Deep audit's P0/P1 findings, on top of the merged desktop app. Enforced model: [SECURITY.md](SECURITY.md). Schema is now **v14** (migrations through 0014); `cargo test -p brops-core` GREEN (**89 tests** at 3a completion). All merged security PRs passed independent zero-trust re-audits.

- **Wave 1 — provider fail-closed** (T-012, PR #15 `15384cb`): no silent governed→ungoverned fallback; ungoverned only via `BROPS_ALLOW_UNGOVERNED=1`; honest 3-state provider status.
- **Wave 2a — webview message provenance** (T-013, PR #16 `d85dcba`): `post_message` roles restricted to `["user"]`; server-held answer via one-time `result_id`.
- **T-010 — Tauri capability boundary** (PR #19 `7d537c3`): deny-by-default manifest over all 65 commands; L2 hard-deletes denied; CI invariant `tools/check_capabilities.py`.
- **T-011 — durable approval + native confirmation** (PR #20/#21, merge `7638a64`): migrations 0012/0013; restart-safe self-approval; native-only approval; nonce compare-and-consume; atomic pre-dispatch execution claim; crash recovery; enforced single-instance lock.
- **Wave 3 — Receipt Protocol v1 design rev 4** (PR #23 `35a6ab5`): Ed25519 signed per-turn receipt, desktop = final verifier, fail-closed. Architect + Owner GREEN.
- **Wave 3a slice 1 — receipt protocol core** (`brops-core::receipt`), **PR #24 MERGED** (approved HEAD `c51031e`, merge commit `6c920d0`): RFC 8785 JCS, strict decode, verify-only `verify_strict`, type-state `parse→verify→bind→resolve_3a` chain, `IssuedRequest` request-hash recompute, private-field `ResolvedManifestKey`, `Wave3aTrustState` (no "Verified" variant). **Zero-trust GREEN** after three RED rounds (`a873501`/`aa4dc01`/`f5b6ffe`), CI 7/7 GREEN, 69 core tests.
- **Wave 3a slice 2 — receipt storage & atomicity** (T-015, **PR #26 MERGED** `9b214e5`, approved HEAD `64c2372`): migration **0014** (`SCHEMA_VERSION`=14) — `receipt_verification_attempts`, one-time challenge nonce bound to `request_sha256`, `receipt_ids_seen` replay ledger; atomic `BEGIN IMMEDIATE` verify→consume→persist; tri-state `outcome {trusted_verified|development_untrusted|blocked}`; `blocked` never becomes a message. Zero-trust GREEN after 2 RED rounds; 83 core tests.
- **Wave 3a slice 3 — transport wiring + receipt trust UI** (T-016, **PR #28 MERGED** `8a580028`, approved HEAD `dee6661`): the desktop CALLS the merged verifier on a real governed turn, fail-closed (`issue_challenge`→`verify_and_record_receipt(&NoTrustedManifest)`→Blocked, no double-post); single `PreparedGovernedTurn` source; structured `system`+`history` bridge authority; dev/blocked badges; JCS cross-language parity + e2e. **Wave 3a COMPLETE.** core **89** / host **42** / bridge **35** / frontend **6** green.
- **Wave 3b-0 — isolated-signer design** (design-only, **PR #30 MERGED** `df3c0ac`, Architect DESIGN GREEN rev 5 `def7711`): [`docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md`](../../docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md). No code.
- **Wave 3b-1 — IN PROGRESS (not merged, not an RC):** **PR #31** (`feat/wave-3b1-isolated-signer`) — 3b-1A isolated-signer boundary code (Architect Code GREEN) + the 3b-1B rev-26 design-lock addendum (**NOT Architect-GREEN**). **PR #32** (`impl/wave-3b1b-execution-binding`, base PR #31, **Draft/WIP**) — 3b-1B authoritative execution→receipt binding implementation; exact-head CI 8/8 GREEN (CI-green is NOT design/audit-green). No production "Verified" yet (`NoTrustedManifest` stays fail-closed). See [`config/current_state.json`](../../config/current_state.json).

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

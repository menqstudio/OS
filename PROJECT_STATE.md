# PROJECT_STATE — live status · կենդանի վիճակ

> **⏭️ CURRENT ACTIVE (2026-08-02): Phase 2 COMPLETE on `main` — PR #48/#49/#50/#51/#52 all MERGED (tip `b91f2356`, green).** All four AI surfaces (`stream_reply` + `reply_in_conversation` #50 + `stream_ask` #51 + `stream_run_step` #52) route through the governed wall; generic fallthrough dev-only (`BROPS_ALLOW_UNGOVERNED`), fail-closed by default. The active workflow is now **PR #53 · branch `feat/windows-broker-machineproof`** (base `main`, task T-017): the **Windows LIVE governed-turn machine-proof** (crate `brops-win-live`) — the full Windows governed turn PROVEN to production `trusted_verified` over real named pipes with peer-SID auth (in-process CI-portable crypto chain; same-account 3-process; cross-account 3 DISTINCT dedicated Windows service accounts; peer-SID gate fail-closed both directions). Additive; no gate-logic change. **Shipped "Verified" stays fail-closed** — `platform_governed_execution_supported()` stays false on Windows pending broker hardening + a separate Architect audit; `main()` keeps `UpstreamBlockedExecutor`. Earlier merged-PR prose below is HISTORY.

> **Canonical file. Read it at the start of every session, and update it in the SAME commit as any change.**
> **Canonical ֆայլ։ Կարդա ամեն session-ի սկզբում, ու թարմացրու նույն commit-ում ինչ փոփոխությունը։**

**Last updated · Վերջին թարմացum:** 2026-08-02 (Wave 3b CONSOLIDATED on `feat/cockpit-pages` / PR #48; 3b-1B design **rev-30 = Architect DESIGN GREEN**; 3 builder security passes converged (all P1 fixed) — Architect CODE-audit still pending; full 7-service production governed turn **proven live on Linux** (first `trusted_verified`); shipped desktop "Verified" **still fail-closed**).
<!-- CURRENT_STATE: the single authoritative present-tense truth. Tokens are validated against config/current_state.json.status_tokens by tools/check_coordination.py. Historical prose is inside HISTORY markers and is NOT current. -->
> **▶ CURRENT STATE — the one authoritative present-tense truth.** Tokens:
> `CURRENT_ACTIVE_TASK: T-017` · `CURRENT_ACTIVE_WAVE: 3b-1B` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: GREEN` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: GREEN` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`
>
> Wave 3a slices 1–3 are **merged, zero-trust GREEN** — the verify-seam, receipt-plumbing, and the real fail-closed governed round-trip **all landed** (PR #28). Wave 3b-0 design **merged** (PR #30). **Phase 0 (repository-truth remediation) is DONE** (baseline `b6c6712`). **The whole Wave 3b workflow is now CONSOLIDATED on branch `feat/cockpit-pages`, PR #48** (base `chore/main-resync`, head `38d5d715…`) — the 3b-1A boundary code, the 3b-1B design addendum, the 3b-1B/3b-2/3b-3 implementation, the live-proof kit, and the 22-page cockpit. This supersedes the earlier split (PR #46 impl / PR #31 design / PR #32 impl). PR #48 is the snapshot's **current_workflow_pr**, a self-carrier exact-head-anchored by its PR-body **`AUDIT_CANDIDATE_HEAD`** marker.
>
> **Design:** the 3b-1B design is **Architect DESIGN GREEN at rev-30** (relayed by the Owner). **Design-GREEN is NOT code-GREEN.** **Code-audit:** three independent adversarial security passes **converged** (10 → 6 → 1 P1, ALL fixed; trust-boundary / chain / manifest CLEAN) — this is the **BUILDER's** evidence; the external **Architect CODE-audit gate is still pending** (do NOT claim Architect code-GREEN). **Live proof:** the **full 7-service production governed turn ran GREEN on real Linux** — the first production `trusted_verified` proven live (real service accounts, setuid launcher → executor, ed25519 keys + root-signed manifest, `verify_and_accept`); 3b-2 + 3b-3 are implemented + wired in the live kit (`engine/ci/live/run_live_turn.sh`). **Shipped-app honesty:** the SHIPPED desktop app's production "Verified" is **STILL fail-closed** — `main()` keeps `UpstreamBlockedExecutor`; the live chain is not yet wired into the desktop runtime, so **no production `trusted_verified`** ships yet. The 22-page cockpit is built + wired to real backends; app functional. **Open:** the Architect CODE-audit, wiring the live chain into the desktop runtime, the remaining AI entry points, **Windows production isolation**, Phases 2–10.
>
> **Next action:** obtain the **Architect CODE-audit GREEN** on PR #48's exact head, then wire the live-proven trust chain into the shipped desktop runtime (retire `UpstreamBlockedExecutor` in `main()`) to enable production `trusted_verified`. Do **not** merge PR #48 or expose "Verified" before Architect code-GREEN + Owner approval.
>
> Machine mirror: [`config/current_state.json`](./config/current_state.json).
<!-- CURRENT_STATE_END -->

---

## 🗄️ Historical / audit log — NOT current state (do not read as present-tense truth)
<!-- HISTORY_BEGIN -->
**[history] Wave 3a slice 2 (receipt storage & atomicity, T-015) — DONE, MERGED** (PR #26, approved HEAD `64c2372`, squash **merge commit `9b214e5`** on `main`; zero-trust GREEN after a YELLOW + two RED rounds; 7/7 CI). **Wave 3a is COMPLETE — slice 3 (transport wiring + receipt trust UI, T-016) DONE, MERGED** (PR #28, approved HEAD `dee6661`, squash **merge commit `8a580028`** on `main`; zero-trust GREEN after a YELLOW + two RED rounds; 7/7 CI). The desktop now CALLS the merged verifier on a real governed turn (one `PreparedGovernedTurn` single source; exact structured `system`+`history` are the bridge signing authority; key-authority resolved in-tx, no fake key; bridge=transport/desktop=authority with the `verified` bool removed; `issue_challenge`→`verify_and_record_receipt(&NoTrustedManifest)`→Blocked turn-level notice, no double-post; transport-fail closes the nonce with a bounded real reason; dev/blocked badges; JCS parity + e2e). Fail-closed strict 3a: every governed turn Blocks until **Wave 3b (T-017)** provisions a key. core 89 · host 42 · bridge 35 py · frontend 6 green; clippy-clean. Slice 2 shipped migration **0014** (`SCHEMA_VERSION`=14 — `receipt_verification_attempts` with `wire_*` + decoded evidence and DB-level accepted⇔message / blocked⇔no-message CHECK, durable one-time `receipt_challenges` nonce, accepted-only `receipt_ids_seen` uniqueness ledger) + `brops-core::receipt_store` (`verify_and_record_receipt` = one `BEGIN IMMEDIATE` verify→consume→persist; `issue_challenge`; `ReceiptOutcome` has **no `TrustedVerified` variant** — production⇒Blocked). Architect **YELLOW** then **RED×2** audit rounds RESOLVED: **R1** (challenge `request_sha256` NOT-NULL+hex compared in-tx; staged decoded evidence on bad-sig/bind-fail; nested-tx reject + explicit COMMIT-failure rollback); **R2** (`issue_challenge(conn, conversation_id, &IssuedRequest, now_ms)` derives nonce+hash from one source — no split-authority; `message_id` `ON DELETE RESTRICT` + full accepted⇔message CHECK so a conversation/message delete with governed evidence is **refused**, keeping output bytes re-hashable; the concurrency test is now a **real threaded race** with a `Barrier`; `rusqlite` `hooks` moved to dev-dependencies). **83 core tests** (14 slice-2 negative-matrix incl. the threaded race), clippy-clean, coordination + capabilities GREEN. Prior: **Wave 3a slice 1 (protocol core) — DONE, MERGED** (T-014, PR #24). Approved HEAD `c51031e`, squash **merge commit `6c920d0`** on `main`; **zero-trust GREEN** after three RED rounds (key-authority binding, `Wave3aTrustState` with no `TrustedVerified` variant, `IssuedRequest` request-hash recompute — all resolved audit history); final CI 7/7 GREEN; `brops-core` **69 tests**, clippy-clean. Slice 1 shipped the pure, I/O-free `brops-core::receipt` (RFC 8785 JCS, strict decode, verify-only `verify_strict`, type-state `parse→verify→bind→resolve_3a`, never a `sign()` oracle). **Wave 2 (T-010 + T-011) + Wave 1 (T-012) + Wave 2a (T-013) complete.**
<!-- HISTORY_END -->
> _(The authoritative present-tense state is the ▶ CURRENT STATE block at the top of this file.)_

---

## 📍 Where we are · Որտեղ ենք

- **Canonical execution source:** [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md) — status
  `v1.0 · Canonical Execution Authority` 🔒 **Locked** (Owner-approved 2026-07-21, basis HEAD `2e0157b`),
  **11 phases** fully expanded (16 sections each) with per-page UI specs from `brops-aios.html`, an
  Execution Ownership Matrix (§G), a Canonical Artifact Registry (§H), and Change Control (§I, now in
  force). A cold-start session takes the next unchecked task there. **Locked = product content
  change-controlled, not execution frozen** — building proceeds.
- **Coordination enforcement (T-007):** the Startup Law / docs-sync is now **enforced, not
  remembered** — a fail-closed **CI gate** (`tools/check_coordination.py`: roadmap 11×16, canonical
  files, TASKS statuses, PROJECT_STATE freshness) plus a fail-open **Stop-hook** (`.claude/`) that
  reminds when code changes without a coordination-doc sync.
- **Phase 0 — Foundation:** ✅ DONE (locked). OS monorepo assembled (`engine/` = Bro, `apps/desktop/` =
  BroPS, subtree history preserved), bilingual docs, unified CI.
- **Engine CI:** ✅ green — the 9 monorepo-coupled tests skip-guard themselves (option **C**);
  `OK (591 passed, 38 skipped, 0 failed)`.
- **Phase 1 — Bridge:** 🔨 in progress — `bridge/DESIGN.md` **APPROVED**; slice 1 (contract + adapter +
  tests + **bridge CI leg**) **merged to `main`** (PR #3, HEAD `41cf4ff`, 10/10 canonical — receipt-must-
  VERIFY invariant landed) **and** slice 2 **transport** — desktop Rust `Provider::GovernedEngine` in
  `ai.rs` (opt-in, default OFF) + governed sidecar wiring + chat receipt badge — **merged** (PR #8). *(The
  Settings governed toggle shipped in PR #8 was **removed in Wave 1** — replaced by a read-only provider
  status, PR #15.)* **DONE via Wave 3a slice 3 (T-016, PR #28 `8a580028`):** the verify-seam (adapter →
  injected verifier), receipt-plumbing into the turn, and one real fail-closed governed round-trip
  end-to-end all **landed** (`CURRENT_VERIFY_SEAM: complete`, `CURRENT_RECEIPT_PLUMBING: complete`,
  `CURRENT_GOVERNED_ROUNDTRIP: complete`). Governed **streaming** is intentionally **not** implemented
  (governed turns are buffered by security design, not a forgotten task). Still open: production
  `trusted_verified` (Wave 3b) and governing the remaining AI entry points.

## 👷 Who's working on what (NOW) · Ով ինչի վրա ա (ՀԻՄԱ)

| Agent | Task (see TASKS.md) | Branch | Status |
|---|---|---|---|
| 🔨 Claude | **Wave 3b (T-017) — isolated signer + execution→receipt binding + production trust chain** | `feat/cockpit-pages` (PR #48) — consolidates the earlier `feat/wave-3b1-isolated-signer` (PR #31) + `impl/wave-3b1b-execution-binding` (PR #32) + PR #46 | 🟡 **CURRENT (supersedes the history below): the whole Wave 3b workflow is CONSOLIDATED on `feat/cockpit-pages`, PR #48 (base `chore/main-resync`, head `38d5d715…`), superseding the earlier split (PR #46 impl / PR #31 design / PR #32 impl). The 3b-1B design is Architect DESIGN GREEN at rev-30 (design-GREEN ≠ code-GREEN). Three independent adversarial security passes converged (10 → 6 → 1 P1, all fixed; trust-boundary/chain/manifest CLEAN) — that is the BUILDER's evidence; the external Architect CODE-audit gate is still PENDING (do NOT claim Architect code-GREEN). The full 7-service production governed turn ran GREEN on real Linux — the first production `trusted_verified` proven live (via `engine/ci/live/run_live_turn.sh`); 3b-2 (signed manifest/anti-rollback) + 3b-3 (production trust resolver) are implemented + wired in the live kit. BUT the SHIPPED desktop app's production "Verified" stays fail-closed (`main()` keeps `UpstreamBlockedExecutor`; the live chain is not yet wired into the desktop runtime), so no production `trusted_verified` ships yet. The 22-page cockpit is built + wired to real backends. PR #48 is the current_workflow_pr, exact-head-anchored by its PR-body AUDIT_CANDIDATE_HEAD marker (nothing exempt). Next — obtain the Architect CODE-audit GREEN on PR #48's exact head, then wire the live chain into the shipped desktop runtime. No merges / no "Verified" until Architect code-GREEN + Owner approval. Machine mirror: [`config/current_state.json`](./config/current_state.json).** &nbsp; — <!-- HISTORY_BEGIN --> _History (accurate through the 3b-0 gate):_ Owner directive: custody boundary = trust boundary, Architect-gated design note before code. [`docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md`](./docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md) **rev 2** locks: dedicated OS **security principal** (not just `0700`) / receipt-key custody unreachable by the sidecar / an **authenticated run-evidence chain** (supervisor = trusted producer + only authenticated caller, `brops.run-attestation.v1`; recompute ≠ authenticity) / not-an-oracle IPC / auth checklist / context-aware `KeyResolutionQuery` + scope-bound key + in-tx anti-rollback / signed-manifest+pinned-root+anti-rollback / fail-closed / normative §4 schemas / threat model. **Architect design RED history:** rev 1 (`6a6882e`, 4 P0) → rev 2 (`9801489`, 2 P0 + 3 P1) → **rev 3** closes them: the supervisor **builds evidence from `{run_id, attempt_id}`** (no `attest(caller_evidence)` oracle anywhere; single topology — sidecar never touches the signer); a **content-addressed protected evidence store** binds containment/large inputs to real artifact bytes; **one fixed 256 KiB IPC frame** (large inputs = handles, no inline); resolver query sourced from the **trusted `Expected`** (not the unsigned receipt); manifest floor **+ exact bytes persisted atomically** with semantic-uniqueness rejects. **Architect design YELLOW on rev 3 (`fa1b8cb`, CI #96 green) — architecture approved, no new P0; rev 4 closes 5 contract redlines:** per-artifact canonical-bytes table pinned to merged formulas + all-formula parity (P1-1), nonce schema fixed to the merged UUIDv4 `id()` not `hex(32B)` (P1-2), durable forensic-attestation record in `sign-result` + containment via bridge result (P1-3), supervisor process/service/ACL/store/IPC reclassified **BUILD** + 4 same-user isolation tests (P1-4), protected-store atomic publish algorithm (P1-5). **Architect design YELLOW on rev 4 (`73ff0f7`) — architecture confirmed; rev 5 closes the final contract:** the desktop resolves the **supervisor-attestation key from the root-signed manifest snapshot** (not signer config) via an explicit `key_usage: receipt_signing | supervisor_attestation` discriminator with **total type separation** (two disjoint in-tx resolvers; a receipt key can never verify an attestation and vice-versa) + attestation-key negative matrix. **✅ Architect DESIGN GREEN on rev 5 (approved HEAD `def7711`, exact-head CI #98 success) — 3b-0 design gate PASSED (no open P0/P1).** 3b implementation may start **only after Owner approval**; the 3b-1 stop condition holds (`NoTrustedManifest` unchanged, no production "Verified"); first `trusted_verified` only after the full 3b-1→3b-2→3b-3 chain is exact-head zero-trust GREEN. **[End of 3b-0 history. Post-3b-0 reality is in the 🟡 CURRENT block at the top of this cell.]** **Wave 3a (slices 1+2+3) COMPLETE + merged** (`8a580028`). <!-- HISTORY_END --> |
| 📐 ChatGPT | — | — | — |
| 👑 Gev | reviews / approvals · roadmap **v1.0 🔒 Locked** (Owner-approved, basis HEAD `2e0157b`) | — | — |

## ⏭️ Next task · Հաջորդ task

Follow [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md). Immediate open items:

1. **Wave 3b — isolated signer + signed manifest + production "Verified" (T-017)** — fill the
   `ReceiptKeyAuthority` seam slice 3 left: a minimal isolated trusted signer with real key custody
   (private key unreachable by the sidecar), an operator-provisioned signed key manifest validated against
   a binary-pinned root anchor (per-key `trust_class`, validity window, epoch, revocation), and
   anti-rollback (durable highest epoch + hash). A production-class key renders **`trusted_verified`**
   ("Verified"). **Consolidated on `feat/cockpit-pages` (PR #48).** The 3b-1B design is **Architect DESIGN
   GREEN at rev-30** (design-GREEN ≠ code-GREEN). The 3b-1B/3b-2/3b-3 implementation is built and
   **proven live on Linux** (the first production `trusted_verified` ran end-to-end via
   `engine/ci/live/run_live_turn.sh`); three builder security passes converged (all P1 fixed). **But** the
   external Architect CODE-audit is still pending, and the SHIPPED desktop app stays fail-closed
   (`main()` keeps `UpstreamBlockedExecutor`; the live chain is not yet wired into the desktop runtime).
   **Next permitted action:** obtain the **Architect CODE-audit GREEN** on PR #48's exact head
   (AUDIT_CANDIDATE_HEAD marker), then wire the live chain into the shipped desktop runtime. No merges /
   no shipped "Verified" until Architect code-GREEN + Owner approval.
2. **Phase 2 (Governance Sidecar)** — can start now (P1 contract exists): `approvals`/`decisions`/
   `security`/`notifications` surfaces, mirror-never-decide.
3. **T-005 — Option-2 (AUDITED, Phase 10)** — engine submodule + worktree-check native fix. Separate
   branch/PR, Owner approval, must not destabilize.

## 🚧 Blockers · Խոչընդոտներ

- ~~A/B root-model decision~~ → **DECIDED: Option 1 (subtree + C)** for stability (Architect call). The 9 enforcement-path tests stay skip-deferred (C); no security code touched. Option 2 (submodule + Bro worktree-check fix) is a future audited task — **T-005**. Verified finding: a submodule alone does NOT fix it (`git worktree list` reports the git-dir). See `CLAUDE.md` §3.
- Bro deferred security items **O-1..O-5** (residual-exploitable; tracked on Bro's `fix/audit-followups`) — do not rush, wall/owner-env coupled.

## 🔁 Startup Law · Startup օրենք

Every session, before anything: **`git pull` → read `CLAUDE.md` → read `PROJECT_STATE.md` → claim your task in `TASKS.md`**. Only then start.
Ամեն session, ամեն բանից առաջ՝ **`git pull` → կարդա `CLAUDE.md` → կարդա `PROJECT_STATE.md` → claim քո task-ը `TASKS.md`-ում**։ Միայն հետո սկսի։

# PROJECT_STATE — live status · կենդանի վիճակ

> **Canonical file. Read it at the start of every session, and update it in the SAME commit as any change.**
> **Canonical ֆայլ։ Կարդա ամեն session-ի սկզբում, ու թարմացրու նույն commit-ում ինչ փոփոխությունը։**

**Last updated · Վերջին թարմացум:** **Wave 3a slice 2 (receipt storage & atomicity, T-015) — IMPLEMENTED, in Review** on `feat/wave-3a-receipt-storage` (cut off `main` @ `75a8d8f`): migration **0014** (`SCHEMA_VERSION`=14 — `receipt_verification_attempts` with `wire_*` + decoded evidence and DB-level accepted⇔message / blocked⇔no-message CHECK, durable one-time `receipt_challenges` nonce, accepted-only `receipt_ids_seen` uniqueness ledger) + `brops-core::receipt_store` (`verify_and_record_receipt` = one `BEGIN IMMEDIATE` verify→consume→persist; `issue_challenge`; `ReceiptOutcome` has **no `TrustedVerified` variant** — production⇒Blocked). Architect **YELLOW** then **RED×2** audit rounds RESOLVED: **R1** (challenge `request_sha256` NOT-NULL+hex compared in-tx; staged decoded evidence on bad-sig/bind-fail; nested-tx reject + explicit COMMIT-failure rollback); **R2** (`issue_challenge(conn, conversation_id, &IssuedRequest, now_ms)` derives nonce+hash from one source — no split-authority; `message_id` `ON DELETE RESTRICT` + full accepted⇔message CHECK so a conversation/message delete with governed evidence is **refused**, keeping output bytes re-hashable; the concurrency test is now a **real threaded race** with a `Barrier`; `rusqlite` `hooks` moved to dev-dependencies). **83 core tests** (14 slice-2 negative-matrix incl. the threaded race), clippy-clean, coordination + capabilities GREEN. **Awaiting re-audit on the new pushed HEAD + Owner merge; NOT merged.** Prior: **Wave 3a slice 1 (protocol core) — DONE, MERGED** (T-014, PR #24). Approved HEAD `c51031e`, squash **merge commit `6c920d0`** on `main`; **zero-trust GREEN** after three RED rounds (key-authority binding, `Wave3aTrustState` with no `TrustedVerified` variant, `IssuedRequest` request-hash recompute — all resolved audit history); final CI 7/7 GREEN; `brops-core` **69 tests**, clippy-clean. Slice 1 shipped the pure, I/O-free `brops-core::receipt` (RFC 8785 JCS, strict decode, verify-only `verify_strict`, type-state `parse→verify→bind→resolve_3a`, never a `sign()` oracle). **After slice 2 (T-015) merges, the next task is slice 3** (transport wiring + receipt UI); isolated signer + manifest + production "Verified" = Wave 3b. **Wave 2 (T-010 + T-011) + Wave 1 (T-012) + Wave 2a (T-013) complete.** **Exact handoff: [`NEXT_CHAT.md`](./NEXT_CHAT.md).**

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
  status, PR #15.)* Slice 2 is **transport/infrastructure only**. **Still pending (not done):**
  the verify-seam (adapter → injected verifier), receipt-plumbing into the turn, one real governed
  round-trip end-to-end, and governed streaming.

## 👷 Who's working on what (NOW) · Ով ինչի վրա ա (ՀԻՄԱ)

| Agent | Task (see TASKS.md) | Branch | Status |
|---|---|---|---|
| 🔨 Claude | Wave 3a — Receipt Protocol v1 **slice 2 (receipt storage & atomicity)** (T-015) — migration 0014 + atomic verify→consume→persist | `feat/wave-3a-receipt-storage` (PR #26) | 🔎 **Review** — **Audit rounds 1 (4) + 2 (3+hardening) RED RESOLVED**: R1 (challenge request_sha256 in-tx compare; staged decoded evidence; nested-tx reject + commit-failure rollback); R2 (`issue_challenge` takes one `IssuedRequest` — no split nonce/hash; `ON DELETE RESTRICT` + full CHECK so deletion refused when governed evidence exists; **real threaded race** test; `hooks` → dev-dep); **83 core tests** green, clippy-clean, coordination+capabilities GREEN; **awaiting re-audit on the new pushed HEAD + Owner merge** |
| 📐 ChatGPT | — | — | — |
| 👑 Gev | reviews / approvals · roadmap **v1.0 🔒 Locked** (Owner-approved, basis HEAD `2e0157b`) | — | — |

## ⏭️ Next task · Հաջորդ task

Follow [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md). Immediate open items:

1. **Phase 1 remaining (post-transport)** — the slice-2 *transport* (sidecar + `Provider::GovernedEngine`
   opt-in + chat receipt badge) is **merged** (PR #8; the inert Settings toggle was removed in Wave 1,
   replaced by a read-only provider status). Still to do: the verify-seam
   (adapter → injected verifier), receipt-plumbing into the turn, one real governed round-trip end-to-end,
   and governed streaming (see roadmap Phase 1 task checklist).
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

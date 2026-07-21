# PROJECT_STATE — live status · կենդանի վիճակ

> **Canonical file. Read it at the start of every session, and update it in the SAME commit as any change.**
> **Canonical ֆայլ։ Կարդա ամեն session-ի սկզբում, ու թարմացրու նույն commit-ում ինչ փոփոխությունը։**

**Last updated · Վերջին թարմացում:** Wave 2b **T-011 implemented** (`feat/t-011-durable-approval`, T-010 merged PR #19 `7d537c3`) — migration 0012 durable approval provenance (`origin_principal`/`origin_session_id`/`request_digest`/`nonce`/confirmation cols), canonical-JSON envelope SHA-256 digest, restart-safe self-approval, and a renderer-independent **native confirmation** dialog (`confirm_approval`) that is the only approve path — approve re-enabled, in-memory `approval_origins` removed. **Audit-round-1 fixes:** envelope binds full execution scope (`approval_id`+`run_plan_sha256`, dialog shows intent+plan+step+detail); native-only-approve invariant moved into the authority layer (`decide` reject-only, `approved_for` requires native-confirmation markers); real in-tx nonce+digest verification; single-active-confirmation + rate limit; file-backed reopen test. **Audit-round-2 fixes:** one canonical `RunExecutionScope` drives digest+dialog+provider-prompt (prompt now includes step_detail — no informed-confirmation mismatch); `confirm_approval` drops the webview-supplied note (server-owned rationale). **Base merged PR #20 `864aab9`. Audit-round-3 (post-merge) fix — concurrency:** migration 0013 `run_steps.execution_attempt_id` + `claim_step_for_execution` atomically claims the step and consumes the grant BEFORE the provider call (one approval → exactly one execution; a second concurrent dispatch is refused before any spend), on `fix/t-011-atomic-execution-claim`. **Round 3b:** the durable claim is crash-recoverable — `execution_owner_session_id`/`execution_started_at` + startup `reconcile_abandoned_executions` settle a dead-session claim fail-closed (no wedged run; grant not restored); `fail_step_execution` checks affected rows. Then Wave 3 (Receipt Protocol v1). Note: Wave 3 receipt migration renumbered to 0014 (0013 now used by this fix). (Wave 2a PR #16 `d85dcba`; Wave 1 PR #15 `15384cb`.)

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
| 🔨 Claude | Wave 2b **T-011** — durable approval + native confirmation (T-010 merged) | `feat/t-011-durable-approval` | 🔎 in review |
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

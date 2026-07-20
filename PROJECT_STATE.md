# PROJECT_STATE — live status · կենդանի վիճակ

> **Canonical file. Read it at the start of every session, and update it in the SAME commit as any change.**
> **Canonical ֆայլ։ Կարդա ամեն session-ի սկզբում, ու թարմացրու նույն commit-ում ինչ փոփոխությունը։**

**Last updated · Վերջին թարմացում:** PR #3 (bridge slice 1) merged to `main` — HEAD `41cf4ff`

---

## 📍 Where we are · Որտեղ ենք

- **Canonical execution source:** [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md) — status
  `v1.0 · Canonical Execution Authority` 🔒 **Locked** (Owner-approved 2026-07-21, basis HEAD `2e0157b`),
  **11 phases** fully expanded (16 sections each) with per-page UI specs from `brops-aios.html`, an
  Execution Ownership Matrix (§G), a Canonical Artifact Registry (§H), and Change Control (§I, now in
  force). A cold-start session takes the next unchecked task there. **Locked = product content
  change-controlled, not execution frozen** — building proceeds.
- **Phase 0 — Foundation:** ✅ DONE (locked). OS monorepo assembled (`engine/` = Bro, `apps/desktop/` =
  BroPS, subtree history preserved), bilingual docs, unified CI.
- **Engine CI:** ✅ green — the 9 monorepo-coupled tests skip-guard themselves (option **C**);
  `OK (591 passed, 38 skipped, 0 failed)`.
- **Phase 1 — Bridge:** 🔨 in progress — `bridge/DESIGN.md` **APPROVED**; slice 1 (contract + adapter +
  tests + **bridge CI leg**) **merged to `main`** (PR #3, HEAD `41cf4ff`, 10/10 canonical — receipt-must-
  VERIFY invariant landed). **Not yet done (slice 2+):** desktop Rust `Provider::GovernedEngine` wiring in
  `ai.rs`, governed round-trip, chat receipt badge, settings toggle, streaming.

## 👷 Who's working on what (NOW) · Ով ինչի վրա ա (ՀԻՄԱ)

| Agent | Task (see TASKS.md) | Branch | Status |
|---|---|---|---|
| 🔨 Claude | — (T-006 ✅ merged; no active claim) · next open = **Phase 1 slice 2** | — | 🟢 available |
| 📐 ChatGPT | — | — | — |
| 👑 Gev | reviews / approvals · roadmap **v1.0 🔒 Locked** (Owner-approved, basis HEAD `2e0157b`) | — | — |

## ⏭️ Next task · Հաջորդ task

Follow [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md). Immediate open items:

1. **Phase 1 slice 2** — prove one governed round-trip, add the bridge CI leg, ship the `chat` verified-
   receipt badge + Settings governed-provider toggle (see roadmap Phase 1 task checklist). `feat/phase1-bridge`.
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

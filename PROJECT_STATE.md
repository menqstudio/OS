# PROJECT_STATE — live status · կենդանի վիճակ

> **Canonical file. Read it at the start of every session, and update it in the SAME commit as any change.**
> **Canonical ֆայլ։ Կարդա ամեն session-ի սկզբում, ու թարմացրու նույն commit-ում ինչ փոփոխությունը։**

**Last updated · Վերջին թարմացում:** master-roadmap PR (branch `docs/master-execution-roadmap`)

---

## 📍 Where we are · Որտեղ ենք

- **Canonical execution source:** [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md) — status
  `v1.0 · Canonical Execution Authority` 🔒 **Locked** (change-controlled per its §I), **11 phases** fully
  expanded (16 sections each) with per-page UI specs from `brops-aios.html`, an Execution Ownership Matrix
  (§G), a Canonical Artifact Registry (§H), and Change Control (§I). A cold-start session takes the next
  unchecked task there. **Locked = plan change-controlled, not execution frozen** — building proceeds.
- **Phase 0 — Foundation:** ✅ DONE (locked). OS monorepo assembled (`engine/` = Bro, `apps/desktop/` =
  BroPS, subtree history preserved), bilingual docs, unified CI.
- **Engine CI:** ✅ green — the 9 monorepo-coupled tests skip-guard themselves (option **C**);
  `OK (591 passed, 38 skipped, 0 failed)`.
- **Phase 1 — Bridge:** 🔨 in progress — `bridge/DESIGN.md` **APPROVED**; slice 1 (contract + adapter +
  tests) **built & verified (8/8)** on `feat/phase1-bridge` (PR #3). Slices 2–3 (round-trip, CI leg, UI
  badge/toggle, streaming) open.

## 👷 Who's working on what (NOW) · Ով ինչի վրա ա (ՀԻՄԱ)

| Agent | Task (see TASKS.md) | Branch | Status |
|---|---|---|---|
| 🔨 Claude | T-006 master execution roadmap | `docs/master-execution-roadmap` | 🔎 in review (draft PR) |
| 📐 ChatGPT | — | — | — |
| 👑 Gev | reviews / approvals | — | — |

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

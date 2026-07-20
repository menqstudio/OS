# PROJECT_STATE — live status · կենդանի վիճակ

> **Canonical file. Read it at the start of every session, and update it in the SAME commit as any change.**
> **Canonical ֆայլ։ Կարդա ամեն session-ի սկզբում, ու թարմացրու նույն commit-ում ինչ փոփոխությունը։**

**Last updated · Վերջին թարմացում:** coordination-canon PR (branch `chore/coordination-canon`)

---

## 📍 Where we are · Որտեղ ենք

- **Phase 0 — Scaffold:** ✅ DONE. OS monorepo assembled (`engine/` = Bro, `apps/desktop/` = BroPS, subtree history preserved), bilingual docs, unified CI.
- **Engine CI:** ✅ green — the 9 monorepo-coupled tests skip-guard themselves (option **C**); `OK (591 passed, 38 skipped, 0 failed)`.
- **Phase 1 — Bridge:** ⏳ not started.

## 👷 Who's working on what (NOW) · Ով ինչի վրա ա (ՀԻՄԱ)

| Agent | Task (see TASKS.md) | Branch | Status |
|---|---|---|---|
| 🔨 Claude | T-001 coordination canon | `chore/coordination-canon` | 🔎 in review (PR open) |
| 📐 ChatGPT | — | — | — |
| 👑 Gev | reviews / approvals | — | — |

## ⏭️ Next task · Հաջորդ task

1. **T-002 — Phase-1 root-model decision (A submodule vs B monorepo-aware).** Owner + Architect call. Blocks the "true" full-enforcement CI.
2. **T-003 — Phase 1 bridge** — route the desktop's AI execution through the engine's supervisor/lease/wall.

## 🚧 Blockers · Խոչընդոտներ

- **A/B root-model decision** pending (see `CLAUDE.md` §3). Until then the 9 enforcement-path tests are skip-deferred (option C), not deleted.
- Bro deferred security items **O-1..O-5** (residual-exploitable; tracked on Bro's `fix/audit-followups`) — do not rush, wall/owner-env coupled.

## 🔁 Startup Law · Startup օրենք

Every session, before anything: **`git pull` → read `CLAUDE.md` → read `PROJECT_STATE.md` → claim your task in `TASKS.md`**. Only then start.
Ամեն session, ամեն բանից առաջ՝ **`git pull` → կարդա `CLAUDE.md` → կարդա `PROJECT_STATE.md` → claim քո task-ը `TASKS.md`-ում**։ Միայն հետո սկսի։

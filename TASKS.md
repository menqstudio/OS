# TASKS — the coordination board · координация board

> **🥇 THE MOST IMPORTANT RULE: never two agents on the same task at the same time.**
> Before you start a task, **claim it here** (set *Claimed by* + status `In-Progress`) in a commit on your branch.
> Check this board **first, every session**. If a task is already `In-Progress` by someone else — pick another.
>
> **🥇 ԱՄԵՆԱԿԱՐԵՎՈՐ ԿԱՆՈՆԸ՝ երբեք երկու agent միաժամանակ նույն task-ի վրա։**
> Task սկսելուց առաջ՝ **claim արա այստեղ** (դիր *Claimed by* + `In-Progress`) քո branch-ի commit-ում։
> Ստուգիր այս board-ը **առաջինը, ամեն session**։ Եթե task-ը արդեն ուրիշի `In-Progress` ա — վերցրու ուրիշը։

**Status values · Status-ի արժեքներ:** `Todo` · `In-Progress` · `Review` · `Done` · `Blocked`

> **Execution source:** the phase-by-phase plan lives in
> [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md). Each roadmap task should get a row here
> when someone claims it. · Կատарման աղբյուրը՝ `MASTER_EXECUTION_ROADMAP.md`։

| ID | Task | Claimed by | Status | Branch / PR |
|----|------|-----------|--------|-------------|
| **T-001** | Coordination canon (OWNERS · PROJECT_STATE · TASKS · PR template · Startup Law) | 🔨 Claude | ✅ Done | `chore/coordination-canon` |
| **T-002** | Root-model decision — **DECIDED: Option 1 (subtree + C)** for stability; see CLAUDE.md §3 | 📐 ChatGPT + 👑 Gev | ✅ Done | — |
| **T-003** | Phase 1 — bridge: `apps/desktop ↔ adapter ↔ engine` (route desktop AI exec through engine supervisor/lease/wall). Design **APPROVED**; slice 1 (contract+adapter+tests) **verified 10/10** (commit `5be8d95`); desktop `Provider::GovernedEngine` wiring + slices 2–3 open | 🔨 Claude | In-Progress | `feat/phase1-bridge` (PR #3) |
| **T-004** | Bro deferred security items O-1..O-5 (from `fix/audit-followups`) — roadmap Phase 10 | _unclaimed_ | Blocked (wall-coupled, needs Owner go) | — |
| **T-005** | Option-2 feasibility (**AUDITED**): engine as submodule + targeted fix to Bro's worktree check (`git rev-parse --show-toplevel` instead of `git worktree list`). **Separate branch/PR, Owner approval, must not destabilize.** — roadmap Phase 10 | _unclaimed_ | Todo | — |
| **T-006** | Master execution roadmap — expand `MASTER_EXECUTION_ROADMAP.md` into the canonical execution source (11 phases × 16 sections, per-page UI specs, docs sync) | 🔨 Claude | Review | `docs/master-execution-roadmap` |

## How to claim · Ինչպես claim անել
1. `git pull` and read this board. · `git pull` ու կարդա board-ը։
2. On your branch, set your name + `In-Progress` on the row, commit ("claim T-00X"). · Քո branch-ում դիր անունդ + `In-Progress`, commit արա։
3. Do the work → set `Review`, open a PR → Owner approves → `Done`. · Աշխատիր → `Review` + PR → Owner approve → `Done`։

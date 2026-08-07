# OWNERS · Դերեր

Three roles, one product. Everyone reads the [canonical files](./CLAUDE.md) at the start of every session.
Երեք դեր, մեկ product։ Բոլորս ամեն session-ի սկզբում կարդում ենք [canonical ֆայլերը](./CLAUDE.md)։

| Who · Ով | Role · Դեր | Responsibility · Պատասխանատվություն |
|---|---|---|
| **Gev** (`menqstudio`) | 👑 **Owner / Final Approver** | Final decisions; approves & merges every PR · Վերջնական որոշում, ամեն PR-ի approve/merge |
| **ChatGPT** | 📐 **Architect / Auditor** | Architecture, rules, review, audit, coordination · Architecture, կանոններ, review, audit, coordination |
| **Claude** (Claude Code) | 🔨 **Builder / Executor** | Code, tests, commits, PRs · Կոդ, tests, commits, PR-ներ |

## Hard rules · Կոշտ կանոններ
- **No direct work on `main`.** Every task = its own branch + PR. · **`main`-ում ուղիղ աշխատանք չկա։** Ամեն task = առանձին branch + PR։
- **Merge only after the Owner's approval.** Claude opens PRs; Gev approves & merges. · **Merge միայն Owner-ի approval-ից հետո։** Claude բացում ա PR, Gev approve/merge ա անում։
- **Never two agents on the same task** — claim it in [`TASKS.md`](./TASKS.md) first. · **Երբեք երկու agent նույն task-ի վրա** — նախ claim արա [`TASKS.md`](./TASKS.md)-ում։
- **Docs stay synced** — `NEXT_CHAT.md` / `PROJECT_STATE.md` / `TASKS.md` and `config/current_state.json` update in the same commit as the change; `tools/check_coordination.py` and `tools/check_repo_state.py` fail the build otherwise. · **Docs-ը sync** — նույն commit-ում, այլապես CI-ը կարմրում ա։
- **The production gate is the Owner's alone.** `platform_governed_execution_supported()` stays false and `main()` keeps `UpstreamBlockedExecutor` until an **independent** audit passes AND Gev approves. A green CI run is not that, and neither is the Builder's confidence. · **Production դարպասը միայն Owner-ինն ա։** Անկախ աուդիտ ԵՎ Gev-ի հաստատում — կանաչ CI-ն դա չի։
- **Only the Owner merges.** Claude opens the PR and pushes to its branch; the merge command is Gev's to run. · **Merge-ը միայն Owner-ն ա անում։**

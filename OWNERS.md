# OWNERS · Դերեր

Three roles, one product. Everyone reads the [canonical files](./CLAUDE.md) at the start of every session.
Երեք դեր, մեկ product։ Բոլորս ամեն session-ի սկզբում կարդում ենք [canonical ֆայլերը](./CLAUDE.md)։

| Who · Ով | Role · Դեր | Responsibility · Պատասխանատվություն |
|---|---|---|
| **Gev** (`menqstudio`) | 👑 **Owner / Final Approver** | Final decisions; owns the roadmap. **Push/merge delegated to the Builder 2026-08-14** (roadmap §B.5, Owner waiver, revocable there) · Վերջնական որոշում; push/merge-ը 2026-08-14-ից պատվիրակված է Builder-ին |
| **ChatGPT** | 📐 **Architect / Auditor** | Architecture, rules, review, audit, coordination · Architecture, կանոններ, review, audit, coordination |
| **Claude** (Claude Code) | 🔨 **Builder / Executor** | Code, tests, commits, PRs · Կոդ, tests, commits, PR-ներ |

## Hard rules · Կոշտ կանոններ
- **No direct work on `main`.** Every task = its own branch + PR. · **`main`-ում ուղիղ աշխատանք չկա։** Ամեն task = առանձին branch + PR։
- **Merge only on an all-green exact head.** Claude opens the PR and merges it, but only once **every** required check has passed **on the head that will merge** — not on an earlier one, and never while a run is still going. Push/merge was delegated to the Builder on 2026-08-14 (roadmap §B.5, Owner waiver — no Architect audit; the Owner revokes it by editing that line). · **Merge միայն ամբողջովին կանաչ ու ճշգրիտ head-ի վրա։** Claude-ը բացում ու merge ա անում, բայց միայն երբ ամեն ստուգում անցել ա հենց այն head-ի վրա որ merge ա լինելու։
- **Never two agents on the same task** — claim it in [`TASKS.md`](./TASKS.md) first. · **Երբեք երկու agent նույն task-ի վրա** — նախ claim արա [`TASKS.md`](./TASKS.md)-ում։
- **Docs stay synced** — `NEXT_CHAT.md` / `PROJECT_STATE.md` / `TASKS.md` and `config/current_state.json` update in the same commit as the change; `tools/check_coordination.py` and `tools/check_repo_state.py` fail the build otherwise. · **Docs-ը sync** — նույն commit-ում, այլապես CI-ը կարմրում ա։
- **The production gate is the Owner's alone.** It stays shut until an **independent** audit passes AND Gev approves. (It is not a function: no `platform_governed_execution_supported()` exists in the tree — that is the §0.1 spec symbol. What refuses is `governed_verification_unconfigured()` returning `Some(...)` unconditionally, `connect_broker()` refusing off Linux, and the broker serving `UpstreamBlockedExecutor` unless `$BROPS_BROKER_CONFIG` names a TCB-root-signed deployment config, which nothing in the shipped app sets.) A green CI run is not that, and neither is the Builder's confidence. · **Production դարպասը միայն Owner-ինն ա։** Անկախ աուդիտ ԵՎ Gev-ի հաստատում — կանաչ CI-ն դա չի։
- **Release and tagging stay the Owner's alone.** The §B.5 delegation covers push and merge to `main` and nothing further: publishing a build is a separate act from landing a commit, and the production gate is shut regardless of either. · **Release-ը ու tag-ը մնում են միայն Owner-ինը։** §B.5-ի պատվիրակումը ծածկում ա push/merge-ը ու ուրիշ ոչինչ։
- **This file said "Only the Owner merges" until 2026-08-14** — four days' worth of nothing, but it was the canonical answer to "who may merge?" while the Builder merged #87, #88 and #89. The roadmap was amended in #88 in four places and this file, which is on the canonical read manifest, was missed. Recorded rather than quietly overwritten. · Այս ֆայլը 2026-08-14-ին դեռ ասում էր հակառակը, մինչ Builder-ը merge էր անում #87/#88/#89։

# Team Protocol — OS

## Roles

- **Gev — Owner / Final Approver**: sets priorities, approves architecture forks, approves the exact final candidate, and authorizes merge.
- **ChatGPT — Architect / Auditor / Coordinator**: defines architecture and governance, audits changes, reviews PRs, detects drift, and keeps the canonical state coherent.
- **Claude Code — Builder / Executor**: implements approved work, runs tests, commits, pushes branches, and prepares draft PR evidence.

## Mandatory workflow

1. Never work directly on `main`.
2. Every task uses a dedicated branch and draft PR.
3. Before work, read `CLAUDE.md`, `AGENTS.md`, this file, and `PROJECT_STATE.md`.
4. Before editing, write the task scope, owner, branch, and affected areas into `PROJECT_STATE.md`.
5. Every meaningful change must be committed and pushed; local-only state is not canonical.
6. The same commit that changes project state must update `PROJECT_STATE.md` and any affected canonical docs.
7. PR description must include: scope, files changed, tests run, results, risks, open decisions, and next action.
8. ChatGPT and Claude Code communicate through GitHub state: commits, PR description/comments, and canonical files — never through assumed chat memory.
9. No overlapping write ownership. One active writer per file/area unless explicitly coordinated.
10. Merge only after Gev approves the exact candidate HEAD.

## Handoff rule

Before stopping or switching sessions, the active worker must update `PROJECT_STATE.md` with:

- current branch and PR,
- latest commit SHA,
- completed work,
- test evidence,
- remaining work,
- blockers/decisions,
- exact next action.

A session is not complete until this handoff is pushed.

---

# Թիմային կանոն — OS

## Դերեր

- **Գև — Owner / Final Approver**․ որոշում է առաջնահերթությունները, հաստատում է ճարտարապետական ընտրությունները, final candidate HEAD-ը և merge-ը։
- **ChatGPT — Architect / Auditor / Coordinator**․ սահմանում է architecture/governance-ը, audit ու review է անում, գտնում է drift-ը և պահում canonical վիճակը համահունչ։
- **Claude Code — Builder / Executor**․ իրականացնում է հաստատված աշխատանքը, վազեցնում tests-ը, commit/push է անում և պատրաստում draft PR evidence-ը։

## Պարտադիր workflow

1. `main`-ի վրա ուղիղ աշխատանք չկա։
2. Ամեն task՝ առանձին branch + draft PR։
3. Սկզբում պարտադիր կարդալ `CLAUDE.md`, `AGENTS.md`, այս ֆայլը և `PROJECT_STATE.md`։
4. Մինչև edit՝ `PROJECT_STATE.md`-ում գրել task scope-ը, owner-ը, branch-ը և affected area-ները։
5. Ամեն meaningful փոփոխություն պարտադիր commit/push է։ Local-only վիճակը canonical չէ։
6. Project state փոխող նույն commit-ը պարտադիր թարմացնում է `PROJECT_STATE.md`-ը և կապված canonical docs-ը։
7. PR-ում պարտադիր գրել scope, changed files, tests/results, risks, open decisions և next action։
8. ChatGPT-ն ու Claude Code-ը իրարից տեղեկանում են GitHub-ի commit/PR/canonical files-ով, ոչ թե ենթադրված chat memory-ով։
9. Նույն file/area-ի վրա միաժամանակ երկու writer չկա՝ առանց հատուկ coordination-ի։
10. Merge միայն Գևի կողմից exact candidate HEAD-ի հաստատումից հետո։

## Handoff կանոն

Session-ը կանգնեցնելուց կամ փոխելուց առաջ active worker-ը պարտադիր թարմացնում և push է անում `PROJECT_STATE.md`-ը՝ current branch/PR, latest SHA, completed work, tests, remaining work, blockers/decisions և exact next action տվյալներով։

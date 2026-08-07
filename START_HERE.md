# 🚦 START HERE · ՍԿՍԻՐ ԱՅՍՏԵՂ

**New session? Told "go read the repo / կարդա ՄԴները"? This is the whole onboarding.
Do it FIRST, no exceptions — then you are ready and need no further explanation.**

**Նոր session? Ասե՞լ են «գնա ռեպո կարդա ՄԴները»։ Սա ամբողջ onboarding-ն ա։
Արա ԱՌԱՋԻՆԸ, բացառություն չկա — հետո պատրաստ ես, ավել բացատրություն պետք չի։**

> **Where things stand (2026-08-08).** `main` = `0efa99e` — a **baseline at the time of writing**;
> resolve the live HEAD yourself every session, and never trust this line over `git log`.
> **Open pull requests: 0.** PRs #64 and #65 merged on 2026-08-07. The last big wave closed
> thirty-odd findings of one shape: *something was built and nothing could reach it, or something
> was displayed and nothing established it.*
>
> **The production gate is CLOSED and must stay closed until you are told otherwise.**
> `platform_governed_execution_supported()` returns false and `main()` keeps
> `UpstreamBlockedExecutor`, so production `trusted_verified` is unreachable. Opening it needs an
> independent audit **and** the Owner's approval — not a green CI run, not a builder's confidence.
>
> Machine-readable truth: [`config/current_state.json`](./config/current_state.json). It is
> checked against live GitHub by `tools/check_repo_state.py`, so it cannot quietly drift.

---

## ✅ Do exactly this · Արա ուղիղ սա

**1. `git pull`** — get the latest state · վերցրու վերջին վիճակը

**2. Read these files IN FULL, in this order · Կարդա այս ֆայլերը ԱՄԲՈՂՋՈՎ, այս հերթով:**

1. [`NEXT_CHAT.md`](./NEXT_CHAT.md) — **the definitive handoff: exact current branch / PR / HEAD / blockers / next action** · վերջնական handoff
2. [`CLAUDE.md`](./CLAUDE.md) — the brain: what this is, how to work, the rules · ուղեղը
3. [`PROJECT_STATE.md`](./PROJECT_STATE.md) — live status: where we are, who's on what, blockers · կենդանի վիճակ
4. [`TASKS.md`](./TASKS.md) — the task board: **claim your task; never collide** · task board
5. [`OWNERS.md`](./OWNERS.md) — who has which role · դերեր
6. [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) — the design · ճարտարապետություն

*(Machine-readable form of this read order:
[`config/canonical-read-manifest.json`](./config/canonical-read-manifest.json) — every path in it
is asserted to exist by the `Coordination · docs consistency gate` in CI, so the chain can never
point at a deleted file.)*

**3. Claim your task in `TASKS.md`** before touching anything · claim արա task-ը որևէ բանի դիպչելուց առաջ

**Only then start.** · **Միայն հետո սկսի։**

---

## 📌 Four things that will save you a wasted day

**A documented claim is not evidence.** This repository's characteristic defect is an honest
comment written the moment it was true and never revisited. Twelve were found and corrected in one
week — a docstring saying a function "cannot be used" after it was fixed; a refusal listing three
outstanding changes after one landed; a page claiming "no verification chain" after its writes
gained records. **Check the code, then trust the sentence.** If you change behaviour, grep for the
comments that described the old one.

**A green test is not a passing check.** Three audit rounds here returned RED on rows a builder had
marked closed. The discipline that came out of it: when you add a check, **delete it once and
confirm its test goes red**, then restore it. Roughly ninety checks were verified that way in the
last wave — and four came back *green*, meaning four tests were testing nothing. Report those
rather than quietly re-rolling.

**Say what you did not do.** ✅ in the audit ledgers means *independently confirmed*. ◑ means *the
builder's own unverified claim*. Never promote your own work to ✅.

**Run the gates before you open a PR.** `for g in tools/check_*.py; do python "$g"; done` plus
`python tools/generate_agent_definitions.py --check` — 15 gates, all expected GREEN. The engine
suite needs `BRO_ENV=ci` or operator-pin gating denies and the tests error rather than run.

---

## 📌 Չորս բան, որ քեզ մեկ օր կփրկի

**Փաստաթղթված պնդումը ապացույց չի։** Այս ռեպոյի բնորոշ դեֆեկտը ազնիվ մեկնաբանությունն ա՝ գրված այն
պահին երբ ճիշտ էր, ու երբեք չվերանայված։ Մեկ շաբաթում տասներկուսը գտնվեց ու ուղղվեց։ **Կոդը կարդա,
հետո նախադասությանը վստահի։** Եթե վարքագիծ ես փոխում, grep արա այն մեկնաբանությունները որ հին
վարքագիծն էին նկարագրում։

**Կանաչ տեստը անցած ստուգում չի։** Երեք աուդիտի փուլ այստեղ RED ա տվել այն տողերի վրա որ builder-ը
նշել էր փակված։ Դրանից ծնված կարգապահությունը՝ երբ ստուգում ես ավելացնում, **ջնջի այն մեկ անգամ ու
համոզվի որ իր տեստը կարմրում ա**, հետո վերականգնի։ Վերջին ալիքում մոտ իննսուն ստուգում այդպես
ստուգվեց — ու չորսը **կանաչ մնաց**, այսինքն չորս տեստ ոչինչ չէր ստուգում։ Այդպիսիք գրանցի, ոչ թե
լուռ վերափորձի։

**Ասա թե ինչ չես արել։** Աուդիտի մատյաններում ✅ նշանակում ա *անկախ հաստատված*։ ◑ նշանակում ա
*builder-ի սեփական չստուգված պնդում*։ Երբեք սեփական գործդ ✅ մի դարձրու։

**PR բացելուց առաջ վազեցրու gate-երը։** `for g in tools/check_*.py; do python "$g"; done` գումարած
`python tools/generate_agent_definitions.py --check` — 15 gate, բոլորը սպասվում են GREEN։ Engine-ի
suite-ին պետք ա `BRO_ENV=ci`, այլապես operator-pin gating-ը մերժում ա ու տեստերը error են տալիս։

---

> If you read all 6 files fully + pulled + claimed a task, you are fully onboarded.
> Applies to **every agent — Claude and ChatGPT — every session.** No exceptions.
>
> Եթե 6-ն էլ ամբողջովին կարդացիր + pull արեցիր + task claim արեցիր՝ լրիվ onboarded ես։
> Վերաբերում ա **ամեն agent-ին — Claude ու ChatGPT — ամեն session։** Բացառություն չկա։

# 🚦 START HERE · ՍԿՍԻՐ ԱՅՍՏԵՂ

**New session? Told "go read the repo / կարդա ՄԴները"? This is the whole onboarding.
Do it FIRST, no exceptions — then you are ready and need no further explanation.**

**Նոր session? Ասե՞լ են «գնա ռեպո կարդա ՄԴները»։ Սա ամբողջ onboarding-ն ա։
Արա ԱՌԱՋԻՆԸ, բացառություն չկա — հետո պատրաստ ես, ավել բացատրություն պետք չի։**

> **Where things stand (2026-08-14).** `main` = `0a0be37` — a **baseline at the time of writing**;
> resolve the live HEAD yourself every session, and never trust this line over `git log`. The machine
> mirror is `config/current_state.json.settled_at_main_head`, which `tools/check_repo_state.py`
> compares against live GitHub — so *that* cannot quietly drift. **This sentence can, and did:** it
> said `c1e0aca` and "#80 was the last" one merge after both stopped being true, then sat at
> `b3010f6` and "#82 is open" through **seven** further merges (#83–#89) — five of them on 2026-08-14
> alone. Nothing checks it. Treat every head and PR number on this page as a date-stamped guess.
> **Open pull requests: 1** — the one carrying this correction. #84–#89 all merged and their branches
> are gone.
>
> **Push and merge were delegated to the Builder on 2026-08-14** (roadmap §B.5, Owner waiver, no
> Architect audit — it says so in its own text). One clause is not delegated with it: a merge needs
> **every** required check green **on the exact head that merges**. #84 merged with `Repo-state` red,
> and #85/#86 merged while their runs were still going, so the head that landed was never the head
> the checks passed on. Release and tagging stay the Owner's.
> The wave before them closed thirty-odd findings of one shape: *something was built and nothing
> could reach it, or something was displayed and nothing established it.* The #71–#81 wave has a
> different shape: a deployment runbook and a trust ceremony that were **written and never run**,
> and nearly every defect in them was found by running it. #81 then found that the repository's own
> prescribed reading order led to its stalest text, and #82 fixed that.
>
> **What changed, and what you must not get wrong.** The desktop app now **provisions its own trust
> material at first launch** — it mints a keypair for every authority the engine knows, signs the
> trusted-key registry, and then **destroys the operator root**; the pin, the anti-rollback floor,
> the registry and the provisioning manifest live in a machine-wide anchor the app's own account
> cannot write. There is no owner ceremony and no USB any more. **But:** that is **Windows-only**
> (sealing the anchor refuses on POSIX, and provisioning aborts startup), **nothing exports the
> provisioned environment into the engine** (the engine still reads the committed *development*
> registry), the audit signer ships in **no** installer, and `broctl` still **cannot mint a
> production registry** at all. Read [`docs/SECURITY_MODEL.md`](./docs/SECURITY_MODEL.md) §1 before
> reasoning about trust here, and [`docs/OWNER_ACTION_REQUIRED.md`](./docs/OWNER_ACTION_REQUIRED.md)
> for what is blocked on whom.
>
> **The production gate is CLOSED and must stay closed until you are told otherwise.** Production
> `trusted_verified` is unreachable: `governed_verification_unconfigured()` returns `Some(…)`
> unconditionally and fires *before the model is called*, `connect_broker()` returns
> `UnsupportedPlatform` off Linux, and the broker's `build_governed_executor` serves
> `UpstreamBlockedExecutor` **unless `$BROPS_BROKER_CONFIG` names a deployment config carrying a
> TCB-root-signed manifest** — nothing in the shipped app sets it. State that third refusal *with its
> condition*: `build_governed_executor` otherwise returns a real `ChainExecutor` over a
> `LinuxGovernedTurnChain` whose resolver can reach `TrustState::Production`, so "the broker hands out
> `UpstreamBlockedExecutor`" — which these documents said flatly until 2026-08-09, because
> `tools/sync_active_pr.py` generated that sentence into three of them at a time — is false, and it
> is false in the direction that tells a reader the wrong thing is load-bearing. (Documents here
> often name this gate `platform_governed_execution_supported()`. **No function of that name exists
> in the tree** — it is the spec symbol from `docs/design/WINDOWS_BROKER_DESIGN.md` §0.1, and
> `config/spec-conformance.json` records §0.1 as `partial` saying exactly that. Cite the three real
> refusals.) Opening the gate needs an independent audit **and** the Owner's approval — not a green
> CI run, not a builder's confidence.
>
> **⚠ The standing independent-audit verdict is RED.** Two independent audits have run. The second
> — [`apps/desktop/AUDIT/2026-08-06-remediation-audit.md`](./apps/desktop/AUDIT/2026-08-06-remediation-audit.md),
> of `main` @ `219c763` AFTER the first round's remediation — confirmed **4 of 18** blockers closed
> and left **122 surviving findings** (1 P0, 7 P1, 32 P2, 82 P3), and **has never been re-run** on any
> later head. Nothing merged since is independently confirmed. The index is
> [`apps/desktop/AUDIT/AUDIT_LEDGER.md`](./apps/desktop/AUDIT/AUDIT_LEDGER.md) — read it before
> believing any ✅ in these documents; ◑ there means *the Builder's unverified claim*. Until
> 2026-08-09 this verdict was in no canonical file, while `NEXT_CHAT.md` opened with the FIRST
> audit's “all code facts CONFIRMED, none refuted” — so two cold reads concluded the audit had come
> back clean. It had not.
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
7. [`apps/desktop/AUDIT/AUDIT_LEDGER.md`](./apps/desktop/AUDIT/AUDIT_LEDGER.md) — **the audit position:
   what an independent auditor confirmed, what is only claimed, and the standing RED verdict** ·
   աուդիտի դիրքը. This file was on no read list until 2026-08-09, which is why two cold reads in a
   row believed the audit had come back clean

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

**A green test is not a passing check.** Audit rounds here returned RED on rows a builder had
marked closed, and the **last independent audit is still RED** (see the block above). The discipline that came out of it: when you add a check, **delete it once and
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

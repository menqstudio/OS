# 🚦 START HERE · ՍԿՍԻՐ ԱՅՍՏԵՂ

**New session? Told "go read the repo / կարդա ՄԴները"? This is the whole onboarding.
Do it FIRST, no exceptions — then you are ready and need no further explanation.**

**Նոր session? Ասե՞լ են «գնա ռեպո կարդա ՄԴները»։ Սա ամբողջ onboarding-ն ա։
Արա ԱՌԱՋԻՆԸ, բացառություն չկա — հետո պատրաստ ես, ավել բացատրություն պետք չի։**

> **Where things stand is not written on this page.** This block carried a dated narrative — a
> `main` head, an open-PR count, "two independent audits have run" — and each of those went stale
> while nothing checked it. The live answers are in files that are checked:
> [`NEXT_CHAT.md`](./NEXT_CHAT.md) (branch, head, next action),
> [`config/current_state.json`](./config/current_state.json) (the machine mirror, compared against
> live GitHub by `tools/check_repo_state.py`) and
> [`apps/desktop/AUDIT/AUDIT_LEDGER.md`](./apps/desktop/AUDIT/AUDIT_LEDGER.md) (the audit position).
> Resolve the live HEAD yourself with `git log`; no head or PR number is printed here any more.
>
> **Push and merge were delegated to the Builder on 2026-08-14** (roadmap §B.5, Owner waiver, no
> Architect audit — it says so in its own text). One clause is not delegated with it: a merge needs
> **every** required check green **on the exact head that merges**. #84 merged with `Repo-state` red,
> and #85/#86 merged while their runs were still going, so the head that landed was never the head
> the checks passed on. Release and tagging stay the Owner's.
>
> **Trust, and what you must not get wrong.** No person holds a key (Owner decision #78): the
> install mints a keypair for every authority the engine knows, signs the trusted-key registry and
> **destroys the operator root**; there is no owner ceremony and no USB. On Windows the app does
> that at first launch. **On POSIX the app never creates the anchor** — `preprovision_refusal`
> refuses before anything is minted, because an anchor the app's own uid built is one it could
> rewrite. A root installer creates it instead (`brops_install_anchor`, which the `.deb` declares as
> its post-install step); an anchor already in place is verified and used, and a machine whose
> install step did not run still refuses first launch. `tauri.conf.json` declares no `externalBin`,
> so the audit signer ships in **no** installer, and `broctl` **cannot mint a production registry**
> at all. Read [`docs/SECURITY_MODEL.md`](./docs/SECURITY_MODEL.md) §1 before reasoning about trust
> here, and [`docs/OWNER_ACTION_REQUIRED.md`](./docs/OWNER_ACTION_REQUIRED.md) for what is blocked
> on whom.
>
> **The production gate is CLOSED and must stay closed until you are told otherwise.** Production
> `trusted_verified` is unreachable: `governed_verification_unconfigured()` returns `Some(…)` while
> any of its five compile-time inputs is absent — all are — and fires *before the model is called*,
> `connect_broker()` returns `UnsupportedPlatform` off Linux, and the broker's
> `build_governed_executor` serves `UpstreamBlockedExecutor` **unless `$BROPS_BROKER_CONFIG` names a
> deployment whose manifest verifies under the floor-pinned root anchor** — nothing in the shipped
> app sets it. State that third refusal *with its condition*: "the broker hands out
> `UpstreamBlockedExecutor`", said flatly, is false. (Documents here often name this gate
> `platform_governed_execution_supported()`. **No function of that name exists in the tree** — it is
> the spec symbol from `docs/design/WINDOWS_BROKER_DESIGN.md` §0.1. Cite the three real refusals.)
> Opening the gate needs an independent audit **and** the Owner's approval — not a green CI run,
> not a builder's confidence.
>
> **⚠ The standing independent-audit verdict is RED.** Ten rounds have run; the current one is the
> tenth, [`2026-09-19-tenth-audit-75fca65.md`](./apps/desktop/AUDIT/2026-09-19-tenth-audit-75fca65.md)
> — RED, no P0. The second round left **45 surviving findings** (1 P0, 5 P1, 13 P2, 26 P3). Read the
> ledger before believing any ✅ in these documents; ◑ there means *the Builder's unverified claim*.
> This paragraph said "two independent audits have run ... never re-run" through eight further
> rounds — the round count belongs to the ledger, and this line is only a pointer to it.

---

## ✅ Do exactly this · Արա ուղիղ սա

**1. `git pull`** — get the latest state · վերցրու վերջին վիճակը

**2. Read, IN FULL and in its order, every path in
[`config/canonical-read-manifest.json`](./config/canonical-read-manifest.json)** · Կարդա ԱՄԲՈՂՋՈՎ ու
իր հերթով այդ manifest-ի ամեն ուղին

That file is the read order and the only one — a second list printed here was the fifth copy, and
the copies disagreed (this page listed seven paths and then said "all 6 files"). It opens with
[`NEXT_CHAT.md`](./NEXT_CHAT.md) — **the definitive handoff: branch / PR / HEAD / blockers / next
action** — and carries [`CLAUDE.md`](./CLAUDE.md), [`PROJECT_STATE.md`](./PROJECT_STATE.md),
[`TASKS.md`](./TASKS.md) and
[`apps/desktop/AUDIT/AUDIT_LEDGER.md`](./apps/desktop/AUDIT/AUDIT_LEDGER.md), **the audit position**.
The startup hook pastes every path in it, and the `Coordination · docs consistency gate` in CI
asserts every path exists, so the chain can never point at a deleted file.

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

> **The accessibility gate lives in the BROWSER project, not the a11y one.** `npm run test:a11y` is
> the fast structural sweep and runs in jsdom with `css: false`, where axe's `color-contrast` rule
> **cannot execute**. The one that measures colour is `npm run test:browser`
> (`pages.axe.browser.spec.tsx`, real Chromium, both themes) and it reports under the CI context
> `Cockpit · computed style (real Chromium)` — a name that predates it. If you change a colour, that
> is the job to watch, along with `python tools/check_contrast.py`.

**Run the gates before you open a PR.** `for g in tools/check_*.py; do python "$g"; done` plus
`python tools/generate_agent_definitions.py --check`. **45 `check_*.py` files exist; 42 are invoked
by path in `.github/workflows/`** (the three that are not — `check_prior_art.py`,
`check_merge_ready.py`, `check_push_ready.py` — are session-side by design: the hook runs the last
two before a `gh pr merge` and a `git push`). *(Measured at `4b25650` on 2026-10-01 with `for f in tools/check_*.py; do grep -rqF
"$(basename $f)" .github/workflows/; done`. This paragraph said 19/18 and `ARCHITECTURE.md` said 18 —
the ninth audit filed it as `I-10` — and then said 40/39 while the tree held 42/41, so the method is
written down here rather than the number alone.)* Four of the 45 need arguments and print usage
instead of a verdict when that loop runs them bare:
`check_canonical_sync.py` (`--staged` / `--base`), `check_prior_art.py`, `check_read_receipt.py`,
`check_merge_ready.py` (`--pr N`).
Two more go RED on a machine that has not built or installed everything — `check_bundle_budget.py`
wants a Vite manifest from `npm run build` **and, since `I-12`, refuses to grade a `dist/` older than
the tree, so it says `the build is stale` after any checkout until you rebuild**, and `check_runbook_snippets.py` fails closed unless
`cryptography` imports. Both are green in CI. *(This paragraph said "15 gates, all expected GREEN"
until 2026-08-14, which set up a reader to treat five non-verdicts as failures — or worse, to stop
counting.)* The engine suite needs `BRO_ENV=ci` or operator-pin gating denies and the tests error
rather than run.

---

## 📌 Չորս բան, որ քեզ մեկ օր կփրկի

**Փաստաթղթված պնդումը ապացույց չի։** Այս ռեպոյի բնորոշ դեֆեկտը ազնիվ մեկնաբանությունն ա՝ գրված այն
պահին երբ ճիշտ էր, ու երբեք չվերանայված։ Մեկ շաբաթում տասներկուսը գտնվեց ու ուղղվեց։ **Կոդը կարդա,
հետո նախադասությանը վստահի։** Եթե վարքագիծ ես փոխում, grep արա այն մեկնաբանությունները որ հին
վարքագիծն էին նկարագրում։

**Կանաչ տեստը անցած ստուգում չի։** Աուդիտի փուլերն այստեղ RED են տվել այն տողերի վրա որ builder-ը
նշել էր փակված, ու **վերջին անկախ աուդիտը դեռ RED ա**։ Դրանից ծնված կարգապահությունը՝ երբ ստուգում ես ավելացնում, **ջնջի այն մեկ անգամ ու
համոզվի որ իր տեստը կարմրում ա**, հետո վերականգնի։ Վերջին ալիքում մոտ իննսուն ստուգում այդպես
ստուգվեց — ու չորսը **կանաչ մնաց**, այսինքն չորս տեստ ոչինչ չէր ստուգում։ Այդպիսիք գրանցի, ոչ թե
լուռ վերափորձի։

**Ասա թե ինչ չես արել։** Աուդիտի մատյաններում ✅ նշանակում ա *անկախ հաստատված*։ ◑ նշանակում ա
*builder-ի սեփական չստուգված պնդում*։ Երբեք սեփական գործդ ✅ մի դարձրու։

**PR բացելուց առաջ վազեցրու gate-երը։** `for g in tools/check_*.py; do python "$g"; done` գումարած
`python tools/generate_agent_definitions.py --check` — **45 `check_*.py` ֆայլ կա; 42-ը workflow-ներում
կանչված են ուղիով**, չկանչված երեքը (`check_prior_art.py`, `check_merge_ready.py`,
`check_push_ready.py`) դիզայնով session-side են։ Դրանցից **չորսը**
արգումենտ են ուզում ու bare վազելիս verdict-ի փոխարեն usage են տպում՝ `check_canonical_sync.py`,
`check_prior_art.py`, `check_read_receipt.py`, `check_merge_ready.py`; **երկուսը** RED են չկառուցված մեքենայի վրա՝
`check_bundle_budget.py` (Vite manifest) ու `check_runbook_snippets.py` (`cryptography`)։
*(Այս տողը գրում էր «15 gate, բոլորը GREEN» — անգլերեն կեսը գրում էր 19/18, ու իններորդ աուդիտը դա
գրանցեց որպես `I-10`՝ **երկրորդ անընդմեջ ռաունդը**, երբ այս թվերը սխալ են։ Չափված ա այս head-ի վրա։)*
Engine-ի suite-ին պետք ա `BRO_ENV=ci`, այլապես operator-pin gating-ը մերժում ա ու տեստերը error են տալիս։

---

> If you read every file in the manifest fully + pulled + claimed a task, you are fully onboarded.
> Applies to **every agent — Claude and ChatGPT — every session.** No exceptions.
>
> Եթե manifest-ի ամեն ֆայլն ամբողջովին կարդացիր + pull արեցիր + task claim արեցիր՝ լրիվ onboarded ես։
> Վերաբերում ա **ամեն agent-ին — Claude ու ChatGPT — ամեն session։** Բացառություն չկա։

<div align="center">

# CLAUDE.md — the brain of `menqstudio/OS`

**Read this first. Every new session — AI or human — starts here.**
**Կարդա սա առաջինը։ Ամեն նոր session սկսում ա այստեղից։**

[English](#english) · [Հայերեն](#հայերեն)

</div>

---

## ⛔ STARTUP LAW — every session, no exceptions

1. **`git pull`**
2. **Read, IN FULL, every path in [`config/canonical-read-manifest.json`](./config/canonical-read-manifest.json)** — that file is the read order and the only one. It starts with `NEXT_CHAT.md` (branch, head, next action), then `CLAUDE.md`, `PROJECT_STATE.md`, `TASKS.md`. The startup hook pastes them; it is not a request.
3. **Claim your task in [`TASKS.md`](./TASKS.md)** — never two agents on one row.

Then start. When Gev says *«գնա ռեպո կարդա ՄԴները»* that phrase **is** this law.

**One read order, both languages.** Until 2026-08-29 there were **five**, and they disagreed: the manifest listed 16 paths, `START_HERE.md` 7, `AGENTS.md` 6, the English law 6, and **the Armenian law 5 — omitting `NEXT_CHAT.md`, the file the manifest itself calls `current_state_pointer`.** The Owner reads the Armenian one.

**The read set is now budgeted.** [`tools/check_canon_budget.py`](./tools/check_canon_budget.py) holds every canonical file to a ceiling in `config/canon-budget.json` and the whole set to one context. It reached **1917 KB (~386,000 tokens)** on 2026-08-29, of which the hook could paste a quarter; `NEXT_CHAT.md` and `PROJECT_STATE.md` were the same document — 3037 identical lines from line 2 — and `TASKS.md` was 92% inside `NEXT_CHAT.md`. History lives in [`docs/archive/`](./docs/archive/).

## ⛔ CONTINUOUS-DOCUMENTATION LAW

After **every** substantive change — design, code, audit verdict, HEAD change, blocker found or closed, merge — update the affected canonical documents, commit, push, and update the PR body **in the same cycle**. No required continuation state may live only in a chat, a memory or an unpushed commit.

At every moment the repository must be sufficient for a brand-new session told only *"go to `menqstudio/OS`, read the manifest, verify the head, continue"* — and then continue correctly **from GitHub alone**.

That was a sentence for weeks. It is a program now: **[`tools/check_handoff_ready.py`](./tools/check_handoff_ready.py)**. Run it before telling anyone to open a fresh session; until it is GREEN, saying so is telling them to start from a repository that cannot carry the work.

**And the update law now cuts both ways.** `.claude/hooks/coordination_stop_guard.py` blocks a session from ending when source changed and the coordination docs did not — so every session was mechanically required to **add**, and nothing ever required removing. 179 pull requests of that produced a 4034-line handoff. While a canonical file is over its ceiling the PreToolUse hook accepts **only an edit that makes it smaller**.

---

# English

## 1. What OS is

**OS** is one product from two halves:

- 🧠 **`engine/`** — the governance brain (Python), vendored from [`menqstudio/Bro`](https://github.com/menqstudio/Bro). Ed25519-signed execution leases, approval gates, an append-only evidence chain, a protected control plane, and a fail-closed hook over every tool call.
- 🖥️ **`apps/desktop/`** — the cockpit (Tauri: React/TypeScript + Rust + SQLite), vendored from [`menqstudio/BroPS`](https://github.com/menqstudio/BroPS).

**The thesis:** the cockpit is the only surface a person touches, and every AI action it triggers must flow through the wall — `lease → gate → sandbox → signed receipt`. No direct, ungoverned model execution.

**Owner:** Gev / MenQ (`menqstudio`, menqstudio@gmail.com). **Reply in Armenian by default**; English for code, identifiers and commands.

## 2. Repository map

```
OS/
├── CLAUDE.md            ← this brain
├── NEXT_CHAT.md         live handoff: branch · head · next action
├── PROJECT_STATE.md     per-part status          TASKS.md  open rows
├── MASTER_EXECUTION_ROADMAP.md   the durable 11-phase plan
├── apps/desktop/        cockpit (git subtree, history preserved)
├── engine/              governance engine (git subtree)
├── bridge/              Phase-1 governed adapter — real code, not a placeholder
├── contracts/           the SOURCE for the five cross-half schemas, drift-gated
├── docs/archive/        history moved out of the read set
└── .github/workflows/   unified CI
```

## 3. Where the state lives

| Question | File |
|---|---|
| What does the next session do first? | `NEXT_CHAT.md` |
| What is the state of each part? | `PROJECT_STATE.md` |
| What is open, and who holds it? | `TASKS.md` |
| What is the plan? | `MASTER_EXECUTION_ROADMAP.md` |
| Machine mirror, checked against live GitHub | `config/current_state.json` |
| What did an independent auditor confirm? | `apps/desktop/AUDIT/AUDIT_LEDGER.md` |
| What is blocked, and on whom? | `docs/OWNER_ACTION_REQUIRED.md` |
| Trust model | `docs/SECURITY_MODEL.md` |

Phase status is in `PROJECT_STATE.md` and the roadmap; this file does not carry a third copy of it. Two tables cannot both be the board.

## 4. Verify commands

```bash
cd engine && BRO_ENV=ci python3 -m unittest discover -s tests    # 2105 OK, 10 skipped
cd apps/desktop/src-tauri && cargo test --workspace              # 1147 passed
cd apps/desktop && npm ci && npm run typecheck && npm test       # 761 tests / 80 files
python3 tools/check_canon_budget.py                              # the read set fits
python3 tools/check_state_fields.py                              # the mirror has no dead fields
python3 tools/check_handoff_ready.py                             # a new session could take over
for g in tools/check_*.py; do python3 "$g"; done                 # see §5 for the ones needing args
```

Measured 2026-08-31, all three, on this box. **Verify before claiming green** — never assume, and never take a number in a document on trust. Every audit round so far has found stale counts in these files.

## 5. Environment

**This is a Debian box.** Until 2026-08-29 five canonical documents said it was a Windows box and that `cargo` must run from PowerShell because Git Bash's `link` shadows MSVC's `link.exe`. That was true of the old machine. Here, `cargo test --workspace` runs from an ordinary shell and passes 1012 tests.

- **Toolchain:** cargo 1.97.1 · node 20.20.2 · npm 10.8.2, recorded in [`config/toolchain.json`](./config/toolchain.json), which is what `tools/check_doc_claims.py` checks every document against. *(The documents said cargo 1.96 / node 24 / npm 11.)*
- **Engine tests need `BRO_ENV=ci`** — without it operator-pin gating denies and tests error rather than run.
- **⚠ The wall loads from the SESSION's project root, not the repository you edit.** `.claude/settings.json` wires **six** events — `SessionStart`, `SubagentStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop` — all addressed `$CLAUDE_PROJECT_DIR/.claude/hooks/…`. **A session opened elsewhere that then works inside `OS/` gets none of them**, and nothing announces their absence: no read receipt, no phase declaration, no prior-art check, no Stop guard. That happened for the whole of `T-019`. **Open the session at this checkout.**
- **Session-scoped gates cannot see a bare shell.** `check_read_receipt.py` and `check_roadmap_order.py` resolve the session from `CLAUDE_SESSION_ID`, which the hooks set and the Bash tool does not. Pass `--session`, or the RED you get means "could not find the session", not "the gate failed".
- **Gates needing arguments** (they print usage, not a verdict, when run bare): `check_canonical_sync.py`, `check_prior_art.py`, `check_read_receipt.py`. **Needing a build or a package:** `check_bundle_budget.py` (a Vite manifest, and it refuses a `dist/` older than the tree), `check_runbook_snippets.py` (`cryptography`).
- **Commit identity:** `user.name "MenQ"`, `user.email "menqstudio@gmail.com"`. End every commit with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **Enforcement-hook wedge:** the engine's own hooks can crash on a non-UTF-8 console and fail-closed-cascade a session. Set `PYTHONUTF8=1` and relaunch, or park the wiring with `deploy/wall.sh off` if that script is present in the checkout you are in.

## 6. Security discipline

The engine is a **security perimeter**. Any change to its wall, leases, gates, signatures, control plane or root model is deliberate, tested and never rushed. When two paths exist, prefer the one that leaves audited security code untouched.

**The production gate is SHUT**, and only the Owner opens it after an independent audit — not a green CI run, not the Builder's confidence. Three refusals hold it. There is no `platform_governed_execution_supported()` in the tree; that is the §0.1 spec symbol, and documents citing it are citing a name that does not exist:

1. `governed_verification_unconfigured()` returns `Some(...)` **unconditionally, before the model is invoked**
2. `connect_broker()` returns `UnsupportedPlatform` **off Linux**
3. the broker serves `UpstreamBlockedExecutor` **unless `$BROPS_BROKER_CONFIG` names a deployment config carrying a TCB-root-signed manifest** — which nothing in the shipped app sets

**The standing independent verdict is RED.** Nine rounds; the current one is [`2026-08-19-ninth-audit-5cf9b8c.md`](./apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md) — RED, no P0, all three refusals read at source and closed for the fourth round running. The second round left **45** surviving findings (1 P0 · 5 P1 · 13 P2 · 26 P3); *the Armenian half of this file said 122, and 1+5+13+26 is 45.*

**O-1…O-5 are all OPEN and none needs an Owner-minted artifact.** Inventory: [`docs/PHASE_10_PRODUCTION_ITEMS.md`](./docs/PHASE_10_PRODUCTION_ITEMS.md). What blocks them is deployment wiring and a second principal. Severities, which `tools/check_residual_items.py` holds identical here, in `docs/SECURITY_MODEL.md` §4 and in the inventory — a severity quietly downgraded in one document is how a production item stops being one: **O-1 (HIGH)** bytecode-shadow, the *read* half — CPython imports an existing `.pyc` before any Python check can run · **O-2 (MED)** audit-head anchor · **O-3 (MED)** conductor session token, fail-closed and set, open until a desktop turn reaches it · **O-4 (LOW)** control-room actor — nothing outside tests mints the artifact `_prove_command_actor` would verify · **O-5 (LOW)** evidence high-water, open deliberately: *when* it is minted is an unanswered design question. The one to know:

> **O-2 — the audit ledger is not tamper-evident against its own writer on any real deployment.** Custody comes from `BRO_AUDIT_ANCHOR_SIGNER` / `BRO_AUDIT_ANCHOR_KEY_ID` and **nothing in the shipped product sets either**; `tauri.conf.json` declares no `externalBin`, so no signer binary is installed. `append()` writes the record, rewrites a **plaintext** `.head`, and produces no `.head.sig`. Anyone who can write the ledger can drop records, recompute the chain and rewrite the head, and an unkeyed `verify()` reports it intact. On Windows the signer is built and in no installer; **on POSIX it has never run.**

**There is no path in this repository to a production trust root.** `broctl build-registry` hardcodes `"production": false`, `broctl keygen --production` refuses, and `bro_signature` refuses a development registry when the pin comes from the production path. See [`docs/DEBIAN_DEPLOYMENT.md`](./docs/DEBIAN_DEPLOYMENT.md).

**Provisioning is Windows-only** — sealing the anchor refuses on POSIX and provisioning aborts startup, so on this Debian box the first-launch trust path is unreachable.

## 7. Rules for AI sessions

1. **Do not start execution without Gev's explicit go** («սկսի» / «start»). He front-loads context across several messages — collect, don't act.
2. **You push and merge**, but **only on an all-green exact head**: `gh run watch --exit-status`, then `gh pr checks`, then merge. Never mid-run. #84 merged with `Repo-state` red and #85/#86 merged in flight, so the head that landed was never the head the checks passed on. **Release and tagging stay the Owner's.**
   **A queue of open PRs costs N² synchronisation.** `check_repo_state` requires every open PR to be named in `prs[]` at its exact live head, so each merge invalidates every other PR's mirror. Seven open on 2026-08-31 cost six extra mirror commits. Merge one at a time, refreshing only the mirror before each, and settle **once** at the end — that is where you read `gh run list --branch main`. An intermediate red `main` is honest if the mirror records it.
3. **A documented claim is not evidence.** Twelve comments that were true when written and false when read were found in one week. Check the code, then trust the sentence.
4. **A green test is not a passing check.** When you add a check, delete it once and confirm its test goes red, then restore it. Of ninety checks swept that way, four came back green — four tests testing nothing. `T-045` ran the same sweep on its own gates and found three of seven checks tested by nothing, plus a fourth with no test at all.
5. **Say what you did not do.** ✅ means independently confirmed; ◑ means the Builder's own claim. Never promote your own work.
6. **Keep this file current** — land the edit in the same commit as the change.
7. **Reply in Armenian.**

---

# Հայերեն

## 1. Ի՞նչ ա OS-ը

Մեկ product երկու կեսից՝ **`engine/`** (կառավարման ուղեղը, Python, Bro-ից) ու **`apps/desktop/`** (cockpit-ը, Tauri + React + Rust + SQLite, BroPS-ից)։ Իմաստը՝ cockpit-ն ա միակ մակերեսը որ մարդ դիպչում ա, ու նրա գործարկած ամեն AI գործողություն **պիտի անցնի wall-ով**՝ `lease → gate → sandbox → signed receipt`։ Ուղիղ, չկառավարվող model execution չկա։

**Owner:** Gev / MenQ (`menqstudio`, menqstudio@gmail.com)։ Պատասխանը՝ հայերեն։

## 2. Ո՞ր ֆայլն ինչի ա

`NEXT_CHAT.md` — ի՞նչ ա անում հաջորդ սեսիան առաջինը · `PROJECT_STATE.md` — ամեն մասի վիճակը · `TASKS.md` — բաց տողերը · `MASTER_EXECUTION_ROADMAP.md` — պլանը · `config/current_state.json` — մեքենայական mirror, ստուգվում ա կենդանի GitHub-ի դեմ · `apps/desktop/AUDIT/AUDIT_LEDGER.md` — աուդիտի դիրքը · `docs/OWNER_ACTION_REQUIRED.md` — ի՞նչ ա խցանված ու ո՞ւմ վրա · `docs/archive/` — պատմությունը։

## 3. Միջավայրը — սա Debian ա

Մինչև 2026-08-29 հինգ canonical ֆայլ գրում էր որ սա Windows ա ու `cargo`-ն պիտի PowerShell-ից վազի։ Այստեղ `cargo test --workspace`-ը սովորական shell-ից ա վազում ու 1012 թեստ անցնում։

Toolchain՝ cargo 1.97.1 · node 20.20.2 · npm 10.8.2։ *(Փաստաթղթերը գրում էին 1.96 / 24 / 11։)*

**⚠ Wall-ը բեռնվում ա SESSION-ի project root-ից, ոչ էն repo-ից որ խմբագրում ես։** `.claude/settings.json`-ը միացնում ա **վեց** event։ Ուրիշ տեղից բացված սեսիան, որ հետո աշխատում ա `OS/`-ի ներսում, դրանցից **ոչ մեկը չի ստանում**, ու ոչինչ չի ազդարարում բացակայությունը։ **Բացիր սեսիան հենց այս checkout-ից։**

Engine-ի թեստերին պետք ա `BRO_ENV=ci`։ Commit identity՝ `MenQ` / `menqstudio@gmail.com`, trailer-ը՝ `Co-Authored-By: Claude Opus 5`։

## 4. Անվտանգություն

Engine-ը **security perimeter** ա. իր wall-ի, lease-ների, ստորագրությունների կամ control-plane-ի ցանկացած փոփոխություն դանդաղ ա արվում։

**Production դարպասը ՓԱԿ ա** ու բացում ա միայն Owner-ը՝ անկախ աուդիտից հետո։ Երեք մերժում ա պահում (տես անգլերեն §6)։ `platform_governed_execution_supported()` անունով ֆունկցիա **ծառում չկա** — դա §0.1-ի spec-ի նշանն ա։

**Գործող անկախ վճիռը RED ա** — իններորդ ռաունդ, `main` @ `5cf9b8c`, P0 չկա։ Երկրորդ ռաունդը թողել ա **45** գտածո (1 P0 · 5 P1 · 13 P2 · 26 P3)։ *Այս ֆայլի հայերեն կեսը գրում էր 122, իսկ 1+5+13+26 = 45։*

**O-1…O-5 բոլորը OPEN են ու ոչ մեկին Owner-ի artifact պետք չի։** Ծանրությունները՝ **O-1 (HIGH)** · **O-2 (MED)** · **O-3 (MED)** · **O-4 (LOW)** · **O-5 (LOW)**, ու `tools/check_residual_items.py`-ն պահում ա որ նույնը գրած լինի նաև `docs/SECURITY_MODEL.md` §4-ում ու inventory-ում։ Ամենակարևորը՝ **O-2. audit ledger-ը իր սեփական գրողի դեմ tamper-evident չի ոչ մի իրական deployment-ի վրա** — shipped արտադրանքում ոչինչ չի դնում custody-ի փոփոխականները, signer-ի binary չի տեղադրվում, ու `append()`-ը գրում ա պարզ տեքստով `.head` առանց ստորագրության։ POSIX-ում **երբեք չի վազել**։

**Production վստահության արմատ սարքելու ճանապարհ այս repo-ում չկա** — `broctl`-ը կոշտ գրում ա `"production": false` ու `--production`-ը մերժում ա։

**Provisioning-ը Windows-only ա** — POSIX-ում startup-ը կանգնում ա, ուրեմն այս Debian-ի վրա առաջին գործարկման վստահության ուղին անհասանելի ա։

## 5. Կանոններ

1. **Մի սկսիր առանց Gev-ի հստակ go-ի** («սկսի»)։ Ինքը նախ context ա տալիս — հավաքիր, մի գործիր։
2. **Push ու merge անում ես դու**, բայց **միայն ամբողջովին կանաչ ու ճշգրիտ head-ի վրա**։ Release-ը ու tag-ը մնում են Owner-ինը։
   **N բաց PR արժենում ա N² համաժամանակացում** — ամեն merge հնացնում ա մնացած բոլորի mirror-ը։ Merge արա հերթով, ամեն մեկից առաջ միայն mirror-ը թարմացրու, ու settle արա **մեկ անգամ** վերջում — այնտեղ կարդա `gh run list --branch main`։
3. **Փաստաթղթված պնդումը ապացույց չի։** Կոդը կարդա, հետո նախադասությանը վստահի։
4. **Կանաչ թեստը անցած ստուգում չի։** Ավելացնելիս՝ ջնջի մեկ անգամ ու համոզվի որ կարմրում ա։
5. **Ասա թե ինչ չես արել։** ✅ = անկախ հաստատված, ◑ = builder-ի պնդում։ Սեփական գործդ երբեք ✅ մի դարձրու։
6. **Պատասխանիր հայերեն։**

---

<div align="center"><sub>menqstudio · OS · governed by the wall 🧱</sub></div>

<div align="center">

# CLAUDE.md — the brain of `menqstudio/OS` · `menqstudio/OS`-ի ուղեղը

**Read this first. Every new session (AI or human) starts here.**
**Կարդա սա առաջինը։ Ամեն նոր session (AI թե մարդ) սկսում ա այստեղից։**

[English](#english) · [Հայերեն](#հայերեն)

</div>

---

## ⛔ STARTUP LAW — mandatory, every session · ՊԱՐՏԱԴԻՐ, ամեն session

**Before doing ANYTHING** (any tool call, any edit, any answer beyond a greeting), every chat — Claude *and* ChatGPT — must:

1. **`git pull`** — get the latest state.
2. **Read, IN FULL, every file in [`START_HERE.md`](./START_HERE.md):** `CLAUDE.md` → `PROJECT_STATE.md` → `TASKS.md` → `OWNERS.md` → `docs/ARCHITECTURE.md`.
3. **Claim your task in `TASKS.md`** — never two agents on the same task.

Only then start. **No exceptions.** When Gev says *"go read the repo / կարդա ՄԴները"* — that phrase **is** this law: read every file in `START_HERE.md` fully, pull, claim a task, then begin, **without waiting for any further explanation.**

**Ամեն բան անելուց ԱՌԱՋ** (ցանկացած tool/edit/պատասխան), ամեն չատ — Claude *ու* ChatGPT — պիտի՝
**1)** `git pull` · **2)** կարդա ԱՄԲՈՂՋՈՎ [`START_HERE.md`](./START_HERE.md)-ի բոլոր ֆայլերը (`CLAUDE.md` → `PROJECT_STATE.md` → `TASKS.md` → `OWNERS.md` → `docs/ARCHITECTURE.md`) · **3)** claim արա task-ը `TASKS.md`-ում։ Միայն հետո սկսի։ **Բացառություն չկա։** Երբ Gev-ը ասում ա *«գնա ռեպո կարդա ՄԴները»* — էդ բառը **հենց** այս օրենքն ա՝ կարդա `START_HERE.md`-ի ամեն ֆայլ ամբողջովին, pull արա, task claim արա, հետո սկսի, **առանց ավել բացատրություն սպասելու։**

**Roles · Դերեր:** [`OWNERS.md`](./OWNERS.md) — 👑 Gev = Owner · 📐 ChatGPT = Architect/Auditor · 🔨 Claude = Builder.
**Canonical files (read every session) · Canonical ֆայլեր:** `CLAUDE.md` · `PROJECT_STATE.md` · `TASKS.md` · `OWNERS.md`.
**Work rule:** no direct `main`; every task = branch + PR (uses the PR template); merge only after the Owner approves.

---

# English

> This file is the single source of truth for what this repo *is*, where it stands, how to
> work in it, and the rules that keep it safe. **When state changes, update this file in the
> same commit** — a stale brain is worse than none.

## 1. What OS is

**OS** is one product assembled from two halves:

- 🧠 **`engine/`** — the **governance brain** (Python), vendored from [`menqstudio/Bro`](https://github.com/menqstudio/Bro). A security harness that safely runs AI agents behind an *enforcement wall*: Ed25519-signed execution leases, approval gates, an append-only evidence chain, a protected control plane, and a fail-closed hook that governs every tool call.
- 🖥️ **`apps/desktop/`** — the **human-facing cockpit** (Tauri: React/TypeScript frontend + Rust backend + SQLite core), vendored from [`menqstudio/BroPS`](https://github.com/menqstudio/BroPS). Conversations, runs, approvals, files, calendar, knowledge — what the owner actually opens.

**The thesis (why we merge them):** the cockpit is the only surface a person touches, and **every AI action it triggers must flow through the engine's wall** — `lease → gate → sandbox → signed receipt`. There must be **no direct, ungoverned model execution**. The result is one safe, coherent product instead of two loose pieces: a beautiful desktop app whose every agent action is contained by an audited security engine underneath.

**Owner:** Gev (`menqstudio`, ohanyan.88@gmail.com). He speaks Armenian — **reply in Armenian by default**; use English only for code, identifiers, and commands. Keep "ընգեր/ախպեր" friendly but not every sentence. 😄

## 2. Repository map

```
OS/
├── CLAUDE.md            ← THIS brain (read first)
├── AGENTS.md            pointer to CLAUDE.md
├── README.md            public intro (bilingual EN/HY, mermaid flow diagram)
├── docs/ARCHITECTURE.md design + resolved decisions (bilingual)
├── apps/desktop/        🖥️  cockpit — BroPS (Tauri app); git subtree, history preserved
├── engine/             🧠  engine — Bro (Python harness); git subtree, history preserved
├── bridge/             🔗  Phase-1 integration layer (placeholder README only today)
├── contracts/          📜  Phase-3 shared schemas (placeholder README only today)
└── .github/workflows/  ✅  unified CI: cockpit-frontend · cockpit-core · engine
```

Both halves arrived **already audited and fixed** (see §6). They were brought in with `git subtree` so their full commit history is preserved (`git log` still tells each half's story). Provenance: `engine/` from Bro `main`; `apps/desktop/` from BroPS `main` (PR #25 merged).

## 3. Roadmap — where we are

| Phase | Goal | Status |
|-------|------|--------|
| **0 — Scaffold** | monorepo assembled · bilingual docs · unified CI · history preserved | ✅ **DONE** |
| **1 — Bridge** | route the desktop's AI execution through the engine's supervisor/lease/wall — replace the direct `claude` spawn in `apps/desktop/src-tauri/src/ai.rs` with a governed call | ⏳ not started |
| **2 — One approval gate** | the desktop defers to the engine's Ed25519 approval/lease system; a single authoritative gate instead of two | ⏳ not started |
| **3 — Contracts** | dedupe the shared schemas (execution-lease · approval · task-contract · mode-grant) into `contracts/` as one source of truth | ⏳ not started |

### ⚠️ OPEN DECISION — blocks a fully-green CI

The engine CI leg fails **9 of ~615 tests** in the monorepo. **Root cause:** Bro's security perimeter assumes `ROOT` **is a git worktree root**, but a subtree makes `engine/` a plain subdirectory (the git top-level is `OS/`). The failing check lives in `engine/runtime/bro_repository_state.py` (`worktrees()` → *"runtime root is not a registered Git worktree"*). The other ~606 tests pass. This is an **architecture fork**, and it **touches freshly-audited security code**, so it must not be rushed. Options:

- **A · Submodule** — vendor `engine/` (and `apps/desktop/`) as git submodules → Bro's worktree assumption stays intact (safest; engine untouched), but the "one repo" feel weakens (clone `--recursive`, 2-step updates).
- **B · Make Bro monorepo-aware** — allow `ROOT` to be a subdirectory of a registered worktree → true one-repo, but a deliberate, tested change to security code we just audited.
- **C · Scope Phase-0 CI now** — run the ~606 independent tests, mark the 9 as documented Phase-1-deferred → honest green now; validate the full enforcement path after A/B is chosen.

**Decision (standing):** **Option 1 — stay on subtree + C.** The engine CI leg is green; the 9 monorepo-coupled tests (`FullExecutionTransactionE2ETests`, `HookSubprocessTests`) skip-guard themselves when `engine/` is not a git checkout root. No runtime/security code touched — only test guards. Stability over architecture for now.

**Verified finding (why not A alone):** making `engine/` a submodule does **not** fix the 9 tests — `git worktree list` reports a submodule's *git-dir* (`.git/modules/engine`), not its working dir (`engine/`), so Bro's `bro_repository_state.worktrees()` check still fails. A true native fix needs **Option 2**: engine as a submodule **plus** a targeted change to Bro's worktree check (use `git rev-parse --show-toplevel` instead of parsing `git worktree list`). That touches security-adjacent code and is deferred to a **separate audited task** (own branch/PR, Owner approval, must not destabilize). **Do not implement it inside a coordination/Phase-0 merge.**

## 4. How to work here — verify commands

Each half still builds independently in Phase 0. **Run each from the component's directory.**

```bash
# Cockpit — frontend (Node)
cd apps/desktop && npm ci && npm run build        # tsc --noEmit + vite build

# Cockpit — Rust data core + app   ⚠️ RUN FROM PowerShell, NOT the Bash tool (see §5)
cargo test  -p brops-core --manifest-path apps/desktop/src-tauri/core/Cargo.toml   # 29 tests
cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml                       # app crate

# Engine — Python governance runtime  (MUST set BRO_ENV=ci)
cd engine && BRO_ENV=ci python -m unittest discover -s tests   # ~615 tests, ~16 Windows platform-skips
```

## 5. Environment gotchas (this is a Windows box) — READ BEFORE RUNNING TOOLS

- **`cargo` MUST run from PowerShell, never the Bash tool.** The Bash tool is Git Bash, whose coreutils `link` shadows the MSVC `link.exe`; every cargo build then fails with a bogus *"extra operand"* linker error. PowerShell has no such shadow. MSVC C++ Build Tools (VCTools workload) are installed.
- **Engine tests need `BRO_ENV=ci`** — without it the operator-pin gating (an M-1 hardening) denies, and many tests error rather than run.
- **The permission classifier BLOCKS `git push` and `gh pr merge` for the AI.** The model prepares commits locally and hands Gev the exact command; **Gev runs push / merge / PR himself.** Never try to work around this.
- **Commit identity:** `user.name "menqstudio"`, `user.email "ohanyan.88@gmail.com"`. End every commit message with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **Enforcement-hook wedge:** `engine/` (Bro) ships `.claude/settings.json` hooks (`bro_hook.py`). On Windows they can crash with a cp1252 `UnicodeEncodeError` and **fail-closed-cascade the entire session** — this genuinely happened and froze every tool. If a session wedges: set `PYTHONUTF8=1` and relaunch, or disable the hooks (rename `settings.json`). The OS **root** has no `.claude/settings.json` yet, so opening OS at the root does not activate them (hooks load only from the repo root, not nested `engine/`).
- **GitHub Actions:** billing was failing (jobs wouldn't start — a red account flag, unrelated to code); resolved. Public repos get free runners. CI triggers on push→`main` and on `pull_request`; a feature-branch push alone does **not** run CI until a PR exists. A merge-conflicted (`DIRTY`) PR also won't run checks until the conflict is pushed-resolved.
- **Toolchain present:** cargo 1.96, node 24, npm 11, python 3.13, Pillow. The Tauri Windows build needs `icons/icon.ico` (already generated for the cockpit).

## 6. Security discipline & provenance

Both halves were audited (multi-agent) and fixed before landing here.

- **Engine (Bro):** 1 Critical (`find`/read-only-shell scope bypass → RCE), 6 High, 9 Medium, 13 Low — all fixed; PR merged. The crypto core (leases, contracts, protected-authority, evidence) was verified sound. **Still residual-exploitable / deferred** (tracked on Bro's `fix/audit-followups`; do **not** rush — wall / owner-env coupled):
  - **O-1 (HIGH)** bytecode-shadow — `assert_no_bytecode_shadow` has no caller and the wall isn't run with `-B`; a forged `.pyc` can shadow the control-plane digest.
  - **O-2 (MED)** audit-head anchor is dead code (no producer; `verify()` gets no keys) → `.head` forgery still open.
  - **O-3 (MED)** conductor session token is wired but off by default (an owner-env deploy step enables it).
  - **O-4 / O-5 (LOW)** control-room actor self-asserted; evidence high-water not bound into the signed manifest.
- **Cockpit (BroPS):** 1 High (non-atomic migration could brick the DB), 8 Medium, 18 Low — all fixed; verified (core `cargo test` 29/29, `cargo check` clean, `npm run build` green); PR merged.

**Golden rule:** the engine is a *security perimeter*. Any change to its wall, leases, gates, signatures, control-plane, or root model is **deliberate, tested, and never rushed.** When two paths exist, prefer the one that leaves audited security code untouched.

## 7. Rules for AI sessions

1. **Do not start execution without Gev's explicit go** ("սկսի" / "start"). He often front-loads context across several messages first — *collect, don't act.*
2. **You cannot push or merge** — hand Gev the exact command and let him run it.
3. **Verify before claiming green** — run the real test/build from the correct shell (§4–§5); never assume.
4. **When you fan out sub-agents, assign disjoint files** to avoid write conflicts, then reconcile the cross-file seams yourself and verify.
5. **Keep this file current** — if you change state, land the edit in `CLAUDE.md` in the same commit.
6. Reply in Armenian; keep "ընգեր/ախպեր" light. 😄

---

# Հայերեն

> Այս ֆայլը միակ ճշմարտության աղբյուրն ա՝ ինչ ա այս repo-ն, որտեղ ա կանգնած, ոնց աշխատել դրանում,
> ու ինչ կանոններ պահել որ անվտանգ մնա։ **Երբ վիճակը փոխվի՝ թարմացրու այս ֆայլը նույն commit-ում** —
> հնացած ուղեղը վատ ա, քան ուղեղ չունենալը։

## 1. Ի՞նչ ա OS-ը

**OS**-ը մեկ product ա՝ հավաքված երկու կեսից․

- 🧠 **`engine/`** — կառավարման **ուղեղը** (Python), բերված [`menqstudio/Bro`](https://github.com/menqstudio/Bro)-ից։ Security harness, որ **անվտանգ վազեցնում ա AI agent-ներին** *enforcement wall*-ի հետևում՝ Ed25519-signed execution lease-եր, approval gate-եր, append-only evidence chain, protected control plane, ու fail-closed hook, որ govern ա անում ամեն tool call։
- 🖥️ **`apps/desktop/`** — մարդուն ուղղված **cockpit-ը** (Tauri՝ React/TypeScript frontend + Rust backend + SQLite core), բերված [`menqstudio/BroPS`](https://github.com/menqstudio/BroPS)-ից։ Conversations, runs, approvals, files, calendar, knowledge — էն, ինչ owner-ը իրական բացում ա։

**Իմաստը (ինչու ենք միացնում)․** cockpit-ն ա միակ surface-ը, որ մարդ դիպչում ա, ու **նրա trigger արած ամեն AI action պիտի անցնի engine-ի wall-ով** — `lease → gate → sandbox → signed receipt`։ **Ոչ մի ուղիղ, չկառավարվող model execution չպիտի լինի**։ Արդյունքը՝ մեկ անվտանգ, ամբողջական product երկու առանձին կտորի փոխարեն՝ գեղեցիկ desktop app, որի ամեն agent-action-ը զսպված ա ներքևի audited security engine-ով։

**Owner:** Gev (`menqstudio`, ohanyan.88@gmail.com)։ Խոսում ա հայերեն — **default-ով պատասխանիր հայերեն**; անգլերեն՝ միայն կոդի, identifier-ների ու կոմանդների համար։ «ընգեր/ախպեր»-ը ընկերական, բայց ոչ ամեն նախադասության մեջ։ 😄

## 2. Repo-ի քարտեզը

```
OS/
├── CLAUDE.md            ← ԱՅՍ ուղեղը (կարդա առաջինը)
├── AGENTS.md            pointer դեպի CLAUDE.md
├── README.md            public intro (երկլեզու EN/HY, mermaid flow diagram)
├── docs/ARCHITECTURE.md design + լուծված որոշումներ (երկլեզու)
├── apps/desktop/        🖥️  cockpit — BroPS (Tauri app); git subtree, history պահած
├── engine/             🧠  engine — Bro (Python harness); git subtree, history պահած
├── bridge/             🔗  Phase-1 ինտեգրման շերտ (հիմա միայն placeholder README)
├── contracts/          📜  Phase-3 shared schemas (հիմա միայն placeholder README)
└── .github/workflows/  ✅  միասնական CI՝ cockpit-frontend · cockpit-core · engine
```

Երկու կեսն էլ եկան **արդեն audited ու fixed** (տես §6)։ Բերվել են `git subtree`-ով, որ ամբողջ commit history-ն պահված լինի (`git log`-ը դեռ պատմում ա ամեն կեսի պատմությունը)։ Ծագում՝ `engine/`՝ Bro `main`-ից; `apps/desktop/`՝ BroPS `main`-ից (PR #25 merged)։

## 3. Roadmap — որտեղ ենք

| Phase | Նպատակ | Վիճակ |
|-------|--------|-------|
| **0 — Scaffold** | monorepo հավաքված · երկլեզու docs · միասնական CI · history պահած | ✅ **DONE** |
| **1 — Bridge** | desktop-ի AI execution-ը անցկացնել engine-ի supervisor/lease/wall-ով — `apps/desktop/src-tauri/src/ai.rs`-ի ուղիղ `claude` spawn-ը փոխարինել governed call-ով | ⏳ չսկսած |
| **2 — Մեկ approval gate** | desktop-ը defer ա անում engine-ի Ed25519 approval/lease համակարգին; մեկ authoritative gate երկուսի փոխարեն | ⏳ չսկսած |
| **3 — Contracts** | shared schema-ները (execution-lease · approval · task-contract · mode-grant) dedupe անել `contracts/`-ում՝ single source of truth | ⏳ չսկսած |

### ⚠️ ԲԱՑ ՈՐՈՇՈՒՄ — блокирует fully-green CI

Engine CI leg-ը **~615-ից 9 test fail ա** monorepo-ում։ **Root cause:** Bro-ի security perimeter-ը ենթադրում ա որ `ROOT`-ը **git worktree root ա**, բայց subtree-ն `engine/`-ը դարձնում ա պարզ subdirectory (git top-level-ը `OS/` ա)։ Fail-վող check-ը `engine/runtime/bro_repository_state.py`-ում ա (`worktrees()` → *"runtime root is not a registered Git worktree"*)։ Մնացած ~606-ը pass են։ Սա **architecture fork ա**, ու **touch ա անում նոր-audited security կոդը**, ուրեմն չպիտի rush արվի։ Տարբերակներ․

- **A · Submodule** — `engine/`-ը (ու `apps/desktop/`-ը) submodule → Bro-ի worktree-assumption-ը անփոփոխ (ամենաանվտանգ; engine-ին ձեռք չենք տա), բայց «one repo» feeling-ը թուլանում ա (clone `--recursive`, 2-քայլ update)։
- **B · Bro-ն monorepo-aware դարձնել** — `ROOT`-ը թույլ տալ որ լինի registered worktree-ի subdirectory → իսկական one-repo, բայց deliberate, tested փոփոխություն հենց նոր-audited security կոդում։
- **C · Phase-0 CI scope** — հիմա run ~606-ը, 9-ը documented Phase-1-deferred → honest green հիմա; լրիվ enforcement path-ը validate ա A/B-ի ընտրությունից հետո։

**Որոշում (գործող):** **Option 1 — մնում ենք subtree + C-ի վրա։** Engine CI leg-ը green ա; 9 monorepo-coupled test-երը (`FullExecutionTransactionE2ETests`, `HookSubprocessTests`) ինքնաբերաբար skip են, երբ `engine/`-ը git checkout root չէ։ Ոչ մի runtime/security կոդ չի դիպչել — միայն test guard-եր։ Հիմա կայունությունը architecture-ից առաջ։

**Verified finding (ինչու ոչ A-ն միայնակ):** `engine/`-ը submodule դարձնելը **չի** ֆիքսում 9 test-ը — `git worktree list`-ը submodule-ի *git-dir-ն* ա վերադարձնում (`.git/modules/engine`), ոչ working dir-ը (`engine/`), ուրեմն Bro-ի `bro_repository_state.worktrees()` check-ը դեռ fail ա։ Իսկական native fix-ը պահանջում ա **Option 2**՝ engine submodule **+** targeted փոփոխություն Bro-ի worktree-check-ում (`git rev-parse --show-toplevel`՝ `git worktree list`-ի փոխարեն)։ Դա touch ա security-adjacent կոդ ու հետաձգված ա **առանձին audited task**-ի (own branch/PR, Owner approval, չդեստաբիլիզացնի)։ **Մի իրականացրու coordination/Phase-0 merge-ի ներսում։**

## 4. Ոնց աշխատել այստեղ — verify կոմանդներ

Ամեն կես դեռ independently build ա Phase 0-ում։ **Ամեն մեկը run արա component-ի directory-ից։**

```bash
# Cockpit — frontend (Node)
cd apps/desktop && npm ci && npm run build        # tsc --noEmit + vite build

# Cockpit — Rust data core + app   ⚠️ RUN PowerShell-ից, ՈՉ Bash tool-ից (տես §5)
cargo test  -p brops-core --manifest-path apps/desktop/src-tauri/core/Cargo.toml   # 29 test
cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml                       # app crate

# Engine — Python governance runtime  (ՊԱՐՏԱԴԻՐ՝ BRO_ENV=ci)
cd engine && BRO_ENV=ci python -m unittest discover -s tests   # ~615 test, ~16 Windows platform-skip
```

## 5. Environment gotchas (սա Windows մեքենա ա) — ԿԱՐԴԱ TOOL ՎԱԶԵՑՆԵԼՈՒՑ ԱՌԱՋ

- **`cargo`-ն ՊԱՐՏԱԴԻՐ PowerShell-ից, երբեք Bash tool-ից։** Bash tool-ը Git Bash ա, որի coreutils `link`-ը shadow ա անում MSVC `link.exe`-ը; ամեն cargo build հետո fail ա անում կեղծ *"extra operand"* linker error-ով։ PowerShell-ում էդ shadow-ը չկա։ MSVC C++ Build Tools (VCTools) installed են։
- **Engine test-երը պահանջում են `BRO_ENV=ci`** — առանց դրա operator-pin gating-ը (M-1 hardening) deny ա անում, ու շատ test-եր error են, ոչ run։
- **Permission classifier-ը блокирует `git push` ու `gh pr merge` AI-ի համար։** Model-ը լոկալ commit ա պատրաստում ու Gev-ին տալիս ա հստак կոմանդը; **Gev-ն ա push / merge / PR անում ինքը։** Երբեք մի փորձիր շրջանցել։
- **Commit identity:** `user.name "menqstudio"`, `user.email "ohanyan.88@gmail.com"`։ Ամեն commit message-ի վերջում՝
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **Enforcement-hook wedge:** `engine/`-ը (Bro) ունի `.claude/settings.json` hooks (`bro_hook.py`)։ Windows-ում կարան crash անեն cp1252 `UnicodeEncodeError`-ով ու **fail-closed-cascade անեն ամբողջ session-ը** — սա իրական պատահել ա ու ամեն tool սառեցրել։ Եթե session wedge լինի՝ դիր `PYTHONUTF8=1` ու relaunch, կամ disable արա hooks-ը (`settings.json`-ը rename)։ OS-ի **root**-ում `.claude/settings.json` դեռ չկա, ուրեմն OS-ը root-ից բացելը դրանք չի активирует (hooks-ը բեռնվում են միայն repo root-ից, ոչ nested `engine/`-ից)։
- **GitHub Actions:** billing-ը fail էր (job-երը չէին ստարտում — account-level red flag, կոդի հետ կապ չուներ); լուծված ա։ Public repo-ները ձրի runner ունեն։ CI trigger՝ push→`main` ու `pull_request`; feature-branch-ի պարզ push-ը **չի** run անում CI մինչև PR-ը լինի։ Merge-conflict (`DIRTY`) PR-ն էլ check չի run անում մինչև conflict-ը push-լուծված լինի։
- **Toolchain:** cargo 1.96, node 24, npm 11, python 3.13, Pillow։ Tauri Windows build-ը պահանջում ա `icons/icon.ico` (արդեն generate արված cockpit-ի համար)։

## 6. Security կարգապահություն ու provenance

Երկու կեսն էլ audit արվել (multi-agent) ու fix արվել են այստեղ գալուց առաջ։

- **Engine (Bro):** 1 Critical (`find`/read-only-shell scope bypass → RCE), 6 High, 9 Medium, 13 Low — բոլորը fixed; PR merged։ Crypto core-ը (leases, contracts, protected-authority, evidence) verified sound։ **Դեռ residual-exploitable / deferred** (Bro-ի `fix/audit-followups`-ում; **մի rush** — wall / owner-env coupled)․
  - **O-1 (HIGH)** bytecode-shadow — `assert_no_bytecode_shadow`-ը caller չունի ու wall-ը `-B`-ով չի վազում; forged `.pyc`-ն կարա shadow անի control-plane digest-ը։
  - **O-2 (MED)** audit-head anchor-ը dead code ա (producer չկա; `verify()`-ը keys չի ստանում) → `.head` forgery դեռ բաց ա։
  - **O-3 (MED)** conductor session token-ը wired ա, բայց off-by-default (owner-env deploy step-ով enable ա լինում)։
  - **O-4 / O-5 (LOW)** control-room actor self-asserted; evidence high-water-ը signed manifest-ում bound չէ։
- **Cockpit (BroPS):** 1 High (non-atomic migration-ը կարար DB-ն brick աներ), 8 Medium, 18 Low — բոլորը fixed; verified (core `cargo test` 29/29, `cargo check` clean, `npm run build` green); PR merged։

**Ոսկե կանոն:** engine-ը *security perimeter* ա։ Իր wall-ի, lease-ների, gate-ների, signature-ների, control-plane-ի, կամ root model-ի ցանկացած փոփոխություն **deliberate ա, tested, ու երբեք rush չի արվում**։ Երբ երկու ճանապարհ կա՝ ընտրիր էն, որ audited security կոդին ձեռք չի տալիս։

## 7. Կանոններ AI session-ների համար

1. **Մի սկսիր execution առանց Gev-ի հստակ go-ի** («սկսի» / «start»)։ Ինքը հաճախ մի քանի message-ով նախ context ա տալիս — *հավաքիր, մի գործիր*։
2. **Չես կարա push կամ merge անես** — տուր Gev-ին հստակ կոմանդը, ինքը կ‑run անի։
3. **Verify արա green ասելուց առաջ** — run արա իսկական test/build ճիշտ shell-ից (§4–§5); երբեք մի ենթադրի։
4. **Երբ sub-agent-ներ ես fan-out անում՝ բաժանիր disjoint ֆայլեր** որ write-conflict չլինի, հետո ինքդ reconcile արա cross-file seam-երը ու verify։
5. **Պահիր այս ֆայլը թարմ** — եթե վիճակ ես փոխում, edit-ը դիր `CLAUDE.md`-ում նույն commit-ում։
6. Պատասխանիր հայերեն; «ընգեր/ախպեր»-ը թեթև պահիր։ 😄

---

<div align="center"><sub>menqstudio · OS · governed by the wall 🧱 · կառավարվում ա wall-ով</sub></div>

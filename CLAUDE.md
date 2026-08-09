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
2. **Read, IN FULL, every file in [`START_HERE.md`](./START_HERE.md):** `NEXT_CHAT.md` (exact current branch/PR/HEAD/blockers) → `CLAUDE.md` → `PROJECT_STATE.md` → `TASKS.md` → `OWNERS.md` → `docs/ARCHITECTURE.md`. (Machine-readable read order: [`config/canonical-read-manifest.json`](./config/canonical-read-manifest.json).)
3. **Claim your task in `TASKS.md`** — never two agents on the same task.

Only then start. **No exceptions.** When Gev says *"go read the repo / կարդա ՄԴները"* — that phrase **is** this law: read every file in `START_HERE.md` fully, pull, claim a task, then begin, **without waiting for any further explanation.**

**Ամեն բան անելուց ԱՌԱՋ** (ցանկացած tool/edit/պատասխան), ամեն չատ — Claude *ու* ChatGPT — պիտի՝
**1)** `git pull` · **2)** կարդա ԱՄԲՈՂՋՈՎ [`START_HERE.md`](./START_HERE.md)-ի բոլոր ֆայլերը (`CLAUDE.md` → `PROJECT_STATE.md` → `TASKS.md` → `OWNERS.md` → `docs/ARCHITECTURE.md`) · **3)** claim արա task-ը `TASKS.md`-ում։ Միայն հետո սկսի։ **Բացառություն չկա։** Երբ Gev-ը ասում ա *«գնա ռեպո կարդա ՄԴները»* — էդ բառը **հենց** այս օրենքն ա՝ կարդա `START_HERE.md`-ի ամեն ֆայլ ամբողջովին, pull արա, task claim արա, հետո սկսի, **առանց ավել բացատրություն սպասելու։**

**Roles · Դերեր:** [`OWNERS.md`](./OWNERS.md) — 👑 Gev = Owner · 📐 ChatGPT = Architect/Auditor · 🔨 Claude = Builder.
**Canonical files (read every session) · Canonical ֆայլեր:** `NEXT_CHAT.md` · `CLAUDE.md` · `PROJECT_STATE.md` · `TASKS.md` · `OWNERS.md`.
**Work rule:** no direct `main`; every task = branch + PR (uses the PR template); merge only after the Owner approves. **A security PR also needs the Architect's zero-trust GREEN on the exact HEAD before merge — CI GREEN is not audit GREEN.**

> **📍 Exact current state (branch, PR, HEAD, blockers, next action) lives in [`NEXT_CHAT.md`](./NEXT_CHAT.md).** This §3 roadmap is the durable product plan; the active **security-remediation track** (Waves 1–5, closing the Challenger Deep audit's P0/P1 findings) is tracked in `NEXT_CHAT.md` + `PROJECT_STATE.md` + `TASKS.md`. As of 2026-08-02: Wave 1 (T-012), Wave 2a (T-013), T-010, T-011 **merged**; Wave 3 design **GREEN + merged**; **Wave 3a is COMPLETE** — slice 1 (T-014, PR #24 `6c920d0`), slice 2 (T-015, PR #26 `9b214e5`, migration 0014), slice 3 (T-016, PR #28 `8a580028`) all zero-trust GREEN + merged. **Wave 3b-0** isolated-signer design merged via **PR #30** (`df3c0ac`). **Active track is now Wave 3b (T-017), consolidated on `feat/cockpit-pages` / PR #48** (base `chore/main-resync`, head `38d5d715…`; supersedes the earlier PR #46 impl / PR #31 design / PR #32 impl split): the **3b-1B design is Architect DESIGN GREEN at rev-30** (design-GREEN ≠ code-GREEN); the implementation + live-proof kit are built and the full 7-service production governed turn is **proven live on Linux** (first `trusted_verified`); the external **Architect CODE-audit is still pending**, and the **shipped desktop "Verified" stays fail-closed**. Exact live state: [`NEXT_CHAT.md`](./NEXT_CHAT.md) + [`config/current_state.json`](./config/current_state.json).

---

## ⛔ CONTINUOUS-DOCUMENTATION LAW — mandatory, every work cycle · ՊԱՐՏԱԴԻՐ

**After EVERY substantive** design change, code change, audit verdict, HEAD change, blocker discovery/closure, status transition, or merge, you MUST — **in the same work cycle** — update **all** affected canonical documents, commit, push, and update the PR body. **No required continuation state may live only in chat, GPT chat, memory, a scratchpad, or an unpushed commit.**

At every moment the repository must be sufficient for a brand-new Claude/GPT session told only *"Go to `menqstudio/OS`, read `NEXT_CHAT.md` and every file in `config/canonical-read-manifest.json`, verify the exact GitHub HEAD/CI, and continue"* — and then continue correctly **from GitHub alone**, without asking Gev to repeat history. This is **continuous**, not a one-time cleanup; do not create a disconnected documentation graveyard — update the authoritative existing files. One file is the **single normative source** per subsystem (e.g. the 3b-1B contracts live only in `docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`); other files reference it and must not re-inline schemas that can drift. Revision history is a **non-normative appendix** — historical prose never redefines a current contract.

**CI is NOT a doc-commit trigger (avoid the commit→CI→doc-commit→CI loop):** **GitHub Checks/Actions is the authoritative current-exact-head CI source.** A **substantive** commit updates canonical docs *before* push; after its CI completes, update the **PR body / status text without changing HEAD** when practical — **do NOT create a new commit solely to change a CI run number**. Canonical docs instruct new sessions to **query GitHub for the current HEAD's real CI** rather than trusting a hardcoded run number; a later substantive commit naturally records the previously-reviewed run as historical evidence. **CI GREEN ≠ design/audit GREEN** remains mandatory (only an Architect verdict on the exact HEAD is GREEN).

**Each substantive cycle:** (1) update at least `NEXT_CHAT.md` (§3 = authoritative current state), `PROJECT_STATE.md`, `TASKS.md`, the relevant `docs/design/*` (banner + changelog), this `CLAUDE.md` where the law/roadmap state belongs, the PR body, and any other roadmap/status/handoff doc holding the changed fact (manifest only if the startup read-set changes); (2) record exact HEAD, the reviewed CI run + result, current revision, verdict, OPEN findings, next permitted action, STOP gates; (3) run `python tools/check_coordination.py` + `python tools/check_capabilities.py` (both GREEN) and verify manifest paths exist; (4) commit, **push**, `gh pr edit <n> --body-file …`, and confirm the remote HEAD.

**Design docs:** one file is the single normative source per subsystem (e.g. the 3b-1B contracts live only in `docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`); other files reference it and must not re-inline schemas that can drift. Revision history is a **non-normative appendix** — historical prose never redefines a current contract.


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

> **The canonical execution plan is [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md)**
> (status `v1.0 · Canonical Execution Authority` — 🔒 **Locked** (Owner-approved 2026-07-21, basis HEAD
> `2e0157b`); product content is change-controlled per its §I). It expands the product into **11 phases** with
> per-phase Objective / Scope / Architecture / UI-UX / Backend / Contracts / Data models / Dependencies /
> Security gates / Tests / CI / Docs / Acceptance / Merge gate / Stop conditions / Definition of Done,
> and per-page UI specs from the canonical prototype `brops-aios.html`. A cold-start session takes the
> next **unchecked** task there. This table is the summary; the roadmap is the source.
>
> The earlier 4-step framing (Scaffold · Bridge · One approval gate · Contracts) is **superseded** by the
> 11-phase plan: *One approval gate* is now Phase 2 (Governance Sidecar); *Contracts dedupe* begins in
> Phase 3 and is finalized in Phase 10.

| Phase | Goal | Status |
|-------|------|--------|
| **0 — Foundation** | monorepo assembled · bilingual docs · unified CI · history preserved | ✅ **DONE (locked)** |
| **1 — Bridge** | route desktop AI exec through the engine supervisor/lease/wall (replace direct `claude` spawn in `ai.rs`) | 🔨 **In progress** — slice 1 **merged** (PR #3, `5be8d95`, 10/10) + slice 2 **transport** merged (PR #8: `Provider::GovernedEngine` opt-in · receipt badge · Settings toggle); verify-seam · receipt-plumbing · streaming · real e2e open |
| **2 — Governance Sidecar** | cockpit surfaces for approvals · decisions · evidence chain · signals (mirror, never decide) | ⏳ ready (P1 contract exists) |
| **3 — Desktop Integration** | app shell + `home`/`chat`(governed)/`settings`; wire the core loop | ⏳ blocked on P1+P2 |
| **4 — UI/UX System** | component library + theming + motion + a11y; `activity`/`analytics`/`library` | ⏳ blocked on P3 |
| **5 — Memory & Knowledge** | `memory`/`knowledge`/`research`(governed)/`files` | ⏳ blocked on P3 |
| **6 — Multi-Agent** | `agents`/`command`/`tasks`/`projects`; governed pack dispatch | ⏳ blocked on P4+P5 |
| **7 — Group Chat** | `group` collaboration hall; per-agent governed turns | ⏳ blocked on P6 |
| **8 — Automation** | `automations`/`calendar`; governed scheduled runs | ⏳ blocked on P4+P5 |
| **9 — Integrations** | `integrations`; governed inbound/outbound, no desktop secrets | ⏳ blocked on P7+P8 |
| **10 — Production** | signed/updatable build; full enforcement-path CI (retire option-C skips via T-005); `contracts/` dedupe; close O-1..O-5 | ⏳ blocked on P9 |

### ⚠️ OPEN DECISION — blocks a fully-green CI

**History, and resolved — see the standing decision below.** The engine CI leg used to fail **9 tests** in the monorepo. **Root cause:** Bro's security perimeter assumes `ROOT` **is a git worktree root**, but a subtree makes `engine/` a plain subdirectory (the git top-level is `OS/`). The failing check lives in `engine/runtime/bro_repository_state.py` (`worktrees()` → *"runtime root is not a registered Git worktree"*). Everything else passed. (Measured 2026-08-09 from this monorepo root: `1282 tests, OK (skipped=43)` on Windows — the 9 now skip-guard themselves, per the decision below.) This is an **architecture fork**, and it **touches freshly-audited security code**, so it must not be rushed. Options:

- **A · Submodule** — vendor `engine/` (and `apps/desktop/`) as git submodules → Bro's worktree assumption stays intact (safest; engine untouched), but the "one repo" feel weakens (clone `--recursive`, 2-step updates).
- **B · Make Bro monorepo-aware** — allow `ROOT` to be a subdirectory of a registered worktree → true one-repo, but a deliberate, tested change to security code we just audited.
- **C · Scope Phase-0 CI now** — run the independent tests, mark the 9 as documented Phase-1-deferred → honest green now; validate the full enforcement path after A/B is chosen.

**Decision (standing):** **Option 1 — stay on subtree + C.** The engine CI leg is green; the 9 monorepo-coupled tests (`FullExecutionTransactionE2ETests`, `HookSubprocessTests`) skip-guard themselves when `engine/` is not a git checkout root. No runtime/security code touched — only test guards. Stability over architecture for now.

**Verified finding (why not A alone):** making `engine/` a submodule does **not** fix the 9 tests — `git worktree list` reports a submodule's *git-dir* (`.git/modules/engine`), not its working dir (`engine/`), so Bro's `bro_repository_state.worktrees()` check still fails. A true native fix needs **Option 2**: engine as a submodule **plus** a targeted change to Bro's worktree check (use `git rev-parse --show-toplevel` instead of parsing `git worktree list`). That touches security-adjacent code and is deferred to a **separate audited task** (own branch/PR, Owner approval, must not destabilize). **Do not implement it inside a coordination/Phase-0 merge.**

## 4. How to work here — verify commands

Each half still builds independently in Phase 0. **Run each from the component's directory.**

```bash
# Cockpit — frontend (Node)
cd apps/desktop && npm ci && npm run build        # tsc --noEmit + vite build

# Cockpit — Rust data core + app   ⚠️ RUN FROM PowerShell, NOT the Bash tool (see §5)
cargo test  -p brops-core --manifest-path apps/desktop/src-tauri/core/Cargo.toml   # 297 `#[test]` fns in core/src (grows per security slice)
cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml                       # app crate

# Engine — Python governance runtime  (MUST set BRO_ENV=ci)
cd engine && BRO_ENV=ci python -m unittest discover -s tests   # 1282 tests, 43 skips on Windows (measured 2026-08-09)
```

## 5. Environment gotchas (this is a Windows box) — READ BEFORE RUNNING TOOLS

- **`cargo` MUST run from PowerShell, never the Bash tool.** The Bash tool is Git Bash, whose coreutils `link` shadows the MSVC `link.exe`; every cargo build then fails with a bogus *"extra operand"* linker error. PowerShell has no such shadow. MSVC C++ Build Tools (VCTools workload) are installed.
- **Engine tests need `BRO_ENV=ci`** — without it the operator-pin gating (an M-1 hardening) denies, and many tests error rather than run.
- **The permission classifier BLOCKS `git push` and `gh pr merge` for the AI.** The model prepares commits locally and hands Gev the exact command; **Gev runs push / merge / PR himself.** Never try to work around this.
- **Commit identity:** `user.name "menqstudio"`, `user.email "ohanyan.88@gmail.com"`. End every commit message with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **Enforcement-hook wedge:** `engine/` (Bro) ships `.claude/settings.json` hooks (`bro_hook.py`). On Windows they can crash with a cp1252 `UnicodeEncodeError` and **fail-closed-cascade the entire session** — this genuinely happened and froze every tool. If a session wedges: set `PYTHONUTF8=1` and relaunch, or disable the hooks (rename `settings.json`). Opening OS at the root does **not** activate the wall — hooks load from the repo root only, not from a nested `engine/`. The OS root *does* now have its own `.claude/settings.json`, but it is **not** the wall: it wires exactly one `Stop` hook, `.claude/hooks/coordination_stop_guard.py`, which checks coordination-document consistency. The wall is `engine/.claude/settings.json`, nine events (`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `SubagentStart`, `SubagentStop`, `Stop`, `InstructionsLoaded`).
- **GitHub Actions:** billing was failing (jobs wouldn't start — a red account flag, unrelated to code); resolved. Public repos get free runners. CI triggers on push→`main` and on `pull_request`; a feature-branch push alone does **not** run CI until a PR exists. A merge-conflicted (`DIRTY`) PR also won't run checks until the conflict is pushed-resolved.
- **Toolchain present:** cargo 1.96, node 24, npm 11, python 3.13, Pillow. The Tauri Windows build needs `icons/icon.ico` (already generated for the cockpit).

## 6. Security discipline & provenance

Both halves were audited (multi-agent) and fixed before landing here.

- **Engine (Bro):** 1 Critical (`find`/read-only-shell scope bypass → RCE), 6 High, 9 Medium, 13 Low — all fixed; PR merged. The crypto core (leases, contracts, protected-authority, evidence) was verified sound. **Still residual-exploitable / deferred** — do **not** rush; these are wall / owner-env coupled. The full inventory, with what each requires and which engine path it lives in, is [`docs/PHASE_10_PRODUCTION_ITEMS.md`](./docs/PHASE_10_PRODUCTION_ITEMS.md), and the engine tracks them under its own IDs in `engine/AUDIT/tickets/` — the `O-n` numbering is this repository's and appears nowhere in `engine/`.
  *(An earlier revision of this line said these are "tracked on Bro's `fix/audit-followups`". That ref exists neither locally nor on any remote branch, so the pointer was unbacked; corrected 2026-08-08.)*
  **All five remain OPEN** in that inventory, which is the status of record. What is *no longer* true is the shape of the blocker: **three of them used to wait on an artifact only Gev could mint, and none of them does now.** First-launch provisioning (`apps/desktop/src-tauri/provision/`) mints every authority key, signs the trusted-key registry, mints the `conductor-session`, destroys the operator root, and retains the delegated `control-room` and `evidence-floor` keys. What is left is deployment wiring and one second principal:
  - **O-1 (HIGH)** bytecode-shadow — `assert_no_bytecode_shadow` has real callers (`bro_control_plane.py:80` and `:271`, plus `bro_protected.verify_control_plane_digest`) and every hook interpreter runs `-B`; the reachability gate defends those call sites. **The read half is not closeable from inside Python:** `-B` stops bytecode being *written*, nothing stops CPython *reading* an existing `.pyc`, and a cache forged before the process starts shadows the very module that would detect it. The compensating rule is that the engine refuses a control plane the running account can write into — which a packaged install gives for free, and which needs verifying on a packaged build rather than asserting.
  - **O-2 (MED)** audit-head anchor — **not dead code:** `append()` is the in-band producer (it assembles the payload, signs it through `BRO_AUDIT_ANCHOR_SIGNER` inside the append lock, and installs it) and keyed `verify()` *requires* an anchor, raising `AuditAnchorMissing` without one. `head_anchor_payload`/`attach_head_anchor` stay caller-less on purpose — they are the out-of-band owner half. **Needs a signer principal the ledger's own writer cannot become.** On Windows that principal is built (`brops-audit-signer` service + `brops-anchor-relay` shim over the peer-authenticated pipe) but is **in no installer** and `register::apply` has no entry point outside tests; on POSIX it is specified and has never run.
  - **O-3 (MED)** conductor session token — fail-closed *and set*: `require_conductor_session_token` is `true` in `engine/.bro/policy.json`, an absent key / wrong type / unreadable policy all mean REQUIRED, and provisioning mints the `conductor-session` artifact. **No Owner artifact is needed.** What is left is one line in the app's startup: exporting `Provisioned::engine_env()` plus `BRO_TRUSTED_REGISTRY_ROOT`, which today nothing does — so the engine still reads the committed *development* registry.
  - **O-4 (LOW)** control-room actor — no longer self-asserted. `_prove_command_actor` routes by actor: a `bro` command presents the operator-signed `conductor-session`; an **owner** command must present a `control-room-command` artifact bound to this exact `command_id`/`task_id`/`command`. The type is registered in `ARTIFACT_AUTHORITY` under the delegated `control-room` authority and **`schemas/control-room-command.schema.json` does carry `artifact_type` / `key_id` / `signature`** — an earlier revision of this line said it did not. Provisioning retains the key and `mint_control_room_command` signs one, so **no Owner artifact is needed**; the *committed* registry still pins no key for the type, which the same registry-root wiring as O-3 closes.
  - **O-5 (LOW)** evidence high-water — the head digest and sequence are required and travel into a hash-chained record in a different store, so a rollback is visible from signed bytes after the evidence store is wiped. `mint_floor_anchor` signs the `evidence-floor-anchor` with the retained delegated key, so **no Owner artifact is needed**. It is deliberately **not** minted at install: no task exists yet, and an anchor produced by reading the very store the check polices would restate that store's claim under a signature — worse than none, because it reads as corroboration.
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

> **Կանոնական կատարման պլանը՝ [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md)**
> (կարգավիճակ՝ `v1.0 · Canonical Execution Authority` — 🔒 **Locked** (Owner-approved 2026-07-21, basis
> HEAD `2e0157b`); product content-ը change-controlled ա ըստ §I-ի)։ Ընդլայնում է product-ը **11 phase**-ի՝ ամեն
> phase-ի Objective/Scope/Architecture/UI-UX/Backend/Contracts/Data models/Dependencies/Security gates/
> Tests/CI/Docs/Acceptance/Merge gate/Stop conditions/Definition of Done-ով, ու էջ-առ-էջ UI spec-երով՝
> canonical prototype `brops-aios.html`-ից։ Cold-start session-ը վերցնում է հաջորդ **unchecked** task-ը
> էնտեղից։ Այս աղյուսակը ամփոփումն է, roadmap-ը՝ աղբյուրը։ Հին 4-քայլ framing-ը (Scaffold · Bridge · One
> approval gate · Contracts) **փոխարինված է**. *One approval gate* → Phase 2 (Governance Sidecar),
> *Contracts dedupe* → սկսվում է Phase 3-ում, ավարտվում Phase 10-ում։

| Phase | Նպատակ | Վիճակ |
|-------|--------|-------|
| **0 — Foundation** | monorepo հավաքված · երկլեզու docs · միասնական CI · history պահած | ✅ **DONE (locked)** |
| **1 — Bridge** | desktop AI exec-ը engine-ի supervisor/lease/wall-ով (`ai.rs`-ի ուղիղ `claude` spawn-ը փոխարինել) | 🔨 **Ընթացքում** — slice 1 **merged** (PR #3, `5be8d95`, 10/10) + slice 2 **transport** merged (PR #8՝ `Provider::GovernedEngine` opt-in · receipt badge · Settings toggle); verify-seam · receipt-plumbing · streaming · real e2e բաց |
| **2 — Governance Sidecar** | cockpit surface-եր՝ approvals · decisions · evidence chain · signals (mirror, ոչ decide) | ⏳ ready (P1 contract կա) |
| **3 — Desktop Integration** | app shell + `home`/`chat`(governed)/`settings`; core loop-ը wire | ⏳ blocked P1+P2 |
| **4 — UI/UX System** | component library + theming + motion + a11y; `activity`/`analytics`/`library` | ⏳ blocked P3 |
| **5 — Memory & Knowledge** | `memory`/`knowledge`/`research`(governed)/`files` | ⏳ blocked P3 |
| **6 — Multi-Agent** | `agents`/`command`/`tasks`/`projects`; governed pack dispatch | ⏳ blocked P4+P5 |
| **7 — Group Chat** | `group` համագործակցության սրահ; per-agent governed turn-եր | ⏳ blocked P6 |
| **8 — Automation** | `automations`/`calendar`; governed scheduled run-եր | ⏳ blocked P4+P5 |
| **9 — Integrations** | `integrations`; governed inbound/outbound, desktop-ում secret չկա | ⏳ blocked P7+P8 |
| **10 — Production** | signed/updatable build; լրիվ enforcement-path CI (T-005-ով option-C skip-երը retire); `contracts/` dedupe; O-1..O-5 փակել | ⏳ blocked P9 |

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
cargo test  -p brops-core --manifest-path apps/desktop/src-tauri/core/Cargo.toml   # 69 test (ամեն security slice-ով աճում ա)
cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml                       # app crate

# Engine — Python governance runtime  (ՊԱՐՏԱԴԻՐ՝ BRO_ENV=ci)
cd engine && BRO_ENV=ci python -m unittest discover -s tests   # 1282 test, 43 skip Windows-ում (չափված 2026-08-09)
```

## 5. Environment gotchas (սա Windows մեքենա ա) — ԿԱՐԴԱ TOOL ՎԱԶԵՑՆԵԼՈՒՑ ԱՌԱՋ

- **`cargo`-ն ՊԱՐՏԱԴԻՐ PowerShell-ից, երբեք Bash tool-ից։** Bash tool-ը Git Bash ա, որի coreutils `link`-ը shadow ա անում MSVC `link.exe`-ը; ամեն cargo build հետո fail ա անում կեղծ *"extra operand"* linker error-ով։ PowerShell-ում էդ shadow-ը չկա։ MSVC C++ Build Tools (VCTools) installed են։
- **Engine test-երը պահանջում են `BRO_ENV=ci`** — առանց դրա operator-pin gating-ը (M-1 hardening) deny ա անում, ու շատ test-եր error են, ոչ run։
- **Permission classifier-ը блокирует `git push` ու `gh pr merge` AI-ի համար։** Model-ը լոկալ commit ա պատրաստում ու Gev-ին տալիս ա հստак կոմանդը; **Gev-ն ա push / merge / PR անում ինքը։** Երբեք մի փորձիր շրջանցել։
- **Commit identity:** `user.name "menqstudio"`, `user.email "ohanyan.88@gmail.com"`։ Ամեն commit message-ի վերջում՝
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **Enforcement-hook wedge:** `engine/`-ը (Bro) ունի `.claude/settings.json` hooks (`bro_hook.py`)։ Windows-ում կարան crash անեն cp1252 `UnicodeEncodeError`-ով ու **fail-closed-cascade անեն ամբողջ session-ը** — սա իրական պատահել ա ու ամեն tool սառեցրել։ Եթե session wedge լինի՝ դիր `PYTHONUTF8=1` ու relaunch, կամ disable արա hooks-ը (`settings.json`-ը rename)։ OS-ը root-ից բացելը **չի** ակտիվացնում wall-ը — hook-երը բեռնվում են միայն repo root-ից, ոչ nested `engine/`-ից։ OS-ի root-ն **արդեն ունի** իր `.claude/settings.json`-ը, բայց դա wall-ը **չի**․ այն միացնում ա ուղիղ մեկ `Stop` hook՝ `.claude/hooks/coordination_stop_guard.py`, որ ստուգում ա coordination փաստաթղթերի համաձայնությունը։ Wall-ը `engine/.claude/settings.json`-ն ա՝ ինը event (`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `SubagentStart`, `SubagentStop`, `Stop`, `InstructionsLoaded`)։
- **GitHub Actions:** billing-ը fail էր (job-երը չէին ստարտում — account-level red flag, կոդի հետ կապ չուներ); լուծված ա։ Public repo-ները ձրի runner ունեն։ CI trigger՝ push→`main` ու `pull_request`; feature-branch-ի պարզ push-ը **չի** run անում CI մինչև PR-ը լինի։ Merge-conflict (`DIRTY`) PR-ն էլ check չի run անում մինչև conflict-ը push-լուծված լինի։
- **Toolchain:** cargo 1.96, node 24, npm 11, python 3.13, Pillow։ Tauri Windows build-ը պահանջում ա `icons/icon.ico` (արդեն generate արված cockpit-ի համար)։

## 6. Security կարգապահություն ու provenance

Երկու կեսն էլ audit արվել (multi-agent) ու fix արվել են այստեղ գալուց առաջ։

- **Engine (Bro):** 1 Critical (`find`/read-only-shell scope bypass → RCE), 6 High, 9 Medium, 13 Low — բոլորը fixed; PR merged։ Crypto core-ը (leases, contracts, protected-authority, evidence) verified sound։ **Դեռ residual-exploitable / deferred** — **մի rush** (wall / owner-env coupled)։ Ամբողջ inventory-ն ու status-of-record-ը [`docs/PHASE_10_PRODUCTION_ITEMS.md`](./docs/PHASE_10_PRODUCTION_ITEMS.md)-ն ա (հինգն էլ **OPEN**), engine-ը իր ID-ներով track ա անում `engine/AUDIT/tickets/`-ում — `O-n` համարակալումը այս repo-ինն ա։ *(Հին տարբերակը գրում էր «Bro-ի `fix/audit-followups`-ում» — էդ ref-ը ոչ լոկալ կա, ոչ remote-ում; ուղղված 2026-08-08։)* **Փոխվել ա blocker-ի ձևը՝ երեքը սպասում էին Gev-ի ձեռքով mint արած artifact-ի, հիմա ոչ մեկը չի սպասում.** first-launch provisioning-ը (`apps/desktop/src-tauri/provision/`) mint ա անում ամեն authority-ի բանալին, ստորագրում ա trusted-key registry-ն, mint ա անում `conductor-session`-ը, **ոչնչացնում ա operator root-ը**, ու պահում ա delegated `control-room` ու `evidence-floor` բանալիները։
  - **O-1 (HIGH)** bytecode-shadow — `assert_no_bytecode_shadow`-ը **իրական caller-ներ ունի** (`bro_control_plane.py:80` ու `:271`, գումարած `bro_protected.verify_control_plane_digest`) ու ամեն hook interpreter վազում ա `-B`-ով; reachability gate-ը պաշտպանում ա էդ call site-երը։ **Read-half-ը Python-ի ներսից չի փակվում:** `-B`-ն կանգնեցնում ա bytecode *գրելը*, ոչինչ չի կանգնեցնում արդեն եղած `.pyc`-ի *կարդալը* — ու CPython-ը կարդում ա import-ի ժամանակ, երբ պրոցեսում դեռ ոչ մի ստուգում չկա։ Փոխհատուցող կանոնը՝ engine-ը մերժում ա control plane, որ վազող account-ը կարա գրի; packaged install-ը էդ տալիս ա ձրի, բայց դա պիտի **packaged build-ի վրա ստուգվի**, ոչ թե պնդվի։
  - **O-2 (MED)** audit-head anchor — **dead code չի:** `append()`-ն ա in-band producer-ը (ինքն ա payload-ը հավաքում, ստորագրում `BRO_AUDIT_ANCHOR_SIGNER`-ով նույն append lock-ի ներսում, ու install անում), ու keyed `verify()`-ը **պահանջում ա** anchor՝ առանց դրա `AuditAnchorMissing`։ `head_anchor_payload`/`attach_head_anchor`-ը caller չունեն **միտումնավոր** — դրանք owner-ի out-of-band կեսն են։ **Պետք ա signer principal, որ ledger-ի գրողը չկարա դառնա։** Windows-ում էդ principal-ը կառուցված ա (`brops-audit-signer` service + `brops-anchor-relay` shim peer-authenticated pipe-ով), բայց **ոչ մի installer-ում չկա**, ու `register::apply`-ը test-երից դուրս entry point չունի; POSIX-ում նկարագրված ա ու երբեք չի վազել։
  - **O-3 (MED)** conductor session token — fail-closed **ու միացած**․ `require_conductor_session_token`-ը `true` ա `engine/.bro/policy.json`-ում, բացակա key / սխալ type / չկարդացվող policy — բոլորը REQUIRED, ու provisioning-ը mint ա անում `conductor-session` artifact-ը։ **Owner-ի artifact պետք չի։** Մնացել ա մեկ տող app-ի startup-ում՝ export անել `Provisioned::engine_env()`-ը գումարած `BRO_TRUSTED_REGISTRY_ROOT`-ը, ինչը այսօր ոչինչ չի անում — ուստի engine-ը դեռ կարդում ա committed *development* registry-ն։
  - **O-4 (LOW)** control-room actor — էլ self-asserted չի։ `_prove_command_actor`-ը երթուղում ա ըստ actor-ի՝ `bro`-ն ներկայացնում ա operator-signed `conductor-session`, իսկ **owner**-ը՝ `control-room-command` artifact, կապված հենց այս `command_id`/`task_id`/`command`-ին։ Type-ը գրանցված ա `ARTIFACT_AUTHORITY`-ում delegated `control-room`-ի տակ, ու **`schemas/control-room-command.schema.json`-ը ՈՒՆԻ `artifact_type` / `key_id` / `signature`** — այս տողի հին տարբերակը գրում էր որ չունի։ Provisioning-ը պահում ա բանալին, `mint_control_room_command`-ը ստորագրում ա, ուրեմն **Owner-ի artifact պետք չի**; *committed* registry-ն դեռ key չի pin անում այդ type-ի համար, ինչը փակվում ա նույն registry-root wiring-ով, ինչ O-3-ը։
  - **O-5 (LOW)** evidence high-water — head digest-ը ու sequence-ը պարտադիր են ու գնում են ուրիշ store-ի hash-chained record-ի մեջ, ուստի evidence store-ը սրբելուց հետո rollback-ը երևում ա ստորագրված բայթերից։ `mint_floor_anchor`-ը ստորագրում ա `evidence-floor-anchor`-ը պահված delegated բանալիով, ուրեմն **Owner-ի artifact պետք չի**։ Install-ի պահին **միտումնավոր չի** mint արվում․ դեռ task չկա, ու anchor, որ app-ը կստանար հենց էն store-ը կարդալով, որը ստուգում ա, կվերաշարադրեր store-ի սեփական պնդումը ստորագրության տակ — ավելի վատ, քան ոչ մի anchor, որովհետև կարդացվում ա որպես հաստատում։
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

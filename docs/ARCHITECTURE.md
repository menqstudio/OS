# Architecture · Ճարտարապետություն

[English](#english) · [Հայերեն](#հայերեն)

---

## English

### The two halves, one product

OS is a **monorepo** that unifies a governance **engine** (`engine/`, from `menqstudio/Bro`) with a desktop **cockpit** (`apps/desktop/`, from `menqstudio/BroPS`). The engine is the security-critical runtime that contains and governs AI agents; the cockpit is the product surface a person uses. Neither is useful alone: the engine has no face, the app has no safe motor.

### Design principles

1. **The cockpit is the only user-facing surface.** All product UX lives in `apps/desktop/`.
2. **The engine owns every security decision.** Leases, approval gates, the audit ledger, and the evidence chain are Ed25519-anchored in `engine/` and are authoritative. The desktop mirrors them for display; it never decides them.
3. **No ungoverned execution.** The desktop must not spawn a model directly. Every AI action is requested from the engine, which issues a scoped, single-use lease and runs the work behind the enforcement wall.
4. **The boundary is a subprocess/sidecar**, not an embedding — it matches the engine's existing CLI/hook model and keeps the two toolchains (Rust, Python) cleanly separated.
5. **History is preserved.** Both codebases are brought in with `git subtree`, so `git log` still tells each half's story.

### The governed execution flow — built, proven, and gated off

```
👤 → Webview (React) → Tauri command (Rust) → bridge
      → engine: supervisor issues an execution lease
      → 🧱 hook WALL (scope / mode / capability checks)
      → sandboxed AI (no tools, private cwd)
      → signed receipt + evidence event
      → back to the cockpit
```

That chain is real. It is machine-proven end to end on Linux (7 services, real uids, a setuid launcher) and on Windows (named pipes, distinct service accounts), and CI runs both on every PR — with `proof_executor`, a fixture, as the step: no model is called.

**And it does not run in the shipped application.** Production `trusted_verified` is unreachable, so every governed turn is refused rather than faked. **`platform_governed_execution_supported()` is not the reason — no function of that name exists in the tree.** It is the specification symbol from [`WINDOWS_BROKER_DESIGN.md`](./design/WINDOWS_BROKER_DESIGN.md) §0.1, recorded as `partial` in `config/spec-conformance.json`. The gate is three real refusals, all in the tree: `governed_verification_unconfigured()` (`apps/desktop/src-tauri/src/commands.rs`) returns `Some(...)` while any of its five compile-time inputs is absent — all are — and fires *before the model is called*; `connect_broker()` (`src/governed_turn.rs`) returns `UnsupportedPlatform` on every host but Linux; and the broker's `build_governed_executor` (`broker/src/main.rs`) serves `UpstreamBlockedExecutor` **unless `$BROPS_BROKER_CONFIG` names a deployment config carrying a TCB-root-signed manifest** — nothing in the shipped app sets that variable, so the fallback is what runs. Chat goes through the `claude` CLI only as a development opt-in: contained, not governed. Opening the gate needs an independent audit and the Owner's approval.

The distinction matters more than it looks. A proof kit that runs is not a shipped guarantee, and this repository keeps them apart on purpose — including in the words the UI is allowed to use.

### Resolved decisions

| Topic | Decision |
|-------|----------|
| Approval authority | **Engine (Bro)** is authoritative; the desktop Rust approval becomes a thin client/mirror. |
| Language boundary | **Subprocess/sidecar** (CLI + hooks), not PyO3 embedding. |
| Data ownership | Desktop SQLite = product/UI state (conversations, tasks, projects). Engine ledger + evidence = the security truth. IDs cross the bridge; no shared table. |
| Git history | **`git subtree`** for both halves. |
| CI | **10 workflow files; 35 contexts are *required* on `main` and 5 jobs are deliberately excluded** — both lists are in `config/required-checks.json`, which `tools/check_repo_state.py` compares against live branch protection. They cover frontend, Rust workspace, engine, bridge, a11y, perf budget, design gates, supply chain, and the repository gates under `tools/`: **45** `tools/check_*.py` files exist and **42** are invoked by path across `.github/workflows/`; the three that are not (`check_prior_art.py`, `check_merge_ready.py`, `check_push_ready.py`) are session-side by design. `main` carries branch protection with `enforce_admins: true`, `strict: true`, linear history, no force pushes and no deletions. Of the five excluded, four are pull-request jobs, each excluded for a measured reason — `AI-surface inventory gate` (its `paths:` filter keeps it silent on a pull request touching no Rust, and GitHub treats a skipped required context as pending), `Trust provisioning + audit signer (windows-latest)` (`T-023`, an intermittent custody refusal), the Windows §0.W broker syscall proof (`T-039`) and the Windows gate self-tests (`T-072`, not required until one green run on `main`) — and the fifth, the release preflight, never reports on a pull request at all. *(This cell said "38 checks report", "the 34 required", "35 required" and "four excluded" while naming two, in one paragraph; its Armenian twin said 37 and "exactly two". It also said protection was off for nine days after it was turned on — eighth audit `H-04`. How many contexts report on a given pull request is not restated: it was measured once, on `#284`.)* |
| The wall | **Two files, and which one runs is decided by the SESSION's project root, not by the directory being edited.** `engine/.claude/settings.json` is the enforcement wall (nine events, `PreToolUse` matcher `*`, so it sees every Bash call) and its hook commands are addressed `$CLAUDE_PROJECT_DIR/runtime/bro_hook.py` — a path that does not exist at the repository root, so **a session opened at the root is not running it**. `.claude/settings.json` at the root is the COORDINATION gate: six events, `canonical_law_gate.py`, enforcing read receipt, phase order, meta scope, prior art and the shrink-only canon budget. The root refuses **`Edit|Write|MultiEdit|NotebookEdit`** before the fact — and, since `T-150`, a `gh pr merge` or non-delete `git push` its gate (`check_merge_ready.py`, `check_push_ready.py`) does not pass — and settles **`Bash|PowerShell|Shell`** after it, against what changed on disk — because deciding which paths a shell command writes is undecidable, and a classifier good enough to catch `sh -c "$(printf ...)"` would also have to wave through the read-only greps agents live on. **The after-the-fact half is detection plus halting the turn, not containment: the write has already landed and nothing undoes it** — the engine's own `PostToolUse` path has the same limit (`bro_hook.py:148-177` settles a lease and emits `{"decision":"block"}`; no revert, no unlink, no restore). `T-053`. |

### The governance surfaces — what the cockpit mirrors, and where the mirror stops

Phase 2 gives the cockpit four read-only windows onto engine governance truth. This section exists
because that phase's own Documentation row names it and it had never been written; the honesty
constraints below are the load-bearing part, and they are enforced in code, not by this paragraph.

**One channel, four read surfaces, one ask.** `apps/desktop/src-tauri/src/governance.rs` registers
five Tauri commands. Four are reads — `read_decision_ledger`, `read_evidence_chain`,
`read_verifier_verdicts`, `read_engine_approval_queue` — each sending one `brops.governance-read.v1`
frame through the same governed sidecar the AI turn uses; the fifth, `request_engine_approval`, is
below. The engine answers from its own stores
(`bro_control_room_api.governance_read`), and `bridge/engine_sidecar.py` relays that reply
**verbatim**, so the three-valued shape survives the hop.

**The window is granted the four reads since 2026-10-09** (Owner). Until then they were outside
the ACL manifest and tauri refused them, seen installed. See `docs/OWNER_ACTION_REQUIRED.md` §2h.

**Three values, and the third is not an error.** A read is `ok` (records, possibly zero), `blocked`
(the engine was reached and refused) or `unreachable` (no engine). `blocked` and `unreachable` are
first-class states rather than exceptions, because a fail-closed engine is an honest answer and a page
that throws turns it into a bug report. An `ok` with zero records is an **empty** surface, never a
satisfied one — nothing downstream may paint a green node on it.

**A mirrored record is not an authenticated record.** Validation is schema-shape only: both engine
schemas declare `additionalProperties: false` and neither carries a signature field, and no trusted
key is reachable from this path. Every `ok` therefore ships `authenticated: false`, and the engine's
own `record_authentication` claim is deliberately **not** wired into it — that would launder a
self-assertion into a verified badge. The engine's account of its own store (why a surface is empty,
its record count, which store it read) travels beside the records as an **attributed** claim.

**Where the mirror stops, stated rather than implied.** The desktop does not walk the evidence chain:
it checks that `previous_event_hash` is null-or-64-hex and nothing more. Detecting a genuine fork
belongs to the supervisor on both platforms (`governed_supervisor_ledger.py`,
`win-live/src/servers.rs`), which re-derives every event digest and refuses a chain whose links or
head do not match. A desktop that re-derived a head from records it cannot authenticate would be
running a check that cannot fail.

**The desktop can ask; it cannot decide, and cannot be told it decided.** The approval-**request**
path exists on both sides since `T-021a`…`T-021d`: `contracts/approval-request.schema.json` (vendored
in `engine/schemas/`), `request_engine_approval`, the sidecar's `approval.request` op, and
`engine/runtime/bro_approval_requests.py`, which appends the ask to a log and adjudicates nothing — the
desktop refuses a reply that claims a decision. The `approvals` page's grant/deny/escalate still drive
the **desktop's own** approval system (T-010/T-011, behind a native confirmation the webview cannot
forge): a real authority, correctly gated, and not a verdict from across the wall.

### What is NOT done yet

- **`contracts/` is the source, not yet the only copy.** Six cross-half schemas live there;
  `engine/schemas/` keeps a byte-identical vendored copy the engine still loads, and
  `tools/check_contracts_single_source.py` turns drift RED. Pointing the engine's loaders at
  `contracts/` is the remaining step and needs its own audited engine branch.
- **The production gate is closed** — see above. This is the single most important "not done" in
  the repository and the one every phase percentage is subordinate to.
- **Path scope is not enforced on the desktop route.** A task's `scope` / `prohibited_scope` travel
  as text inside the prompt Bro writes; `engine/runtime/bro_security.enforce_scope` is what genuinely
  contains a path, and a desktop spawn never reaches it. Principle 3 — "no ungoverned execution" —
  therefore holds for the *governed* turn and not for the ordinary chat turn, and every delegation
  card states which one it is showing.
- **Five engine residual items remain OPEN** (`docs/PHASE_10_PRODUCTION_ITEMS.md`). **None of them
  needs an Owner-minted artifact** — first-launch provisioning mints every authority key and the
  `Needs an Owner secret?` column in that file reads `no` for all five, machine-checked by
  `tools/check_residual_items.py`. *(This said “three needing an Owner-minted artifact” until
  2026-08-09, three documents after that stopped being true.)* What blocks them is deployment
  wiring and a second principal, not a secret. *(This also said conductor stops and owner-issued
  control-room commands "still refuse because nothing exports the provisioned registry to the
  engine"; the export landed 2026-08-09 — `engine_trust::apply` at `ai::governed_sidecar_call` —
  so the engine reads the provisioned registry. What still blocks them is named per item in
  `docs/PHASE_10_PRODUCTION_ITEMS.md`: the sidecar's fail-closed real mode for O-3, and the
  absence of any shipped caller of `mint_control_room_command` for O-4.)*
- **`_real_callables()` in the bridge raises unconditionally**, pending the supervisor-reserved
  execution attempt and the authoritative execution→receipt binding. Correct and fail-closed.

---

## Հայերեն

### Երկու կես, մեկ product

OS-ը **monorepo** ա, որ միավորում ա governance **engine**-ը (`engine/`, `menqstudio/Bro`-ից) desktop **cockpit**-ի (`apps/desktop/`, `menqstudio/BroPS`-ից) հետ։ Engine-ը security-critical runtime ա, որ զսպում ու կառավարում ա AI agent-ներին; cockpit-ը product-ի երեսն ա, որ մարդ օգտագործում ա։ Առանձին ոչ մեկը օգտակար չի՝ engine-ը երես չունի, app-ը՝ անվտանգ motor։

### Դիզայնի սկզբունքներ

1. **Cockpit-ն ա միակ user-facing surface-ը։** Ամբողջ product UX-ը `apps/desktop/`-ում ա։
2. **Engine-ն ա տիրապետում ամեն security որոշման։** Lease-երը, approval gate-երը, audit ledger-ը, evidence chain-ը Ed25519-anchored են `engine/`-ում ու authoritative են։ Desktop-ը mirror ա անում ցուցադրության համար; երբեք չի որոշում։
3. **Ոչ մի չկառավարվող execution։** Desktop-ը չպիտի ուղիղ model spawn անի։ Ամեն AI action խնդրվում ա engine-ից, որ scoped, single-use lease ա տալիս ու աշխատանքը վազեցնում wall-ի հետևում։
4. **Boundary-ն subprocess/sidecar ա**, ոչ embedding — համապատասխանում ա engine-ի CLI/hook model-ին ու երկու toolchain-ը (Rust, Python) մաքուր բաժանում։
5. **History-ն պահվում ա։** Երկու codebase-ը բերվում են `git subtree`-ով, ուրեմն `git log`-ը դեռ պատմում ա ամեն կեսի պատմությունը։

### Governed execution flow (թիրախ — Phase 1)

```
👤 → Webview (React) → Tauri command (Rust) → bridge
      → engine՝ supervisor-ը execution lease ա տալիս
      → 🧱 hook WALL (scope / mode / capability ստուգում)
      → sandboxed AI (ոչ tools, private cwd)
      → signed receipt + evidence event
      → հետ՝ cockpit
```

Այդ շղթան իրական ա ու մեքենայորեն ապացուցված ծայրից ծայր՝ Linux-ի (7 ծառայություն, իրական uid-եր, setuid launcher) ու Windows-ի (named pipe, cross-account) վրա, ու CI-ը երկուսն էլ վազեցնում ա ամեն PR-ի վրա — քայլը `proof_executor` fixture-ն ա, model չի կանչվում։

**Ու այն shipped հավելվածում չի աշխատում։** production `trusted_verified`-ը անհասանելի ա, ուստի ամեն կառավարվող turn մերժվում ա, ոչ թե կեղծվում։ **`platform_governed_execution_supported()` անունով ֆունկցիա ծառում չկա։** Դա spec-ի սիմվոլն ա (`docs/design/WINDOWS_BROKER_DESIGN.md` §0.1), ու `config/spec-conformance.json`-ը գրանցում ա որպես `partial`։ Դարպասը երեք իրական մերժումն են՝ `governed_verification_unconfigured()`-ը `Some(...)` ա վերադարձնում, քանի դեռ իր հինգ compile-time input-ից որևէ մեկը բացակայում ա (բոլորն էլ բացակայում են), ու մոդելին կանչելուց առաջ, `connect_broker()`-ը Linux-ից դուրս վերադարձնում ա `UnsupportedPlatform`, ու broker-ի `build_governed_executor`-ը տալիս ա `UpstreamBlockedExecutor` **քանի դեռ `$BROPS_BROKER_CONFIG`-ը չի ցույց տալիս TCB-root-ով ստորագրված manifest-ով config** — shipped հավելվածում ոչինչ այդ փոփոխականը չի դնում։ Չատը `claude` CLI-ով անցնում ա միայն development opt-in-ով՝ զսպված, ոչ կառավարվող։ Դարպասը բացելու համար պետք ա անկախ աուդիտ ու Տիրոջ հաստատումը։

### Լուծված որոշումներ

| Թեմա | Լուծում |
|------|---------|
| Approval authority | **Engine (Bro)** authoritative; desktop Rust approval-ը thin client/mirror |
| Language boundary | **Subprocess/sidecar** (CLI + hooks), ոչ PyO3 |
| Data ownership | Desktop SQLite = product/UI state; Engine ledger + evidence = security truth; ID-երն են անցնում bridge-ով |
| Git history | **`git subtree`** երկու կեսի համար |
| CI | **10 workflow ֆայլ; 35 context *պարտադիր* ա `main`-ի վրա, ու 5 job միտումնավոր բացառված ա** — երկու ցանկն էլ `config/required-checks.json`-ում են, որ `tools/check_repo_state.py`-ն համեմատում ա կենդանի branch protection-ի հետ։ `tools/`-ում **45** `check_*.py` ֆայլ կա, **42**-ը կանչված ա ուղիով. չկանչված երեքը (`check_prior_art.py`, `check_merge_ready.py`, `check_push_ready.py`) դիզայնով session-side են։ `main`-ը կրում ա branch protection՝ `enforce_admins`, `strict`, գծային պատմություն, ոչ force-push, ոչ ջնջում։ Հինգ բացառվածից չորսը pull-request job են, ամեն մեկը չափված պատճառով՝ `AI-surface inventory gate` (`paths:` ֆիլտր), `Trust provisioning + audit signer (windows-latest)` (`T-023`), Windows §0.W broker syscall proof (`T-039`), Windows gate self-test-երը (`T-072`), իսկ հինգերորդը՝ release preflight-ը, pull request-ի վրա ընդհանրապես չի հաշվետվում։ *(Այս վանդակը գրում էր 37 ստուգում ու «ուղիղ երկուսը», անգլերենը՝ 38, 34, 35 ու «չորս»՝ նույն պարբերությունում։)* |
| Wall | **Երկու ֆայլ, ու որը վազի՝ որոշում ա SESSION-ի project root-ը։** `engine/.claude/settings.json`-ը enforcement wall-ն ա (ինը event, `PreToolUse` matcher `*`, ուրեմն տեսնում ա ամեն Bash), բայց իր hook-երը հասցեագրված են `$CLAUDE_PROJECT_DIR/runtime/bro_hook.py`-ին, որ root-ում **գոյություն չունի** — ուրեմն root-ից բացված session-ը դա չի վազեցնում։ Root-ի `.claude/settings.json`-ը coordination gate-ն ա՝ վեց event, `canonical_law_gate.py`։ Root-ը մերժում ա **`Edit|Write|MultiEdit|NotebookEdit`**-ը նախապես (ու `T-150`-ից՝ `gh pr merge`-ը ու ոչ-ջնջող `git push`-ը, եթե իրենց gate-ը կանաչ չի), ու **`Bash|PowerShell|Shell`**-ը settle ա անում հետո՝ ըստ նրա թե ինչ փոխվեց սկավառակի վրա, որովհետև shell-ի գրած ուղին նախապես որոշելը **անորոշելի ա**։ **Հետո-ստուգումը detection ա ու turn-ի կանգնեցում, ոչ containment** — գրվածը մնում ա։ `T-053`. |

### Ինչ դեռ արված չէ

- **`contracts/`-ը աղբյուրն ա, բայց դեռ միակ օրինակը չի։** Պատով անցնող վեց schema-ն այնտեղ են.
  `engine/schemas/`-ը պահում ա բայթ առ բայթ նույն պատճենը, որ engine-ը դեռ բեռնում ա, ու
  `tools/check_contracts_single_source.py`-ն շեղումը RED ա դարձնում։ Engine-ի loader-ները
  `contracts/`-ին ուղղելը մնացած քայլն ա ու պահանջում ա առանձին audited engine branch։
- **Production դարպասը փակ ա** — տես վերևը։ Սա ռեպոյի ամենակարևոր «արված չէ»-ն ա, ու ամեն phase-ի
  տոկոս ստորադաս ա դրան։
- **Ուղու scope-ը desktop-ի ճանապարհին չի պարտադրվում։** Տասկի `scope`/`prohibited_scope`-ը գնում ա
  որպես տեքստ Բրոյի գրած prompt-ի ներսում; `bro_security.enforce_scope`-ն ա իրական պարունակողը, ու
  desktop-ի spawn-ը դրան չի հասնում։
- **Հինգ engine-ի մնացորդային կետ OPEN ա** (`docs/PHASE_10_PRODUCTION_ITEMS.md`)։ **Ոչ մեկին Տիրոջ mint արած artifact պետք չի** — first-launch provisioning-ը mint ա անում ամեն authority-ի բանալին, ու էդ ֆայլի `Needs an Owner secret?` սյունը հինգի համար էլ `no` ա, մեքենայորեն ստուգված `tools/check_residual_items.py`-ով։ *(Այս տողը գրում էր «երեքին պետք ա Տիրոջ ստորագրած artifact» մինչև 2026-08-09 — անգլերեն կեսը ուղղվել էր, հայերենը՝ ոչ։)* Խոչընդոտը deployment-ի wiring-ն ա ու երկրորդ principal-ը, ոչ թե գաղտնիք։
- **Bridge-ի `_real_callables()`-ը անվերապահ raise ա անում** — ճիշտ ու fail-closed։

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

That chain is real. It is machine-proven end to end on Linux (7 services, real uids, a setuid launcher) and on Windows (named pipes, cross-account, distinct service accounts), and CI runs both on every PR.

**And it does not run in the shipped application.** Production `trusted_verified` is unreachable, so every governed turn is refused rather than faked. **`platform_governed_execution_supported()` is not the reason — no function of that name exists in the tree.** It is the specification symbol from [`WINDOWS_BROKER_DESIGN.md`](./design/WINDOWS_BROKER_DESIGN.md) §0.1, recorded as `partial` in `config/spec-conformance.json`. The gate is three real refusals, all in the tree: `governed_verification_unconfigured()` (`apps/desktop/src-tauri/src/commands.rs`) returns `Some(...)` unconditionally and fires *before the model is called*; `connect_broker()` (`src/governed_turn.rs`) returns `UnsupportedPlatform` on every host but Linux; and the broker's `build_governed_executor` (`broker/src/main.rs`) serves `UpstreamBlockedExecutor` **unless `$BROPS_BROKER_CONFIG` names a deployment config carrying a TCB-root-signed manifest** — nothing in the shipped app sets that variable, so the fallback is what runs. Ordinary chat goes through the `claude` CLI in a private sandbox: contained, not governed, and labelled as such. Opening the gate needs an independent audit and the Owner's approval.

The distinction matters more than it looks. A proof kit that runs is not a shipped guarantee, and this repository keeps them apart on purpose — including in the words the UI is allowed to use.

### Resolved decisions

| Topic | Decision |
|-------|----------|
| Approval authority | **Engine (Bro)** is authoritative; the desktop Rust approval becomes a thin client/mirror. |
| Language boundary | **Subprocess/sidecar** (CLI + hooks), not PyO3 embedding. |
| Data ownership | Desktop SQLite = product/UI state (conversations, tasks, projects). Engine ledger + evidence = the security truth. IDs cross the bridge; no shared table. |
| Git history | **`git subtree`** for both halves. |
| CI | **7 workflows; 33 checks run on every pull request** (2 further jobs, in `release.yml`, run only on a version tag) — frontend, Rust workspace, engine, bridge, a11y, perf budget, design gates, supply chain, and **18** repository gates under `tools/`. *(This cell said 31 checks and 15 gates until 2026-08-14; counted from three consecutive PRs — #89, #90, #91 — at 33 each, and from a digit-safe grep of `tools/check_*.py` invocations across `.github/workflows/`. 19 such files exist; the one not wired is `check_prior_art.py`, which is session-side by design.)* **None of them is a *required* check.** `main` carries no branch protection and no rulesets: `gh api repos/menqstudio/OS/branches/main/protection` returns `404 Branch not protected`, and both `.../rulesets` and `.../rules/branches/main` return `[]` (verified 2026-08-09). The checks run and the Owner reads them; enforcement is convention. **Turning protection on is the Owner's to do** — no Builder change can make a check required. |
| The wall | **`engine/.claude/settings.json`**, wired for nine events. The OS-root `.claude/` is NOT the wall: it holds the 262 generated specialist definitions and one `Stop` guard for coordination-document consistency. Wiring the wall at the root is an open decision — today it would deny every tool call until a session state directory and an operator-signed workspace binding exist, and `engine/` is not its own git checkout. |

### What is NOT done yet

- **`contracts/` is still a placeholder** — a README describing intent, no extracted schemas. The
  canonical definitions live in `engine/schemas/` and are mirrored informally in the desktop's Rust
  domain. Principle 2 says the engine is authoritative, and today that is true by convention rather
  than by a shared file.
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

Այդ շղթան իրական ա ու մեքենայորեն ապացուցված ծայրից ծայր՝ Linux-ի (7 ծառայություն, իրական uid-եր, setuid launcher) ու Windows-ի (named pipe, cross-account) վրա, ու CI-ը երկուսն էլ վազեցնում ա ամեն PR-ի վրա։

**Ու այն shipped հավելվածում չի աշխատում։** production `trusted_verified`-ը անհասանելի ա, ուստի ամեն կառավարվող turn մերժվում ա, ոչ թե կեղծվում։ **`platform_governed_execution_supported()` անունով ֆունկցիա ծառում չկա։** Դա spec-ի սիմվոլն ա (`docs/design/WINDOWS_BROKER_DESIGN.md` §0.1), ու `config/spec-conformance.json`-ը գրանցում ա որպես `partial`։ Դարպասը երեք իրական մերժումն են՝ `governed_verification_unconfigured()`-ը անպայման `Some(...)` ա վերադարձնում մոդելին կանչելուց առաջ, `connect_broker()`-ը Linux-ից դուրս վերադարձնում ա `UnsupportedPlatform`, ու broker-ի `build_governed_executor`-ը տալիս ա `UpstreamBlockedExecutor` **քանի դեռ `$BROPS_BROKER_CONFIG`-ը չի ցույց տալիս TCB-root-ով ստորագրված manifest-ով config** — shipped հավելվածում ոչինչ այդ փոփոխականը չի դնում։ Սովորական չատը անցնում ա `claude` CLI-ով private sandbox-ում՝ զսպված, ոչ կառավարվող, ու հենց այդպես էլ պիտակավորված։ Դարպասը բացելու համար պետք ա անկախ աուդիտ ու Տիրոջ հաստատումը։

### Լուծված որոշումներ

| Թեմա | Լուծում |
|------|---------|
| Approval authority | **Engine (Bro)** authoritative; desktop Rust approval-ը thin client/mirror |
| Language boundary | **Subprocess/sidecar** (CLI + hooks), ոչ PyO3 |
| Data ownership | Desktop SQLite = product/UI state; Engine ledger + evidence = security truth; ID-երն են անցնում bridge-ով |
| Git history | **`git subtree`** երկու կեսի համար |
| CI | **7 workflow; 33 ստուգում ա աշխատում ամեն pull request-ի վրա** (ևս 2 job `release.yml`-ում՝ միայն տագի վրա) + **18** gate `tools/`-ում։ *(Այս վանդակը գրում էր 31 ու 15 մինչև 2026-08-14; հաշվված ա երեք իրար հետևից PR-ից — #89, #90, #91 — ամեն մեկը 33, ու `.github/workflows/`-ի grep-ից։ Ֆայլերը 19 են; wire չարվածը `check_prior_art.py`-ն ա, որ դիզայնով session-side ա։)* **Ոչ մեկը *պարտադիր* չի։** `main`-ը branch protection ու ruleset չունի (ստուգված 2026-08-09)՝ ստուգումները աշխատում են, Owner-ը կարդում ա, բայց enforcement-ը պայմանավորություն ա։ Protection-ը միացնելը Owner-ինն ա։ |
| Wall | **`engine/.claude/settings.json`**, ինը event։ OS-root-ի `.claude`-ը wall-ը **չի** — այնտեղ 262 գեներացված մասնագետի սահմանում ա ու մեկ `Stop` guard։ Root-ում wire անելը բաց որոշում ա (կմերժեր ամեն tool call)։ |

### Ինչ դեռ արված չէ

- **`contracts/`-ը դեռ placeholder ա** — README, ոչ հանված schema։ Կանոնական սահմանումները
  `engine/schemas/`-ում են։ 2-րդ սկզբունքը ասում ա engine-ն ա authoritative, ու այսօր դա ճիշտ ա
  պայմանավորվածությամբ, ոչ թե ընդհանուր ֆայլով։
- **Production դարպասը փակ ա** — տես վերևը։ Սա ռեպոյի ամենակարևոր «արված չէ»-ն ա, ու ամեն phase-ի
  տոկոս ստորադաս ա դրան։
- **Ուղու scope-ը desktop-ի ճանապարհին չի պարտադրվում։** Տասկի `scope`/`prohibited_scope`-ը գնում ա
  որպես տեքստ Բրոյի գրած prompt-ի ներսում; `bro_security.enforce_scope`-ն ա իրական պարունակողը, ու
  desktop-ի spawn-ը դրան չի հասնում։
- **Հինգ engine-ի մնացորդային կետ OPEN ա** (`docs/PHASE_10_PRODUCTION_ITEMS.md`)։ **Ոչ մեկին Տիրոջ mint արած artifact պետք չի** — first-launch provisioning-ը mint ա անում ամեն authority-ի բանալին, ու էդ ֆայլի `Needs an Owner secret?` սյունը հինգի համար էլ `no` ա, մեքենայորեն ստուգված `tools/check_residual_items.py`-ով։ *(Այս տողը գրում էր «երեքին պետք ա Տիրոջ ստորագրած artifact» մինչև 2026-08-09 — անգլերեն կեսը ուղղվել էր, հայերենը՝ ոչ։)* Խոչընդոտը deployment-ի wiring-ն ա ու երկրորդ principal-ը, ոչ թե գաղտնիք։
- **Bridge-ի `_real_callables()`-ը անվերապահ raise ա անում** — ճիշտ ու fail-closed։

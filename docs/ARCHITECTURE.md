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

### The governed execution flow (target — Phase 1)

```
👤 → Webview (React) → Tauri command (Rust) → bridge
      → engine: supervisor issues an execution lease
      → 🧱 hook WALL (scope / mode / capability checks)
      → sandboxed AI (no tools, private cwd)
      → signed receipt + evidence event
      → back to the cockpit
```

Today (in `apps/desktop/`) the `ai.rs` layer spawns the `claude` CLI directly in a private sandbox. Phase 1 replaces that spawn with a `bridge` call into the engine's `bro_supervisor`, so the same turn now carries a lease and produces a receipt.

### Resolved decisions

| Topic | Decision |
|-------|----------|
| Approval authority | **Engine (Bro)** is authoritative; the desktop Rust approval becomes a thin client/mirror. |
| Language boundary | **Subprocess/sidecar** (CLI + hooks), not PyO3 embedding. |
| Data ownership | Desktop SQLite = product/UI state (conversations, tasks, projects). Engine ledger + evidence = the security truth. IDs cross the bridge; no shared table. |
| Git history | **`git subtree`** for both halves. |
| CI | One workflow, three legs (npm build · cargo test · python unittest) + a bridge smoke test (Phase 1). |
| The wall | The OS-root `.claude/` hooks govern the repo's own dev/agent work too. |

### What is NOT done yet (Phase 0 scope)

- `contracts/` is a placeholder describing intent — no dedupe code yet.
- The desktop no longer *only* spawns `claude` directly: **Phase 1** added an **opt-in governed provider** (`Provider::GovernedEngine` in `ai.rs`, default OFF, merged PR #8) that routes an AI turn through the engine sidecar. This is **transport only** — the direct `claude` path is still the default, and the verify-seam, receipt-plumbing, governed streaming, and a real end-to-end round-trip are still pending.
- Both halves still build and test independently. Phase 0 assembled; Phase 1 has begun wiring (transport landed, governance of the turn not yet complete).

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

Հիմա (`apps/desktop/`-ում) `ai.rs`-ը ուղիղ `claude` CLI ա spawn անում private sandbox-ում։ Phase 1-ը էդ spawn-ը փոխարինում ա `bridge` call-ով engine-ի `bro_supervisor`-ի մեջ, ուրեմն նույն turn-ը հիմա lease ա կրում ու receipt ա արտադրում։

### Լուծված որոշումներ

| Թեմա | Լուծում |
|------|---------|
| Approval authority | **Engine (Bro)** authoritative; desktop Rust approval-ը thin client/mirror |
| Language boundary | **Subprocess/sidecar** (CLI + hooks), ոչ PyO3 |
| Data ownership | Desktop SQLite = product/UI state; Engine ledger + evidence = security truth; ID-երն են անցնում bridge-ով |
| Git history | **`git subtree`** երկու կեսի համար |
| CI | Մեկ workflow, 3 leg + bridge smoke (Phase 1) |
| Wall | OS-root `.claude/` hooks-ը govern ա անում նաև repo-ի dev/agent work-ը |

### Ինչ դեռ արված չէ (Phase 0-ի scope)

- `contracts/`-ը placeholder ա՝ intent-ը նկարագրող, ոչ dedupe կոդ։
- Desktop-ը այլևս *միայն* ուղիղ `claude` չի spawn անում. **Phase 1**-ը ավելացրեց **opt-in governed provider** (`Provider::GovernedEngine` `ai.rs`-ում, default OFF, merged PR #8), որ AI turn-ը route ա անում engine sidecar-ով։ Սա **transport-only** ա — ուղիղ `claude` path-ը դեռ default ա, ու verify-seam-ը, receipt-plumbing-ը, governed streaming-ը ու իրական end-to-end round-trip-ը դեռ pending են։
- Երկու կեսն էլ դեռ independently build ու test են։ Phase 0-ը հավաքեց; Phase 1-ը սկսել ա wire անել (transport-ը land ա, turn-ի governance-ը դեռ ամբողջական չէ)։

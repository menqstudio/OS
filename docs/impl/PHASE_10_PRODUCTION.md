# Phase 10 — Production · Implementation Spec

> Blueprint for a cold-start session. Grounds roadmap **Phase 10** (`MASTER_EXECUTION_ROADMAP.md`
> L1215–1297) in the real code. Scope: signed + auto-updating Tauri build; the **T-005** native
> worktree-check fix to retire the option-C CI skips and run the **full** enforcement path; **O-1..O-5**
> engine remediation (each its own audited task); final `contracts/` dedupe; production a11y + perf gates
> over all 22 pages. Ownership: 🔨 Builder · 📐 Audit (full-enforcement CI) · 🛑 Gev + Architect security
> sign-off **before implementation** (roadmap §G.1 P10). Depends on P9 (feature-complete). Last phase.

## 1. Objective & current state

**Intent.** Turn the wired product into a shippable, hardened, updatable desktop app under the wall.

**What exists today:**
- `apps/desktop/src-tauri/tauri.conf.json` — `productName BroPS`, `version 0.1.0`, `identifier
  studio.menq.brops`, `bundle.active true`, `targets "all"`, icons incl. `icons/icon.ico` (Windows).
  **No `plugins.updater` block, no signing config, no update endpoint.**
- `apps/desktop/src-tauri/Cargo.toml` — `tauri = "2"`, `tauri-build = "2"`, `reqwest`(rustls),
  `tokio`, `rusqlite(bundled)`. **No `tauri-plugin-updater`, no signing deps.**
- CI `.github/workflows/ci.yml` — 6 legs: `cockpit-frontend` (build + test), `cockpit-core`
  (`cargo test -p brops-core`), `engine` (`python -m unittest`, `BRO_ENV=ci`), `bridge`,
  `coordination` (docs gate). **No signed-build/update smoke, no a11y/perf gate.**
- Engine root-model is on **Option 1 (subtree + option-C skip-guard)**: the monorepo-coupled
  enforcement-path tests `FullExecutionTransactionE2ETests` + `HookSubprocessTests` **skip-guard
  themselves** when `engine/` is not a git checkout root (roadmap L384–387). Reported green as
  591 passed / 38 skipped (roadmap L408).
- `contracts/` exists but lease/approval/task-contract/mode-grant shapes are **still duplicated**
  (roadmap §F: "Phase 3 begins → Phase 10 final").
- Verified-receipt spine intact but real-mode verify seam still Architect-pending
  (`bridge/engine_sidecar.py::_real_callables` raises).

**Gap Phase 10 closes:** production packaging/signing/updater; T-005 (retire the skips, full
enforcement CI); O-1..O-5; contracts dedupe; a11y+perf gates; onboarding/first-run.

## 2. Production build · signing · auto-update

- **Add the updater + signing plugin.** `Cargo.toml`: add `tauri-plugin-updater` (+ signing deps).
  `tauri.conf.json`: add `plugins.updater` `{active, endpoints[], pubkey, dialog|windows.installMode}`
  and a `bundle.createUpdaterArtifacts`/signing block; bump `version` off `0.1.0` with a real release
  scheme. Keep `targets` scoped to `nsis`/`msi` for the Windows-first ship (roadmap L1227).
- **Signing.** Code-sign the Windows installer + sign the update manifest (Ed25519 updater key held
  **outside** the model, operator/CI secret — never committed, never on the desktop). The private
  signing key is a §G.2 secret task class.
- **Updater UX (per §D):** progress / failure / rollback states; integrity-checked download (signature
  verified before apply). Ship real HY copy (no placeholder).
- **Onboarding / first-run:** provision the sidecar (issuer key registry + workspace binding as an
  operator step, roadmap L1228) and run the first governed turn; designed + shipped as a flow.
- **Migrations stay atomic + tested** (the cockpit non-atomic-migration High was fixed; keep that
  invariant for update-time schema changes — `core/src/db.rs`).

## 3. T-005 — native worktree fix, retire the option-C skips, full enforcement CI

**Problem.** Under subtree vendoring, `engine/` is not its own git checkout root, so
`bro_repository_state.worktrees()` cannot resolve the worktree and the 9 monorepo-coupled
enforcement-path tests skip-guard themselves (Option 1). The wall's full path is therefore **not
exercised in CI** — a real gap hidden behind skips.

**Fix (audited engine task).** Convert `engine/` to a **submodule** (or otherwise a real checkout root)
and make `bro_repository_state.worktrees()` resolve the top level natively via
`git rev-parse --show-toplevel` instead of assuming `ROOT` is the worktree root. This lets
`FullExecutionTransactionE2ETests` + `HookSubprocessTests` run **unskipped**, retiring the option-C
skip-guards so CI runs the **full** enforcement path.

**Because this touches `engine/` security perimeter code, T-005 is:**
- its **own** audited branch + PR (never folded into packaging work),
- 🛑 Owner approval **and** Architect security sign-off **before implementation** (§G.2 engine class),
- never rushed, never parallelized (§E serialization rule).

**CI change (`.github/workflows/ci.yml`):** after T-005, the `engine` leg checks out the submodule and
runs the suite with **zero enforcement-path skips**; a check asserts the previously-skipped tests now
execute. Add a **signed-build + update smoke** job (Windows) and **a11y + perf + contract-version**
gate jobs (§4/§5).

## 4. O-1..O-5 — residual engine remediation (each its own audited task)

Named in the roadmap glossary (L1321–1322) — residual/deferred engine security items, closed in
Phase 10, **each its own audited engine branch/PR/Owner+Architect sign-off** (§G.2), never rushed:

| Item | Concern (roadmap glossary) | Remediation shape |
|---|---|---|
| **O-1** | bytecode-shadow | ensure `.pyc`/shadowed bytecode cannot mask verified source on the enforcement path. |
| **O-2** | audit-head anchor | anchor the audit/evidence head so a rewound/forged head is detected. |
| **O-3** | conductor session token | bind the conductor↔sidecar session so a token cannot be replayed/lifted. |
| **O-4** | control-room actor | pin the control-plane actor identity (no ambient authority). |
| **O-5** | evidence high-water | enforce an append-only evidence high-water mark (no silent truncation). |

Each is closed **or** explicitly, honestly **owner-signed-deferred** — never hidden behind a skip.

## 5. Contracts dedupe · a11y + perf gates

- **Contracts.** Finalize `contracts/` as the single home for `execution-lease`, `approval`,
  `task-contract`, `mode-grant`; both halves consume from there; **delete** the duplicated shapes;
  **version** the contracts for update compatibility (roadmap §F, H-registry: this retires the "Target
  (Phase 3 → Phase 10 final)" row). A contract change ⇒ 📐 mandatory audit, consumers updated same PR.
- **a11y gate (all 22 pages, §C.2).** Keyboard-complete, AA contrast on `--bg`/`--surface`, live
  regions, HY screen-reader labels; the prototype's 457 aria attributes are the floor. Run
  `jest-axe`/testing-library assertions in the frontend leg as a **blocking** gate.
- **Perf gate.** First-paint + interaction-latency budgets + reduced-motion parity as a CI check.
- **No placeholder copy ships** — every empty/error/`blocked` state carries real HY install copy.

## 6. Data models / contracts

- `contracts/` becomes the versioned single source (lease/approval/task-contract/mode-grant); duplicates
  deleted. No new product tables — telemetry/crash stores are **local-first, opt-in, purgeable**
  (`core/src/`), consistent with the engine's local-first posture. Update/rollback migrations atomic +
  tested (`core/src/db.rs`).

## 7. Exact files to touch

- `apps/desktop/src-tauri/tauri.conf.json` — `plugins.updater`, signing/bundle config, version scheme, Windows targets.
- `apps/desktop/src-tauri/Cargo.toml` — `tauri-plugin-updater` + signing deps.
- `apps/desktop/src-tauri/src/lib.rs` — register the updater plugin; onboarding/first-run wiring.
- `.github/workflows/ci.yml` — full-enforcement `engine` leg (post-T-005, no skips) + signed-build/update-smoke + a11y/perf/contract-version gate jobs.
- `engine/runtime/bro_repository_state.py` (`worktrees()`) + submodule setup — **T-005, audited engine branch only.**
- `engine/tests/` — unskip `FullExecutionTransactionE2ETests` + `HookSubprocessTests` once T-005 lands.
- Engine security code for **O-1..O-5** — each its **own** audited branch (do not batch).
- `contracts/` — final dedupe + versioning; delete duplicated lease/approval/task-contract/mode-grant shapes; update consumers (`bridge/`, engine, desktop).
- All 22 `apps/desktop/src/features/*` — production a11y + perf + real-HY-copy pass.
- Docs: `README` (install/first-run), `docs/ARCHITECTURE.md` (final contracts + full enforcement path), `docs/SECURITY_MODEL.md` (O-1..O-5 status), `CLAUDE.md` (roadmap → all phases done), `PROJECT_STATE.md`.

## 8. Tests & acceptance

- **Full** engine suite **including** the previously-skipped enforcement-path tests (post-T-005),
  `BRO_ENV=ci` — **zero enforcement-path skips**.
- Cockpit core + frontend; bridge; end-to-end governed flows across pages; **update/rollback** tests;
  a11y + perf gates as CI checks; signed-build + update smoke on Windows.
- **Merge-gate acceptance:** a signed, updatable OS install runs the full governed product; **full**
  enforcement-path CI green (no skips); `contracts/` is the single source; O-1..O-5 closed or
  owner-signed-deferred; every page passes production a11y + perf gates; verified-receipt invariant
  holds product-wide; no secret in the desktop.

## 9. Security notes

- **🛑 T-005 and every O-item are Architect-audited engine tasks** — Owner approval + Architect security
  sign-off **before implementation**, each its own branch/PR, never rushed, never parallelized (§E/§G.2,
  CLAUDE.md §6). Signing keys are §G.2 secret task class, held outside the model.
- Full enforcement-path CI must go green **honestly** — do not hide a failure behind a skip (roadmap
  stop condition, L1278–1279).
- The verified-receipt invariant and no-desktop-secret rule from Phases 1/9 must still hold across the
  whole shipped product; auto-update is signature/integrity-checked before apply.

## 10. Dependencies & stop conditions

Depends on **P9** (feature-complete). T-005 + O-1..O-5 are security-adjacent audited tasks gating the
merge gate. **Stop conditions:** T-005 or any O-item rushed or destabilizing the wall → stop, audited
task. A page shipping placeholder copy or failing the a11y/perf gate → stop, not done. Full-enforcement
CI that cannot go green honestly → stop, do not hide it behind skips.

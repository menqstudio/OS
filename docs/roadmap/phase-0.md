## Phase 0 — Foundation · Հիմք  ✅ Locked

**Objective.** Assemble the two audited halves into one monorepo with preserved history, unified CI, and
bilingual canonical docs, so all later phases build on one stable base. *(Done; frozen.)*

**Scope.** In: `git subtree` vendoring of `engine/` (Bro) and `apps/desktop/` (BroPS), unified
`.github/workflows` CI (3 legs), bilingual `README`/`CLAUDE`/`ARCHITECTURE`, coordination canon
(`OWNERS`/`PROJECT_STATE`/`TASKS`/Startup Law). Out: any wiring between the halves (that is Phase 1+).

**Architecture.** Two independent toolchains (Python engine, Rust+TS cockpit) coexisting; the git
top-level is `OS/`, each half a subdirectory. The engine's security perimeter still assumes `ROOT` is a
worktree root — resolved for now by **Option 1 (subtree + C)**: the 9 monorepo-coupled enforcement-path
tests (`FullExecutionTransactionE2ETests`, `HookSubprocessTests`) skip-guard themselves when `engine/`
is not a git checkout root. No runtime/security code touched. A native fix (submodule + `git rev-parse
--show-toplevel` in `bro_repository_state.worktrees()`) is deferred to **T-005**, a separate audited task.

**UI/UX work.** None new. Establishes that `brops-aios.html` is the canonical visual reference (§C) and
that the cockpit's existing shell in `apps/desktop/` is the starting point. Deliverable: the design-token
extraction table (§C.1) and the 22-page inventory (§C.2) — done in this roadmap.

**Backend work.** None new; both halves build independently (§B.4). Provenance recorded: `engine/` from
Bro `main`; `apps/desktop/` from BroPS `main` (PR #25).

**Contracts / schemas.** None new. The engine's existing contracts (lease, receipt, evidence, mode-grant)
are inventoried in §F as the shared truth later phases consume.

**Data models.** None new. Desktop SQLite (product/UI state) and engine ledger+evidence (security truth)
remain separate; IDs will cross the bridge in Phase 1 — no shared table.

**Dependencies.** None (this is the root).

**Security gates.** Both halves arrived audited & fixed (Engine: 1 Critical + 6 High + 9 Med + 13 Low, all
fixed; Cockpit: 1 High + 8 Med + 18 Low, all fixed). Residual/deferred engine items **O-1..O-5** are
tracked on Bro's `fix/audit-followups` and are **not** in scope here (wall/owner-env coupled).

**Tests.** Engine `BRO_ENV=ci python -m unittest discover -s tests` → green (1282 tests, 43 skipped, 0
failed, option-C skip-guard). Cockpit `cargo test -p brops-core` 29/29; `npm run build` green.

**CI requirements.** One workflow, three legs: cockpit-frontend (npm build) · cockpit-core (cargo test) ·
engine (python unittest). Triggers on push→`main` and on `pull_request`.

**Documentation updates.** `README`, `CLAUDE.md`, `docs/ARCHITECTURE.md`, coordination canon — all
bilingual and current at merge.

**Acceptance criteria.** Monorepo assembled with both histories intact; all three CI legs green; canonical
docs present and bilingual; the root-model decision recorded with its verified finding.

**Merge gate.** ✅ Met (merged).

**Stop conditions.** Any attempt to change engine security code inside a Phase-0/coordination merge →
stop, split into an audited task (this is the exact failure Option 1 avoids).

**Definition of Done.**
- [x] Both halves vendored via `git subtree`, history preserved.
- [x] Unified CI, three legs green.
- [x] Bilingual canonical docs (`README`/`CLAUDE`/`ARCHITECTURE`) + coordination canon.
- [x] Root-model decision recorded (Option 1 now; T-005 deferred).

**Task checklist.** *(Phase complete — retained for provenance.)*
- [x] Vendor `engine/` and `apps/desktop/` with history.
- [x] Author unified CI workflow (3 legs).
- [x] Land coordination canon + Startup Law.
- [x] Record root-model decision + verified submodule finding.

---

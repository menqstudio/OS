## Phase 10 — Production · Արտադրություն

**Objective.** Turn the wired product into a shippable, hardened, updatable desktop application: signed
builds, auto-update, packaging, performance + a11y gates across all 22 pages, the full enforcement-path
CI restored, the `contracts/` dedupe finalized, and the residual engine items resolved — so OS is
production-ready under the wall.

**Scope.** In: production build/packaging/signing, auto-update, crash/telemetry (local-first), a
production a11y + performance gate over every page, the native root-model fix (**T-005**) so the full
enforcement path runs in CI (retiring the option-C skips), the final `contracts/` dedupe, and closing the
residual engine items **O-1..O-5**. Out: nothing further — this is the last phase.

**Architecture.** Tauri production build (Windows first; `icon.ico` present) with code signing + auto-
update; the engine sidecar packaged/provisioned for a real install (issuer key registry + workspace
binding as an operator step); CI runs the **full** enforcement path (T-005 replaces the subtree worktree
check with `git rev-parse --show-toplevel`, unskipping `FullExecutionTransactionE2ETests` /
`HookSubprocessTests`); `contracts/` becomes the single source for lease/approval/task-contract/mode-grant.

**UI/UX work.** No new pages; instead a **production polish + gate pass** over all 22:
- Every page passes a production a11y audit (keyboard-complete, AA contrast, live regions, HY SR labels)
- Empty/error/`blocked` states reviewed for real-install copy (Armenian) — no placeholder text ships.
- Onboarding/first-run flow (provision the sidecar, connect the first governed turn) is designed and shipped.
- Installer/updater UX (progress, failure, rollback) specified per §D.

**Backend work.** Packaging + signing + auto-update; sidecar provisioning/onboarding; crash reporting
(local-first, opt-in); the T-005 engine worktree-check fix (audited); the `contracts/` dedupe migration;
O-1..O-5 remediation (each its own audited engine task).

**Contracts / schemas.** Finalize `contracts/` as the single home for `execution-lease`, `approval`,
`task-contract`, `mode-grant`; both halves consume from there; delete the duplicated shapes. Version the
contracts for update compatibility.

**Data models.** Migration story for updates (the cockpit's non-atomic-migration High was fixed; keep
migrations atomic + tested). Telemetry/crash stores local-first, opt-in, purgeable.

**Dependencies.** Phase 9 (feature-complete). T-005 (root-model native fix) and O-1..O-5 (engine
residuals) are **security-adjacent audited tasks** — each its own branch/PR/Owner approval; never rushed.

**Security gates.** Full enforcement-path CI green (no option-C skips). O-1..O-5 closed or explicitly,
honestly deferred with owner sign-off. Signed builds; auto-update integrity-checked. Verified-receipt
invariant holds across the whole product. No secret in the desktop. The engine golden rule governs every
security-code change here.

**Tests.** Full engine suite **including** the previously-skipped enforcement-path tests (post-T-005);
cockpit core + frontend; bridge; end-to-end governed flows across pages; update/rollback tests; a11y +
performance gates as CI checks.

**CI requirements.** All legs green with the **full** enforcement path (skips retired). Add a11y +
performance + contract-version gates. A signed-build + update smoke on Windows.

**Documentation updates.** `README` (install/first-run), `docs/ARCHITECTURE.md` (final contracts + full
enforcement path), `docs/SECURITY_MODEL.md` (O-1..O-5 status), `CLAUDE.md` roadmap → all phases done,
`PROJECT_STATE.md` → production.

**Acceptance criteria.** A signed, updatable OS install runs the full governed product; **full**
enforcement-path CI is green (no skips); `contracts/` is the single source; O-1..O-5 closed or
owner-signed-deferred; every page passes production a11y + performance gates.

**Merge gate.** Full-enforcement CI green; security review of T-005 + O-1..O-5; signed-build + update
smoke green; Architect + Owner final approval.

**Stop conditions.** If T-005 or any O-item is rushed or destabilizes the wall → stop, it is an audited
task. If a page ships placeholder copy or fails the a11y/perf gate → stop, it is not done. If full-
enforcement CI cannot go green honestly → stop, do not hide it behind skips.

**Definition of Done.**
- [ ] Signed, auto-updating Windows build; onboarding/first-run flow shipped.
- [ ] **Full** enforcement-path CI green (option-C skips retired via T-005).
- [ ] `contracts/` finalized as the single source; duplicates deleted; versioned. — **versioned and gated, NOT deduped**: `contracts/index.json` carries a `version_pointer` per schema and `tools/check_contracts_single_source.py` makes drift RED, but `engine/schemas/` still holds a byte-identical copy of all five, so the box stays unticked.
- [ ] O-1..O-5 closed or owner-signed-deferred (each audited).
- [x] Every page passes production a11y + performance gates; no placeholder copy. — **DONE 2026-08-29**: axe runs in real Chromium with the app's stylesheet graph and `color-contrast` enabled over 23 pages in two states and two themes, plus the shell and the ⌘K dock, and `perf-budget.json` carries a gzip ceiling for all 23 routes.
- [ ] `README`/`ARCHITECTURE`/`SECURITY_MODEL`/`CLAUDE`/`PROJECT_STATE` all final and synced.

**Task checklist.**
- [ ] Production build + signing + auto-update (Windows) + update/rollback tests.
- [ ] Onboarding/first-run (sidecar provisioning + first governed turn).
- [ ] T-005 (audited): engine worktree-check native fix → retire option-C skips → full enforcement CI green.
- [ ] `contracts/` final dedupe (lease/approval/task-contract/mode-grant) + versioning. — **versioning is done, the dedupe is not** (see the Definition-of-Done row above), and `approval` names a schema that exists nowhere in the tree, so this row cannot be finished as written until the approval-request path is built.
- [ ] O-1..O-5 remediation (each its own audited engine branch/PR/Owner approval).
- [x] Production a11y + performance gate pass over all 22 pages; real HY copy. — **DONE 2026-08-29**, see the Definition-of-Done row above; the honest count is **23** route components in `pages.fixtures.tsx`, each measured in both themes by the browser axe sweep and each given its own gzip ceiling in `apps/desktop/perf-budget.json`.
- [ ] Finalize all docs; mark every phase ✅.

---

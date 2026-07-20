# Bro

> A governed Agent Operating System for one always-available conductor, specialized agent packs, hard runtime laws, evidence-backed execution, analytics, learning, and owner-controlled release authority.

> **Security remediation status (2026-07-19).** The independent adversarial audit of snapshot `60a94dc` (**RED: 2 Critical, 9 High, 4 Medium**) — a self-verifying trust root, a review-mode containment bypass, and more — has been **remediated**: blockers #1–#9 are merged (PRs #38–#50), followed by owner-environment hardening (PRs #51–#52). Each fix landed as an isolated PR with a regression test and **independent adversarial verification at its exact HEAD** — the auditor was never the sole verifier of a fix. A follow-up internal multi-agent review has since surfaced further correctness/hardening items, now being fixed the same way. Deployment additionally requires the owner-environment steps in [After the blockers](#after-the-blockers).

## What Bro is

Bro is Gev's single highest-ranking AI conductor. There is exactly one Bro: `bro-000`.

Bro converts a request into a governed task contract, selects the correct pack or cross-pack task force, remains available for new instructions, receives checkpoints, and reports only evidence-backed results.

## Core guarantees

- **One Bro only.** No subordinate role may use the Bro identity.
- **SST-first architecture.** Every domain has one canonical Single Source of Truth registered in `config/sst-registry.json`.
- **Hard execution gates.** Missing, stale, malformed, conflicting, or unverifiable state fails closed.
- **Scoped autonomy.** Agents may build only inside governed task boundaries.
- **Exact designated verification.** No broad role-name substring can grant verifier authority.
- **Evidence over claims.** Completion and release require signed, current evidence.
- **Protected release path.** Only the canonical Push Executor may transport an exact owner-approved candidate.
- **Recovery before GREEN.** Interrupted or ambiguous mutation blocks completion and release until proof-backed recovery or honest quarantine.
- **Canonical orchestration.** Task lifecycle, queue classes, routing policy, checkpoints, budgets, cancellation, recovery, quarantine, and Control Room commands are owned by one orchestration SST.
- **Durable runtime truth.** Task contracts and append-only SHA-256 chained runtime records live outside Git, with deterministic claims, expiring leases, evidence-backed checkpoints, budget gates, and fail-closed integrity checks.

## Current merged baseline

Execution Control Plane V2, Orchestration/Control Room V1 contracts, Orchestration Runtime V1, and Control Room API V1 are merged into `main`. The containment, issuance, and execution-integrity **components** are merged; `LIVE_PROVEN` is a traceability-validator label (a named test/path exists), **not** a proof of production wiring. The 2026-07-19 audit established that several of these are not wired end-to-end — see the caveats below.

> **`LIVE_PROVEN` caveat.** The label reflects validator-checked existence, not runtime wiring — but the wiring gaps the 2026-07-19 audit named are now closed (see the remediation section). A dedicated live-wiring assurance validator (`tools/bro_live_validate.py`, blocker 9b) runs each law's allow/deny cases through the wired interpreter and gates CI, so `ENFORCED` now means live-proven, not merely present.

- latest merged PR: `#52`
- main merge commit: `bc3b8533aa8f66ed5fa8693b23e0d16621cd4cc9`
- laws: 17 (L0–L16), live-proven by the assurance gate; includes L15 (secret confidentiality) and L16 (auditable stop + incident ledger)
- live enforcement: workspace binding, path scope, and the protected control-plane digest are wired into `runtime/bro_control_plane.py`
- issuance: Ed25519 authorities, an owner-signed trusted-key registry, and the `tools/broctl.py` minting/signing CLI; the external Supervisor issues leases in the one canonical execution-lease shape the runtime enforces (blocker 8b) and can produce a supervised builder's full authorization bundle (PR #52)
- execution integrity: signed execution receipts feed the completion verdict against the exact candidate (blocker 6a)
- STOP Controller v2 is wired into supervision with whole-group teardown and a corrected group-liveness check (blocker 8a)
- owner authorization has a green end-to-end bundle+ALLOW test; the durable-runtime completion path now requires an independent verifier-signed receipt (builder ≠ verifier, blocker 6b)
- legacy retired: the dead v1/v2 release-grant loaders are removed; Ed25519 Release Grant V3 is the only release path
- operational rollout: shadow (observe-only) enforcement, integrity-checked backup/restore, a live health monitor, and an operator runbook are merged
- CI: foundation GREEN on ubuntu-latest and windows-latest (SHA-pinned actions, `--require-hashes` deps, least-privilege token — blocker 9c); ~616 tests
- inventories: 52 packs, 42 skills, 63 documents

## Resolved findings and current open work

The 2026-07-16 audit findings against the PR #8 baseline are resolved:

- **Issuer.** `tools/broctl.py` mints and Ed25519-signs task contracts, agent profiles, mode grants and receipts against an operator-signed trusted-key registry.
- **Asymmetric signatures.** The evidence chain and execution receipts verify with Ed25519, so a builder key can no longer mint its own GREEN verifier receipt.
- **Contained reads.** Every tool action, reads included, is bound to the registered workspace and rejected on path escape before it runs.
- **Registered delegation.** `Agent`, `Task` and `Skill` classify as orchestration, so the conductor can delegate.
- **Conductor completion.** The conductor may end a turn with no bound task contract; it owes no builder evidence because it never builds.

Both prior open items are now closed:

- **Conductor bootstrap read deadlock — resolved (PR #15).** `runtime/bro_policy.py` grants the canonical conductor a read-only, allowlisted (`Read`/`Glob`/`Grep`), workspace-bound bootstrap exemption, so the enforcement wall stays up while Bro reads to orchestrate; it cannot authorize mutation, orchestration, push, unknown actions, or path escape.
- **Owner Authorization Phase 1 — merged (PRs #17–#27).** Every in-process-verified authorization artifact (mode grant, execution lease, completion manifest, verifier receipt, Release Grant V3, recovery record) is Ed25519-verified against an operator-signed trusted-key registry, not HMAC, so a policed builder process cannot forge its own authority. The mode grant anchors the task/agent/skill hashes; `tools/bro_skill_receipt.py` and `tools/bro_authorize_specialist.py` produce a specialist bundle; a first green end-to-end test proves an owner-produced bundle loads and binds.

## Operating modes

- **Review:** read and analyze only.
- **Work:** scoped mutation in an isolated verified worktree under signed one-time authority; push denied.
- **Release:** exact completion/verifier evidence, Release Grant V3, external credential boundary, canonical Push Executor only.

## Start here

1. Read `CLAUDE.md` and `AGENTS.md`.
2. Load every path from `config/canonical-read-manifest.json`.
3. Inspect `config/sst-registry.json` before changing any domain object.
4. Run `python tools/bro_validate.py`.
5. Run `python tools/bro_docs_freshness.py`.
6. Run `python -m unittest discover -s tests -v`.
7. Continue only when the exact repository state is GREEN.

> **Operator configuration required (trust anchor).** The operator-root public key is now pinned from **outside** the trusted-key registry. Before `bro_validate` or any signature-verifying runtime path will run, set the pin: production points `BRO_OPERATOR_ROOT_PUBKEY_FILE` at an operator-controlled file (absolute path, outside the repository, a regular non-symlink, not group/other-writable); CI passes the key in `BRO_OPERATOR_ROOT_PUBKEY`. If both are set they must match; a mismatch, or neither being set, is a hard failure. The registry payload is never the anchor.

## Security remediation (all blockers resolved)

All nine blockers from the 2026-07-19 independent adversarial audit are **resolved and merged**. Each was fixed one per PR, with a regression test and independent adversarial verification at the exact candidate HEAD — the auditor was not the sole verifier of a fix.

1. **Review-mode shell containment — resolved (PR #38).** Review mode denies shell/command tools and allows only structured `Read`/`Glob`/`Grep` (workspace-contained), non-shadowably.
   - **1b. Work-mode shell classifier — resolved.** A command-specific argument parser denies destructive shell such as `find . -delete` in work mode. (A follow-up review hardened `git -c` code-execution configs to the same standard.)
2. **External operator-key pin — resolved (PR #42).** The trusted-key registry is anchored to an owner-controlled operator public key held outside it — `BRO_OPERATOR_ROOT_PUBKEY_FILE` (production, OS-protected regular non-symlink file outside the repo) or `BRO_OPERATOR_ROOT_PUBKEY` (CI). A missing pin, a payload fallback, or a pin/registry mismatch hard-fails. Owner-side configuration remains an operator task — see `tools/bro_deploy_preflight.py`.
3. **Backup restore traversal — resolved (PR #39).** `bro_backup` restore rejects `..`, absolute paths, symlinks and duplicates and keeps the destination within the target.
4. **Corrupt monitor state — resolved (PR #40).** `bro_monitor` treats missing/unreadable runtime state as ATTENTION, not GREEN.
5. **Full secret redaction — resolved (PR #41).** Redaction removes entire PEM key bodies and covers modern token formats.
6. **Unified completion + evidence path — resolved (PRs #43, #44).** Execution receipts feed the completion verdict (6a); the durable runtime requires an independent, verifier-signed GREEN receipt, builder ≠ verifier (6b).
7. **Owner-signed recovery proof — resolved (PR #45).** `prove_recovery` requires a real owner-signed proof artifact via a dedicated `recovery` authority.
8. **STOP integration and Supervisor compatibility — resolved (PRs #46, #47).** The process-group liveness false-negative is fixed and the STOP controller is wired into supervision with whole-group teardown (8a); the supervisor issues the one canonical runtime-enforced execution lease (8b).
9. **Hardening — resolved (PRs #48, #49, #50).** Atomic audit-ledger append under a cross-process lock (9a), a fail-closed live-wiring assurance CI gate (9b), and CI supply-chain hardening — SHA-pinned actions, `--require-hashes` deps, least-privilege token, timeout, concurrency (9c).

Owner-environment hardening then landed (PRs #51–#52): a fail-closed deployment-posture preflight (`tools/bro_deploy_preflight.py`) and the supervisor's full builder-bundle producer. A follow-up internal multi-agent review is surfacing and closing further correctness/hardening items by the same one-PR, independently-verified process.

## After the blockers

- **Client integration contract:** expose Bro's enforced authority — mode grants, execution leases, the append-only audit chain, recovery state — to an operator client (e.g. BroPS) through a defined Bro-side integration surface, so a product UI's approval and evidence rest on the runtime wall rather than on its own local store. Bro-side work only; the client repository stays out of scope here.
- **Owner-environment hardening:** the dedicated non-admin account, workspace-scoped filesystem ACLs, a fine-grained GitHub credential, and the `main` branch ruleset. Owner-operated, outside any agent process.
- **Control Room visual surfaces:** the rendered surfaces belong to the operator client (BroPS); Bro exposes the read-only data and the client renders it.

A trust root cannot be issued by the system it roots, so the first bootstrap authority is signed by Gev by hand, outside any agent process.

## Authority

Gev is the owner. Bro plans, routes, delegates, and reports. Packs execute scoped work. Exact designated verifiers issue evidence-based verdicts. The Push Executor performs only the final transport step and never substitutes for owner approval or verification.

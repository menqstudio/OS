# Bro

> A governed Agent Operating System for one always-available conductor, specialized agent packs, hard runtime laws, evidence-backed execution, analytics, learning, and owner-controlled release authority.

> ⛔ **DEPLOYMENT BLOCKED — pending security remediation.** An independent adversarial audit of `main` (2026-07-19, snapshot `60a94dc`) returned **RED: 2 Critical, 9 High, 4 Medium**, including a self-verifying trust root and a review-mode containment bypass. The operational rollout is **scaffolded, not deployment-ready**. Do not deploy or enable mutation-capable usage until the blockers are closed — see [Security remediation](#security-remediation-deployment-blockers).

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

> **`LIVE_PROVEN` caveat.** The label reflects validator-checked existence, not runtime wiring. The audit found the STOP controller has no production caller (and a leader-only liveness false-negative), the external Supervisor's lease schema is rejected by the runtime, execution receipts do not feed the completion verdict, and the durable-runtime completion path requires no independent verifier. Read the items below as *components merged/scaffolded*, not *production-proven*.

- latest merged PR: `#36`
- main merge commit: `60a94dc1412bc41e592949281a623825ab66c76a`
- laws: 17 (L0–L16), all validator-labelled `LIVE_PROVEN` (see caveat); includes L15 (secret confidentiality) and L16 (auditable stop + incident ledger)
- live enforcement: workspace binding, path scope, and the protected control-plane digest are wired into `runtime/bro_control_plane.py` (no longer inert)
- issuance: Ed25519 authorities, a real owner-signed trusted-key registry (PR #29), and the `tools/broctl.py` minting/signing CLI; a Supervisor component issues leases — but its lease schema is not yet accepted by the runtime (audit blocker 8)
- execution integrity: signed execution receipts exist as a component; they do **not** yet feed the completion verdict (audit blocker 6)
- STOP Controller v2 exists but is **not wired** into the runtime and has a leader-only liveness false-negative (audit blocker 8)
- owner authorization has a green end-to-end bundle+ALLOW test (`authorize_tool` ALLOWs a specialist mutation against a real workspace binding, task lock, execution lease and recovery ledger, with failure and interruption drills, PRs #31, #33); however the **durable-runtime** completion path does not require an independent verifier (audit blocker 6)
- legacy retired: the dead v1/v2 release-grant loaders are removed; Ed25519 Release Grant V3 is the only release path (PR #30)
- operational rollout: shadow (observe-only) enforcement, integrity-checked backup/restore, a live health monitor, and an operator runbook are merged (PRs #32, #34, #35, #36)
- CI: foundation GREEN on ubuntu-latest and windows-latest (PR #36, 482 tests)
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

## Security remediation (deployment blockers)

The 2026-07-19 independent adversarial audit is RED; the components below are merged but **not deployment-ready**. These blockers are the priority and are fixed one per PR, each with a regression test and independent adversarial verification at the exact candidate HEAD — the auditor is not the sole verifier of a fix.

1. **Review-mode shell containment.** Review mode must deny shell/command tools and allow only structured `Read`/`Glob`/`Grep` (with `Glob` patterns workspace-contained), and that denial must be non-shadowable; unparsed shell arguments let `find . -delete` and out-of-workspace reads pass the read-only classification.
   - **1b. Work-mode shell classifier (separate blocker).** The same unparsed-shell classification means a destructive command such as `find . -delete` still classifies as a *non-mutating read* in work mode, where scope is enforced only for mutating actions. Closing it needs a command-specific argument parser.
2. **External operator-key pin.** The trusted-key registry must be anchored to an owner-controlled operator public key held outside the registry (OS-protected config / env / secret manager / HSM); a missing pin, a payload fallback, or a pin/registry mismatch must hard-DENY.
3. **Backup restore traversal.** `bro_backup` restore must reject `..`, absolute paths, symlinks and duplicates and require the destination to stay within the target.
4. **Corrupt monitor state.** `bro_monitor` must treat missing/unreadable runtime state as ATTENTION, not GREEN.
5. **Full secret redaction.** Redaction must remove entire PEM key bodies and cover modern token formats (`sk-proj-…`, `github_pat_…`).
6. **Unified completion + evidence path.** The durable runtime must require an independent, verifier-signed GREEN receipt (builder ≠ verifier) to complete, matching the Stop-gate; execution receipts must feed the completion verdict.
7. **Owner-signed recovery proof.** `prove_recovery` must require a real owner-signed proof artifact, not an arbitrary hex string.
8. **STOP integration and Supervisor compatibility.** Fix the process-group liveness check, wire the STOP controller into the runtime, and align the supervisor-issued lease schema and environment bundle with the runtime.
9. **Hardening.** Audit-log atomicity/locking, an assurance validator that proves live wiring (not path existence), and CI supply-chain hardening (pinned action SHAs, hashed dependencies, workflow permissions/timeout/concurrency).

## After the blockers

- **Client integration contract:** expose Bro's enforced authority — mode grants, execution leases, the append-only audit chain, recovery state — to an operator client (e.g. BroPS) through a defined Bro-side integration surface, so a product UI's approval and evidence rest on the runtime wall rather than on its own local store. Bro-side work only; the client repository stays out of scope here.
- **Owner-environment hardening:** the dedicated non-admin account, workspace-scoped filesystem ACLs, a fine-grained GitHub credential, and the `main` branch ruleset. Owner-operated, outside any agent process.
- **Control Room visual surfaces:** the rendered surfaces belong to the operator client (BroPS); Bro exposes the read-only data and the client renders it.

A trust root cannot be issued by the system it roots, so the first bootstrap authority is signed by Gev by hand, outside any agent process.

## Authority

Gev is the owner. Bro plans, routes, delegates, and reports. Packs execute scoped work. Exact designated verifiers issue evidence-based verdicts. The Push Executor performs only the final transport step and never substitutes for owner approval or verification.

# Bro

> A governed Agent Operating System for one always-available conductor, specialized agent packs, hard runtime laws, evidence-backed execution, analytics, learning, and owner-controlled release authority.

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

Execution Control Plane V2, Orchestration/Control Room V1 contracts, Orchestration Runtime V1, and Control Room API V1 are merged into `main`. On top of that foundation, the containment, issuance, and execution-integrity work is now merged and **live-wired** into the runtime, and all 17 laws (L0–L16) are traceability-backed and `LIVE_PROVEN`.

- latest merged PR: `#13`
- main merge commit: `5a095750000f1838abac6fe3e794a9d11bed63d0`
- laws: 17 (L0–L16), all `LIVE_PROVEN`; includes L15 (secret confidentiality) and L16 (auditable stop + incident ledger)
- live enforcement: workspace binding, path scope, and the protected control-plane digest are wired into `runtime/bro_control_plane.py` (no longer inert)
- issuance: Ed25519 authorities, an operator-signed trusted-key registry, and the `tools/broctl.py` minting/signing CLI; an external supervisor owns and issues execution leases
- execution integrity: signed execution receipts binding command, working tree, environment and runner identity
- STOP Controller v2: process-group termination with an append-only hash-chained audit ledger
- CI: foundation GREEN on ubuntu-latest and windows-latest (PR #13, 415 tests)
- inventories: 52 packs, 42 skills, 62 documents

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

## Next phase

- **Full execution-transaction E2E:** drive `authorize_tool` to ALLOW a specialist mutation end-to-end against a real worktree, workspace binding, task lock, execution-lease and recovery ledgers — the integration layer beyond the Phase 1 bundle proof.
- **Retire the legacy paths:** delete the dead `release-grant-v2` loader in `runtime/bro_contracts.py`.
- **Operational rollout:** shadow mode, canary tasks, failure drills, monitoring, backup/restore, and operator runbooks.
- **Control Room visual surfaces V1:** still deferred until routine task execution is exercised end-to-end.

A trust root cannot be issued by the system it roots, so the first bootstrap authority is signed by Gev by hand, outside any agent process.

## Authority

Gev is the owner. Bro plans, routes, delegates, and reports. Packs execute scoped work. Exact designated verifiers issue evidence-based verdicts. The Push Executor performs only the final transport step and never substitutes for owner approval or verification.

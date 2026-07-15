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

Execution Control Plane V2, Orchestration/Control Room V1 contracts, and Orchestration Runtime V1 foundation are merged into `main`.

- merged PR: `#6`
- approved candidate HEAD: `65f95171853cecacbfdff98be8e15884c1029909`
- main merge commit: `2395570bc9571e6c721373751a6dbfa2b6a8f75b`
- final CI run: `29392001475`
- Windows: GREEN
- Ubuntu: GREEN
- independent real-worktree audit: foundation GREEN; docs freshness GREEN
- runtime targeted tests: 14/14 GREEN
- full unique suite: 116/116 GREEN
- documentation inventory: 61/61 at merge
- open P0/P1 findings at merge: none

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

## Next product phase

The next scoped phase is **Control Room API V1**: governed read endpoints over validated runtime projections, evidence drill-down, task/agent/queue status, approval inbox, recovery/quarantine views, audit timeline, and command-intent validation. Visual UI, production credentials, external evidence-service deployment, BroPS, deployment, and production rollout remain separate phases.

## Authority

Gev is the owner. Bro plans, routes, delegates, and reports. Packs execute scoped work. Exact designated verifiers issue evidence-based verdicts. The Push Executor performs only the final transport step and never substitutes for owner approval or verification.

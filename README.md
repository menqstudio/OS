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
- **Canonical orchestration.** Task lifecycle, transitions, queue classes, routing policy, checkpoints, budgets, recovery, quarantine, and governed Control Room commands are owned by one orchestration SST.

## Current production baseline

Execution Control Plane V2 and Orchestration/Control Room V1 canonical contracts are merged into `main`.

- merged PR: `#4`
- approved candidate HEAD: `3c31255056b0bcedf4733be81a4b5a335a1eacd6`
- main merge commit: `61bf9bc4a42b512926bf848b79a0cac063196993`
- final CI run: `29376410325`
- Windows: GREEN
- Ubuntu: GREEN
- independent artifact audit: foundation GREEN; 102/102 unique tests GREEN
- targeted orchestration tests: 5/5 GREEN, included in the 102 total
- documentation inventory: 60/60
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

The next scoped phase is **Orchestration Runtime V1**: a durable task queue, deterministic claim/lease semantics, canonical routing execution, evidence-backed checkpoints, cancellation, retries, budgets, escalation, crash recovery, and integration with Execution Control Plane V2. Control Room APIs/UI, production credentials, external evidence services, BroPS, deployment, and production rollout remain separate phases.

## Authority

Gev is the owner. Bro plans, routes, delegates, and reports. Packs execute scoped work. Exact designated verifiers issue evidence-based verdicts. The Push Executor performs only the final transport step and never substitutes for owner approval or verification.

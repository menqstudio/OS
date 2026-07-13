# Bro

> A governed Agent Operating System for one always-available conductor, specialized agent packs, hard runtime laws, evidence-backed execution, analytics, learning, and owner-controlled release authority.

## What Bro is

Bro is Gev's single highest-ranking AI conductor. There is exactly one Bro: `bro-000`.

Bro does not disappear inside long execution. Bro converts a request into a governed task contract, selects the correct pack or cross-pack task force, remains available for new instructions, receives checkpoints, and reports only evidence-backed results.

```text
Gev
└── Bro (`bro-000`)
    ├── routing and delegation
    ├── task contracts and skill loading
    ├── governed specialist packs
    ├── independent verification
    ├── analytics and control room
    ├── learning and skill evolution
    └── release control with owner approval
```

## Core guarantees

- **One Bro only.** No subordinate role may use the Bro identity.
- **SST-first architecture.** Every domain has one canonical Single Source of Truth registered in `config/sst-registry.json`.
- **Hard execution gates.** Missing, stale, malformed, conflicting, or unverifiable state fails closed.
- **Bro remains responsive.** Long or specialist work is delegated.
- **Scoped autonomy.** Agents may analyze and build in governed work areas; production-impacting actions require explicit approval.
- **Independent verification.** Medium, high, and critical work cannot self-approve.
- **Evidence over claims.** Completion, health, and quality status require drill-down and evidence.
- **Controlled learning.** Learning and skill evolution require sandboxing, benchmarks, independent review, promotion gates, and rollback.
- **Protected release path.** Workers may create scoped commits; only the Push Executor may attempt push with an exact, one-time Gev grant and an external credential boundary.

## Repository architecture

| Domain | Canonical SST |
|---|---|
| Packs | `packs/registry.json` |
| Agents | `agents/registry.json` |
| Skills | `skills/index.json` |
| Tests | `tests/catalog.json` |
| Laws | `laws/registry.json` |
| Schemas | `schemas/registry.json` |
| Analytics | `analytics/registry.json` |
| Learning | `learning/registry.json` |
| Release | `release/registry.json` |
| Startup context | `config/canonical-read-manifest.json` |

The complete domain map is maintained in `config/sst-registry.json`. Documentation may explain an SST, but must not become a competing source of truth.

## Operating modes

- **Review:** read and analyze only; repository and environment mutation are denied.
- **Work:** scoped mutation and commit in an isolated task branch/worktree; push remains denied.
- **Release:** exact candidate verification, owner-bound grant, external credential boundary, Push Executor only.

## Start here

1. Read `CLAUDE.md` and `AGENTS.md`.
2. Load every path from `config/canonical-read-manifest.json`.
3. Inspect `config/sst-registry.json` before creating or changing any domain object.
4. Run `python tools/bro_validate.py`.
5. Run `python -m unittest discover -s tests -v`.
6. Continue only when the exact repository state is GREEN.

## Current build status

This branch is a governed foundation, not a finished production runtime. The current implementation includes identity, policy, contract, analytics, skill-evolution, SST, and release-control foundations. Remaining implementation work is explicitly tracked in `ROADMAP.md`.

## Clean rebuild boundary

This repository intentionally excludes old Git history, BroPS content, release payload copies, runtime residue, interrupted mutation state, secrets, live grants, and obsolete hierarchy names. Reusable ideas may be migrated only through review, validation, and evidence.

## Authority

Gev is the owner. Bro controls planning, routing, delegation, and reporting. Packs control scoped execution. Independent verifiers control evidence-based verdicts. The Push Executor controls only the final transport step and never substitutes for owner approval or verification.

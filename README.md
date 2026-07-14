# Bro

> A governed Agent Operating System for one always-available conductor, specialized agent packs, hard runtime laws, evidence-backed execution, analytics, learning, and owner-controlled release authority.

## What Bro is

Bro is Gev's single highest-ranking AI conductor. There is exactly one Bro: `bro-000`.

Bro converts requests into governed task contracts, selects the correct pack or cross-pack task force, remains available for new instructions, receives checkpoints, and reports only evidence-backed results.

## Core guarantees

- **One Bro only.** No subordinate role may use the Bro identity.
- **SST-first architecture.** Every domain has one canonical source registered in `config/sst-registry.json`.
- **Hard execution gates.** Missing, stale, malformed, conflicting, or unverifiable state fails closed.
- **Canonical authorization.** Direct tools and shell actions use one capability classifier; unknown actions are denied.
- **Exact designated verification.** Broad role-name matching is forbidden; medium, high, and critical work cannot self-approve.
- **Verified repository state.** Mutation binds worktree, CWD, branch, HEAD, tracked and untracked non-ignored files, task, agent, session, and one exclusive worktree lock.
- **One-time execution.** Signed execution leases reserve atomically, deny replay, and quarantine ambiguity.
- **Evidence before completion.** Stop requires signed completion evidence and, when required, an independent verifier receipt.
- **Owner-controlled release.** Only the canonical Push Executor may use Release Grant V3 for an exact push.
- **Recovery before GREEN.** Interrupted or ambiguous mutation blocks completion and release until proof-backed recovery or honest quarantine.

## Canonical sources

| Domain | Canonical SST |
|---|---|
| Packs | `packs/registry.json` |
| Agents | `agents/registry.json` |
| Agent authority | `agents/authority-policy.json` |
| Skills | `skills/index.json` |
| Tests | `tests/catalog.json` |
| Laws | `laws/registry.json` |
| Schemas | `schemas/registry.json` |
| Analytics | `analytics/registry.json` |
| Learning | `learning/registry.json` |
| Release | `release/registry.json` |
| Tool capabilities | `tools/registry.json` |
| Documentation freshness | `config/documentation-manifest.json` |
| Startup context | `config/canonical-read-manifest.json` |

## Operating modes

- **Review:** read and analyze only.
- **Work:** scoped mutation in a verified task worktree under a signed one-time execution lease; push denied.
- **Release:** exact completion/verifier evidence, Release Grant V3, external credential boundary, canonical Push Executor only.

## Validation

```bash
python tools/bro_validate.py
python tools/bro_docs_freshness.py
python -m unittest discover -s tests -v
```

## Current build status — 2026-07-14

Security phases 1–7 are implemented. The exact candidate `a8ab286a8f45e34214ec709f6f38e0843b06e791` passed Windows and Ubuntu CI run `29365674292`. Independent artifact audit passed foundation validation, **95/95 tests**, documentation inventory **59/59**, designated-verifier checks, full current-tree identity checks, recovery CAS contention checks, and Release V3 executor-state checks.

The PR remains draft/open/unmerged. The remaining gate is Gev's explicit approval bound to the final exact candidate after this documentation-only refresh also passes exact-head CI.

## Boundaries

BroPS is out of scope. Production credential isolation, external evidence-service deployment, and operational rollout remain separate trust-boundary work.

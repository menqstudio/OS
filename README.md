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

Execution Control Plane V2, Orchestration/Control Room V1 contracts, Orchestration Runtime V1, and Control Room API V1 are merged into `main`.

- merged PR: `#8`
- approved candidate HEAD: `f2c457a675248eb805c02889509a40d8a5e1c520`
- main merge commit: `f736bce585e0e911c36a73d0181c8eb4ef3aebef`
- final CI run: `29434543079`
- Windows: GREEN
- Ubuntu: GREEN
- independent exact-head real-worktree audit: foundation GREEN; docs freshness GREEN
- Control Room API targeted tests: 12/12 GREEN
- full unique suite: 128/128 GREEN
- documentation inventory: 62/62 at merge

## Open findings

An independent audit on 2026-07-16 found the merged baseline is not operable and
not self-defending. These are open:

- **No issuer.** The repository validates signed task contracts, completion
  manifests, verifier receipts, evidence events and mode grants that nothing in
  the repository can produce. There is no signer, no key generation, no CLI.
  Every gate therefore fails closed on an artifact that cannot exist yet.
- **Symmetric signatures.** `verify_signed_document` is HMAC, so the verifying
  key is the signing key. The hook runs inside the agent's own process, so a
  builder holds the key that mints its own GREEN verifier receipt. Verifier
  independence is unenforceable until signatures are asymmetric.
- **Unscoped local reads.** `READ_LOCAL` carries `requires_scope: false`, so any
  path on the machine is readable, and `WebFetch` is classified as a read. Read
  anything, send anywhere.
- **Delegation is unregistered.** `Agent`, `Task` and `Skill` are absent from the
  tool registry, so the conductor's only sanctioned action classifies as UNKNOWN
  and denies.
- **The conductor cannot finish a turn.** The Stop gate demands a specialist
  completion manifest from an agent that by design never executes.

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

Containment, not surfaces. Control Room visual surfaces are deferred until Bro
can actually run.

- **Phase A — containment.** External walls first, because they are the only work
  with no bootstrap dependency: a dedicated non-admin account for the agent, NTFS
  ACLs limited to the registered workspace, a fine-grained credential scoped to
  this repository alone, and a `main` ruleset with no bypass. In-repository:
  workspace binding, path scope enforcement, and the protected control-plane
  digest.
- **Phase B — issuance.** Ed25519 authorities, an operator-signed public key
  registry, an issuer CLI, and an external supervisor that owns leases. The
  conductor never holds a lease; a builder runs as a separate process with the
  lease injected only into it.
- **Phase C — execution integrity.** Signed test receipts binding command,
  working tree, environment and runner identity, so "I ran the tests" becomes
  checkable rather than trusted.

A trust root cannot be issued by the system it roots, so the first bootstrap
authority is signed by Gev by hand, outside any agent process.

## Authority

Gev is the owner. Bro plans, routes, delegates, and reports. Packs execute scoped work. Exact designated verifiers issue evidence-based verdicts. The Push Executor performs only the final transport step and never substitutes for owner approval or verification.

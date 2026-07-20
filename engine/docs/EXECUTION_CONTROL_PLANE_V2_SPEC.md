# Bro Execution Control Plane V2 — Normative Security Specification

**Status:** Implemented, independently audited, and merged to `main`  
**Repository:** `menqstudio/Bro`  
**Merged PR:** `#2`  
**Merged candidate:** `66788ee5876871d36038d9e19ce54f9fec864684`  
**Merge commit:** `3250d4cc55edc2adf8e5247deab8060983de3b47`  
**Owner:** Gev

## Purpose

Bro V2 forms one fail-closed execution chain connecting capability, identity, task authority, repository state, one-time execution authority, evidence, independent verification, completion, recovery, and release.

Every security-sensitive request resolves to `ALLOW`, `DENY`, `WAIT_FOR_APPROVAL`, or `QUARANTINE`. Hooks are adapters; canonical authorization lives in the Control Plane modules.

## Mandatory invariants

```text
No mutation without a canonical agent.
No verifier authority from a role-name substring.
No mutation without an exact signed one-time execution lease.
No mutation outside the verified task worktree.
No unknown tool, sub-action, executable, or capability.
No scope expansion without exact authority.
No completion without signed evidence and current repository binding.
No required verification without a canonical designated verifier.
No release without exact owner, evidence, HEAD, tree, branch, remote, and nonce binding.
No GREEN while execution, release, or recovery state is pending or ambiguous.
No false claim that an irreversible external effect was restored.
```

## Trust boundaries

1. Gev — owner authority and explicit merge/release approval.
2. Bro — plans, routes, delegates, and reports; does not mutate.
3. Builder agents — scoped work under task contracts and execution leases.
4. Designated verifiers — exact canonical verifier roles or exact policy overrides.
5. Push Executor — canonical release transport authority only.
6. Control Plane — classifies, authorizes, reserves, settles, and quarantines.
7. External ledgers/evidence stores — outside ordinary agent write authority.
8. Credential boundary — outside model-controlled state.

## Implemented controls

- One canonical tool/action classifier backed by `tools/registry.json`; unknown actions are denied.
- Deterministic immutable agent IDs and exact designated verifier authority.
- Mutation binding to registered worktree, CWD, branch, HEAD, tracked and untracked non-ignored files, task, agent, session, and one exclusive external worktree lock.
- Signed one-time execution leases with atomic reservation, replay denial, and ambiguity quarantine.
- Signed evidence chain, completion manifest, verifier receipt, and fail-closed Stop gate.
- Release Grant V3 with exact owner, evidence, repository, remote, branch, HEAD, tree, command, Push Executor, and one-time nonce binding.
- Signed recovery journal with guarded compare-and-swap transitions, proof-backed restoration, quarantine, and honest irreversible-effect outcomes.
- Completion and release remain blocked while execution, release, or recovery state is unresolved.

## Audit evidence — 2026-07-14

- Audited code candidate: `a8ab286a8f45e34214ec709f6f38e0843b06e791`.
- Final merged candidate: `66788ee5876871d36038d9e19ce54f9fec864684`.
- Final PR CI run `29365910692`: Windows GREEN and Ubuntu GREEN.
- Independent artifact audit: foundation validator GREEN and 95/95 tests GREEN.
- Documentation inventory: 59/59 active Markdown and `SKILL.md` files.
- Open P0/P1 findings at merge: none.

## Product boundary

This specification governs the merged execution-control foundation. Production credential isolation, external evidence-service deployment, orchestration product surfaces, operational rollout, and future product UX remain separate phases requiring their own audited branches and owner-approved merges.

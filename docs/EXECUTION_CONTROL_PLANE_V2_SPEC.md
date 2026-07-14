# Bro Execution Control Plane V2 — Normative Security Specification

**Status:** Implemented and independently audited; owner-approved merge pending  
**Repository:** `menqstudio/Bro`  
**Target branch:** `bro-execution-control-plane-v2`  
**Draft PR:** `#2`  
**Base commit:** `a0f40d5aa3de96f05f2a9f90cdfd0f4e09fa7bca`  
**Owner:** Gev

## 1. Purpose

Bro V2 forms one fail-closed execution chain connecting tool capability, canonical identity, task authority, repository state, one-time execution authority, evidence, independent verification, completion, recovery, and release.

Every security-sensitive request resolves to `ALLOW`, `DENY`, `WAIT_FOR_APPROVAL`, or `QUARANTINE`. Hooks are adapters; canonical authorization lives in the Control Plane modules.

## 2. Mandatory invariants

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

## 3. Trust boundaries

1. Gev / owner authority — exact approvals and final merge authorization.
2. Bro conductor — plans, routes, delegates, and reports; does not mutate.
3. Builder agent — scoped work under a task contract and execution lease.
4. Designated verifier — final declared verifier role or exact policy override.
5. Push Executor — canonical `git-release-control` transport authority only.
6. Control Plane — classifies, authorizes, reserves, settles, and quarantines.
7. External ledgers/evidence stores — outside the repository and ordinary agent write authority.
8. Credential boundary — outside model-controlled state.

## 4. Canonical capability model

Every request is normalized through `tools/registry.json`. Unknown tool, action, executable, wrapper, or capability is denied. Direct tools and shell commands share one classifier path.

## 5. Canonical identity and authority

Identity is deterministic: `pack + role + ordinal -> exact canonical agent_id`.

Task contract, agent profile, environment identity, execution lease, verifier receipt, completion manifest, and release evidence must describe the same exact principals.

Verifier authority is never inferred from words such as `Reviewer`, `Tester`, `Auditor`, or `Evaluator`. For packs requiring independent verification, only the exact designated role may verify; exceptional release roles require exact overrides.

## 6. Repository execution binding

Before mutation the Control Plane verifies:

- absolute registered Git worktree;
- process CWD inside that exact worktree;
- task branch equals current branch;
- task HEAD equals current HEAD;
- tree identity covers tracked and untracked non-ignored files, including symlink identity;
- direct `main`/`master` mutation is denied;
- one external lock slot per normalized worktree;
- lock binds schema, active state, task, agent, session, worktree, branch, HEAD, and tree;
- lock ledger and lock file cannot escape through repository placement or symlink substitution;
- resolved targets remain in allowed scope and outside prohibited scope.

## 7. One-time execution leases

A signed lease binds lease ID, nonce, task, agent, session, repository, branch, worktree, HEAD, tree, capabilities, issue/expiry time, and call limit.

Reservation is atomic. Active reuse, replay, expiry, wrong binding, missing capability, and ambiguity are denied. Success consumes the lease. Failure or unknown outcome quarantines it pending recovery.

## 8. Evidence, completion, and verification

Completion requires a signed completion manifest, exact current-state binding, satisfied criteria with evidence, passed tests, no open risks, rollback readiness, clean repository, no active or ambiguous lease, and no unresolved recovery state.

When verification is required, the signed receipt binds the exact builder, designated verifier, task hash, manifest hash, candidate HEAD/tree, evidence chain, GREEN verdict, time validity, authority ceiling, and minimum independence level. Stop fails closed when any requirement is missing or stale.

## 9. Release Grant V3

Live push accepts only schema `3`; historical V2 validation is audit-only.

Release requires canonical Push Executor identity in release mode, confirmed external credential boundary, valid completion/verifier evidence, exact owner `owner-gev`, exact hashes, repository, origin remote, branch, HEAD, tree, command shape, and one-time nonce.

Authorization and settlement both validate canonical executor state. Settlement distinguishes success, proven remote absence, proven exact remote HEAD, and ambiguity. Ambiguity quarantines the nonce and blocks GREEN.

## 10. Recovery

Before mutation a signed external recovery record captures task, agent, session, tool-use ID, action hash, capabilities, targets, HEAD, tree, and Git-status hash.

Recovery transitions use versioned compare-and-swap guarded by an atomic external transition lock and durable temp-write replacement. Concurrent or interrupted transitions fail closed for reconciliation.

```text
REVERSIBLE -> RECOVERY_REQUIRED
COMPENSATABLE -> RECOVERY_REQUIRED
UNKNOWN -> QUARANTINED
IRREVERSIBLE -> FAILED_WITH_IRREVERSIBLE_EFFECT
```

A reversible or compensatable action may move to rework only after HEAD, full tree identity, and status hash exactly match the recorded original state and a valid proof hash exists. Unknown or irreversible effects cannot be marked restored.

## 11. Implemented phases

1. Tool authorization kernel.
2. Canonical identity and exact designated verifier authority.
3. Repository/worktree/current-state binding.
4. One-time execution leases.
5. Completion manifest, evidence, verifier receipt, Stop gate.
6. Release Grant V3 and release settlement.
7. Signed interruption recovery and completion/release recovery blocker.

## 12. Audit evidence — 2026-07-14

Audited code candidate: `a8ab286a8f45e34214ec709f6f38e0843b06e791`.

- Windows and Ubuntu CI run `29365674292`: GREEN.
- Foundation validator: GREEN.
- Independent artifact tests: 95/95 GREEN.
- Documentation inventory: 59/59.
- No open P0/P1 finding after remediation.

The documentation-only finalization commit must also pass exact-head CI. PR #2 remains draft/open/unmerged until Gev explicitly authorizes merge against the exact final HEAD.

## 13. Product claim boundary

Production credential isolation, external evidence-service deployment, operational hardening, and product rollout remain separate trust-boundary work. Technical readiness does not imply merge approval or production deployment.

# Bro Execution Control Plane V2 — Normative Security Specification

**Status:** Implemented security specification; phases 1–7 exact-head CI GREEN, final independent audit pending  
**Repository:** `menqstudio/Bro`  
**Target branch:** `bro-execution-control-plane-v2`  
**Draft PR:** `#2`  
**Base commit:** `a0f40d5aa3de96f05f2a9f90cdfd0f4e09fa7bca`  
**Owner:** Gev  
**Runtime behavior:** Implemented on the draft branch; merge remains owner-controlled

## 1. Purpose

Bro V2 forms one fail-closed execution chain connecting tool capability, canonical identity, task authority, repository state, one-time execution authority, evidence, independent verification, completion, recovery, and release.

Every security-sensitive request resolves to one machine decision:

```text
ALLOW
DENY
WAIT_FOR_APPROVAL
QUARANTINE
```

Hooks are adapters. Canonical authorization lives in the Control Plane modules.

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

1. **Gev / owner authority** — exact approvals and final merge authorization.
2. **Bro conductor** — plans, routes, delegates, and reports; does not mutate.
3. **Builder agent** — performs scoped work under a task contract and execution lease.
4. **Designated verifier** — the final declared role of a pack requiring independent verification, or an exact policy override.
5. **Push Executor** — canonical `git-release-control` transport authority only.
6. **Control Plane** — classifies, authorizes, reserves, settles, and quarantines.
7. **External ledgers/evidence stores** — outside the repository and ordinary agent write authority.
8. **Credential boundary** — outside model-controlled state.

## 4. Canonical action and capability model

Every request is normalized before authorization. The Tool Capability Registry is `tools/registry.json`.

Capability classes include:

```text
READ_LOCAL
READ_EXTERNAL
WRITE_REPOSITORY
WRITE_FILESYSTEM
WRITE_EXTERNAL
EXECUTE_CODE
USE_NETWORK
USE_CREDENTIAL
SEND_COMMUNICATION
PUBLISH
SPEND
CHANGE_ACCESS
DELETE
DESTRUCTIVE
UNKNOWN
```

Unknown tool, action, executable, wrapper, or capability is denied.

## 5. Canonical identity and authority

Identity is deterministic:

```text
pack + role + ordinal -> exact canonical agent_id
```

Task contract, agent profile, environment identity, execution lease, verifier receipt, completion manifest, and release evidence must describe the same exact principals.

Verifier authority is not inferred from words such as `Reviewer`, `Tester`, `Auditor`, or `Evaluator`. For packs with `independent_verifier_required=true`, only the final declared role is the designated verifier. Exact policy overrides cover exceptional release roles.

## 6. Repository execution binding

Before mutation the Control Plane verifies:

- absolute registered Git worktree;
- process CWD inside that exact worktree;
- task branch equals current branch;
- task HEAD equals current HEAD;
- task tree identity equals current tracked-file tree;
- direct `main`/`master` mutation is denied;
- external active-task lock matches task/worktree/branch/HEAD/tree;
- resolved targets remain in allowed scope and outside prohibited scope.

## 7. One-time execution leases

A signed lease binds:

- lease ID and nonce;
- task, agent, session;
- repository, branch, worktree, HEAD, tree;
- exact capabilities;
- issue/expiry time and call limit.

Reservation is atomic. Active reuse, replay, expiry, wrong binding, missing capability, and ambiguous state are denied. Success consumes the lease. Failure or unknown outcome quarantines it pending recovery.

## 8. Evidence, completion, and verification

Completion requires:

- signed completion manifest;
- exact task/agent/current HEAD/current tree binding;
- satisfied done criteria with evidence references;
- passed tests;
- no open risks;
- rollback readiness;
- clean repository;
- no active/ambiguous lease;
- no unresolved recovery state.

When verification is required, the signed verifier receipt must bind the exact builder, designated verifier, task hash, manifest hash, candidate HEAD/tree, evidence chain, GREEN verdict, time validity, authority risk ceiling, and minimum independence level.

The Stop hook fails closed when any requirement is missing or stale.

## 9. Release Grant V3

Live push accepts only schema `3`. Historical V2 validation remains audit-only.

Release requires:

- canonical Push Executor identity and release mode;
- confirmed external credential boundary;
- valid completion manifest and verifier receipt;
- exact owner principal `owner-gev`;
- exact task/manifest/receipt hashes;
- exact repository, origin remote, branch, HEAD, and tree;
- exact push command shape;
- one-time nonce reservation.

Settlement distinguishes success, proven remote absence, proven exact remote HEAD, and ambiguity. Ambiguity quarantines the nonce and blocks GREEN.

## 10. Recovery

Before mutation a signed external recovery record captures task, agent, session, tool-use ID, action hash, capabilities, targets, HEAD, tree, and Git-status hash.

Recovery state uses compare-and-swap versioning. Interruption or failed mutation transitions according to effect class:

```text
REVERSIBLE -> RECOVERY_REQUIRED
COMPENSATABLE -> RECOVERY_REQUIRED
UNKNOWN -> QUARANTINED
IRREVERSIBLE -> FAILED_WITH_IRREVERSIBLE_EFFECT
```

A reversible or compensatable action may move to rework only after current HEAD, tree, and status hash exactly match the recorded original state and a recovery proof hash exists. Unknown or irreversible effects cannot be marked restored.

## 11. Implemented phases

1. Tool authorization kernel.
2. Canonical identity and exact designated verifier authority.
3. Repository/worktree/current-state binding.
4. One-time execution leases.
5. Completion manifest, evidence, verifier receipt, Stop gate.
6. Release Grant V3 and release settlement.
7. Signed interruption recovery and completion/release recovery blocker.

## 12. Acceptance gates

Final V2 GREEN requires all of the following on the same exact HEAD:

- foundation validator GREEN;
- documentation freshness validator GREEN;
- full test suite GREEN on Windows and Ubuntu;
- Python compile GREEN;
- canonical audit snapshot produced;
- no open P0/P1 independent-audit finding;
- PR metadata accurately describes actual runtime changes;
- PR remains draft until Gev explicitly authorizes merge.

CI success alone is not an independent audit. An older successful run is never evidence for a newer HEAD.

## 13. Product claim boundary

Until the final exact-head audit and owner-authorized merge, the repository remains a draft implementation of the Bro Agent OS Governance Foundation and Execution Control Plane V2. Production credential isolation, external evidence-service hardening, and operational deployment remain separate trust-boundary work.

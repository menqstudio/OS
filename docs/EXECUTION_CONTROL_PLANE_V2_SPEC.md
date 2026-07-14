# Bro Execution Control Plane V2 — Normative Security Specification

**Status:** Draft normative specification  
**Repository:** `menqstudio/Bro`  
**Target branch:** `bro-execution-control-plane-v2`  
**Base commit:** `a0f40d5aa3de96f05f2a9f90cdfd0f4e09fa7bca`  
**Owner:** Gev  
**Runtime behavior changed by this commit:** None

This document defines the security architecture required before Bro may be described as a zero-trust agent execution operating system. It is a design and acceptance contract only. Runtime code, hooks, policies, grants, schemas, and workflows remain unchanged until later remediation phases.

---

## 1. Purpose

Bro V1 provides a governed Agent OS foundation with strong Git/release controls. The remaining gap is end-to-end execution integrity: separate gates exist, but they do not yet form one atomic chain connecting identity, task, repository state, tool capability, worktree, approval, evidence, verification, completion, recovery, and release.

V2 introduces one logical authority:

> **Bro Execution Control Plane**

Every security-sensitive action must resolve through this authority and receive exactly one machine-readable decision:

```text
ALLOW
DENY
WAIT_FOR_APPROVAL
QUARANTINE
```

Hooks must become adapters. They may collect input and enforce the returned decision, but they must not independently implement competing authorization logic.

---

## 2. Security objectives

The Control Plane must guarantee the following invariants:

```text
No mutation without a canonical agent.
No mutation without an active one-time execution lease.
No mutation outside the verified task worktree.
No action without a registered tool/action capability.
No unknown tool or action.
No scope expansion without exact approval.
No required verification without a canonical independent verifier.
No completion without completion evidence.
No release without exact evidence-chain binding.
No GREEN while execution or recovery state is ambiguous.
```

Each invariant must have at least one positive test and one bypass-oriented negative test.

---

## 3. Non-goals

This specification does not:

- add packs, agents, skills, laws, dashboards, or product UI;
- make Bro autonomous by itself;
- replace host, OS, GitHub, credential, or cloud security;
- claim protection against a fully privileged local administrator;
- allow direct mutation of `main`;
- permit merge without Gev's explicit approval.

The immediate target is runtime integrity, not inventory expansion or orchestration UX.

---

## 4. Threat model

### 4.1 In-scope threats

The system must fail closed against:

- malformed or forged task, profile, grant, lease, approval, manifest, or verifier data;
- non-canonical or fake agent and verifier identifiers;
- duplicated mutation classifiers with semantic drift;
- unknown tools, MCP actions, connectors, or custom actions;
- command wrappers, aliases, redirections, substitutions, chained commands, and unknown executables;
- repository, branch, HEAD, tree, CWD, scope, and worktree mismatch;
- replayed work authority or release authority;
- concurrent task use of one worktree;
- incomplete work claiming completion;
- release without evidence and verifier binding;
- interruption, ambiguous tool outcomes, stale reservations, and partial mutation;
- silent continuation after budget or approval boundaries;
- evidence deletion, reordering, or modification detectable through chain validation.

### 4.2 Out-of-scope threats

V2 does not claim absolute protection when an attacker controls:

- the operating-system administrator account;
- the Control Plane signing keys;
- the evidence-store authority and its external anchors;
- GitHub organization ownership;
- the host process before hooks execute.

These are external trust anchors and must be documented, isolated, monitored, and rotated.

---

## 5. Trust boundaries

The design recognizes separate principals:

1. **Owner authority** — Gev; provides exact approvals.
2. **Bro conductor** — decomposes and routes; does not mutate.
3. **Builder agent** — performs scoped work under a lease.
4. **Verifier agent** — independently evaluates the candidate.
5. **Push Executor** — performs exact approved release transport.
6. **Control Plane service** — authorizes actions and commits state transitions.
7. **Evidence signer/store** — appends and anchors evidence; must not be writable by ordinary agents.
8. **Credential boundary** — holds repository/external credentials outside model-controlled state.

The implementation must not collapse these roles merely because they share a host.

---

## 6. Component architecture

The logical authority must be modular rather than one monolithic module.

```text
runtime/control_plane/
  decision.py
  capabilities.py
  classifier.py
  identity.py
  verifier.py
  repository_state.py
  state_machine.py
  leases.py
  approvals.py
  evidence.py
  completion.py
  release.py
  recovery.py
  transactions.py
```

A thin compatibility facade may exist at `runtime/bro_authorization.py`, but it must delegate to these modules.

The pure decision layer must be deterministic for the same normalized input and trusted state snapshot. Side effects such as reservations, state writes, and evidence append operations must occur in a transaction layer.

---

## 7. Canonical action model

Every tool request must be normalized into one action object before authorization.

```json
{
  "request_id": "req-...",
  "session_id": "ses-...",
  "task_id": "tsk-...",
  "agent_id": "agt-...",
  "tool": "GitHub",
  "action": "update_file",
  "normalized_arguments_hash": "sha256:...",
  "capabilities": ["WRITE_EXTERNAL"],
  "targets": ["menqstudio/Bro:runtime/example.py"],
  "repository": "menqstudio/Bro",
  "branch": "task-123",
  "cwd": "...",
  "timestamp": 0
}
```

Authorization may not depend only on the top-level tool name.

---

## 8. Tool Capability Registry

A canonical registry must map tools and sub-actions to capability classes.

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

Normative rules:

- Unknown tool = `DENY`.
- Unknown sub-action = `DENY`.
- Registry entries must declare whether scope, task, lease, approval, network allowlist, credentials, or post-action settlement are required.
- Shell tools require command classification in addition to registry classification.
- Registry updates require validator changes and negative tests in the same commit.

Example:

```json
{
  "tool": "GitHub",
  "actions": {
    "fetch_file": {
      "capabilities": ["READ_EXTERNAL"]
    },
    "update_file": {
      "capabilities": ["WRITE_EXTERNAL"],
      "requires_task": true,
      "requires_lease": true,
      "requires_scope": true
    },
    "merge_pull_request": {
      "capabilities": ["WRITE_EXTERNAL", "PUBLISH"],
      "requires_exact_approval": true,
      "requires_release_state": true
    }
  }
}
```

---

## 9. Unified classifier

There must be one canonical classifier:

```python
classify_tool_action(tool_name, tool_input) -> Classification
```

It must be used by:

- pre-tool authorization;
- identity enforcement;
- scope enforcement;
- evidence logging;
- completion accounting;
- release settlement;
- recovery analysis.

The existing identity-hook regex may remain temporarily only as defense in depth. It must not be the source of the identity guarantee.

---

## 10. Canonical identity enforcement

Identity must be resolved inside the core contract gate.

```text
pack + role + ordinal -> exact canonical agent ID
```

The following values must match exactly:

```text
profile.agent_id
profile.pack_id
profile.role
task.agent_id
task.pack_id
task.role
environment agent identity
lease.agent_id
grant/approval agent binding, when applicable
```

A syntactically valid but non-canonical ID must be denied before any mutation decision.

---

## 11. Agent Authority Registry

Canonical identity alone is insufficient. Each agent must have machine-readable authority.

```json
{
  "agent_id": "agt-p20-r05",
  "pack_id": "zero-trust-verification",
  "role": "Independent Verifier",
  "can_build": false,
  "can_verify": true,
  "can_release": false,
  "allowed_modes": ["review", "work"],
  "risk_ceiling": "critical",
  "allowed_capabilities": ["READ_LOCAL", "READ_EXTERNAL", "EXECUTE_CODE"]
}
```

Task-required skills must be compatible with the permanent core skills and authority profile. Empty or contradictory skill selection must be denied.

---

## 12. Verifier authority and independence

For tasks requiring verification, the verifier must:

- exist in the canonical Agent SST;
- have an exact deterministic ID;
- have `can_verify=true`;
- support the task risk class;
- differ from the builder;
- use a separate execution lease;
- sign its own verdict;
- verify the exact candidate HEAD and tree.

Independence levels:

```text
L1 — different canonical agent identity
L2 — separate process and execution lease
L3 — isolated context without builder reasoning transcript
L4 — separate credential or execution authority
L5 — external independent reviewer
```

The risk policy must define the minimum required level. Critical release work may not rely solely on L1.

---

## 13. Task state machine

Canonical states:

```text
CREATED
PLANNED
APPROVED
LEASED
PREPARING_WORKTREE
RUNNING
BUILDER_DONE
VERIFYING
VERIFIED_GREEN
RELEASE_READY
RELEASED
COMPLETED
FAILED
RECOVERING
RECOVERED
REWORK_REQUIRED
CANCELLED
QUARANTINED
```

Transitions must be explicit and atomic. Examples:

```text
CREATED -> PLANNED
PLANNED -> APPROVED
APPROVED -> LEASED
LEASED -> PREPARING_WORKTREE
PREPARING_WORKTREE -> RUNNING
RUNNING -> BUILDER_DONE
BUILDER_DONE -> VERIFYING
VERIFYING -> VERIFIED_GREEN
VERIFIED_GREEN -> RELEASE_READY
RELEASE_READY -> RELEASED
RELEASED -> COMPLETED
RUNNING -> FAILED
FAILED -> RECOVERING
RECOVERING -> RECOVERED
RECOVERED -> REWORK_REQUIRED
ANY -> QUARANTINED
```

Invalid transitions include:

- `RUNNING -> COMPLETED` when verification is required;
- `BUILDER_DONE -> RELEASE_READY` without a valid verifier receipt;
- any mutation-capable state without an active lease;
- any GREEN terminal claim while state or tool outcome is ambiguous.

Persistent state must include `state_version`. Transitions require compare-and-swap semantics using an expected version.

---

## 14. Execution lease

A mutation lease is one-time, exact-bound authority.

```json
{
  "lease_id": "lease-...",
  "nonce": "...",
  "task_id": "tsk-...",
  "agent_id": "agt-...",
  "session_id": "ses-...",
  "repository": "menqstudio/Bro",
  "branch": "task-123",
  "worktree": "...",
  "head_sha": "...",
  "tree_identity": "...",
  "allowed_capabilities": ["WRITE_REPOSITORY"],
  "scope": ["runtime/"],
  "issued_at": 0,
  "expires_at": 0,
  "max_tool_calls": 100,
  "max_duration_seconds": 3600
}
```

Lifecycle:

```text
ISSUED -> RESERVED -> ACTIVE -> CONSUMED
ACTIVE -> RECOVERY_REQUIRED -> RECOVERED -> CLOSED
ACTIVE -> AMBIGUOUS -> QUARANTINED
```

The same lease or nonce may not become active twice. Reservations and transitions must be atomic and crash-aware.

---

## 15. Verified worktree and repository binding

Before mutation the Control Plane must verify:

- worktree path is absolute and inside an allowed root;
- worktree appears in `git worktree list --porcelain`;
- process CWD is inside the exact worktree;
- task branch matches the worktree branch;
- current HEAD equals the task/lease bound HEAD;
- current tree identity equals the task/lease bound tree;
- the canonical `main` checkout is not a mutation target;
- the worktree has no conflicting active lease;
- resolved write targets are inside allowed scope and outside prohibited scope.

Task contract, lease, process state, and Git state must describe one exact repository state. Inconsistency is a deny condition, even if each object is individually signed.

---

## 16. Approval engine

Approval types:

```text
PLAN
MUTATION
DESTRUCTIVE
EXTERNAL_WRITE
COMMUNICATION
CREDENTIAL_USE
SPENDING
RELEASE
ROLLBACK
```

Approval object:

```json
{
  "approval_id": "approval-...",
  "principal_id": "owner-gev",
  "task_id": "tsk-...",
  "action_class": "RELEASE",
  "exact_payload_hash": "sha256:...",
  "one_time": true,
  "issued_at": 0,
  "expires_at": 0,
  "key_id": "...",
  "signature": "..."
}
```

A generic text such as `approved` is not authority. Approval must bind the exact normalized payload or decision request. Key storage, rotation, revocation, and compromise response must be defined before production use.

---

## 17. Evidence store

Evidence must be stored outside the task repository through an append-only service or equivalent protected boundary.

Event shape:

```json
{
  "event_id": "evt-...",
  "previous_event_hash": "sha256:...",
  "task_id": "tsk-...",
  "event_type": "TOOL_AUTHORIZED",
  "agent_id": "agt-...",
  "payload_hash": "sha256:...",
  "timestamp": 0,
  "key_id": "...",
  "event_hash": "sha256:...",
  "signature": "..."
}
```

Required events include task creation, approval, lease state, worktree preparation, tool requests and decisions, mutations, tests, builder completion, verifier execution and verdict, recovery, release approval, push settlement, and task closure.

A local hash chain alone is not sufficient against a same-user attacker. Production design must separate agent runtime, evidence signer, and evidence storage authority, and periodically anchor checkpoints to an external immutable location.

---

## 18. Completion manifest

A builder may not claim completion without a manifest.

```json
{
  "task_id": "tsk-...",
  "agent_id": "agt-...",
  "task_contract_sha256": "sha256:...",
  "base_commit": "...",
  "candidate_head": "...",
  "candidate_tree": "...",
  "done_criteria": [
    {
      "criterion": "...",
      "status": "satisfied",
      "evidence": ["evt-..."]
    }
  ],
  "changed_files": [],
  "tests": [],
  "artifacts": [],
  "open_risks": [],
  "rollback_ready": true,
  "issued_at": 0,
  "signature": "..."
}
```

Stop is allowed only when:

- the manifest is valid and current;
- evidence references resolve and hashes match;
- candidate HEAD/tree match current execution state;
- dirty state is absent or explicitly represented;
- no pending mutation or ambiguous result exists;
- recovery is not required;
- verification state satisfies task risk requirements.

Allowed terminal task outcomes are:

```text
COMPLETED
FAILED_WITH_EVIDENCE
CANCELLED
RECOVERED
QUARANTINED
FAILED_WITH_IRREVERSIBLE_EFFECT
QUARANTINED_PENDING_OWNER_ACTION
```

---

## 19. Signed verifier receipt

```json
{
  "verifier_receipt_id": "vr-...",
  "task_id": "tsk-...",
  "builder_agent_id": "agt-...",
  "verifier_agent_id": "agt-...",
  "independence_level": "L3",
  "task_contract_sha256": "sha256:...",
  "completion_manifest_sha256": "sha256:...",
  "candidate_head": "...",
  "candidate_tree": "...",
  "commands_executed": [],
  "evidence_hashes": [],
  "verdict": "GREEN",
  "issued_at": 0,
  "expires_at": 0,
  "key_id": "...",
  "signature": "..."
}
```

The receipt is invalid if identity, authority, independence level, candidate state, evidence, time validity, or signature validation fails.

---

## 20. Release Grant V3

```json
{
  "schema": 3,
  "principal_id": "owner-gev",
  "task_id": "tsk-...",
  "task_contract_sha256": "sha256:...",
  "completion_manifest_sha256": "sha256:...",
  "verifier_receipt_sha256": "sha256:...",
  "repository": "menqstudio/Bro",
  "remote": "menqstudio/Bro",
  "branch": "task-123",
  "expected_head_sha": "...",
  "expected_tree_identity": "...",
  "nonce": "...",
  "allowed_action": "git-push",
  "issued_at": 0,
  "expires_at": 0,
  "key_id": "...",
  "signature": "..."
}
```

Release requires all of the following:

```text
Task state == RELEASE_READY
Verifier verdict == GREEN
Completion manifest == valid
Evidence chain == valid
HEAD == approved HEAD
Tree == approved tree
Nonce == unused and atomically reservable
Owner approval == exact-bound and valid
Push command == exact approved shape
```

Post-tool settlement must distinguish success, confirmed failure, and ambiguity. Ambiguous release state must quarantine the task and nonce.

---

## 21. Recovery engine

Before the first mutation, record:

- HEAD and tree identity;
- Git status;
- tracked file hashes;
- untracked inventory;
- worktree and branch;
- active task, lease, and scope;
- active processes relevant to the task;
- planned rollback or compensation actions.

After each mutation, record path, before hash, after hash, action request ID, agent, and timestamp.

Actions must be classified:

```text
REVERSIBLE
COMPENSATABLE
IRREVERSIBLE
UNKNOWN
```

Interruption procedure:

1. transition task to `RECOVERY_REQUIRED` or `QUARANTINED`;
2. block new mutation;
3. detect active processes and reserved authorities;
4. reconcile actual repository and external state;
5. restore reversible state or execute approved compensation;
6. verify the restored state or record irreversible effects;
7. append recovery evidence;
8. transition only to a valid terminal or rework state.

No GREEN is allowed without recovery proof. Recovery must not falsely claim that irreversible external effects were undone.

---

## 22. Resource governance

Each execution lease must define enforceable limits for duration, tool calls, retries, parallel agents, token/cost budget, files changed, artifact size, and allowed network domains.

Limit exhaustion causes:

```text
PAUSE -> WAIT_FOR_APPROVAL
```

It must not cause silent continuation or automatic limit inflation.

---

## 23. Decision object

Every authorization result must be serializable and evidence-bound.

```json
{
  "decision": "ALLOW",
  "reason_code": "AUTHORIZED_SCOPED_REPOSITORY_WRITE",
  "request_id": "req-...",
  "session_id": "ses-...",
  "task_id": "tsk-...",
  "agent_id": "agt-...",
  "mode": "work",
  "tool": "Write",
  "action": "write_file",
  "capabilities": ["WRITE_REPOSITORY"],
  "targets": ["runtime/file.py"],
  "repository": "menqstudio/Bro",
  "branch": "task-123",
  "head_sha": "...",
  "tree_identity": "...",
  "worktree": "...",
  "lease_id": "lease-...",
  "approval_id": null,
  "state_version": 17,
  "timestamp": 0,
  "decision_hash": "sha256:..."
}
```

Reason codes must be stable enough for tests, analytics, and audit review.

---

## 24. Transaction and concurrency semantics

Security state changes must be atomic or explicitly recoverable.

Required properties:

- compare-and-swap using `state_version`;
- exclusive reservation for one-time nonces and leases;
- idempotency keys for repeated hook delivery;
- no authorization from stale state snapshots;
- durable write before returning success;
- ambiguous transaction outcome produces quarantine, not retry-by-assumption;
- deterministic reconciliation procedure after crash.

---

## 25. Migration plan from V1

Migration must be incremental and fail closed.

1. Introduce schemas, registries, and decision model without changing behavior.
2. Add shadow classification and compare it against V1 decisions.
3. Move canonical identity validation into the core bundle loader.
4. Enable unknown-tool deny after registry coverage is complete.
5. Add worktree/state binding and execution leases.
6. Add evidence, completion, and verifier receipts.
7. introduce Release Grant V3 while retaining V2 validation only for historical audit reads.
8. Enable recovery enforcement.
9. Remove duplicate regex/security logic only after equivalence and bypass tests pass.

No phase may claim the next phase's guarantee.

---

## 26. Implementation phases and commit boundaries

### Phase 0 — Specification

- threat model;
- trust boundaries;
- invariants;
- schemas and state transitions;
- failure semantics;
- acceptance-test catalog;
- migration plan.

### Phase 1 — Tool authorization kernel

- capability registry;
- normalized action model;
- unified classifier;
- unknown deny;
- composition tests.

### Phase 2 — Identity and verifier authority

- canonical identity in core validation;
- authority registry;
- verifier resolution;
- independence enforcement.

### Phase 3 — Repository execution binding

- verified worktree;
- CWD/branch/HEAD/tree binding;
- main mutation denial;
- active-task lock.

### Phase 4 — Execution leases

- reservation and activation;
- replay denial;
- expiry and budget limits;
- ambiguity handling.

### Phase 5 — Completion and verification

- completion manifest;
- Stop gate;
- signed verifier receipt;
- evidence validation.

### Phase 6 — Release V3

- evidence-bound grant;
- exact approval;
- release transition;
- settlement and quarantine.

### Phase 7 — Recovery

- pre-mutation journal;
- mutation journal;
- recovery state machine;
- reversible/irreversible handling;
- interruption tests.

Orchestration and Control Room work begin only after these security phases are independently audited.

---

## 27. Acceptance-test catalog

The implementation is not GREEN until tests prove at minimum:

- unknown tool is denied;
- unknown sub-action is denied;
- fake agent ID is denied;
- canonical ID with wrong pack or role is denied;
- fake verifier is denied;
- verifier without authority is denied;
- insufficient verifier independence level is denied;
- reused lease and nonce are denied;
- expired lease is denied;
- wrong worktree is denied;
- CWD outside worktree is denied;
- `main` mutation is denied;
- task/HEAD mismatch is denied;
- task/tree mismatch is denied;
- out-of-scope resolved target is denied;
- incomplete task cannot Stop;
- dirty or ambiguous execution cannot claim GREEN;
- release without completion manifest is denied;
- release without valid verifier receipt is denied;
- release after candidate HEAD/tree change is denied;
- external action without exact approval is denied;
- stale state transition loses compare-and-swap;
- interruption blocks new mutation;
- recovery without original-state or effect proof is denied;
- irreversible effect is reported honestly rather than marked restored;
- Windows and Ubuntu behavior is equivalent.

All critical gates require mutation-style tests, not only happy-path unit tests.

---

## 28. Definition of Done

Bro Execution Control Plane V2 is GREEN only when:

- all normative invariants are enforced in code;
- all acceptance tests pass on Windows and Ubuntu;
- no duplicate mutation classifier remains authoritative;
- schemas and registries validate;
- evidence and lease transaction semantics survive interruption tests;
- release requires exact evidence-chain binding;
- an independent exact-head audit finds no open P0 findings;
- Gev explicitly approves merge.

Until then the product name remains:

> **Bro Agent OS Governance Foundation**

Only after the Definition of Done is proven may it be described as:

> **Zero-Trust Agent Execution Operating System**

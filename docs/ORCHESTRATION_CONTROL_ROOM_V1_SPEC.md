# Bro Orchestration and Control Room V1 — Scope Specification

**Status:** Phase 1 canonical contracts merged to `main`  
**Reviewed:** 2026-07-15  
**Repository:** `menqstudio/Bro`  
**Approved candidate HEAD:** `3c31255056b0bcedf4733be81a4b5a335a1eacd6`  
**Merge commit:** `61bf9bc4a42b512926bf848b79a0cac063196993`

## 1. Purpose

Define the first owner-facing product layer above the merged Execution Control Plane V2 without weakening its security boundaries.

Phase 0 specification and Phase 1 canonical orchestration contracts are complete and merged. This baseline includes the orchestration SST, event and command schemas, deterministic Control Room projection, validator wiring, negative tests, and canonical registry integration. It does not include the durable runtime, production credentials, external evidence services, governed API endpoints, visual UI, deployment, or production automation.

## 2. Locked actors

- Gev is the owner and final approval authority.
- `bro-000` is the only conductor and owner-facing conversational agent.
- Specialist agents keep immutable canonical IDs.
- Builders cannot self-verify medium, high, or critical work.
- Only the canonical Push Executor may perform release transport under Release Grant V3.

## 3. Canonical orchestration SST

The canonical source is:

```text
orchestration/registry.json
```

It owns task lifecycle states and transitions, queue classes, routing policy, verifier separation, checkpoint and budget policies, governed commands, recovery/quarantine semantics, and Control Room surface contracts. No competing orchestration truth may be added to prose, analytics files, runtime code, or UI code.

## 4. Merged lifecycle and boundaries

The merged lifecycle is fail closed from `draft` through approval, queueing, routing, running, verification, recovery/quarantine, and terminal states. Every event binds task identity, sequence, previous/next state, actor identity, time, reason, evidence, correlation, and repository binding when code mutation is involved.

Unknown states, impossible transitions, broken event chains, stale commands, invalid actor identity, missing evidence, expired commands, and mutation events without repository binding are denied.

Control Room remains read-first. V1 command contracts cover approve, deny, cancel, retry, reassign, and request-verification; direct repository, credential, evidence-ledger, or release mutation from UI is forbidden.

## 5. Verification evidence

- exact candidate HEAD: `3c31255056b0bcedf4733be81a4b5a335a1eacd6`
- GitHub Actions run `29376410325`: Windows GREEN and Ubuntu GREEN
- independent exact-head artifact audit in a temporary real Git worktree: foundation GREEN
- unique full suite: 102/102 GREEN
- targeted orchestration tests: 5/5 GREEN, included in the 102 total
- documentation inventory: 60/60
- open P0/P1 findings at merge: none

## 6. Next phase

Phase 2 is **Orchestration Runtime V1**:

- durable task and append-only event persistence;
- deterministic queue ordering and claim/lease semantics;
- canonical routing execution and cross-pack task-force binding;
- evidence-backed checkpoints and heartbeats;
- cooperative cancellation with fail-closed mutation handling;
- retry, budget, timeout, escalation, and crash recovery;
- integration with Execution Control Plane V2 leases, completion evidence, recovery, and release boundaries.

Control Room APIs/UI, production credentials, external evidence services, BroPS, deployment, and production rollout remain separate scopes.

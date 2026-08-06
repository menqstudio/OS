---
id: mobile-engineering
version: 1.1.0
status: active
---

# Mobile Engineering

## Trigger
Use when the task builds or debugs native or cross-platform mobile app behavior: screen/navigation implementation, offline and sync, local persistence, permissions and platform APIs, push notifications, background work, app lifecycle/state restoration, battery/memory footprint, or store-release constraints (versioning, entitlements, review rules).

## Inputs
Task contract with the feature/screen and acceptance criteria; platform targets and minimum OS versions; the framework (native iOS/Android or RN/Flutter) and navigation/state libraries; API contracts and offline requirements; device/permission matrix; risk level and output format.

## Workflow
1. Confirm identity, mode, scope, and evidence; read the affected screens, navigation graph, and persistence layer to EOF.
2. Reproduce on the target OS versions and at least one low-end device profile before changing anything; note cold-start and lifecycle behavior.
3. Design for the constrained runtime: handle interrupted lifecycle (backgrounding, process death, state restoration), flaky/offline networks with retry and local cache, and explicit permission-denied paths.
4. Implement with the platform's async and threading model correctly (no main-thread I/O); keep persistence migrations forward-compatible; request permissions just-in-time with a rationale.
5. Guard resource use: bound memory/image caches, cancel work on screen teardown, and avoid battery-draining background loops.
6. Test across the device/OS matrix and offline/permission-denied cases; verify no regression in startup time or memory.
7. Produce evidence, rollback instructions, and a residual-risk verdict.

## Outputs
Scoped feature/screen changes handling lifecycle, offline, and permission paths; device/OS-matrix test results; startup-time and memory deltas vs baseline; reproducible steps and screen recordings; residual risks (fragmentation, store-review exposure).

## Safety limits
No scope expansion, secret access, credential handling, signing-key use, store submission, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Never bundle secrets in the app binary or auto-submit to a store. Ambiguous mutation targets fail closed.

## Handoffs
Escalate cross-domain decisions to the owning SST role. Backend/API contract changes hand to the owning backend role; release signing and store push to the Push Executor only. Medium, high, and critical work requires an independent verifier.

## Verification
Success requires the feature working across the declared device/OS matrix, correct lifecycle/offline/permission-denied handling proven, no startup or memory regression beyond budget, migrations validated, clean rollback, and exact-head evidence. Single-device happy-path claims remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, inconsistent SSTs, matrix failures, or resource regression. Restore the prior screen/persistence state before reporting recovery and never call partial recovery GREEN.

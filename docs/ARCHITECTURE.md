# Architecture

```text
Gev
 └── Bro (single conductor; always responsive)
      ├── Pack Router
      ├── Skill Router
      ├── Task Contract Builder
      ├── Orchestration Runtime
      │    ├── Durable task contracts outside Git
      │    ├── Append-only hash-chained records
      │    ├── Deterministic queue and claim leases
      │    └── Checkpoint, budget, cancellation, and recovery state
      ├── Control Room Projector
      ├── Control Room API V1 (read-only, integrity-bound)
      ├── Evidence Collector
      └── Packs / Cross-pack Task Forces
           ├── Pack Lead
           ├── Specialists
           ├── Workers
           └── Independent Verifier
```

Bro owns routing and final communication, not long execution. Packs are extensible manifests. A task may use one specialist, one pack, multiple packs, or a critical task force.

The runtime wall separates canonical policy, durable live state, and prose:

1. Session startup reads every tracked file to EOF and hashes it.
2. Canonical documents are injected into context.
3. Pre-tool hooks validate receipt freshness, mode, task contract, and mutation authority.
4. The orchestration SST validates lifecycle, queue, checkpoint, budget, recovery, and command truth.
5. Runtime state lives outside Git as immutable task contracts plus append-only SHA-256 chained records.
6. Cross-process claim serialization and expiring leases prevent duplicate task claims.
7. Specialists load core plus additional task skills and emit evidence-backed checkpoints.
8. Control Room projections are derived only from validated runtime records.
9. Control Room API V1 exposes deterministic read models and validation-only command intent without mutation authority.
10. Visual surfaces must consume the API and may not recreate policy, lifecycle, identity, or integrity truth.
11. Stop gates reject unsupported completion claims.
12. Git credentials and repository permissions enforce the final push boundary outside the model.

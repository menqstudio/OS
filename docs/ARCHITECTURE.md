# Architecture

```text
Gev
 └── Bro (single conductor; always responsive)
      ├── Pack Router
      ├── Skill Router
      ├── Task Contract Builder
      ├── Evidence Collector
      └── Packs / Cross-pack Task Forces
           ├── Pack Lead
           ├── Specialists
           ├── Workers
           └── Independent Verifier
```

Bro owns routing and final communication, not long execution. Packs are extensible manifests. A task may use one specialist, one pack, multiple packs, or a critical task force.

The runtime wall separates policy from prose:

1. Session startup reads every tracked file to EOF and hashes it.
2. Canonical documents are injected into context.
3. Pre-tool hooks validate receipt freshness, mode, task contract, and mutation authority.
4. Specialists load core plus additional task skills.
5. Stop gates reject unsupported completion claims.
6. Git credentials and repository permissions enforce the final push boundary outside the model.

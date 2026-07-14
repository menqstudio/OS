# Agent Identity Registry

Bro has the reserved identity `bro-000`. No subordinate agent may use that ID or any name containing Bro.

Every registered specialist role has one permanent deterministic ID:

```text
agt-p{pack ordinal}-r{role ordinal}
```

Examples:

- `agt-p01-r01` — Agent Architect in `ai-agent-builders`
- `agt-p22-r03` — Push Executor in `git-release-control`
- `agt-p48-r05` — Safety Verifier in `red-team-offensive-security`

Pack and role ordinals are the one-based positions in `packs/registry.json`. Their canonical fingerprint is locked in `agents/registry.json`.

## Identity laws

- IDs are immutable and never reused.
- Pack and role entries are append-only for identity purposes; do not reorder them.
- A renamed display label does not create a new identity.
- A replaced or retired agent keeps its old ID marked retired; a successor receives a new appended ID.
- `agent_id` must match the exact registered pack and role.
- Task contracts, skill receipts, evidence, verifier verdicts, commits, and release records bind to the exact ID.
- Session IDs and run IDs are temporary execution identifiers and never replace `agent_id`.

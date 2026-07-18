# Bro Roadmap — Post-Merge

**Reviewed:** 2026-07-19  
**Repository:** `menqstudio/Bro`  
**Canonical branch:** `main`  
**Merged PR:** `#27`  
**Merge commit:** `b7c18f248243e63c6d281f74628125469874534d`

## Completed foundation

1. Execution Control Plane V2, canonical orchestration and Control Room V1 contracts, Orchestration Runtime V1, and Control Room API V1 are merged.
2. Containment is merged and live-wired: workspace binding, path scope enforcement, and the protected control-plane digest now gate `runtime/bro_control_plane.py`.
3. Issuance is merged: Ed25519 authorities, an operator-signed trusted-key registry, the `tools/broctl.py` minting/signing CLI, and an external supervisor that owns and issues execution leases.
4. Execution integrity is merged: signed execution receipts binding command, working tree, environment and runner identity.
5. STOP Controller v2 and an append-only hash-chained audit ledger (L16), plus content secret confidentiality (L15), are merged.
6. All 17 laws (L0–L16) are traceability-backed and `LIVE_PROVEN`.
7. CI: foundation GREEN on ubuntu-latest and windows-latest; inventories 52 packs / 42 skills / 62 documents.
8. Conductor bootstrap read deadlock resolved (PR #15): a conductor-only, read-only, allowlisted, workspace-bound exemption in `runtime/bro_policy.py`.
9. Owner Authorization Phase 1 merged (PRs #17–#27): every in-process-verified authorization artifact (mode grant, execution lease, completion manifest, verifier receipt, Release Grant V3, recovery record) is Ed25519-verified against an operator-signed trusted-key registry, not HMAC; the mode grant anchors the task/agent/skill hashes; `tools/bro_skill_receipt.py` and `tools/bro_authorize_specialist.py` produce a specialist bundle; a first green end-to-end proof exists (`tests/test_owner_authorization_e2e.py`).

## Next phases

1. **Full execution-transaction E2E:** drive `authorize_tool` to ALLOW a specialist mutation end-to-end against a real worktree, workspace binding, task lock, execution-lease and recovery ledgers — the integration layer beyond the Phase 1 bundle proof.
2. **Retire the legacy paths:** delete the dead `release-grant-v2` loader in `runtime/bro_contracts.py`.
3. **Operational rollout:** shadow mode, canary tasks, failure drills, monitoring, backup/restore, operator runbooks.
4. **Control Room visual surfaces V1:** deferred until routine task execution is exercised end-to-end.

Each phase requires a dedicated branch, draft PR, exact-head CI, independent verification, current documentation, and Gev's explicit merge approval.

## Architecture Freeze v1

A new architectural idea must show it closes a concrete bug or audit finding, or
it does not land. This freeze exists because ten rounds of design refinement
produced zero applied lines.

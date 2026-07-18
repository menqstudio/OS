# Bro Roadmap — Post-Merge

**Reviewed:** 2026-07-18  
**Repository:** `menqstudio/Bro`  
**Canonical branch:** `main`  
**Merged PR:** `#13`  
**Merge commit:** `5a095750000f1838abac6fe3e794a9d11bed63d0`

## Completed foundation

1. Execution Control Plane V2, canonical orchestration and Control Room V1 contracts, Orchestration Runtime V1, and Control Room API V1 are merged.
2. Containment is merged and live-wired: workspace binding, path scope enforcement, and the protected control-plane digest now gate `runtime/bro_control_plane.py`.
3. Issuance is merged: Ed25519 authorities, an operator-signed trusted-key registry, the `tools/broctl.py` minting/signing CLI, and an external supervisor that owns and issues execution leases.
4. Execution integrity is merged: signed execution receipts binding command, working tree, environment and runner identity.
5. STOP Controller v2 and an append-only hash-chained audit ledger (L16), plus content secret confidentiality (L15), are merged.
6. All 17 laws (L0–L16) are traceability-backed and `LIVE_PROVEN`.
7. CI: foundation GREEN on ubuntu-latest and windows-latest (PR #13, 415 tests); inventories 52 packs / 42 skills / 62 documents.

## Next phases

1. **Conductor bootstrap read deadlock (open P0):** add a conductor-only, read-only, workspace-bound bootstrap exemption in `runtime/bro_policy.py` so the enforcement wall can stay up while the canonical conductor reads to bootstrap and orchestrate.
2. **Owner Authorization Phase 1:** owner-side minting and Ed25519 signing of governed specialist authorizations via `tools/broctl.py`.
3. **Operational rollout:** shadow mode, canary tasks, failure drills, monitoring, backup/restore, operator runbooks.
4. **Control Room visual surfaces V1:** deferred until routine task execution is exercised end-to-end.

Each phase requires a dedicated branch, draft PR, exact-head CI, independent verification, current documentation, and Gev's explicit merge approval.

## Architecture Freeze v1

A new architectural idea must show it closes a concrete bug or audit finding, or
it does not land. This freeze exists because ten rounds of design refinement
produced zero applied lines.

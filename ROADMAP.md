# Bro Roadmap — Post-Merge

**Reviewed:** 2026-07-19  
**Repository:** `menqstudio/Bro`  
**Canonical branch:** `main`  
**Merged PR:** `#36`  
**Merge commit:** `60a94dc1412bc41e592949281a623825ab66c76a`  
**Status:** `operational-rollout-scaffolded`  
**Deployment:** `blocked-pending-security-remediation`

> ⛔ **DEPLOYMENT BLOCKED.** The 2026-07-19 independent adversarial audit of `main` returned **RED — 2 Critical, 9 High, 4 Medium**. The rollout below is scaffolded, not deployment-ready; the security remediation backlog is the priority and must close before any deployment or mutation-capable use.

> **`LIVE_PROVEN` is a validator label, not a wiring proof.** The items below are merged *components*; the audit found the STOP controller unwired, the Supervisor lease runtime-incompatible, execution receipts not feeding completion, and the durable-runtime completion path lacking an independent verifier. Read "merged" as *component present and validator-labelled*, not *production-wired*.

## Completed foundation

1. Execution Control Plane V2, canonical orchestration and Control Room V1 contracts, Orchestration Runtime V1, and Control Room API V1 are merged.
2. Containment is merged and live-wired: workspace binding, path scope enforcement, and the protected control-plane digest now gate `runtime/bro_control_plane.py`.
3. Issuance is merged: Ed25519 authorities, an operator-signed trusted-key registry, the `tools/broctl.py` minting/signing CLI, and an external supervisor that owns and issues execution leases.
4. Execution integrity is merged: signed execution receipts binding command, working tree, environment and runner identity.
5. STOP Controller v2 and an append-only hash-chained audit ledger (L16), plus content secret confidentiality (L15), are merged.
6. All 17 laws (L0–L16) are traceability-backed and `LIVE_PROVEN`.
7. CI: foundation GREEN on ubuntu-latest and windows-latest; inventories 52 packs / 42 skills / 63 documents.
8. Conductor bootstrap read deadlock resolved (PR #15): a conductor-only, read-only, allowlisted, workspace-bound exemption in `runtime/bro_policy.py`.
9. Owner Authorization Phase 1 merged (PRs #17–#27): every in-process-verified authorization artifact (mode grant, execution lease, completion manifest, verifier receipt, Release Grant V3, recovery record) is Ed25519-verified against an operator-signed trusted-key registry, not HMAC; the mode grant anchors the task/agent/skill hashes; `tools/bro_skill_receipt.py` and `tools/bro_authorize_specialist.py` produce a specialist bundle; a first green end-to-end proof exists (`tests/test_owner_authorization_e2e.py`).
10. Trust root replaced with the real owner-signed public key registry (PR #29).
11. Legacy release-grant loaders retired — the unsigned v1 and HMAC v2 loaders are removed; Ed25519 Release Grant V3 is the sole release path (PR #30).
12. Full execution-transaction E2E and failure drills (PRs #31, #33): `authorize_tool` ALLOWs a specialist mutation end-to-end against a real workspace binding, task lock, execution lease and recovery ledger; a failed or interrupted transaction quarantines the lease, requires recovery, and fences further mutation on the task.
13. Operational rollout merged: shadow (observe-only) enforcement with a fail-safe would-block ledger (#32), integrity-checked backup/restore of machine-local state (#34), an operator runbook (#35), and a live health monitor over the runtime ledgers (#36). Foundation GREEN at 482 tests.

## Security remediation — deployment blockers (priority)

The audit is RED; these close before any deployment. Fixed one per PR, each with a regression test and independent adversarial verification at the exact candidate HEAD (the auditor is not the sole verifier of a fix). Order:

1. **Review-mode shell containment** — deny shell/command tools in review; allow only structured `Read`/`Glob`/`Grep` (with `Glob` patterns workspace-contained); the review denial is non-shadowable.
   - **1b. Work-mode shell classifier** — `find . -delete` still classifies as a non-mutating read in work mode; needs a command-specific argument parser.
2. **External operator-key pin** — anchor the trusted-key registry to an owner-controlled key held outside the registry; missing pin / payload fallback / mismatch → hard-DENY. Separate security PR + owner-side configuration.
3. **Backup restore traversal** — reject `..`, absolute paths, symlinks, duplicates; destination must stay within the target.
4. **Corrupt/missing monitor state → ATTENTION**, never GREEN.
5. **Full secret redaction** — whole PEM bodies and modern token formats.
6. **Unified completion + evidence path** — the durable runtime requires an independent verifier-signed GREEN receipt (builder ≠ verifier); execution receipts feed the verdict.
7. **Owner-signed recovery proof** — replace the arbitrary-hex proof.
8. **STOP integration** (process-group liveness + runtime wiring), then **Supervisor** lease-schema / full-environment E2E.
9. **Hardening** — audit-log atomicity, an assurance validator proving live wiring (not path existence), docs, and CI supply-chain hardening.

## After the blockers

1. **Client integration contract.** Expose Bro's enforced authority — mode grants, execution leases, the append-only audit chain, recovery state — to an operator client (e.g. BroPS) through a defined Bro-side surface, so a product UI's approval and evidence rest on the runtime wall rather than its own local store. Bro-side only; the client repository stays out of scope here.
2. **Owner-environment hardening.** Dedicated non-admin account, workspace-scoped filesystem ACLs, a fine-grained GitHub credential scoped to `menqstudio/Bro`, and the `main` branch ruleset (PR required, force-push/deletion blocked, required foundation checks, empty bypass actors). Owner-operated, outside any agent process.
3. **Control Room visual surfaces.** The rendered surfaces belong to the operator client, not this runtime: Bro exposes read-only data, the client renders it.

Each phase requires a dedicated branch, draft PR, exact-head CI, independent verification, current documentation, and Gev's explicit merge approval.

## Architecture Freeze v1

A new architectural idea must show it closes a concrete bug or audit finding, or
it does not land. This freeze exists because ten rounds of design refinement
produced zero applied lines.

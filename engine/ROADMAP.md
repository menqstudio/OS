# Bro Roadmap — Post-Merge

**Reviewed:** 2026-07-19  
**Repository:** `menqstudio/Bro`  
**Canonical branch:** `main`  
**Merged PR:** `#52`  
**Merge commit:** `bc3b8533aa8f66ed5fa8693b23e0d16621cd4cc9`  
**Status:** `security-remediation-complete`  
**Deployment:** `pending-owner-environment-hardening`

> **Security remediation complete.** The 2026-07-19 independent adversarial audit (**RED — 2 Critical, 9 High, 4 Medium**) is fully remediated: blockers #1–#9 merged (PRs #38–#50), then owner-environment hardening (#51–#52). A follow-up internal multi-agent review is closing further items the same way (one PR, regression test, independent verification at exact HEAD). Deployment still requires the owner-environment steps.

> **`LIVE_PROVEN` now means live-proven.** The wiring gaps the audit named are closed, and a fail-closed live-wiring assurance validator (`tools/bro_live_validate.py`, blocker 9b) gates CI by running each law's allow/deny cases through the wired interpreter.

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
13. Operational rollout merged: shadow (observe-only) enforcement with a fail-safe would-block ledger (#32), integrity-checked backup/restore of machine-local state (#34), an operator runbook (#35), and a live health monitor over the runtime ledgers (#36).

## Security remediation — all blockers resolved

Every blocker from the 2026-07-19 audit is merged, one per PR, each with a regression test and independent adversarial verification at the exact candidate HEAD (the auditor was not the sole verifier of a fix):

1. **Review-mode shell containment — #38.** Deny shell/command tools in review; allow only structured `Read`/`Glob`/`Grep` (workspace-contained); non-shadowable. (1b work-mode classifier resolved; a follow-up hardened `git -c` code-exec configs the same way.)
2. **External operator-key pin — #42.** Trusted-key registry anchored to an owner-controlled key outside it; missing pin / payload fallback / mismatch → hard-DENY.
3. **Backup restore traversal — #39.** Rejects `..`, absolute paths, symlinks, duplicates; destination stays within the target.
4. **Corrupt/missing monitor state — #40.** Treated as ATTENTION, never GREEN.
5. **Full secret redaction — #41.** Whole PEM bodies and modern token formats.
6. **Unified completion + evidence path — #43, #44.** Execution receipts feed the verdict (6a); the durable runtime requires an independent verifier-signed GREEN receipt, builder ≠ verifier (6b).
7. **Owner-signed recovery proof — #45.** A real owner-signed proof via a dedicated `recovery` authority.
8. **STOP integration + Supervisor — #46, #47.** Group-liveness fixed and STOP wired into supervision with whole-group teardown (8a); the supervisor issues the one canonical runtime-enforced lease (8b).
9. **Hardening — #48, #49, #50.** Atomic audit-ledger lock (9a), a fail-closed live-wiring assurance CI gate (9b), CI supply-chain hardening (9c).

Then owner-environment hardening (#51 deployment-posture preflight, #52 supervisor builder-bundle). A follow-up internal multi-agent review continues closing further correctness/hardening items by the same process.

## After the blockers

1. **Client integration contract.** Expose Bro's enforced authority — mode grants, execution leases, the append-only audit chain, recovery state — to an operator client (e.g. BroPS) through a defined Bro-side surface, so a product UI's approval and evidence rest on the runtime wall rather than its own local store. Bro-side only; the client repository stays out of scope here.
2. **Owner-environment hardening.** Dedicated non-admin account, workspace-scoped filesystem ACLs, a fine-grained GitHub credential scoped to `menqstudio/Bro`, and the `main` branch ruleset (PR required, force-push/deletion blocked, required foundation checks, empty bypass actors). Owner-operated, outside any agent process.
3. **Control Room visual surfaces.** The rendered surfaces belong to the operator client, not this runtime: Bro exposes read-only data, the client renders it.

Each phase requires a dedicated branch, draft PR, exact-head CI, independent verification, current documentation, and Gev's explicit merge approval.

## Architecture Freeze v1

A new architectural idea must show it closes a concrete bug or audit finding, or
it does not land. This freeze exists because ten rounds of design refinement
produced zero applied lines.

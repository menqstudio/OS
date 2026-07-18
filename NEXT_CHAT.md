# Bro Post-Merge Handoff — 2026-07-18

Continue only in `menqstudio/Bro` from current `main`. Do not touch BroPS.

## Merged baseline

- latest merged PR: `#13`
- main merge commit: `5a095750000f1838abac6fe3e794a9d11bed63d0`
- containment, issuance, and execution-integrity work is merged and live-wired into the runtime
- all 17 laws (L0–L16) are traceability-backed and `LIVE_PROVEN`, including L15 (secret confidentiality) and L16 (auditable stop + incident ledger)
- CI: foundation GREEN on ubuntu-latest and windows-latest (415 tests)
- inventories: 52 packs, 42 skills, 62 documents

## Mandatory startup

1. Fetch current `main` and confirm HEAD.
2. Read `README.md`, `CLAUDE.md`, `AGENTS.md`, `ROADMAP.md`, `NEXT_CHAT.md`, and every path in `config/canonical-read-manifest.json`.
3. Run foundation, documentation freshness, and full tests.
4. Report exact baseline before editing.
5. Create a new scoped branch and draft PR; never work directly on `main`.
6. Never merge without Gev's explicit approval bound to the exact candidate HEAD.

## Locked foundation

Execution Control Plane V2, Orchestration/Control Room V1 contracts, Orchestration Runtime V1, and Control Room API V1 are merged, and the containment, issuance, and execution-integrity controls are now wired into `runtime/bro_control_plane.py` rather than inert. Runtime state remains outside Git and is reconstructed from immutable task contracts plus append-only SHA-256 chained records. The merged API is read-only, integrity-bound, fail-closed, honest about unavailable data, and validates command intent without executing or authorizing mutation.

## Next task

**Control Room visual surfaces V1 remains deferred.** The current priority is a live, self-defending conductor.

1. **Resolve the conductor bootstrap read deadlock (open P0).** In `work`/`release` mode `authorize_classified_action` in `runtime/bro_policy.py` requires a full task-contract bundle for every action, including read-only ones. There is no conductor read exemption, so the canonical conductor cannot read the repository to bootstrap or orchestrate while the enforcement wall is up. Add a conductor-only, read-only, workspace-bound bootstrap exemption — symmetric with the existing conductor delegation and stop exemptions — with a test that proves it cannot authorize mutation, orchestration, push, unknown actions, or path escape.
2. **Owner Authorization Phase 1.** The owner-side flow that mints and Ed25519-signs governed specialist authorizations with `tools/broctl.py`.

Owner-only environment hardening (still valid, blocking nothing else):

1. dedicated non-admin account for the agent;
2. filesystem ACL limited to the registered workspace, inheritance disabled;
3. deny that account access to the owner profile, `.ssh`, and credential stores;
4. fine-grained GitHub credential scoped to `menqstudio/Bro` alone, without Administration, Secrets or Workflows;
5. no general owner credential inside the agent account;
6. `main` ruleset requiring a pull request, blocking force-push and deletion, requiring `foundation (ubuntu-latest, 3.12)` and `foundation (windows-latest, 3.12)`, with `bypass_actors: []`.

Out of scope unless Gev explicitly expands it:

- production credentials;
- external evidence-service deployment;
- distributed queue/database deployment;
- direct repository, release, deployment, or production mutation;
- BroPS changes;
- deployment or production rollout.

## Architecture Freeze v1

The architecture is frozen. A new architectural idea must show it closes a
concrete bug or audit finding, or it does not land. Ten rounds of design
improvement with zero applied lines is the failure mode this freeze exists to
stop.

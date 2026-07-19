# Bro Post-Merge Handoff — 2026-07-19

Continue only in `menqstudio/Bro` from current `main`. Do not touch BroPS.

> ⛔ **DEPLOYMENT BLOCKED — `blocked-pending-security-remediation`.** The 2026-07-19 independent adversarial audit returned **RED: 2 Critical, 9 High, 4 Medium**. Status is `operational-rollout-scaffolded`, not complete. Do not deploy or enable mutation-capable use until the blockers below close. Implementation is driver; the auditor verifies each fix's exact HEAD independently (auditor is not the sole verifier of a fix).

## Merged baseline

- latest merged PR: `#36`
- main merge commit: `60a94dc1412bc41e592949281a623825ab66c76a`
- containment (workspace binding / path scope / control-plane digest) is wired into the runtime; issuance and execution-integrity are merged as components but not yet wired end-to-end (see audit blockers 6, 8)
- owner authorization has a green end-to-end bundle+ALLOW test and the operational-rollout **components** are merged (see audit caveats): real owner-signed trust root (#29), legacy release-grant loaders retired (#30), full execution-transaction E2E + failure drills (#31, #33), shadow enforcement (#32), backup/restore (#34), operator runbook (#35), live health monitor (#36)
- all 17 laws (L0–L16) are validator-labelled `LIVE_PROVEN` — a checked test/path exists, **not** a proof of production wiring; the audit found the Supervisor lease, STOP controller, execution receipts, and durable-runtime completion are not wired end-to-end (blockers 6, 8)
- CI: foundation GREEN on ubuntu-latest and windows-latest (482 tests)
- inventories: 52 packs, 42 skills, 63 documents

## Mandatory startup

1. Fetch current `main` and confirm HEAD.
2. Read `README.md`, `CLAUDE.md`, `AGENTS.md`, `ROADMAP.md`, `NEXT_CHAT.md`, and every path in `config/canonical-read-manifest.json`.
3. Run foundation, documentation freshness, and full tests.
4. Report exact baseline before editing.
5. Create a new scoped branch and draft PR; never work directly on `main`.
6. Never merge without Gev's explicit approval bound to the exact candidate HEAD.

## Locked foundation

Execution Control Plane V2, Orchestration/Control Room V1 contracts, Orchestration Runtime V1, and Control Room API V1 are merged, and the **containment** controls (workspace binding, path scope, control-plane digest) are wired into `runtime/bro_control_plane.py` rather than inert. Issuance and execution-integrity are merged as components but are **not** proven wired end-to-end — the audit found the Supervisor lease incompatible with the runtime and the STOP controller unwired (blocker 8). Runtime state remains outside Git and is reconstructed from immutable task contracts plus append-only SHA-256 chained records. The merged API is read-only, integrity-bound, fail-closed, honest about unavailable data, and validates command intent without executing or authorizing mutation.

## Next task — security remediation (deployment blockers)

The operational rollout is scaffolded but the 2026-07-19 audit is RED; deployment is blocked until these close. Fix one per PR, each with a regression test, draft/hold until independently verified at the exact candidate HEAD. Order:

1. **Review-mode shell containment** — deny shell/command tools in review; allow only structured `Read`/`Glob`/`Grep` (with `Glob` patterns workspace-contained); the review denial is non-shadowable (fastest active containment).
   - **1b. Work-mode shell classifier** — a destructive shell command (`find . -delete`) still classifies as a non-mutating read in work mode; needs a command-specific argument parser.
2. **External operator-key pin** — anchor the trusted-key registry to an owner-controlled operator public key outside the registry; missing pin / payload fallback / registry mismatch → hard-DENY. Separate security PR + owner-side config; do not touch `trusted-keys.json` in that PR.
3. **Backup restore path-traversal reject.**
4. **Corrupt/missing monitor state → ATTENTION.**
5. **Full secret redaction** (whole PEM bodies, `sk-proj-…`, `github_pat_…`).
6. **Unified completion + evidence path** (durable runtime requires an independent verifier-signed GREEN receipt; execution receipts feed the verdict).
7. **Owner-signed recovery proof.**
8. **STOP integration**, then **Supervisor** lease schema + full real E2E.
9. **Hardening**: audit-log atomicity, assurance validator (live wiring, not path existence), docs, CI supply-chain.

Acceptance tests that must go from bypass to DENY: attacker registry replacement; `cat /etc/passwd`, `find . -delete`, `git -C /tmp status` in review; leader-exits-child-remains (group still alive, STOP kills child); full PEM into any persistence path (no key bytes retained); supervisor-issued lease accepted by the real runtime; crafted `../` archive rejected before write; corrupt recovery journal → non-zero; builder completes without a verifier receipt → DENY.

**After the blockers:** the Bro-side client integration contract (expose enforced authority to an operator client such as BroPS; client repo out of scope — `Do not touch BroPS`), then owner-environment hardening, then Control Room visual surfaces as the client's responsibility.

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

# Bro Post-Merge Handoff — 2026-07-15

Continue only in `menqstudio/Bro` from current `main`. Do not touch BroPS.

## Merged baseline

- PR `#8` is closed and merged.
- approved candidate HEAD: `f2c457a675248eb805c02889509a40d8a5e1c520`
- main merge commit: `f736bce585e0e911c36a73d0181c8eb4ef3aebef`
- final CI run: `29434543079`
- Windows and Ubuntu: GREEN
- independent exact-head real-worktree audit: foundation GREEN; docs freshness GREEN
- Control Room API targeted tests: 12/12 GREEN
- full unique suite: 128/128 GREEN
- documentation inventory: 62/62 at merge
- open P0/P1 findings: none

## Mandatory startup

1. Fetch current `main` and confirm HEAD.
2. Read `README.md`, `CLAUDE.md`, `AGENTS.md`, `ROADMAP.md`, `NEXT_CHAT.md`, and every path in `config/canonical-read-manifest.json`.
3. Run foundation, documentation freshness, and full tests.
4. Report exact baseline before editing.
5. Create a new scoped branch and draft PR; never work directly on `main`.
6. Never merge without Gev's explicit approval bound to the exact candidate HEAD.

## Locked foundation

Execution Control Plane V2, Orchestration/Control Room V1 contracts, Orchestration Runtime V1, and Control Room API V1 are merged. Runtime state remains outside Git and is reconstructed from immutable task contracts plus append-only SHA-256 chained records. The merged API is read-only, integrity-bound, fail-closed, honest about unavailable data, and validates command intent without executing or authorizing mutation.

## Next task

**Control Room visual surfaces V1 is deferred.** Building an owner-facing view of
a system that cannot execute a task would report an empty room. See the open
findings in `README.md` first.

Start **Phase A containment**. Order matters, and it is not the order intuition
suggests: external walls come before the issuer, because they are the only work
with no bootstrap dependency and the only work that protects the owner from the
agent rather than the agent from itself.

Owner-only, and blocking nothing else:

1. dedicated non-admin Windows account for the agent;
2. NTFS ACL limited to the registered workspace, inheritance disabled;
3. deny that account access to the owner profile, `.ssh`, and credential stores;
4. fine-grained GitHub credential scoped to `menqstudio/Bro` alone, without
   Administration, Secrets or Workflows;
5. no general owner credential inside the agent account;
6. `main` ruleset requiring a pull request, blocking force-push and deletion,
   requiring `foundation (ubuntu-latest, 3.12)` and
   `foundation (windows-latest, 3.12)`, with `bypass_actors: []`.

In-repository, landed on `remediation/contained-autonomy-phase-a`:

- `runtime/bro_workspace.py` — external workspace binding and path containment;
- `runtime/bro_protected.py` — fail-closed protected roots and control-plane digest;
- `runtime/bro_freeze.py` — settlement-only state after a protected mutation;
- `config/protected-control-plane.json` — access roots and digest roots.

Not yet wired into `runtime/bro_control_plane.py`: the modules are tested but
inert. Wiring them requires a workspace binding to exist, so it fails closed for
every caller including CI until one is issued. That wiring is itself the first
security-maintenance task.

Then Phase B: Ed25519 authorities, operator-signed key registry, issuer CLI,
external supervisor. Then Phase C: signed execution receipts.

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

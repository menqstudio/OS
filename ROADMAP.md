# Bro Roadmap — Post-Merge

**Reviewed:** 2026-07-15  
**Repository:** `menqstudio/Bro`  
**Canonical branch:** `main`  
**Merged PR:** `#8`  
**Merge commit:** `f736bce585e0e911c36a73d0181c8eb4ef3aebef`

## Completed foundation

1. Execution Control Plane V2 is merged.
2. Canonical orchestration and Control Room V1 contracts are merged.
3. Orchestration Runtime V1 foundation is merged.
4. Control Room API V1 is merged as a governed read-only boundary over validated runtime state.
5. Runtime and API truth now include immutable task contracts, append-only hash-chained records, deterministic queue claims, canonical agent workload, checkpoints, budgets, approval inbox, recovery/quarantine, audit timeline, integrity roots, honest missing-data markers, and validation-only command intents.
6. Final PR #8 evidence: Windows and Ubuntu GREEN, independent exact-head real-worktree audit GREEN, Control Room API tests 12/12 GREEN, full unique suite 128/128 GREEN, documentation inventory 62/62, and no open P0/P1 findings.

## Audit correction — 2026-07-16

Item 6 above recorded "no open P0/P1 findings" at PR #8. That was true of the
merged tests and false of the system: the suite proved the gates reject, never
that they can pass. An independent audit found the baseline is a verifier with no
issuer. See the open findings in `README.md`.

The consequence for this roadmap is that visual surfaces are not next. A Control
Room over a system that cannot execute a task would render an empty room.

## Next phases

1. **Phase A — containment.** External walls first: dedicated non-admin account,
   NTFS ACL limited to the registered workspace, repository-scoped credential,
   `main` ruleset with no bypass. In-repository: workspace binding, path scope,
   protected control-plane digest. This phase alone has no bootstrap dependency
   and is the only one that protects the owner from the agent rather than the
   agent from itself.
2. **Phase B — issuance.** Ed25519 authorities, operator-signed public key
   registry, issuer CLI, external supervisor owning leases. The conductor never
   holds a lease; the builder is a separate process with the lease injected only
   into it.
3. **Phase C — execution integrity.** Signed test receipts binding command,
   working tree, environment and runner identity.
4. **Credential and evidence services:** isolate production credentials, deploy
   external append-only ledgers and evidence storage.
5. **Control Room visual surfaces V1:** deferred until a task can actually run.
6. **Operational rollout:** shadow mode, canary tasks, failure drills, monitoring,
   backup/restore, operator runbooks.

Each phase requires a dedicated branch, draft PR, exact-head CI, independent verification, current documentation, and Gev's explicit merge approval.

## Architecture Freeze v1

A new architectural idea must show it closes a concrete bug or audit finding, or
it does not land. This freeze exists because ten rounds of design refinement
produced zero applied lines.

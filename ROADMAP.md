# Bro Agent OS Roadmap

This roadmap is executable by a fresh chat. Each phase has inputs, actions, gates, and completion evidence. Do not skip phases or merge the draft PR until the release gates are satisfied.

## Phase 0 — Re-establish exact state

**Inputs**
- repository: `menqstudio/Bro`
- branch: `bro-agent-os-v1`
- draft PR: `#1`

**Actions**
1. Read the complete repository to EOF.
2. Load every canonical path in `config/canonical-read-manifest.json`.
3. Read `config/sst-registry.json` and identify every domain SST.
4. Run foundation validation and all tests.
5. Compare the branch HEAD with the PR HEAD.

**Gate**
- exact HEAD identified,
- no uncommitted local changes,
- validation and tests produce reproducible results.

## Phase 1 — Complete SST consolidation

**Actions**
1. Make `packs/registry.json` the only Pack SST.
2. Migrate analytics packs and the mandatory Automation & Flow role into that SST without changing existing IDs.
3. Append the Learning Intelligence pack after all existing packs.
4. Delete obsolete competing pack registries only after equivalence is proven.
5. Recalculate and lock `agents/registry.json` fingerprint and counts.
6. Ensure every domain in `config/sst-registry.json` has exactly one existing SST and validator.

**Required evidence**
- old IDs remain unchanged,
- new IDs are append-only,
- no duplicate pack truth remains,
- identity tests cover known historical IDs and the newest appended IDs.

## Phase 2 — Complete runtime enforcement

**Actions**
1. Make `runtime/bro_contracts.py` read the Pack and Agent SSTs rather than a partial registry.
2. Enforce SST registration before creating a skill, test, law, schema, dashboard, learning rule, agent, or pack.
3. Enforce sandbox-first autonomy, temporary permission leases, concurrency and budget limits.
4. Add shadow mode, canary promotion, mission replay, watchdog recovery, and recovery-before-GREEN.
5. Require critical-task quorum and independent verifier separation.

**Gate**
- every law in `laws/registry.json` has a machine enforcement target and registered test,
- unsupported or missing enforcement fails validation.

## Phase 3 — Complete tests and schemas

**Actions**
1. Create every test registered in `tests/catalog.json`.
2. Reject orphan tests not registered in the Test SST.
3. Validate every schema registered in `schemas/registry.json`.
4. Add positive, negative, mutation, interruption-recovery, stale-receipt, identity-drift, and permission-boundary tests.
5. Run on Linux and Windows-compatible Python paths.

**Gate**
- deterministic GREEN locally and in GitHub Actions,
- no skipped security-critical tests,
- exact-head workflow run is successful.

## Phase 4 — Import and strengthen skills

**Actions**
1. Audit all 42 skill bodies before import.
2. Preserve `skills/<skill-id>/SKILL.md` structure.
3. Map permanent core skills to every registered agent.
4. Add task-time supplemental skill selection.
5. Apply the Skill Evolution pipeline: proposal, benchmark, independent review, owner approval, promotion, monitoring, rollback.

**Gate**
- every registered skill has a body and hash,
- every agent has valid core skills,
- no skill can self-promote.

## Phase 5 — Agent profiles and execution wrappers

**Actions**
1. Generate permanent machine-readable profiles for all registered agents.
2. Add UI-only gender metadata using only `M` or `F`.
3. Keep UI gender outside routing, permissions, evaluation, identity, and verification.
4. Build event-driven, scheduled, on-demand, and condition-watch wrappers.
5. Keep agents dormant by default; spawn only when needed.

**Gate**
- profile count equals Agent SST count,
- every profile validates against its exact immutable ID,
- no always-running worker swarm.

## Phase 6 — Analytics, control room, and learning engine

**Actions**
1. Implement evidence-backed agent and system status events.
2. Build the four canonical dashboards from the Analytics SST.
3. Add workload, quality, failure, approval, policy-denial, cost, latency, and bottleneck analysis.
4. Implement quarantined learning proposals and conflict review.
5. Add version, confidence, expiry, retirement, and rollback to learned items.

**Gate**
- every KPI has source, owner, freshness, thresholds, drill-down, and evidence link,
- unknown or stale data cannot display GREEN.

## Phase 7 — Independent audit and release readiness

**Actions**
1. Perform a full zero-trust audit of the exact candidate HEAD.
2. Exercise Claude hooks in a real Windows Claude Code checkout.
3. Verify interruption recovery and original-tree restoration.
4. Confirm external Git credential isolation.
5. Update PR description with exact counts, files, tests, and workflow run.

**Release gate**
- exact-head CI GREEN,
- independent audit GREEN,
- no unresolved critical/high findings,
- Gev approval bound to exact commit and tree,
- PR remains draft until all gates are met.

## Definition of Done

Bro Agent OS is not done because files exist. It is done when every declared rule has one SST, machine enforcement, deterministic tests, evidence, recovery behavior, and an owner-controlled release path.

# Next Chat Handoff

## Mission

Continue the clean Bro Agent OS build in `menqstudio/Bro` without touching BroPS. Work only on branch `bro-agent-os-v1` and draft PR `#1`. Do not merge.

## Mandatory startup

1. Read the complete repository to EOF.
2. Read `CLAUDE.md`, `AGENTS.md`, `README.md`, `ROADMAP.md`, and every path in `config/canonical-read-manifest.json`.
3. Read `config/sst-registry.json` before creating or changing any domain object.
4. Confirm the branch HEAD equals the draft PR HEAD.
5. Run:

```bash
python tools/bro_validate.py
python -m unittest discover -s tests -v
```

6. Report the exact baseline before editing. Never claim GREEN from an older SHA.

## Locked architecture

- Gev is the owner.
- There is exactly one Bro: `bro-000`.
- Bro remains available and delegates long or specialist execution.
- Every subordinate agent has an immutable `agt-pNN-rNN` ID.
- Every pack must contain exactly one `Automation & Flow Engineer`.
- UI gender metadata accepts only `M` or `F` and has no authority or routing effect.
- Agents are dormant by default and spawn event-driven, scheduled, on-demand, or as condition watches.
- Review is read-only; Work permits scoped commit but no push; Release is Push Executor only with exact owner-bound grant and external credential isolation.
- Medium, high, and critical work requires an independent verifier.
- Learning and skill evolution require sandboxing, benchmark evidence, independent review, controlled promotion, monitoring, and rollback.

## SST law

Every domain has one canonical Single Source of Truth registered in `config/sst-registry.json`. Documentation may explain an SST but must not duplicate changing inventory facts. An agent creating or changing a pack, agent, skill, test, law, schema, dashboard, learning rule, release rule, or startup file must update the corresponding SST and its validator/tests in the same scoped change.

## Current verified facts

- Draft PR remains open and unmerged.
- The branch contains identity, task/skill/release contracts, analytics foundations, skill-evolution foundations, SST registries, and release boundaries.
- Some older files still require consolidation and exact-head revalidation.
- `ROADMAP.md` is the execution order and Definition of Done.

## Immediate next task

Execute **ROADMAP Phase 1** completely:

1. consolidate Pack SST into `packs/registry.json`,
2. preserve all existing agent IDs,
3. append analytics, mandatory Flow roles, and Learning Intelligence cleanly,
4. update Agent SST fingerprint/counts,
5. remove competing registries only after equivalence proof,
6. update runtime contract lookup to the consolidated SST,
7. update tests and stale documentation,
8. run validation and exact-head GitHub Actions.

Do not start skill-body import until Phase 1–3 are GREEN.

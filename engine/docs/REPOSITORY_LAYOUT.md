# Repository Layout

```text
engine/                   (`Bro/` upstream; vendored here as a git subtree of menqstudio/Bro)
├── .bro/                 runtime policy; generated state is ignored
├── .claude/              committed Claude Code hooks
├── .github/workflows/    CI verification upstream; GitHub does not run this copy inside the monorepo
├── AUDIT/                the 2026-07-19 read-only security audit and its tickets
├── agents/               specialist identity registry and profiles
├── analytics/            analytics SST: registry, metrics and dashboards
├── ci/                   isolation proofs and the live governed-turn kits the monorepo CI runs
├── config/               canonical startup and documentation manifests
├── contracts/            the signer wire-protocol schemas (brops-*.v1)
├── docs/                 active architecture, phase, and operating documentation
├── install/              the privileged installer (brops_install.sh)
├── laws/                 canonical laws
├── learning/             learning SST registry
├── orchestration/        canonical lifecycle, queue, checkpoint, budget, and command SST
├── packs/                pack registry and pack manifests
├── release/              release SST registry
├── runtime/              fail-closed policy, orchestration runtime, and read-only Control Room API code
├── schemas/              strict machine-readable schemas
├── skills/               Anthropic-compatible skill library
├── tests/                deterministic positive and negative tests
├── tools/                repository validators and maintenance commands
```

Only reusable contracts, schemas, templates, laws, code, and documentation are tracked. Live credentials, approvals, receipts, task state, claim locks, worktrees, and generated evidence never become canonical source by accident.

Durable orchestration state is stored outside Git. Each runtime task is reconstructed from one validated immutable contract plus append-only SHA-256 chained records. Repository code and `orchestration/registry.json` define behavior; live state does not redefine policy.

Control Room visual surfaces belong in a separately scoped product layer and must consume `runtime/bro_control_room_api.py`; they may not read mutable runtime internals directly or become a competing SST.

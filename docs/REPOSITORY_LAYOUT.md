# Repository Layout

```text
Bro/
├── .bro/                 runtime policy; generated state is ignored
├── .claude/              committed Claude Code hooks
├── .github/workflows/    CI verification
├── agents/               specialist identity registry and profiles
├── config/               canonical startup and documentation manifests
├── docs/                 active architecture, phase, and operating documentation
├── laws/                 canonical laws
├── orchestration/        canonical lifecycle, queue, checkpoint, budget, and command SST
├── packs/                pack registry and pack manifests
├── runtime/              fail-closed policy, contract, execution, and orchestration runtime code
├── schemas/              strict machine-readable schemas
├── skills/               Anthropic-compatible skill library
├── tests/                deterministic positive and negative tests
├── tools/                repository validators and maintenance commands
```

Only reusable contracts, schemas, templates, laws, code, and documentation are tracked. Live credentials, approvals, receipts, task state, claim locks, worktrees, and generated evidence never become canonical source by accident.

Durable orchestration state is stored outside Git. Each runtime task is reconstructed from one validated immutable contract plus append-only SHA-256 chained records. Repository code and `orchestration/registry.json` define behavior; live state does not redefine policy.

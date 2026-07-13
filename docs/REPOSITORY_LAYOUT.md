# Repository Layout

```text
Bro/
├── .bro/                 runtime policy; generated state is ignored
├── .claude/              committed Claude Code hooks
├── .github/workflows/    CI verification
├── agents/               specialist identity registry and profiles
├── approvals/            release-grant format; live grants stay ignored
├── config/               canonical startup manifest
├── contracts/            task-contract format; live contracts stay ignored
├── docs/                 active architecture and operating documentation
├── evidence/             evidence format; generated evidence stays ignored
├── laws/                 canonical laws
├── packs/                pack registry and pack manifests
├── runtime/              fail-closed policy and contract validators
├── schemas/              strict machine-readable schemas
├── skills/               Anthropic-compatible skill library
├── templates/            safe examples for generated runtime objects
├── tests/                deterministic positive and negative tests
├── tools/                repository validators and maintenance commands
└── workspaces/           isolated task-worktree conventions
```

Only reusable contracts, schemas, templates, laws, code, and documentation are tracked. Live credentials, approvals, receipts, task state, worktrees, and generated evidence never become canonical source by accident.

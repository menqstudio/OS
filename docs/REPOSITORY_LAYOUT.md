# Repository Layout

```text
Bro/
├── .bro/                 runtime policy; generated state is ignored
├── .claude/              committed Claude Code hooks
├── .github/workflows/    CI verification
├── agents/               specialist identity registry and profiles
├── config/               canonical startup manifest
├── docs/                 active architecture and operating documentation
├── laws/                 canonical laws
├── packs/                pack registry and pack manifests
├── runtime/              fail-closed policy and contract validators
├── schemas/              strict machine-readable schemas
├── skills/               Anthropic-compatible skill library
├── tests/                deterministic positive and negative tests
├── tools/                repository validators and maintenance commands
```

Only reusable contracts, schemas, templates, laws, code, and documentation are tracked. Live credentials, approvals, receipts, task state, worktrees, and generated evidence never become canonical source by accident.

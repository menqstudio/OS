# Operating Modes

## Review

Read repository files, history, diffs, PRs, and checks. Analyze and report. Do not create, edit, delete, rename, install, commit, push, open PRs, comment, rerun workflows, or change settings.

## Work

Use a task contract and isolated branch/worktree. Modify only scoped paths. Commit only owned changes. Push remains denied.

## Release

Only the Git & Release Control Pack participates:

- Integration Lead collects approved commits.
- Release Verifier independently validates the exact candidate SHA.
- Push Executor may push only the exact approved SHA.
- Rollback Coordinator preserves recovery evidence and rollback steps.

Release mode without external credentials and branch permissions is still non-push-capable.

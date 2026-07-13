# Git and Release Control

## Commit policy

Approved specialists may commit only in their isolated task worktree and task branch. Commits must contain only owned scope and reference the task ID and evidence path.

## Push policy

No ordinary specialist, pack lead, auditor, or verifier may push. The only push-capable role is `push-executor` inside `git-release-control`.

A valid push requires:

- exact repository and remote,
- exact branch and expected HEAD SHA,
- independent release verification,
- owner approval bound to that SHA,
- external write credential available only to the Push Executor environment,
- branch protection and audit receipt.

Prompt rules and hooks are defense in depth. Real security comes from credential isolation and repository permissions.

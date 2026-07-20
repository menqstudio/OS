# M-7 — CI workflow has no `permissions:` block → jobs run with default (often write) `GITHUB_TOKEN`

- **Severity:** Medium
- **Confidence:** High (flagged independently by two auditors)
- **Type:** Supply chain / CI hardening
- **Files:** `.github/workflows/ci.yml` (top level)
- **Status:** Proposed patch (read-only audit)

## Problem
No `permissions:` key means each job's `GITHUB_TOKEN` inherits the repository default, which on push-to-`main` is commonly `contents: write` (plus more). All three jobs execute large amounts of third-party code with that token present: `npm ci` lifecycle scripts, ~500 crates' `build.rs`/proc-macros, the full Tauri release build. A compromised transitive dependency could use the ambient token to push commits/tags or tamper with the repo. (Fork PRs get a read-only token by default, so the exposure is push builds on `main`.)

## Fix
Add a least-privilege top-level block (nothing in this workflow needs write):
```yaml
name: ci

permissions:
  contents: read

on:
  push:
    branches: [main]
  pull_request:
```

## Acceptance criteria
- [ ] `permissions: contents: read` present at workflow top level (or per-job if any job legitimately needs more).
- [ ] All CI jobs still pass (read-only token is sufficient for build/test).

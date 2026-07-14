# Bro V2 Finalization Handoff — 2026-07-14

Continue work only in `menqstudio/Bro` on branch `bro-execution-control-plane-v2`, draft PR `#2`. Do not touch BroPS and do not merge without Gev's explicit approval.

## Verified state

- Base `main`: `a0f40d5aa3de96f05f2a9f90cdfd0f4e09fa7bca`
- Security phases 1–7: implemented and exact-head CI GREEN on Windows and Ubuntu
- Runtime: capability kernel, canonical identity and designated verifier authority, repository binding, one-time leases, completion/verifier evidence, Release Grant V3, interruption recovery
- Documentation inventory: every Markdown and `SKILL.md` file must be registered in `config/documentation-manifest.json`
- PR remains draft/open/unmerged

## Mandatory next gates

1. Confirm current branch HEAD equals PR #2 HEAD.
2. Run `python tools/bro_validate.py`.
3. Run `python tools/bro_docs_freshness.py`.
4. Run `python -m unittest discover -s tests -v`.
5. Perform an independent exact-head audit against `docs/EXECUTION_CONTROL_PLANE_V2_SPEC.md`.
6. Fix every P0/P1 finding before any final GREEN claim.
7. Update PR title/body so they describe runtime, hooks, schemas, tests, recovery, and documentation changes.
8. Keep the PR draft and unmerged until Gev explicitly authorizes merge.

Never report GREEN from an older SHA. Never treat CI success alone as independent audit evidence.

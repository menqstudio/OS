# NEXT_CHAT — definitive handoff · վերջնական handoff

> **This file is the live handoff and nothing else** — 4034 lines of appended write-ups moved to
> [`docs/archive/SESSION_LOG_2026-07_2026-08.md`](docs/archive/SESSION_LOG_2026-07_2026-08.md).
> `config/canon-budget.json` holds it to 8500 bytes; over that, the wall accepts only an edit that
> shrinks it. *(This note said 12 KB — a number nothing checked, beside the gate that checks.)*

**Active branch:** `feat/floor-writer-service` — `main` @ `87bfe73`. A handoff names the merge base or `main`; a branch commit is a dead object after a squash. · **task** `egress-authorizer`
<!-- BANNER -->
> **⏭️ CURRENT ACTIVE: PR #219 · branch `feat/floor-writer-service`** (base `main`, tip `87bfe73`, task **T-020**). No other pull request is open.
>
> Five states kept apart: #112's DESIGN **merged** · Architect design audit **done** · five rulings **issued** · implementation **in progress, NOT approved** · production trust claim **NOT granted**.
>
> **Standing verdict: RED** -- the NINTH round, `apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

**Next: FINISH T-020's FW-1 correction — it is mid-flight, not merge-ready.** The Architect
BLOCKED `#219` at its frozen head (B1–B7 · C1–C7). The boundary rewrite is done and measured on this
box: kernel `SO_PEERCRED` peer identity checked against a **per-op** allowlist, all scope from the
TCB-owned `BROPS_FLOOR_WRITER_CONFIG`, **no `install_id` on the wire in either direction** (a request
carrying one is `malformed`), roster and floor in ONE document committed by ONE rename, and a closed
two-posture resolver in `bro_completion.py` — an unconfigured floor now REFUSES instead of silently
meaning "local". 26 negatives in `engine/tests/test_floor_writer.py`.

**What is NOT done, and the head is deliberately NOT frozen:** provisioning (B6), the real
distinct-UID and crash-injection tests, `SECURITY_MODEL.md` §1.3a as a deployment-enforceable
contract (C6), C1–C4/C7, and the cargo+frontend regression. §1.7 and §1.10 are declared **partial**
in `config/spec-conformance.json`, naming which half is missing. FW-3 (`scope.pin`, task/lease/pin
authority) is intentionally OUT of FW-1 by Architect ruling — `unknown_op`, and it says so.

The transport and the produced agent's egress are **T-058** in [`TASKS.md`](TASKS.md); that text
lived here as a second copy of the row.

*A green PR is not a green `main`, and `gh pr checks` is not `gh run list --branch main`.* A commit
named in the canon must be an **ancestor of `main`** — `check_doc_claims` refuses a branch head (#204).
Three more things must be true at every push: the PR body carries exactly one
`AUDIT_CANDIDATE_HEAD: <40-hex>` equal to the pushed head, `config/current_state.json` names the live
`main`, and the head named above moves **in its own commit** — an amend leaves the handoff naming a
commit that no longer exists.

Stamp with `tools/stamp_pr_head.py --pr <N>`; `gh pr edit` dies here.

**The app version is declared five times in four files and nothing reconciled them** until
`tools/check_version_parity.py` (`apps/desktop/package.json`, `src-tauri/tauri.conf.json`,
`src-tauri/Cargo.toml`, and `package-lock.json` twice; all `0.1.0`). `npm ci` exits 0 on a lock
that disagrees — measured. **No `v*` tag is compared**: `git tag -l` prints one tag,
`brops-desktop-v0.1.0`, which does not match `v*`, so `release.yml` has never run, and whether
these files hold the LAST released version or the NEXT one is a release policy the Owner has not
stated. Until he does, a tag arm would be a guess in a required context.

## Verify before you believe any of this

Run these. The numbers below have been wrong in every audit round so far.

```bash
cd engine && BRO_ENV=ci python3 -m unittest discover -s tests    # 2069 OK, 10 skipped
cd apps/desktop/src-tauri && cargo test --workspace              # 1147 passed
cd apps/desktop && npm ci && npm run typecheck && npm test       # 761 tests / 80 files
python3 tools/check_canon_budget.py       # the read set fits one context
python3 tools/check_state_fields.py       # no field of the mirror answers to nothing
python3 tools/check_doc_claims.py         # paths, commits, tickets, versions are real
python3 tools/check_no_assumptions.py     # no unmarked guess in the canon
python3 tools/check_handoff_ready.py      # a new session could take over
python3 tools/check_version_parity.py     # one product, one version, in all four files
```

Measured on **Debian**, `cargo` from an ordinary shell; the toolchain numbers come from
`config/toolchain.json` and nowhere else.

## The position, in four sentences

**The production gate is SHUT** and only the Owner opens it, after an independent audit.
Three refusals hold it, and they are the real ones — there is no
`platform_governed_execution_supported()` in the tree, that is the §0.1 spec symbol:
`governed_verification_unconfigured()` returns `Some(...)` unconditionally before the
model is invoked; `connect_broker()` refuses off Linux; and the broker serves
`UpstreamBlockedExecutor` unless `$BROPS_BROKER_CONFIG` names a deployment config carrying
a TCB-root-signed manifest, which nothing in the shipped app sets.

**The standing independent verdict is RED.** Nine rounds; the current one is
[`2026-08-19-ninth-audit-5cf9b8c.md`](apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md)
— RED, no P0, all three refusals read at source and closed for the fourth round running.
**56 pull requests, 192 files and 39,396 inserted lines have merged since that head**, and
none of it is independently confirmed. Every mark added since is ◑. *(Said 20/107/19688 until 2026-08-31 —
nearly a third of the real surface.)*

**Nothing is waiting on the Owner.**
[`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md) is the page of record. O-1…O-5
are all OPEN and none needs an Owner-minted artifact; what blocks them is deployment wiring and
a second principal.

**There is no path in this repository to a production trust root** — everything runnable
produces a *development* one, enough to exercise every path end to end and not enough to close
O-2, O-3 or O-5. The three refusals that make it so are in
[`docs/DEBIAN_DEPLOYMENT.md`](docs/DEBIAN_DEPLOYMENT.md) and CLAUDE.md §6.

## How to read the marks

`✅` independently confirmed · `◑` the Builder's own claim. Both RED verdicts here came from
rows a session marked `✅` about its own fix. Read
[`AUDIT_LEDGER.md`](apps/desktop/AUDIT/AUDIT_LEDGER.md) before believing any tick in prose.

## Two things that will save you a day

**Open the session at THIS checkout** or you get none of the six hooks, and nothing announces
their absence (it happened for all of T-019). **A green test is not a passing check** — mutate it
once and watch a NAMED test go red. Both in full: CLAUDE.md §5 and §7 rule 4.

## Where the state lives

CLAUDE.md §3 is the one table; this was a third copy of it. The two to open first:
[`config/current_state.json`](config/current_state.json) — the machine mirror, verified against
live GitHub by `tools/check_repo_state.py` — and
[`apps/desktop/AUDIT/AUDIT_LEDGER.md`](apps/desktop/AUDIT/AUDIT_LEDGER.md), the audit position.
Open tasks are [`TASKS.md`](TASKS.md); what is blocked on whom is
[`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md).

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document. *(That requirement is why one document came to live in three files: three places obliged to carry the same text, and nothing obliging any of them to stay short.)*

`CURRENT_ACTIVE_TASK: floor-writer` · `CURRENT_ACTIVE_WAVE: production-half` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

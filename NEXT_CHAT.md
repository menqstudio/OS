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

**Next:** the TRANSPORT. §4 landed as a REFERENCE store — the desktop names where a secret lives
and never holds one (migration 0022), so the transport is what carries a reference across the wall.

The produced agent now **RUNS**: the 60s tick enqueues AND dispatches, up to
`MAX_DISPATCH_PER_TICK`. It was measured first — `claim_and_run` had ONE non-test caller, a CI demo
binary, so every piece built for that agent was unreachable from the product. Bundles are **BORN
DISARMED**; arming needs a natively confirmed grant, disarming does not.

**Two populations, two mechanisms** (Owner, 2026-08-30). The PRODUCED agent's list is the grant's
`egress` TABLE, so the flow names a row and never a URL (§2.3 rule 6); it has no spawn and no `Bash`,
so no namespace is needed. The BUILD agent keeps a broad fixed `build_egress` and is **not** jailed.
No class holds `USE_NETWORK`, so every valid lease still names **no** destination.

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
cd engine && BRO_ENV=ci python3 -m unittest discover -s tests    # 2043 OK, 10 skipped
cd apps/desktop/src-tauri && cargo test --workspace              # 1110 passed
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

**The wall loads from the SESSION's project root, not the repository you edit.** Open the
session at the OS checkout itself, or you get none of the five hooks and *nothing announces
their absence* — it happened for a whole task (T-019). CLAUDE.md §5 has the full list.

**A green test is not a passing check.** When you add a check, delete it once, **grep the line
to confirm the mutation applied**, and confirm its test goes red. `T-045` swept its own two gates
and found **three of seven checks tested by nothing**, plus a fourth with no test at all. Of
roughly ninety checks swept in an earlier wave, four came back green.

## Where the state lives

CLAUDE.md §3 is the one table; this was a third copy of it. The two to open first:
[`config/current_state.json`](config/current_state.json) — the machine mirror, verified against
live GitHub by `tools/check_repo_state.py` — and
[`apps/desktop/AUDIT/AUDIT_LEDGER.md`](apps/desktop/AUDIT/AUDIT_LEDGER.md), the audit position.
Open tasks are [`TASKS.md`](TASKS.md); what is blocked on whom is
[`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md).

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document. *(That requirement is why one document came to live in three files: three places obliged to carry the same text, and nothing obliging any of them to stay short.)*

`CURRENT_ACTIVE_TASK: egress-authorizer` · `CURRENT_ACTIVE_WAVE: production-half` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

# NEXT_CHAT — definitive handoff · վերջնական handoff

> **This file is the live handoff and nothing else** — 4034 lines of appended write-ups moved to
> [`docs/archive/SESSION_LOG_2026-07_2026-08.md`](docs/archive/SESSION_LOG_2026-07_2026-08.md).
> `config/canon-budget.json` holds it to 8500 bytes; over that, the wall accepts only an edit that
> shrinks it.

**Active branch:** `t108/two-phase-root-ceremony` — `main` @ `b39b087`. A handoff names the merge base or `main`; a branch commit is a dead object after a squash. · **task** `floor-writer`
<!-- BANNER -->
> **⏭️ CURRENT ACTIVE: PR #279 · branch `t108/two-phase-root-ceremony`** (base `main`, tip `b39b087`, task T-108).
>
> trusted_verified was unreachable on Linux by construction; it is not now
>
> **Standing verdict: RED** -- the TENTH round, `apps/desktop/AUDIT/2026-09-19-tenth-audit-75fca65.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

**Next: T-020's FW-1 correction MERGED as `#219` (`2a50081`) and is NOT approved.** B1-B7 and C1, C2,
C4, C6, C7 are done and measured — the full account and the B/C list live only in `#219`'s body;
`SECURITY_MODEL.md` §1.3a names what enforces each row. Proofs: `engine/ci/floor_writer_boundary_proof.sh` 23/23 ×3 here and in CI;
`test_floor_writer_durability.py`. **NOT done:** C3 test structure and a second Architect pass. §1.7
stays **partial**; §1.10 is **implemented** and does not close **O-5**. FW-3 is OUT.

**`#220` merged as `157e292`:** the supply-chain gate is green again, the `T-055` promise is executed
(context required, entry deleted), and `main_ci` is no longer typed — `#221` makes the generator take
the reading. `main`'s own `ci` at `157e292` is `success` (run 35403529178), read by the generator into
`config/current_state.json.main_ci` -- the first green reading of `main` since 2026-08-31.

**T-061, and a slice of T-062.** The gate set is what CI runs, not `tools/check_*.py`:
`generate_negative_matrix.py --check` refuses a hand-edited mirror.

**T-059 and T-060 are corrected here too.** `main_ci` demanded a reading of the NEWEST run on
`main`, which taking a reading can never be; an older one now passes while everything since it was
green. And a squash re-dates a commit to the merge moment — both dates, 0 of 796 differ — so the
`Last updated` gate checks the law that date stood for: did that commit MOVE the line.

The transport and the produced agent's egress are **T-058**.

*A green PR is not a green `main`, and `gh pr checks` is not `gh run list --branch main`.* A commit
named in the canon must be an **ancestor of `main`**; `check_doc_claims` refuses a branch head (#204).
Three more things must hold at every push: the PR body carries one `AUDIT_CANDIDATE_HEAD: <40-hex>`
equal to the pushed head, `config/current_state.json` names the live `main`, and the head named
above moves **in its own commit** — an amend leaves the handoff naming a dead commit.

Stamp with `tools/stamp_pr_head.py --pr <N>`; `gh pr edit` dies.

## Verify before you believe any of this

Run these. The numbers below have been wrong in every audit round so far.

```bash
cd engine && BRO_ENV=ci python3 -m unittest discover -s tests    # 2243 OK; skips are per-env
cd apps/desktop/src-tauri && cargo test --workspace              # 1149 passed
cd apps/desktop && npm ci && npm run typecheck && npm test       # 794 tests / 84 files
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
**76 pull requests, 240 files and 46,612 inserted lines have merged since that head**, and
none of it is independently confirmed. Every mark added since is ◑. *(58/206/44,055 earlier on 2026-09-19; 20/107/19688 until 2026-08-31.)*

**Two one-line edits wait on the Owner**, both in files a Builder does not touch:
`.github/supply-chain/gitleaks.toml` carries a false positive that any edit can wake — the committed
operator PUBLIC key is allowed by its whole 64-hex value, and gitleaks captured a 57-character prefix
at one file size and not at another (79,665 bytes red, 79,744 green) — and
`config/required-checks.json` should promote the new Windows tools job once it has one green run.
[`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md) is the page of record. Branch
protection is live and verified. O-1…O-5 are all OPEN and none needs an Owner-minted artifact.

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

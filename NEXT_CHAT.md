# NEXT_CHAT — definitive handoff · վերջնական handoff

> **This file is the live handoff and nothing else.** It was 4034 lines on 2026-08-29,
> because every session appended its write-up and none removed one. That log is
> [`docs/archive/SESSION_LOG_2026-07_2026-08.md`](docs/archive/SESSION_LOG_2026-07_2026-08.md).
> `tools/check_canon_budget.py` holds this file to 12 KB: over that ceiling, the only edit
> the wall accepts is one that makes it smaller.

**Active branch:** `gate/canon-budget` · **head** `ab9dc23` · **task** `T-045` · **PR #180** (draft)
**`main` is settled at** `96c013a` (PR #179) · **also open, deliberately unmerged:** PR #112 (`design/floor-writer-service`)

**Next:** take PR #180 out of draft once `gh pr checks 180` is green on the exact head. Two
things must be true at every push: the PR body carries exactly one `AUDIT_CANDIDATE_HEAD: <40-hex>`
line equal to the pushed head, and `config/current_state.json` names the live `main`. Both were
wrong here and neither was visible, because the job that checks them died at an earlier step every
time. Then put the roadmap's structure to the Owner. *The previous handoff said `T-045` was "GREEN on
every gate it added" and CI said otherwise on that same head — four red jobs, three of them
`T-045`'s own doing. All four are fixed here; the lesson is the repository's own first rule,
applied to a claim about gates: run `gh pr checks`, do not read the sentence.* The remaining
work: `MASTER_EXECUTION_ROADMAP.md` is 41 KB because `check_coordination.py:698-708` requires
phases 0..10 with all 16 sections in one file, while `check_roadmap_order.py` forbids working
any phase but the first open one — so ten phases are carried into every session that may not
touch them. **Recommended: one file per phase under `docs/roadmap/`**, with the gate taught to
follow an index. It is the real fix rather than another trim, it costs a change to a
load-bearing gate plus its tests, and because of that it is the Owner's call.
See `config/canon-budget.json.rationale`.

## Verify before you believe any of this

Run these. Do not take the numbers below on trust — that is this repository's first rule,
and the numbers in these documents have been wrong in every audit round so far.

```bash
cd engine && BRO_ENV=ci python3 -m unittest discover -s tests    # 2002 OK, 10 skipped
cd apps/desktop/src-tauri && cargo test --workspace              # 1012 passed
cd apps/desktop && npm ci && npm run typecheck && npm test       # 758 tests / 80 files
python3 tools/check_canon_budget.py       # the read set fits one context
python3 tools/check_state_fields.py       # no field of the mirror answers to nothing
python3 tools/check_doc_claims.py         # paths, commits, tickets, versions are real
python3 tools/check_no_assumptions.py     # no unmarked guess in the canon
python3 tools/check_handoff_ready.py      # a new session could take over
```

Measured 2026-08-29 on **Debian**, cargo 1.97.1 / node 20.20.2 / npm 10.8.2, `cargo` run
from an ordinary shell. The documents that called this a Windows box were corrected by
`T-045`. Those three numbers have one source of record now — `config/toolchain.json` —
because `check_doc_claims.py` compared the documents against whatever machine ran it, and
the only machine that runs it is a CI runner with a different node.

## The position, in four sentences

**The production gate is SHUT** and only the Owner opens it, after an independent audit.
Three refusals hold it, and they are the real ones — there is no
`platform_governed_execution_supported()` in the tree, that is the §0.1 spec symbol:
`governed_verification_unconfigured()` returns `Some(...)` unconditionally before the
model is invoked; `connect_broker()` refuses off Linux; and the broker serves
`UpstreamBlockedExecutor` unless `$BROPS_BROKER_CONFIG` names a deployment config carrying
a TCB-root-signed manifest, which nothing in the shipped app sets.

**The standing independent verdict is RED.** Nine rounds have run; the current one is
[`2026-08-19-ninth-audit-5cf9b8c.md`](apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md)
— RED, no P0, all three refusals read at source and closed for the fourth round running.
**17 pull requests, 66 files and 6496 inserted lines have merged since that head**, and
none of it is independently confirmed. Every mark added since is ◑.

**Nothing is waiting on the Owner.**
[`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md) is the page of record and
as of 2026-08-29 it says so explicitly. O-1…O-5 are all OPEN and none needs an
Owner-minted artifact; what blocks them is deployment wiring and a second principal.

**There is no path in this repository to a production trust root.**
[`docs/DEBIAN_DEPLOYMENT.md`](docs/DEBIAN_DEPLOYMENT.md) states it: `broctl build-registry`
hardcodes `"production": false`, `broctl keygen --production` refuses, and `bro_signature`
refuses a development registry whenever the operator pin comes from the production path.
Everything runnable produces a **development** trust root. That is enough to exercise every
path end to end and not enough to close O-2, O-3 or O-5.

## How to read the marks

`✅` an independent audit confirmed it. `◑` the Builder believes it and **nobody else has
looked** — treat as an unverified claim. `🔴`/`⚠️` open. Both RED verdicts in this
repository's history came from rows marked `✅` by the session that wrote the fix, so never
promote your own work. The index is
[`AUDIT_LEDGER.md`](apps/desktop/AUDIT/AUDIT_LEDGER.md); read it before believing any tick
in any prose document.

## Two things that will save you a day

**The wall loads from the SESSION's project root, not the repository you edit.** Open the
session at the OS checkout itself. A session opened elsewhere that then works inside `OS/`
gets none of the five hooks — no read receipt, no phase declaration, no prior-art check, no
Stop guard — and *nothing announces their absence*. That happened for a whole task (T-019)
before anyone noticed.

**A green test is not a passing check.** When you add a check, delete it once and confirm
its test goes red, then restore it. `T-045` ran that sweep on its own two gates and found
**three of seven checks tested by nothing** — the tests were passing on a different
assertion — plus a fourth with no test at all. All four are isolated and mutation-verified
now. Of roughly ninety checks swept this way in an earlier wave, four came back green.

## Where the state lives

| | |
|---|---|
| Machine mirror, checked against live GitHub | [`config/current_state.json`](config/current_state.json) · `tools/check_repo_state.py` |
| Open tasks | [`TASKS.md`](TASKS.md) |
| Durable product plan | [`MASTER_EXECUTION_ROADMAP.md`](MASTER_EXECUTION_ROADMAP.md) |
| Audit position | [`apps/desktop/AUDIT/AUDIT_LEDGER.md`](apps/desktop/AUDIT/AUDIT_LEDGER.md) |
| Blocked on whom | [`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md) |
| Trust model, read before reasoning about trust | [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md) |
| History | [`docs/archive/`](docs/archive/) |

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document. *(That requirement is why one document came to live in three files: three places obliged to carry the same text, and nothing obliging any of them to stay short.)*

`CURRENT_ACTIVE_TASK: T-045` · `CURRENT_ACTIVE_WAVE: canon` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

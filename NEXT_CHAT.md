# NEXT_CHAT — definitive handoff · վերջնական handoff

> **This file is the live handoff and nothing else.** It was 4034 lines on 2026-08-29,
> because every session appended its write-up and none removed one. That log is
> [`docs/archive/SESSION_LOG_2026-07_2026-08.md`](docs/archive/SESSION_LOG_2026-07_2026-08.md).
> `tools/check_canon_budget.py` holds this file to 12 KB: over that ceiling, the only edit
> the wall accepts is one that makes it smaller.

**Active branch:** `menqstudio-patch-1` · **head** `9a3407f` · **task** `security-policy` · **PR #195**
<!-- BANNER -->
> **⏭️ CURRENT ACTIVE: PR #195 · branch `menqstudio-patch-1`** (base `main`, tip `454e5fc`, task security-policy). Also open, and not this PR's work: PR #112 on `design/floor-writer-service`.
>
> A security policy that points at artifacts rather than asserting a posture: the governed path is not enabled in shipped builds, and the negatives and the dated deferrals each name a file.
>
> **Standing verdict: RED** -- the NINTH round, `apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

**Next:** `T-055` — the first produced artifact, and nothing before it. Run
`python3 tools/check_produced_artifact.py`: it prints the five conditions and which are missing, and is **RED
by design** until the production half exists. `docs/design/PRODUCTION_HALF_DESIGN.md` is the design behind
those five; it is DESIGN-green only — no independent architect has read it and no product code exists. §3
names **which runtime code** enforces the network axis, because a grant stated in a prompt is not enforcement;
§4 puts credential SLOTS in the bundle and the binding outside it, so rotating a key cannot un-approve the
customer's agent by changing the digest.

*A green PR is not a green `main`, and `gh pr checks` is not `gh run list --branch main`.* Both red
`main`s of one session were called green because the PR's checks were read and the branch's were not.
Three more things must be true at every push: the PR body carries exactly one
`AUDIT_CANDIDATE_HEAD: <40-hex>` equal to the pushed head, `config/current_state.json` names the live
`main`, and the head named above moves **in its own commit** — an amend leaves the handoff naming a
commit that no longer exists.

`T-046`'s row stays open although it merged: one green run does not prove an intermittent. Stamp with
`tools/stamp_pr_head.py --pr <N>` — REST since `T-047`; `gh pr edit` dies here.

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

**The standing independent verdict is RED.** Nine rounds; the current one is
[`2026-08-19-ninth-audit-5cf9b8c.md`](apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md)
— RED, no P0, all three refusals read at source and closed for the fourth round running.
**20 pull requests, 107 files and 19688 inserted lines have merged since that head**, and
none of it is independently confirmed. Every mark added since is ◑.

**Nothing is waiting on the Owner.**
[`docs/OWNER_ACTION_REQUIRED.md`](docs/OWNER_ACTION_REQUIRED.md) is the page of record. O-1…O-5
are all OPEN and none needs an Owner-minted artifact; what blocks them is deployment wiring and
a second principal.

**There is no path in this repository to a production trust root.**
[`docs/DEBIAN_DEPLOYMENT.md`](docs/DEBIAN_DEPLOYMENT.md) states it: `broctl build-registry`
hardcodes `"production": false`, `broctl keygen --production` refuses, and `bro_signature` refuses
a development registry whenever the operator pin comes from the production path. Everything
runnable produces a **development** trust root — enough to exercise every path end to end, and not
enough to close O-2, O-3 or O-5.

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

**A green test is not a passing check.** When you add a check, delete it once, **grep the line
to confirm the mutation applied**, and confirm its test goes red. `T-045` swept its own two gates
and found **three of seven checks tested by nothing**, plus a fourth with no test at all. Of
roughly ninety checks swept in an earlier wave, four came back green.

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

`CURRENT_ACTIVE_TASK: security-policy` · `CURRENT_ACTIVE_WAVE: canon` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

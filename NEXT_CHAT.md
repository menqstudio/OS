# NEXT_CHAT — definitive handoff · վերջնական handoff

> **This file is the live handoff and nothing else.** It was 4034 lines on 2026-08-29,
> because every session appended its write-up and none removed one. That log is
> [`docs/archive/SESSION_LOG_2026-07_2026-08.md`](docs/archive/SESSION_LOG_2026-07_2026-08.md).
> `tools/check_canon_budget.py` holds this file to 12 KB: over that ceiling, the only edit
> the wall accepts is one that makes it smaller.

**Active branch:** `gate/canon-budget` · **head** `9e71923` · **task** `T-045`
**`main` is settled at** `b190a16` (PR #179) · **also open, deliberately unmerged:** PR #112 (`design/floor-writer-service`)

**Next:** finish `T-045` on `gate/canon-budget` — the canonical read set is still over
budget, so `python tools/check_canon_budget.py` is RED and this branch may not merge.
What remains is `TASKS.md`, `MASTER_EXECUTION_ROADMAP.md`, `config/current_state.json`
and `apps/desktop/AUDIT/AUDIT_LEDGER.md`. Run the gate; it names every file and its
overage. Then `python tools/check_handoff_ready.py`.

## Verify before you believe any of this

Run these. Do not take the numbers below on trust — that is this repository's first rule,
and the numbers in these documents have been wrong in every audit round so far.

```bash
cd engine && BRO_ENV=ci python3 -m unittest discover -s tests    # 2002 OK, 10 skipped
cd apps/desktop/src-tauri && cargo test --workspace              # 1012 passed
cd apps/desktop && npm ci && npm run typecheck && npm test       # 758 tests / 80 files
python3 tools/check_canon_budget.py                              # RED until T-045 lands
python3 tools/check_handoff_ready.py                             # RED until then too
```

Measured 2026-08-29 on **Debian**, cargo 1.97.1 / node 20.20.2 / npm 10.8.2, `cargo`
run from an ordinary shell. Several canonical documents still say this is a Windows box
and that `cargo` must run from PowerShell; on this machine that is false, and correcting
it everywhere is part of `T-045`.

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

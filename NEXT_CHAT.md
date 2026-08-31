# NEXT_CHAT — definitive handoff · վերջնական handoff

> **This file is the live handoff and nothing else.** It was 4034 lines on 2026-08-29,
> because every session appended its write-up and none removed one. That log is
> [`docs/archive/SESSION_LOG_2026-07_2026-08.md`](docs/archive/SESSION_LOG_2026-07_2026-08.md).
> `tools/check_canon_budget.py` holds this file to 12 KB: over that ceiling, the only edit
> the wall accepts is one that makes it smaller.

**Active branch:** `fix/handoff-names-a-dead-branch-commit` · **head** `629749c` (the MERGE BASE — a squash erases branch commits, so a handoff naming one names a dead object on `main`, and only the merge, after the fact, can see it) · **task** `egress-authorizer`
<!-- BANNER -->
> **⏭️ CURRENT ACTIVE: PR #213 · branch `docs/evidence-index`** (base `main`, tip `d42cb65`, task T-062). Also open, and not this PR's work: PR #112 on `design/floor-writer-service`, PR #207 on `feat/credential-store`, PR #208 on `feat/control-invocation`, PR #209 on `fix/prior-art-latest-declaration`, PR #210 on `feat/audit-rows-name-their-source`, PR #211 on `verify/queue-1-reverification`, PR #212 on `feat/negative-matrix-declared`.
>
> docs/EVIDENCE_INDEX.md: what an outside reviewer reads, in order, and what each artefact does not establish.
>
> **Standing verdict: RED** -- the NINTH round, `apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

**Next:** §4's credential store, then the TRANSPORT. Without a credential a call reaches no real
customer API, so transport-first would be more unreachable code.

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
Three things must be true at every push: the PR body carries exactly one
`AUDIT_CANDIDATE_HEAD: <40-hex>` equal to the pushed head, `config/current_state.json` names the
live `main`, and the head above moves **in its own commit**.

Stamp with `tools/stamp_pr_head.py --pr <N>`; `gh pr edit` dies here.

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

Measured on **Debian**, `cargo` from an ordinary shell. The three toolchain numbers have one
source of record — `config/toolchain.json` — and the documents that called this a Windows box
were corrected by `T-045`.

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
looked**. Both RED verdicts here came from rows marked `✅` by the session that wrote the
fix, so never promote your own work. Read
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

`CURRENT_ACTIVE_TASK: egress-authorizer` · `CURRENT_ACTIVE_WAVE: production-half` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

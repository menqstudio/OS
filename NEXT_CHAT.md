# NEXT_CHAT — definitive handoff · վերջնական handoff

> **This file is the live handoff and nothing else.** It was 4034 lines on 2026-08-29,
> because every session appended its write-up and none removed one. That log is
> [`docs/archive/SESSION_LOG_2026-07_2026-08.md`](docs/archive/SESSION_LOG_2026-07_2026-08.md).
> `tools/check_canon_budget.py` holds this file to 12 KB: over that ceiling, the only edit
> the wall accepts is one that makes it smaller.

**Active branch:** `fix/handoff-names-a-dead-branch-commit` · **head** `629749c` (the MERGE BASE — a squash erases branch commits, so a handoff naming one names a dead object on `main`, and only the merge, after the fact, can see it) · **task** `egress-authorizer`
<!-- BANNER -->
> **✅ SETTLED — `main` is at `094ea44`.** The pull request that records it is PR #202 on `chore/settle-at-green-main`. Also open, and deliberately not merged here: PR #112 (`design/floor-writer-service`). Blocked on whom: `docs/OWNER_ACTION_REQUIRED.md`.
>
> **Next:** Design SS3.3 slice 3: wire the authorizer into the StepKind::Call arm of repo.rs so the PRODUCED agent's Grant.egress is enforced, and let write_grant carry a non-empty egress. The build agent stays unjailed by the Owner's decision (T-058).
>
> **Standing verdict: RED** -- the NINTH round, `apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

**Next:** §3.3 slice 3 — the enforcement point. Slices 1+2 are in: `allowed_egress` is a REQUIRED
lease field (schema 1→2, absent ⇒ `LeaseError`) and `core/src/egress_proxy.rs` is the authorizer,
23 tests, no network, every check mutation-swept. `call` is still REFUSED, correctly.

**Two populations, two allowlists** (Owner, 2026-08-30 — §3.3 corrected in place). The PRODUCED agent's
list is `agent_bundle::Grant.egress`, already in the tree and forced empty; it enforces at the `Call` arm
of `repo.rs` — in-process, **no spawn**, and its closed four-kind vocabulary has no `Bash` to spell around
a matcher. The BUILD agent keeps a broad fixed `build_egress` and is **not** jailed. `ai.rs` has **three**
spawn sites, not two. No class holds `USE_NETWORK`, so every valid lease names **no** destination — the
axis exists, is required, and says "none".

*A green PR is not a green `main`, and `gh pr checks` is not `gh run list --branch main`.* Both red
`main`s of one session were called green because the PR's checks were read and the branch's were not.
Three more things must be true at every push: the PR body carries exactly one
`AUDIT_CANDIDATE_HEAD: <40-hex>` equal to the pushed head, `config/current_state.json` names the live
`main`, and the head named above moves **in its own commit** — an amend leaves the handoff naming a
commit that no longer exists.

Stamp the head with `tools/stamp_pr_head.py --pr <N>` — REST since `T-047`; `gh pr edit` dies here.

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

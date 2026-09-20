# PROJECT_STATE — live status · կենդանի վիճակ

**Last updated · Վերջին թարմացում:** 2026-09-20 — 49 pull requests merged (`#219`–`#267`), `main` at
`2045830`, its own `ci` green there. Seven of eleven phases have every box ticked (0, 2–7); 97 of 115
rows. Phase 1 waits on 24 prerequisites an installer and an administrator provide, the Linux kernel, and
one offline root signature only the Owner can make — that last one is the whole blocker, named on the
Owner page. The negative matrix reads: **155 implemented · 52 blocked · 35 unreviewed**, from 39/21/182.
Before: 2026-09-19 — twenty merged (`#219`–`#237`), `main` at `3909ede`: the supply-chain gate green
again, the `T-055` promise executed by the Owner, three canon tools fixed so the mirror cannot drift
unread, the §D keydown race closed.
It answers what `NEXT_CHAT.md` does not: **the state of each part of the product**. Its history
is in [`docs/archive/`](docs/archive/SESSION_LOG_2026-07_2026-08.md).

<!-- BANNER -->
> **⏭️ CURRENT ACTIVE: PR #271 · branch `t100/one-ucred-format`** (base `main`, tip `33b22b7`, task T-100).
>
> One kernel struct read five ways: the signed one is reconciled and the agreement is now checked
>
> **Standing verdict: RED** -- the TENTH round, `apps/desktop/AUDIT/2026-09-19-tenth-audit-75fca65.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

## Phases

Status is *what exists*, never *what is guaranteed to work*. The production gate is shut on every row;
where this and [`MASTER_EXECUTION_ROADMAP.md`](MASTER_EXECUTION_ROADMAP.md) disagree, the roadmap wins.

| Phase | Status |
|---|---|
| 0 Foundation | DONE, locked |
| 1 Bridge | In-Progress — contract, adapter, broker and receipt are real; `_real_callables()` raises unconditionally, and the desktop pre-flight MEASURES its five missing inputs now rather than asserting them (`T-048`). Both refuse |
| 2 Governance Sidecar | Done — 11/11; the approval-**request** path exists on both sides now (`T-021a`–`T-021d`), and nothing in it decides |
| 3 Desktop Integration | Done — 11/11 |
| 4 UI/UX System | Done — 12/12 |
| 5 Memory & Knowledge | Done — 11/11; local writes stay *recorded, not verified*, nothing is signed |
| 6 Multi-Agent | Done — 10/10 |
| 7 Group Chat | Done — 8/8 |
| 8 Automation | In-Progress — 7/9; `run_automation` is a local write, not a governed dispatch, so its receipt evidence is permanently unobserved |
| 9 Integrations | In-Progress — 7/9; inbound/outbound has no backing command and renders as blocked rather than pretending |
| 10 Production | Blocked — release refuses to ship unsigned; O-1 to O-5 all OPEN, none needing an Owner artifact |

## Suites

| Windows, 2026-09-20 | |
|---|---|
| engine (Python) | 2205 OK, 97 skipped |
| frontend | typecheck clean, 781 / 82 files |
| `tools/` self-tests | 1169 OK |
| **Debian, 2026-09-01** | |
| Rust, 10 crates | 1149 passed |
| `npm audit --audit-level=high` | 0 vulns |
| FW-1 boundary proof | 23/23 x3 |

Toolchain: `config/toolchain.json`, checked by `tools/check_doc_claims.py`; Debian, `cargo` from an ordinary shell.

## Standing risks

**RED is the independent verdict** — ninth round, `main` at `5cf9b8c`, no P0. **76 pull
requests, 240 files and 46,612 inserted lines** have merged since, none independently
confirmed — measured `5cf9b8c..main`, all squash-merged PRs.

**The audit ledger is not tamper-evident on any real deployment.** `BRO_AUDIT_ANCHOR_SIGNER`
and `BRO_AUDIT_ANCHOR_KEY_ID` decide custody and nothing in the shipped product sets either;
`tauri.conf.json` declares no `externalBin`, so no signer binary is installed. `append()`
therefore rewrites a plaintext `.head` and produces no `.head.sig`. This is O-2 and it has
never run outside a test.

**The app version is stated five times in four files;** `tools/check_version_parity.py` refuses drift.
No `v*` tag is compared — `release.yml` has never run — and what the files mean between tags is a
release policy the Owner has not stated (`T-063`).

**Branch protection was OFF for a day, and that is why 2026-09-19's merges were gated by reading.** A
private Free-plan repository gets neither the gate (`GET protection` → 403) nor free Actions minutes,
which ran out mid-session at 01:53Z: every job of `#229` failed in two seconds with zero steps. The
Owner made the repository public again; going private had DELETED the rules, so they were restored from
`config/required-checks.json` — 34 contexts, `strict`, `enforce_admins`, linear, no force-push, no
deletions — and `check_repo_state.py` verifies them against live GitHub.

**Provisioning is Windows-only.** Sealing the anchor refuses on POSIX and provisioning aborts startup,
so the first-launch trust path is unreachable on the Debian dev box.

**Two audit reports went missing, one unrecoverable** — the fifth never filed (15 promotions not
carried), the seventh reconstructed from two commit messages. `A-06` in the ledger.

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document.

`CURRENT_ACTIVE_TASK: floor-writer` · `CURRENT_ACTIVE_WAVE: production-half` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

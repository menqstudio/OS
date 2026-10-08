# PROJECT_STATE — live status · կենդանի վիճակ

**Last updated · Վերջին թարմացում:** 2026-10-08 — 147 pull requests merged (`#219`–`#366`), `main` at
`1b5c860`: all seven workflows green there. Seven of eleven phases have
every box ticked (0, 2–7); 97 of 115 rows. Phase 1 waits on 24 prerequisites an installer and an
administrator provide and the Linux kernel. The broker now reads its root from the floor-pinned
anchor (`T-140`); the install mints accounts and the engine anchor (`T-136`–`T-138`), not yet the
deployment or the broker root. The negative matrix reads: **171 implemented · 54 blocked · 17
unreviewed**, from 39/21/182.
It answers what `NEXT_CHAT.md` does not: **the state of each part of the product**. Its history
is in [`docs/archive/`](docs/archive/SESSION_LOG_2026-07_2026-08.md).

<!-- BANNER -->
> **✅ SETTLED as of `main` `1b5c860`.** PR #367 on `rust/undefended` records it and merges after: read the live head with `git log -1`. Blocked on whom: `docs/OWNER_ACTION_REQUIRED.md`.
>
> **Next:** Owner: commission the next independent audit.
>
> **Standing verdict: RED** -- the TENTH round, `apps/desktop/AUDIT/2026-09-19-tenth-audit-75fca65.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

## Phases

Status is *what exists*, never *what is guaranteed to work*. The production gate is shut on every row;
where this and [`MASTER_EXECUTION_ROADMAP.md`](MASTER_EXECUTION_ROADMAP.md) disagree, the roadmap wins.

| Phase | Status |
|---|---|
| 0 Foundation | DONE, locked |
| 1 Bridge | In-Progress — contract, adapter, broker and receipt are real; both live kits evaluate the §2.5 floor as root before any service starts (`T-115`); `_real_callables()` raises unconditionally, and the desktop pre-flight MEASURES its five missing inputs now rather than asserting them (`T-048`). Both refuse |
| 2 Governance Sidecar | Done — 11/11; the approval-**request** path exists on both sides now (`T-021a`–`T-021d`), and nothing in it decides |
| 3 Desktop Integration | Done — 11/11 |
| 4 UI/UX System | Done — 12/12 |
| 5 Memory & Knowledge | Done — 11/11; local writes stay *recorded, not verified*, nothing is signed |
| 6 Multi-Agent | Done — 10/10 |
| 7 Group Chat | Done — 8/8 |
| 8 Automation | In-Progress — 7/9; `run_automation` is a local write, not a governed dispatch, so its receipt evidence is permanently unobserved |
| 9 Integrations | In-Progress — 7/9; inbound/outbound has no backing command and renders as blocked; no connector can be toggled (OWNER 2g) |
| 10 Production | Blocked — release refuses to ship unsigned; O-1 to O-5 all OPEN, none needing an Owner artifact |

## Suites

Each row carries the date it was measured, because they are not measured together.

| Windows | |
|---|---|
| engine (Python) · 2026-09-21 | not re-measured |
| `tools/` self-tests · 2026-10-08 | 1769 OK; contrast gate 98 pairs |
| frontend · 2026-10-08 | typecheck clean, 1075 / 87 files |
| **Debian** | |
| engine (Python), non-root, Debian 13 · 2026-10-08 | 2741 OK, 17 skipped |
| Rust, 10 crates · 2026-10-08 | 1430 passed, 1 ignored (needs root; CI runs it) |
| `npm audit --audit-level=high` · 2026-09-01 | 0 vulns |
| FW-1 boundary proof · 2026-09-01 | 23/23 x3 |

Toolchain: `config/toolchain.json`, checked by `tools/check_doc_claims.py`; Debian, `cargo` from an ordinary shell.

## Standing risks

**RED is the independent verdict** — the TENTH round, `main` at `75fca65`, no P0. **112 pull
requests, 903 files and 106,095 inserted lines** have merged since, none independently
confirmed — measured `75fca65..main` at `40244f0` on 2026-10-08, PRs `#253`–`#365`.

**The audit ledger is not tamper-evident on any real deployment.** `BRO_AUDIT_ANCHOR_SIGNER`
and `BRO_AUDIT_ANCHOR_KEY_ID` decide custody and nothing in the shipped product sets either;
`tauri.conf.json` declares no `externalBin`, so no signer binary is installed. `append()`
therefore rewrites a plaintext `.head` and produces no `.head.sig`. This is O-2 and it has
never run outside a test.

**The app version is stated five times in four files;** `tools/check_version_parity.py` refuses drift.
No `v*` tag is compared and `release.yml` has never run. An UNSIGNED `brops-desktop-v0.1.0` release,
published by hand, is a DRAFT since 2026-10-08. The tag policy is the Owner's (`T-063`).

**Branch protection is in force again — the repository is public (read live 2026-10-08).**
All 35 contexts in `config/required-checks.json` are required on `main`, with `strict` and
`enforce_admins`; `check_repo_state.py` is GREEN. Private from 2026-10-05 it had none (`T-168`):
on this plan a private repository carries no protection, and going private deletes the rules.

**Provisioning is Windows-only.** Sealing the anchor refuses on POSIX and provisioning aborts startup,
so the first-launch trust path is unreachable on the Debian dev box.

**Two audit reports went missing, one unrecoverable** — the fifth never filed (15 promotions not
carried), the seventh reconstructed from two commit messages. `A-06` in the ledger.

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document.

`CURRENT_ACTIVE_TASK: floor-writer` · `CURRENT_ACTIVE_WAVE: production-half` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

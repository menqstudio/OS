# PROJECT_STATE — live status · կենդանի վիճակ

**Last updated · Վերջին թարմացում:** 2026-08-31 — the produced agent's egress is ENFORCED. `repo.rs`'s
`Call` arm decides every call against the grant's `egress` table (grant schema 1→2, a name→destination
table, so the flow never states a URL) and records each decision. The 60s tick now DISPATCHES armed
bundles instead of only enqueuing; bundles are born disarmed and arming needs a confirmed grant. A
permitted call is still refused for want of a transport. The BUILD agent's half is not built. `check_doc_claims` requires a named commit to be an ancestor of
`main`, so a dead branch hash is refused on the branch, not on `main` after the merge. The audit pointer and the toolchain are records
(`code_audit.last_independent_audit`, `config/toolchain.json`).
`T-046`, `T-048`–`T-053` merged.
It answers what `NEXT_CHAT.md` does not: **the state of each part of the product**. Its history
is in [`docs/archive/`](docs/archive/SESSION_LOG_2026-07_2026-08.md).

<!-- BANNER -->
> **⏭️ CURRENT ACTIVE: PR #219 · branch `feat/floor-writer-service`** (base `main`, tip `87bfe73`, task **T-020**). No other pull request is open.
>
> Five states kept apart: #112's DESIGN **merged** · Architect design audit **done** · five rulings **issued** · implementation **in progress, NOT approved** · production trust claim **NOT granted**.
>
> **Standing verdict: RED** -- the NINTH round, `apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md`. Check any tick in prose against `apps/desktop/AUDIT/AUDIT_LEDGER.md` before believing it.
<!-- /BANNER -->

## Phases

Status is *what exists*, never *what is guaranteed to work*. The production gate is shut on
every row. Where this table and [`MASTER_EXECUTION_ROADMAP.md`](MASTER_EXECUTION_ROADMAP.md)
disagree, the roadmap wins.

| Phase | Status |
|---|---|
| 0 Foundation | DONE, locked |
| 1 Bridge | In-Progress — contract, adapter, broker and receipt are real; `_real_callables()` raises unconditionally, and the desktop pre-flight MEASURES its five missing inputs now rather than asserting them (`T-048`). Both refuse |
| 2 Governance Sidecar | In-Progress — 8/11; the three open boxes are one fact, the approval-**request** path exists on neither side (`T-021`) |
| 3 Desktop Integration | Done — 11/11 |
| 4 UI/UX System | Done — 12/12 |
| 5 Memory & Knowledge | Done — 11/11; local writes stay *recorded, not verified*, nothing is signed |
| 6 Multi-Agent | Done — 10/10 |
| 7 Group Chat | Done — 8/8 |
| 8 Automation | In-Progress — 7/9; `run_automation` is a local write, not a governed dispatch, so its receipt evidence is permanently unobserved |
| 9 Integrations | In-Progress — 7/9; inbound/outbound has no backing command and renders as blocked rather than pretending |
| 10 Production | Blocked — release refuses to ship unsigned; O-1 to O-5 all OPEN, none needing an Owner artifact |

## Suites, measured on Debian 2026-08-29

| | |
|---|---|
| engine (Python) | 2069 OK, 10 skipped |
| Rust workspace, 10 crates | 1147 passed, 0 failed |
| frontend | typecheck clean, 761 tests / 80 files |
| `npm audit --audit-level=high` | 0 vulnerabilities |

Toolchain: `config/toolchain.json`, checked against every canonical document by
`tools/check_doc_claims.py`. This is Debian; `cargo` runs from an ordinary shell.

## Standing risks

**RED is the independent verdict** — ninth round, `main` at `5cf9b8c`, no P0. **56 pull
requests, 192 files and 39,396 inserted lines** have merged since, none independently
confirmed. *(Said 20/107/19688 until 2026-08-31.)*

**The audit ledger is not tamper-evident on any real deployment.** `BRO_AUDIT_ANCHOR_SIGNER`
and `BRO_AUDIT_ANCHOR_KEY_ID` decide custody and nothing in the shipped product sets either;
`tauri.conf.json` declares no `externalBin`, so no signer binary is installed. `append()`
therefore rewrites a plaintext `.head` and produces no `.head.sig`. This is O-2 and it has
never run outside a test.

**The app version was unheld across four files.** `package.json`, `tauri.conf.json`,
`Cargo.toml` and `package-lock.json` (twice) each state it; all say `0.1.0` and nothing compared
them — `npm ci` exits 0 on a disagreeing lock, measured. `tools/check_version_parity.py` now
refuses drift and names the file. It does **not** compare a `v*` git tag: `git tag -l` prints only
`brops-desktop-v0.1.0`, which does not match `v*`, so `release.yml` has never run, and what these
files mean between tags is a release policy the Owner has not stated.

**Provisioning is Windows-only.** Sealing the anchor refuses on POSIX and provisioning aborts
startup, so the first-launch trust path is unreachable on the Debian box this project now
develops on.

**Two audit reports went missing and one is unrecoverable.** The fifth round's report was
never filed and its 15 promotions are not carried; the seventh's was reconstructed from two
commit messages. `A-06` in the ledger.

## Status tokens

Restated verbatim from `config/current_state.json.status_tokens`, which `tools/check_coordination.py` requires of each coordination document. *(That requirement is why one document came to live in three files: three places obliged to carry the same text, and nothing obliging any of them to stay short.)*

`CURRENT_ACTIVE_TASK: floor-writer` · `CURRENT_ACTIVE_WAVE: production-half` · `CURRENT_PHASE0: done` · `CURRENT_DESIGN_GATE: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_CANDIDATE: rev-30` · `CURRENT_LAST_REVIEWED: rev-30` · `CURRENT_LAST_VERDICT: OWNER_APPROVED_NOT_ARCHITECT_AUDITED` · `CURRENT_DESIGN_PR: 48` · `CURRENT_IMPL_PR: 48` · `CURRENT_IMPL_STATE: consolidated` · `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` · `CURRENT_LINUX_E2E: proven` · `CURRENT_WINDOWS_LIVE_PROOF: proven` · `CURRENT_PRODUCTION_VERIFIED: false` · `CURRENT_VERIFY_SEAM: complete` · `CURRENT_RECEIPT_PLUMBING: complete` · `CURRENT_GOVERNED_ROUNDTRIP: complete`

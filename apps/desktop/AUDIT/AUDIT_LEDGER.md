# BroPS Audit Ledger · desktop + engine

> **Why this file exists (audit D-06/D-07):** the security tickets under `apps/desktop/AUDIT/tickets/`
> and `engine/AUDIT/tickets/` carried **no status/resolution field**, so a fixed finding and a forgotten
> one looked identical, and the desktop tickets were referenced from **nowhere** outside their own folder
> (orphaned). This ledger is the single index of record: it links both ticket sets, points at the current
> authoritative assessment, and records the status the Builder can evidence. It does **not** invent a
> status it cannot back — anything not individually re-verified is marked so, with the independent audit
> as the live source of truth for current-code behaviour.

**Authoritative current assessment:** [`2026-10-09-eleventh-audit-e3fc507.md`](./2026-10-09-eleventh-audit-e3fc507.md)
— the **ELEVENTH** independent audit, of `main` @ `e3fc507`, range `75fca65..e3fc507`. **Verdict:
RED, and no P0**: four P1, five P2, one P3. All three production-gate refusals were read in the code
and confirmed. The same auditor reviewed the `T-169` design and **rejected** it:
[`OWNER_COMMAND_PATH_REVIEW.md`](../../../docs/design/OWNER_COMMAND_PATH_REVIEW.md).

**Who audited.** OpenAI Codex CLI 0.151.0, model `gpt-5.6-sol`, commissioned by the Owner — a
different vendor and a different model from the Builder. The brief was written by the Builder and
approved by the Owner. During the run the Builder changed two things in the audit clone's environment
and nothing in its code: `npm ci`, and the clone's `origin` URL (a local path there made sixteen
engine tests error). The run took about thirteen minutes, and the report's own last section names
what it did not read.

The tenth round, superseded: [`2026-09-19-tenth-audit-75fca65.md`](./2026-09-19-tenth-audit-75fca65.md) — `main` @ `75fca65`, RED, no P0. Its narrative and
`J-01`–`J-04` are in [`AUDIT_LEDGER_ARCHIVE.md`](./AUDIT_LEDGER_ARCHIVE.md) under *Round 10*; the
ninth is there under *Round 9*.

> ## THE ELEVENTH ROUND: TEN FILED, TWO ANSWERED BY THE BUILDER
>
> The gate is shut and the round confirms it. What it found is **behind** the gate and beside it:
> `K-01` and `K-02` make the governed path fail the day refusal 3 is cleared, `K-03` was **reachable**
> by any user who types a non-ASCII unit into an automation trigger (fixed since, ◑), and `K-05` is the
> Builder's own `#378`, which granted the window a command that runs a shell on Windows and called
> it a read. **Nothing was fixed in the change that filed the report.**
>
> **What the Builder measured beside it (◑, not the auditor's).** In the same clone at `e3fc507`,
> outside the auditor's sandbox: engine **2741 OK** (17 skipped), `cargo test --workspace
> --no-fail-fast` **1432 passed, 0 failed**, frontend **1153 of 1153**. The auditor's own runs
> could not finish clean — its sandbox refuses `AF_UNIX` bind — which is `K-10`, and its point
> stands: the counted claim names no environment.

## How to read the status column

Three rounds of audit have now found a row's ✅ overclaimed. So the column no longer says ✅ for
anything an independent audit has not re-checked:

* ✅ — an independent audit confirmed it closed.
* ◑ — the Builder believes it closed and can point at code and tests, and **nobody else has
  looked**. Treat exactly as an unverified claim; that is what the last two rounds punished.
* 🔴 / ⚠️ — open.

The distinction is not bureaucratic. Both RED verdicts came from rows marked ✅ by the session
that wrote the fix, and in the worst case (F-02) the ✅ was written while the defect was still
live on the only platform where the Owner had ever been shown a `production_verified=true`.

## The eleventh round's own findings

Filed at `e3fc507`. Open unless the row says otherwise; the report has the reproduction and the fix for each.

| # | P | Finding | Status |
|---|---|---|---|
| `K-01` | P1 | **A verified output can be committed and then be undeliverable**: the contract admits 8,388,608 bytes, the broker's reply frame 8,192. | 🔴 Open |
| `K-02` | P1 | **A governed conversation blocks after its first reply**: the desktop stores role `agent`, the broker accepts `user`/`assistant`/`system`, and the passing fixture hand-inserts `assistant`. | ◑ Fixed after the round: one mapping, `governed_prepare::history_role_for_stored` (`agent` → `assistant`), used by the broker's window read; a stored role it does not know still Blocks, `assistant` included. The test goes through the real schema and `chat::post_message` and returned `UpstreamBlocked` first. It also found the window ordered same-millisecond messages by random UUID, not by write order; the tie-break is `rowid` now, as in the desktop. Not looked at: the broker hashes the raw body, the desktop's own path hashes an author-attributed transcript. |
| `K-03` | P1 | **A non-ASCII automation trigger panics the scheduler while it holds the database mutex** — `parse_interval_ms` splits on a byte index. | ◑ Fixed after the round: the unit comes off by `strip_suffix`, an overflowing count is refused, and two tests panicked on the old parser first — one of them through `run_due` with the row enabled |
| `K-04` | P1 | **Native approval text can be forged by the payload being approved**: control and bidi characters reach the trusted dialog. | ◑ Fixed after the round: every renderer-written field is shown indented or on one line with hidden and reordering characters as visible escapes (`core/src/dialog_text.rs`); three tests showed the forgery on the old code first. Display boundary only — nothing is rejected at write. Not done: the real dialog on each release OS, and how a backend wraps a very long body. |
| `K-05` | P2 | **`#378` granted a shell-running, unbounded command as tier R** — the trust self-test, on Windows with `BROPS_SELFTEST_MODEL_CMD` set. | ◑ Fixed after the round: the self-test spawns nothing on any platform and reads no variable; the grant stays. The test fails when a spawn is put back. Not looked at: `demonstration_verified_reply` still runs that variable on Windows, as tier X |
| `K-06` | P2 | **The automation delete prompt is text-spoofable and checks less than it shows** (`enabled` is displayed, not compared). | ◑ Fixed after the round: the fields are display-safe as in `K-04`, and after the dialog the prompt rebuilt from the current row must equal the one that was answered, so whatever is shown is compared. A toggle while the dialog is open deleted the row before; the test showed it. |
| `K-07` | P2 | **Signer store corruption raises instead of refusing** — OWNER item 5, now with a reproduction. Signs nothing. | 🔴 Open, engine security code |
| `K-08` | P2 | **A failed run step does not fail the run**; the next pending step stays claimable. | ◑ Fixed after the round: `fail_step_execution` fails the run in the same transaction; `next_runnable_step` offers nothing and `claim_step_for_execution` refuses when the run has a failed step or is finished. Three tests, the first two failed on the old code (the run stayed `drafted`). Not done: a test through the `stream_run_step` handler itself — it needs a Tauri window; the two functions it calls are the ones tested. |
| `K-09` | P2 | **Release CI builds POSIX packages whose first launch cannot provision** — only the `.deb` carries the installer. | 🔴 Open |
| `K-10` | P3 | **The counted full-suite claim names no environment** and did not reproduce in the auditor's. | 🔴 Open |

## Still open in the earlier rounds

Carried forward from [`AUDIT_LEDGER_ARCHIVE.md`](./AUDIT_LEDGER_ARCHIVE.md), which holds rounds 1–8 and the Builder sweeps in full. A row moved out of sight is a row that stops being answered, so the open ones stay here.

| # | Finding |
|---|---|
| `A-06` | The fifth audit's report was never filed; this ledger named the fourth as authoritative while the OWNER page carried the fifth's 15 promotions. |
| `A-09` | Three routes get a credential past the no-lease / no-secret whitelists; the tests prove frame shape and word-absence, not credential-absence. |

---

**Rounds 1–8 and the Builder sweeps:** [`AUDIT_LEDGER_ARCHIVE.md`](./AUDIT_LEDGER_ARCHIVE.md).

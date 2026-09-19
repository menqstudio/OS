# BroPS Audit Ledger · desktop + engine

> **Why this file exists (audit D-06/D-07):** the security tickets under `apps/desktop/AUDIT/tickets/`
> and `engine/AUDIT/tickets/` carried **no status/resolution field**, so a fixed finding and a forgotten
> one looked identical, and the desktop tickets were referenced from **nowhere** outside their own folder
> (orphaned). This ledger is the single index of record: it links both ticket sets, points at the current
> authoritative assessment, and records the status the Builder can evidence. It does **not** invent a
> status it cannot back — anything not individually re-verified is marked so, with the independent audit
> as the live source of truth for current-code behaviour.

**Authoritative current assessment:** [`2026-09-19-tenth-audit-75fca65.md`](./2026-09-19-tenth-audit-75fca65.md)
— the **TENTH** independent audit, of `main` @ `75fca65`. **Verdict: RED, and no P0** — and the
reason is now three named items rather than thirteen unconfirmed claims: `A-06` (a report that cannot
be recovered), `A-09` route 1 (open **by declaration**, with an enumeration in place of a heuristic),
and three documentation counts corrected in the change that filed the report. Nothing in this ledger
forbids building the approval-**request** path; the tenth round says so in writing.

The ninth round's own paragraph, kept because a superseded assessment is not a deleted one:
[`2026-08-19-ninth-audit-5cf9b8c.md`](./2026-08-19-ninth-audit-5cf9b8c.md)
— the **NINTH** independent audit, of `main` @ `5cf9b8c` (tree `9580b86d`, pin proven). **Verdict:
RED, and no P0** — all three production-gate refusals read at that head and verified closed for the
fourth round running, with `AnswerProvenance::Governed` confirmed constructed only inside
`#[cfg(test)]` and nothing in the tree setting `$BROPS_BROKER_CONFIG`.

> ## THE TENTH ROUND: TWELVE ✅, ONE REOPENED, THREE FILED
>
> Every one of the ninth round's thirteen was attacked **differently from the way its own fix
> describes** — re-running a Builder's own mutant confirms their arithmetic, not the finding — and
> where a row is a statement about file content it was read at `75fca65`. **Twelve earned ✅. One is
> REOPENED**, and it is a documentation count: `I-10`, whose gate numbers are stale for the third
> consecutive round. Nothing in the thirteen that touches a control, a gate or a trust boundary was
> found overstated.
>
> **Two of the confirmations are worth reading as attacks rather than as ticks.** `I-01`'s fix computes
> the credential register from each leaf's real validator, but computes it over a hand-written list of
> caller-controlled paths — so the probe added a leaf (`operator_hint`) to the wire frame, and **five
> tests died by name**, including `the frame is exactly its declared fields`. `I-02`'s fix claims an
> inverse assertion; the probe dropped a declared leaf out of the **production** frame builder rather
> than out of the fixture, and **ten of nineteen** went red. A test that only fails when you edit the
> test proves nothing.
>
> **Three filed.** `J-01` the architecture CI cell, stale in five places at once. `J-03` **the roadmap
> was in no gate's read set** — the document that decides which phase a session may work, whose 84
> checked boxes are this repository's central claim about what is finished, checked by nothing; every
> citation in it resolved when the gate was first pointed at it, which is the finding, because nothing
> kept it that way. `J-04` this ledger listed `G-05` as open while its own archive marks it ✅.
> **One withdrawn before filing** (`J-02`): drafted against `I-11` leaving `Decision.status` a `string`
> with no SQL `CHECK`, withdrawn on reading that both are stated decisions with a reason. A withdrawn
> finding is evidence the round read the answers and not only the code.
>
> **What the round does not say:** that the trust boundary is proven. No governed round trip runs on a
> default deployment, and phases 1, 2, 8 and 9 each hold Definition-of-Done rows open for stated
> reasons. Phase 1's is a **wiring** gap, not missing code: the §4.10(f) hop is in
> `broker/src/ladder_executor.rs`, and the row is open because `build_governed_executor` serves
> `UpstreamBlockedExecutor` without `$BROPS_BROKER_CONFIG`.

> ## THE NINTH ROUND — superseded, and its narrative is in the archive
>
> Nine Builder claims landed in PRs #153–#162 and the round decided them: **six ✅, two REOPENED, one
> held at ◑ on evidence no head can settle.** It then filed thirteen findings of its own, which the
> tenth round re-attacked — twelve confirmed, `I-10` reopened. The full narrative and all thirteen
> rows, each carrying the tenth round's verdict, are in
> [`AUDIT_LEDGER_ARCHIVE.md`](./AUDIT_LEDGER_ARCHIVE.md) under *Round 9*. They moved for the reason
> this file has a byte ceiling: it is read at the start of every session, and a round that has been
> answered is history.

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

## Promotions decided by the NINTH independent audit — in the archive

Thirteen findings, `I-01`–`I-13`, each with the Builder's response and the tenth round's verdict beside
it: [`AUDIT_LEDGER_ARCHIVE.md`](./AUDIT_LEDGER_ARCHIVE.md), *Round 9*. **Twelve ✅, one REOPENED**
(`I-10`, a gate count stale for a third round, corrected in the change that filed the tenth report).

## The tenth round's own findings

Filed at `75fca65`, and each corrected in the change that carries the report unless the row says
otherwise.

| # | P | Finding | Status |
|---|---|---|---|
| `J-01` | P2 | **`docs/ARCHITECTURE.md`'s CI cell was stale in five places at once**, in both language halves: 7 workflows against **8**; 33 checks per pull request against **37** reported on `#252`; 22 gates under `tools/` against **39** invoked; 23 files against **40**; 33 required against **34**; and *"exactly two"* excluded pull-request jobs against **four**. The cell's own parenthetical said the check count *"is not re-measured here"* — honest, and how it went four further rounds unmeasured. | ◑ Corrected in this change, both halves |
| `J-02` | — | **Withdrawn before filing.** Drafted as *"`I-11`'s fix left the type and the column open"*: `status: string` appears six times in `entities.ts` and `0002_decisions.sql` has no `CHECK`. Both are stated decisions with a reason — the value is read from a ledger this app does not own — and the test says so. | Withdrawn |
| `J-03` | P2 | **The roadmap was in no gate's read set.** `docs/roadmap/phase-*.md` is what `tools/check_roadmap_order.py` reads to decide which phase a session may work, and its **84** checked boxes across phases 1–9 are this repository's central claim about what is finished. It was in neither the canonical read manifest nor `ALSO_CHECKED`. Pointing the gate at all eleven files reported **nothing** beyond the two known `config/toolchain.json` lines: every path, hash and ticket it cites resolves. That is the finding — the referents were sound and nothing kept them sound. | ◑ Closed in this change: eleven files in `ALSO_CHECKED`, a test that the named set equals the set on disk, and a test that a dead path inside a phase file is caught |
| `J-04` | P3 | **This ledger listed a closed finding as open.** `G-05` sat in *"Still open in the earlier rounds"* — a table whose own words are *"the open ones"* — while the archive marks it ✅ with its attack. | ◑ Corrected in this change |

## Still open in the earlier rounds

Carried forward from [`AUDIT_LEDGER_ARCHIVE.md`](./AUDIT_LEDGER_ARCHIVE.md), which holds rounds 1–8 and the Builder sweeps in full. A row moved out of sight is a row that stops being answered, so the open ones stay here.

| # | Finding |
|---|---|
| ~~`G-05`~~ | **Closed, and it was listed here in error** — `AUDIT_LEDGER_ARCHIVE.md` marks it ✅ with the attack that closed it (`""` → RED, `None` → RED, `OPEN` → GREEN, all four `A-11` doors re-attacked). Removed by the tenth round as `J-04`: a table that says it holds the open ones must not argue with its own archive. |
| `A-06` | The fifth audit's report was never filed; this ledger named the fourth as authoritative while the OWNER page carried the fifth's 15 promotions. |
| `A-09` | Three routes get a credential past the no-lease / no-secret whitelists; the tests prove frame shape and word-absence, not credential-absence. |

---

**Rounds 1–8 and the Builder sweeps:** [`AUDIT_LEDGER_ARCHIVE.md`](./AUDIT_LEDGER_ARCHIVE.md).

# TASKS archive — 2026-09 · merged, awaiting independent confirmation

Every row here shipped: its pull request is merged and `main` was green after it. **None of it is
independently confirmed.** The standing verdict is RED — the ninth round,
[`apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md`](../../apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md)
— and a `◑` on a row here is the Builder's own claim, never a confirmation. Check any tick in prose
against [`apps/desktop/AUDIT/AUDIT_LEDGER.md`](../../apps/desktop/AUDIT/AUDIT_LEDGER.md) before
believing it.

They are here rather than on [`TASKS.md`](../../TASKS.md) because that file is read at the start of
every session and carries a 7,000-byte ceiling. Five consecutive pull requests met that ceiling by
shortening prose, including other people's; the ceiling's own remedy text says to move the history
out and leave the live statement behind. The live statement is on the board in one line naming all
18 of these and their pull requests. What is here is the account of each defect, which is
what "how did we get here" means.

Nothing was summarised on the way in. Each row is verbatim from the board as of 2026-09-19.

| ID | Task | Claimed by | Status | Branch / PR |
|----|------|-----------|--------|-------------|
| **T-073** | **Six front-page numbers were never measured** — five stale, and the control split `45 / 14` summed to a right 59 while wrong at every head ◑ | Bro | Review | merged `#239` |
| **T-071** | **Every stamp burned a full `ci` run** — `restamp()` moved a correct marker past the attribution line, so `edited` restarted 21 jobs ◑ | Bro | Review | merged `#231` |
| **T-070** | **Three advisories, one HIGH, waived under a neighbour's reason** — a gate refuses both shapes now ◑ | Bro | Review | merged `#230` |
| **T-069** | **The §D keydown listener was a commit behind its data** — a keypress in the passive-effect window was dropped silently ◑ | Bro | Review | merged `#227` |
| **T-068** | **The frontend suite oversubscribed the machine** — vitest's default spent half its time in `environment`; `maxWorkers: 4` halves it | Bro | Review | merged `#223` |
| **T-067** | **`_rest_open_prs` named `menqstudio/OS`** (H-05); built from `_repo_slug()` now, no slug ⇒ no read ◑ | Bro | Review | merged `#222` |
| **T-066** | **Two tools lied, untested** — UTF-8 git reads, the carrier moves `what`/`current`, `main_ci` measured ◑ | Bro | Review | merged `#221` |
| **T-065** | **Supply-chain gate was red for weeks** — `browserslist` and `rustls` lifted, `T-055` done by the Owner ◑ | Bro | Review | merged `#220` |
| **T-064** | **The shut gate names WHICH requirement a machine fails** — `preflight.rs`, and who provisions each | Bro | Review | merged `#217` |
| **T-063** | **The app version is stated 5x in 4 files** — the gate refuses drift. **Open: the git-tag arm**, a release policy the Owner has not stated | Bro | Todo | merged `#214` |
| **T-059** | **`main_ci` was stale by construction** — an OLDER reading passed while every run since was `success`; refused now | Bro | Review | merged `#219` |
| **T-060** | **A PR outliving its `Last updated` line reddened `main` on merge** — the gate asks whether the commit MOVED the line | Bro | Review | merged `#219` |
| **T-072** | **The gates had never run on Windows** — every `tools/` self-test step ran on ubuntu, five printed `a\b` and two `check_audit_actor` tests were red here ◑ | Bro | Review | merged `#232` |
| **T-074** | **No gate read the front page** — in no manifest meant in no check; `ALSO_CHECKED`, 145 → 204 paths, and a C0 byte found ◑ | Bro | Review | merged `#241` |
| **T-075** | **A test that does not exist cannot fail** — NM-CRASH-01 bound; its first copy landed past `unittest.main()` ◑ | Bro | Review | merged `#242` |
| **T-076** | **A required gate failed 1 run in 40** — `pages.browser.spec.tsx` sampled the DOM once after `mount`; polling instead, 18-red proof ◑ | Bro | Review | merged `#243` |
| **T-077** | **The crash family is closed in §3** — NM-CRASH-12/13/14; the floor turns out to be defended twice, so one mutant each survives and both together kill ◑ | Bro | Review | merged `#244` |
| **T-078** | **Every TCB violation test poked one file** — the floor is now asserted over the WHOLE pinned set and all seven principals; plus a trigger a neighbour claimed and never checked ◑ | Bro | Review | merged `#245` |

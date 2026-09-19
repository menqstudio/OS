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
35 of these and their pull requests. What is here is the account of each defect, which is
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
| **T-079** | **Four predicates, four independent kills** — a spent nonce, a divergent challenge context, an accessor nobody may add, and a trust class nobody may infer ◑ | Bro | Review | merged `#246` |
| **T-080** | **Three bare sections got artwork, nothing was removed** — and a designer "Verified" a dark sheet it never shipped; nine mechanical checks on every sheet since ◑ | Bro | Review | merged `#247` |
| **T-081** | **A key with everything right except audience, and a refusal that must carry no bytes** — NM-SCOPE-04, NM-TERM-04 ◑ | Bro | Review | merged `#248` |
| **T-082** | **The triage sent a test where it could not import what it tests** — only 4 of 12 runtime modules import without `cryptography` ◑ | Bro | Review | merged `#249` |
| **T-083** | **A mutation that did not run looks exactly like a survivor** — five times in one day; the harness now refuses a verdict it cannot prove it applied ◑ | Bro | Review | merged `#250` |
| **T-084** | **The page re-trued for four landings at once** — matrix 144→150, engine 2148→2152, the to-scale bar redrawn, and T-072 carried off the board ◑ | Bro | Review | merged `#251` |
| **T-085** | **No gate read the front page's pictures** - `check_artwork_geometry.py`, eleven rules; it found a dark panel a step lighter than every other panel on its first run ◑ | Bro | Review | merged `#252` |
| **T-086** | **The roadmap was in no gate, and three documents were stale** - `check_doc_claims` reads all 11 phase files now; START_HERE said 23 gates against 40 ◑ | Bro | Review | merged `#253` |
| **T-087** | **Phase 1 waits on a decision, not a deployment** - `custody.committed_label_resolver` is `NotProvisionableOnAMachine` and was on no Owner page; a test now refuses that class of silence ◑ | Bro | Review | merged `#258` |
| **T-089** | **The roadmap sheet said all ten phases were partly built** - seven of eleven have every box ticked; the figure, its alt text and both summaries re-trued at `a94513e` ◑ | Bro | Review | merged `#259` |
| **T-090** | **Three roadmap rows named things that had stopped being absent** - a schema that exists now, a count of five that is six, and a record that ended in the present tense ◑ | Bro | Review | merged `#261` |
| **T-091** | **NM-MAN-06 bound** - an attestation key id the manifest never pinned is refused before any signature check, and the refusal spends neither the receipt nor the nonce ◑ | Bro | Review | merged `#262` |
| **T-092** | **NM-TCB-25 bound** - an allowlist emptied after signing refuses the NEXT turn and leaves the signed record verifying byte for byte; read on exactly one path ◑ | Bro | Review | merged `#263` |
| **T-093** | **NM-OUTPUT-05 bound** - an execution receipt that agrees about the run and the attempt but names another turn's real output is refused, naming the document and the field; measured unprotected first (2,198 tests green with the rule removed) ◑ | Bro | Review | merged `#264` |
| **T-094** | **The one thing blocking phases 1, 8 and 9 was in no document, and the fact it rests on was checked by nothing** - a gate derives a public key from every 32-byte literal in the tree and refuses if one is a pinned production root's private half; the Owner page names the offline seed as the single remaining action ◑ | Bro | Review | merged `#265` |
| **T-095** | **Ten assertions could not fail, and the byte that killed them is refused now** - five word-boundary regexes in each of two honesty tests were literal backspaces, so the UI's receipt vocabulary was unguarded; proved by injecting `custody` ◑ | Bro | Review | merged `#266` |
| **T-096** | **The lease bounded launch and nothing after it** - a completion past `lease_expires_at_ms` is refused as `lease_expired` on both the run's stamp and the supervisor's clock, while an idempotent crash-retry still recovers; `NM-TIME-13` and `NM-TIME-18` out of `blocked` ◑ | Bro | Review | merged `#267` |

# T-156 — the audit ledger's append lock: CODE-AUDIT request

> **For the Architect.** Roadmap §G.2 makes an Architect audit mandatory for engine security code,
> and the Owner chose the audit over a waiver for this change on 2026-10-02. The code is written and
> is **not merged**. It was built before the audit, not after it as §G.2 asks; that order is the
> Builder's, and it is said here rather than left to be noticed.
>
> **What the merge gate needs from you.** A report committed on this pull request's branch at
> `apps/desktop/AUDIT/changes/` (see the second round below for why not `engine/AUDIT/`) carrying two lines,
> `Audited-PR: #328` and `Audited-Head: <the 40-hex commit you read>`. The gate
> (`tools/check_merge_ready.py`) refuses the merge unless that commit is an ancestor of the head
> being merged and no audit-required path differs since it. Take the head from
> `gh pr view 328 --json headRefOid`; this page names no commit on purpose, because a page inside
> the branch cannot name the branch's own head.
>
> Everything below marked ◑ is the Builder's claim. Nothing here is independently confirmed.

## 1. What changed, in one paragraph

`engine/runtime/bro_audit_log.py::append` is one critical section: read the chain, derive `seq` and
`prev_hash` from its tail, append the record, replace the plaintext head, anchor. Until this change
the section was guarded by a lock **file** created with `O_CREAT|O_EXCL`. A holder that died left the
file behind and every append after it was refused until a person deleted the file. The section is
now guarded by an exclusive **kernel advisory lock** held on a descriptor of `<ledger>.append-lock`:
`flock` on POSIX, a byte-range lock on Windows. The kernel releases it when the holder dies.

## 2. What is accepted now that was refused before

**One thing, and it is the point of the change:** an append after a holder died while holding the
lock. Before: refused forever. Now: proceeds.

The Builder's argument that this widens nothing that mattered: the old refusal did not protect the
ledger's content — a dead holder is not writing — it only denied service. **This argument is the
first thing to attack.**

## 3. What is refused now that was accepted before

- `append()` onto a ledger whose last byte is not a newline (`AuditTornTail`). Before this change it
  appended, fusing two records into one line no reader could parse.
- A lock path that is a symbolic link, or is not a regular file; a platform or filesystem with no
  kernel lock; a live holder that does not release within `_LOCK_TIMEOUT` (`AuditLockUnavailable`).
  The wait is bounded and fails closed: it never proceeds unlocked and never waits forever.

## 4. What is deliberately NOT changed

- **O-2 is untouched.** The lock is advisory. It is an agreement between honest writers, not an
  integrity control: the ledger is still not tamper-evident against its own writer wherever anchor
  custody is unconfigured, which is every shipped deployment today.
- **`append()` still does not consult the head.** An append onto a *truncated* ledger (head ahead of
  the chain) still succeeds and writes a fresh, consistent head over the truncation, exactly as
  before. Only a `verify()` that runs first, or a signed anchor, sees it. The Builder recommends
  making `append()` verify the head under the lock and refuse; that is **not** in this pull request,
  because it is a second change to the same perimeter and the Owner has not been asked to decide it.
- A leftover `<ledger>.lock` from the old scheme is never read, trusted or deleted.
- The lock is not shared with `bro_approval_requests._write_lock`. That lock yields the handle of
  the log it locks and has no POSIX deadline; the two are pinned against drift by a test instead of
  being merged into one helper.

## 5. What a dead writer leaves, and the rule for each

The write order is fixed: record line (record and newline together, then fsync), then head (temp
file, atomic rename), then anchor.

| Left behind | `verify()` | next `append()` |
|---|---|---|
| nothing | passes | proceeds |
| a torn record (no trailing newline) | refuses, `AuditTornTail` | refuses, `AuditTornTail`; nothing is repaired |
| a complete record whose head never landed | refuses, `AuditHeadBehind` | proceeds and writes a head that covers the record; nothing is dropped |
| record and head, no anchor (custody configured) | every keyed `verify()` refuses | proceeds and re-anchors |

Nothing is claimed about power loss: neither the head's temp file nor the directory entry is fsynced.

## 6. Files

| File | What |
|---|---|
| `engine/runtime/bro_audit_log.py` | the lock (`_append_lock`, `_open_lock_file`, `_try_lock`, `_is_still_the_lock_file`, `_close_lock`, `_drop_inherited_locks`), `_refuse_unterminated_tail`, three named refusals |
| `engine/tests/test_stop_and_audit.py` | 23 new tests |
| `engine/tests/catalog.json` | the new coverage names |
| `apps/desktop/src-tauri/provision/src/audit_signer.rs` | comments only: they described the lock file |

## 7. What the Builder ran ◑

- Engine suite on this branch: 2689 tests, OK, 13 skipped (Debian 13, non-root, `BRO_ENV=ci`); it was 2666 before the 23 new tests.
- A mutation sweep of 31 mutants over the new code; each was killed by the tests named for it and
  the suite was green again after the restore.
- Each state in §5 was reproduced on the old code before the change and then tested on the new.

## 8. What was NOT run

- **Nothing was run on Windows.** The `msvcrt` byte-range arm is exercised here only against a fake
  `msvcrt`. CI's Windows engine job runs the suite; whether its tests reach the real arm is for the
  auditor to read, not for this page to assert.
- No test kills a holder with a real power loss, a full disk, or an NFS mount.
- No second principal was involved at any point.

## 9. Questions for the audit

1. Is §2's argument sound — is there any state in which the old permanent refusal was protecting the
   ledger, so that releasing on death now admits a write that should have been stopped?
2. `flock` is per open file description. A `fork()`ed child inherits the description; the change
   closes the child's copy in an at-fork hook. Is there an inheritance path that hook misses —
   `subprocess` with `close_fds=False`, a descriptor passed over a socket, `posix_spawn`?
3. A waiter re-checks that the lock path still names the inode it locked. Can a party who may write
   the ledger's directory still make two writers each believe they hold the lock, and does that
   differ from what the same party could do to the old lock file?
4. On Windows a byte-range lock at `_LOCK_OFFSET` is mandatory for the range, not advisory. Does
   anything else open that file in a way the lock would break, and is the range beyond any real size
   of the file?
5. The signer runs inside the lock with `_SIGNER_TIMEOUT` equal to `_LOCK_TIMEOUT`. Can a slow signer
   make every other writer fail closed, and is failing closed there the right answer?
6. `AuditHeadBehind` is recovered by the next `append()` without a human. Is there a way to produce
   "exactly one correctly linked record more than the head" by tampering, so that the recovery
   launders it?
7. `AuditTornTail` is never repaired by code. Is refusing every append until an operator looks the
   right availability trade for an audit ledger, given that every governed allow records here?
8. Should `append()` verify the head under the lock and refuse a truncated ledger (§4)? The Builder
   says yes, as its own change.
9. Is anything in the docstring's claims about what the lock does and does not guarantee stronger
   than the code supports?

## 10. Second round — what changed after the first audit

The first audit (`apps/desktop/AUDIT/changes/pr-328-audit-ledger-lock.md`, verdict **RED** at the
head it names) is answered as follows. Nothing below is confirmed by anyone but the Builder ◑.

| Finding | What was done |
|---|---|
| **F-05** `append()` overwrote the head of a truncated ledger | **Fixed.** `append()` now runs `_check_chain` and `_check_head` — the same functions `verify()` runs — under the lock and before writing. A truncation, a head for another chain, records with no head, and a chain with a broken link are refused and nothing is written; `AuditHeadBehind` alone is let through, because the append is its repair. The head cases raise `AuditTruncated`, a new subclass of `AuditError`. Three tests over fifteen ledger shapes; 13 mutants, each killed by a named test. §4's second bullet above is therefore no longer true. |
| **F-01** the full suite was not green on the auditor's host | **Not a change to this pull request.** The auditor's host had Python 3.14 with no `venv`, no `cryptography`, and no `python` on `PATH`. The same suite is 2692 tests, OK, 13 skipped here and green in CI. Two of the six are worth their own look and are recorded as open: the sudoers tests fail against a real `visudo`, and no `visudo` exists on the Builder's box, so that branch has never run here. |
| **F-04** Windows not live-certified | **Run on Windows at the second-round head by a separate Codex session, tests only; the transcript, relayed by the Owner, is [`apps/desktop/AUDIT/changes/pr-328-windows-run-relayed.md`](../../apps/desktop/AUDIT/changes/pr-328-windows-run-relayed.md).** `test_stop_and_audit`: 40 tests, OK, 9 skipped; 24 tests take the real `msvcrt` lock on a real file; a terminated holder did not strand the ledger; a truncated ledger was refused with `AuditTruncated`. **Not run there:** the three symlink tests (the account could not create a symbolic link). The full suite there has 10 failures and 1 error, none in this module; they are recorded as open items B-04 to B-07 in `docs/WHOLE_REPO_READ_2026-10-02.md`. |
| **F-02** descriptor passing is outside the fork defence | Docstring now says exactly that. No code: nothing in the engine passes that descriptor. |
| **F-03** the lock is advisory | Unchanged and documented, as the audit says. |
| **F-06** the signer runs inside the lock | Unchanged: fail-closed is the intent. |

**Where the report goes, and a defect found in the merge gate.** The first report was filed under
`engine/AUDIT/changes/`, as `tools/check_merge_ready.py` recommended. Every Markdown file under
`engine/` must be registered in `engine/config/documentation-manifest.json`
(`tools/bro_docs_freshness.py`), and that file is an audit-required path: registering the report
is a change to engine security configuration AFTER the audited head, which the same gate refuses.
The recommendation could not be followed. The report was moved, unchanged, to
`apps/desktop/AUDIT/changes/`, which the gate accepts and no manifest lists. **File the
second-round report there:** `apps/desktop/AUDIT/changes/pr-328-audit-ledger-lock-round-2.md`.

**New questions.**

10. `append()` now pays a full chain walk on every call. Is there a ledger size at which that
    becomes a denial of service on the governed path, and should it be bounded?
11. A ledger with a pre-existing break now refuses every append until an operator acts. Is that the
    right availability trade for the plaintext-head check, given it adds no tamper-evidence?

**Question 10, measured** (Builder, Debian 13): one `append()` costs 11 ms at 1,000 records, 58 ms at 5,000, 225 ms at 20,000 and 1.17 s at 100,000 (34 MB) — linear, about a third of it the read that was always there. Nothing bounds it. Recorded as open item B-08; a rotation or checkpoint design is not part of this pull request.

## 11. Third round — the Architect's 33 failures, and where a Windows run can be audited

**The full suite on the Architect's host (Python 3.12, hashed install): 2692 run, 3 failures,
30 errors, 15 skipped.** The Builder read all 33. Two causes, neither in this pull request's diff ◑:

- **31** (`test_audit_head_anchor` 21, `test_backup_restore` 7, `test_monitor` 3): the stand-in
  signer the tests start cannot import `cryptography`. `_signer_argv` resolves the signer's
  interpreter through symbolic links, and a virtualenv's `python` is one, so the signer runs
  under the base interpreter. Open item B-09. That code is unchanged by this pull request.
- **2** (`test_live_sudoers_install`): the host's `visudo` rejects the kits' sudoers rule with
  `wildcards are not allowed in command arguments`. Open item B-03. Unchanged by this pull request.

**The claim to check, rather than believe:** the same 33 fail on `main` at the merge base on the
same host. If they do, this pull request did not introduce them.

**A Windows run that can be audited.** CI ran the engine suite on `windows-latest` for the
audited head: run `37002084820`, job `110821857190`, Python 3.12,
`python -B -m unittest discover -s tests -v`, `Ran 2692 tests ... OK (skipped=233)`. Its log is
readable with `gh api repos/menqstudio/OS/actions/jobs/110821857190/logs`. In it the three symlink
tests of `test_stop_and_audit` are `ok` (the runner may create symbolic links; the relayed session
could not), as are `test_a_holder_killed_while_holding_the_lock_does_not_strand_the_ledger` and
`test_separately_started_processes_appending_together_keep_one_valid_chain`. The Linux job of the
same run is `110821857399`: 2692 tests OK there too.

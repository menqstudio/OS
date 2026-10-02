Audited-PR: #328
Audited-Head: e53ce35b5edb32e5d5917812094e6c41248fd73a

VERDICT: RED — the T-156 lock implementation passes its focused 37-test class and the independent failure-injection probes below, but the required full engine suite is not green (2689 run, 5 failures, 1 error, 15 skips). The required fresh virtualenv could not be created because this host's Python 3.14 lacks ensurepip. In addition, the audit identifies advisory-lock limitations that the code documents but does not eliminate: file writers that bypass the lock, descriptor transfer over an IPC channel, and append recovery that does not verify a head-ahead/truncated ledger before overwriting its head.

## Method and environment

I verified `gh auth status` as `menqstudio`, cloned a fresh checkout, checked out PR #328, and verified the exact audited head. The requested venv command failed before installation because `python3.14-venv`/ensurepip is unavailable. I therefore ran the suite with the host interpreter (Python 3.14) and recorded that limitation. No repository code was changed. All ad-hoc probes were under `/tmp`.

The focused T-156 test class was run with:
`BRO_ENV=ci PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest tests.test_stop_and_audit`
Result: **37 tests, OK**.

The required full suite was run with:
`cd engine && BRO_ENV=ci PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests`
Result: **Ran 2689 tests in 77.838s; FAILED (failures=5, errors=1, skipped=15)**.
Failures/errors were independently captured in `/tmp/t156-suite.out`:
- `test_live_required_dependencies_resolve`: `cryptography (imported)` environment health error.
- wired interpreter tests: `settings.json` names `python`, which is not on this host PATH.
- two live sudoers tests: real `visudo` rejects wildcard command arguments.
These are reported, not altered.

Independent `/tmp/t156_break.py` probes:
- two separately started processes: both exit 0; 100 records; 100 unique sequence numbers; verify succeeds.
- holder killed with SIGKILL: subsequent append succeeds; one recovery record remains.
- child killed between record write and head replacement: verify reports `AuditHeadBehind`; next append recovers and verify succeeds with all records retained.
- symlink at lock path: `AuditLockUnavailable`; no redirected append.
- fork while holding lock: child exits; parent releases; subsequent append succeeds.

## Findings

### F-01 — Full required suite is not green (HIGH, environment/CI evidence)
Evidence: the exact required command measured 2689 tests with 5 failures, 1 error and 15 skips. This blocks a GREEN audit verdict even though the T-156-focused tests pass. The failures are in `engine/tests/test_env_health.py`, `engine/tests/test_bytecode_shadow.py`, `engine/tests/test_live_hook_deny.py`, and `engine/tests/test_live_sudoers_install.py`; no T-156 source was changed to hide them.

### F-02 — Descriptor-transfer inheritance is outside the at-fork defense (MEDIUM, code analysis)
Evidence: `engine/runtime/bro_audit_log.py:332-353` tracks descriptors held by this process and closes copied descriptors in `register_at_fork(after_in_child=...)`. Python's normal non-inheritable/close-on-exec behavior covers ordinary subprocess/exec inheritance. A descriptor explicitly transferred after fork over a Unix socket/SCM_RIGHTS, or otherwise made inheritable and passed through a custom file-action mechanism, is not covered by this hook. I did not claim that such a transfer is possible through the current application path; it is a boundary of the stated fork defense.

### F-03 — Lock is advisory and inode replacement is only defended for cooperating writers (MEDIUM, code and probe evidence)
Evidence: `bro_audit_log.py:114-123` expressly calls the lock advisory; `:423-440` checks the inode after acquisition. The probe confirmed a waiter refuses/recontends when the lock path is replaced. A process that never calls `_append_lock`, or a party able to replace the path and write the ledger directly, is outside the guarantee. This is correctly documented, but it is not a tamper control.

### F-04 — Windows locking path is not live-certified here (MEDIUM, test/code evidence)
Evidence: `bro_audit_log.py:409-417` uses `msvcrt.locking` at `_LOCK_OFFSET`; the focused suite's Windows test is explicitly a fake `msvcrt` arm, not a Windows kernel run. I did not execute on Windows, so sparse-file/byte-range behavior, sharing modes, and real cross-process contention remain unverified in this audit.

### F-05 — Append recovery can overwrite a head that is ahead of a truncated ledger (HIGH, code/document evidence)
Evidence: `bro_audit_log.py:114-123` explicitly states append does not police a head-ahead/truncated ledger; `append()` derives the new head from records read at `:867-930` and atomically replaces the sidecar. A prior `verify()` or a signed external anchor can detect this, but an append performed first can make the new head internally consistent with the shortened chain. This is a documented integrity limitation and is a blocking finding for a claim that append alone detects every truncation.

### F-06 — Signer timeout trades availability for fail-closed integrity (LOW/MEDIUM, code evidence)
Evidence: `_SIGNER_TIMEOUT` and `_LOCK_TIMEOUT` are both 10 seconds at `bro_audit_log.py:198-210`; signing occurs while the append lock is held at `:918-929`. A wedged signer therefore causes all competing writers to time out/refuse rather than proceed. This is fail-closed and intentional; no real slow-signer process was run here.

## T-156 audit request: nine questions answered

1. **Was the old permanent refusal sound?** No for content integrity. The old O_EXCL lock-file existence refusal treated a dead holder's leftover file as a permanent deny and protected availability, not the chain; it did not distinguish a live holder from a stale marker. The new kernel lock removes that dead-writer denial while retaining content refusals.

2. **What fork/inheritance path is missed?** The registered at-fork hook closes descriptors copied by `fork()` in the child. Ordinary Python subprocess exec is protected by non-inheritable descriptors. Explicit descriptor transfer over IPC (for example SCM_RIGHTS), or custom inheritable/file-action passing, is outside the hook and was not exercised by the application tests.

3. **Is there an inode/path replacement race?** For cooperating appenders, the post-acquisition `(st_dev, st_ino)` comparison at `:423-440` detects replacement and re-contends; my replacement probe exercised this. The lock remains advisory, so a non-cooperating direct writer can bypass it, as the module documents.

4. **Does Windows byte-range locking behave correctly?** The implementation seeks to `_LOCK_OFFSET` and locks one byte with `msvcrt.locking`, then unlocks the same position. The repository test uses a fake Windows arm only. No live Windows kernel run was available, so real cross-process Windows semantics are NOT CERTIFIED by this audit.

5. **Does signer timeout equal lock timeout and what is the effect?** Yes: both are 10 seconds. The signer runs inside the critical section. A slow or wedged signer blocks the section until the bounded timeout and then fails closed; competing writers refuse rather than write unanchored or wait forever. This is an availability cost accepted for anchor correctness.

6. **Can `AuditHeadBehind` launder exactly one tampered record?** A complete record with a head rolled back by one is indistinguishable from the crash state and the next append rolls the head forward. The record is not dropped and its hash link remains. Without an external signed anchor, a party able to rewrite the ledger can still rewrite the chain; with anchor custody, keyed verification/anti-rollback is the required control. This is a known limitation, not proof of authenticity.

7. **Is `AuditTornTail` refusal the right tradeoff?** Yes. Refusing a partial or unterminated final record preserves evidence and prevents silently dropping bytes. The focused test and mutation probe confirmed that removing `_refuse_unterminated_tail()` makes the test fail.

8. **Should append verify the head under the lock?** Yes, if the desired property is that append itself must not overwrite a head-ahead/truncated ledger. Current code intentionally does not; it relies on a prior `verify()` or an external signed anchor. That is the blocking F-05 limitation above and must be addressed for a stronger claim.

9. **Does the docstring overclaim?** It is careful to call the lock advisory and to state the head-ahead limitation. The only boundary requiring operational qualification is that the fork statement applies to descriptors copied by `fork()`, not descriptors later transferred over IPC or custom inheritance paths, and the Windows arm is not live-certified here.

## Mutation testing of five defenses

Each mutation was applied to a saved temporary copy of the one source file, the named test was run, the mutation was restored byte-for-byte immediately, and the working tree was rechecked clean:

1. Removed the post-acquisition `_is_still_the_lock_file` condition (`:490`): `test_a_waiter_does_not_take_its_lock_on_a_lock_file_that_was_replaced_under_it` went RED because the waiter appended concurrently.
2. Removed `O_NOFOLLOW` from `_open_lock_file` (`:368-376`): `test_a_symlinked_lock_path_is_refused_and_cannot_redirect_the_lock` went RED (symlink was treated as contention/timeout rather than named symlink refusal).
3. Replaced `os.register_at_fork(after_in_child=_drop_inherited_locks)` (`:352-353`) with a no-op: `test_a_forked_child_of_a_dead_holder_does_not_keep_the_lock_alive` went RED with `AuditLockUnavailable`.
4. Removed `_refuse_unterminated_tail(p)` (`:867-930`): `test_a_complete_last_record_with_no_newline_is_never_appended_to` went RED because `AuditTornTail` was not raised.
5. Changed the POSIX `BlockingIOError` contention return from `False` to `True` (`:405-407`): `test_a_live_holder_that_never_releases_makes_the_append_refuse_and_write_nothing` went RED because the second writer appended.

## What I did NOT check

- No live Windows kernel run.
- No IPC descriptor-passing/SCM_RIGHTS integration path.
- No production signer/anchor-custody deployment or trusted-key registry; the audited branch's focused tests exercise seams.
- No power-loss/fsync durability test (the module explicitly makes no such claim).
- No full pre-tool hook execution around the two shell-classifier findings (that belongs to Task B design).
- No merge, deployment, or production-host certification; this task forbids merge and code changes.
- The fresh venv/dependency-lock install could not be completed because ensurepip is absent on this host.

## Required changes before GREEN

Resolve the full-suite environment failures in their owning runtime/CI setup without weakening assertions, add real Windows certification for the Windows arm, and decide whether append must verify the sidecar head against the chain before replacing it. If that stronger truncation property is required, implement it and add a regression test; otherwise keep the limitation explicitly outside the security claim. No T-156 source was changed by this audit.

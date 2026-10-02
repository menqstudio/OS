# Pull request #328 (T-156) — the Windows run, as relayed

**This is not an audit report and carries no verdict.** It is the output of a Codex session on a
Windows machine, run by the Owner with a tests-only prompt on 2026-10-02 and pasted by him to the
Builder, who filed it here unchanged so that the Architect can read it from the repository. The
Builder did not run any of it and cannot vouch for it: it is a relayed transcript ◑. The session
changed nothing and pushed nothing. The Owner's own connecting sentences were in Armenian and are
given in English; everything inside a code block is verbatim.

- Head tested: `5d266284dc029c71f1c1b2f07c8edf54967c3691` (the head both Architect rounds 2 name).
- Fresh clone `os-audit-win-2`, PowerShell, GitHub account `menqstudio`.
- Python was not on `PATH`; the virtualenv was created with a bundled Windows Python 3.12.
  Dependencies installed with `--require-hashes`.

## 1. The two runs

Full suite (`python -B -m unittest discover -s tests`), exit code 1:

```
Ran 2692 tests in 165.509s

FAILED (failures=10, errors=1, skipped=253)
```

`test_stop_and_audit.py` alone, exit code 0:

```
Ran 40 tests in 2.266s

OK (skipped=9)
```

## 2. Every failure and error in the full suite

None is in `test_stop_and_audit`.

```
ERROR: test_live_required_dependencies_resolve (test_env_health.CheckEnvironmentTests.test_live_required_dependencies_resolve)
bro_env_health.EnvHealthError: required runtime dependency RED: python3 (executable 'python3' not found on PATH)

FAIL: test_the_wired_interpreter_really_disables_bytecode_writing (test_bytecode_shadow.HookInterpreterFlagTests.test_the_wired_interpreter_really_disables_bytecode_writing)
AssertionError: unexpectedly None : SessionStart: settings.json wires 'python', which is not on PATH

FAIL: test_the_probe_beats_os_access_where_they_disagree (test_control_plane_writable.ControlPlaneWritabilityTests.test_the_probe_beats_os_access_where_they_disagree)
AssertionError: Lists differ: ['runtime', 'runtime/sub'] != []

FAIL: test_present_interpreter_reports_version (test_env_health.ResolveTests.test_present_interpreter_reports_version)
AssertionError: False is not true

FAIL: test_wired_command_denies_out_of_scope (test_live_hook_deny.LiveHookWiringTests.test_wired_command_denies_out_of_scope)
AssertionError: unexpectedly None : the wired interpreter does not resolve on PATH

FAIL: test_wired_interpreter_resolves_on_path (test_live_hook_deny.LiveHookWiringTests.test_wired_interpreter_resolves_on_path)
AssertionError: unexpectedly None : settings.json wires the PreToolUse hook to 'python', which does not resolve on PATH; the live enforcement wall would never execute (dead wiring)

FAIL: test_every_live_shell_script_parses (test_live_provisioning_anchor.KitScriptTests.test_every_live_shell_script_parses) (script='run_ladder_turn.sh')
AssertionError: 1 != 0 : run_ladder_turn.sh: 

FAIL: test_every_live_shell_script_parses (test_live_provisioning_anchor.KitScriptTests.test_every_live_shell_script_parses) (script='run_live_turn.sh')
AssertionError: 1 != 0 : run_live_turn.sh: 

FAIL: test_the_rewrite_question_is_answered_for_owners_that_are_not_this_account (test_signature_authority.OperatorRootPinTests.test_the_rewrite_question_is_answered_for_owners_that_are_not_this_account) (right='FILE_WRITE_DATA')
AssertionError: unexpectedly None : a descriptor granting FILE_WRITE_DATA to this token was read as un-rewritable — the refusal would not apply

FAIL: test_the_rewrite_question_is_answered_for_owners_that_are_not_this_account (test_signature_authority.OperatorRootPinTests.test_the_rewrite_question_is_answered_for_owners_that_are_not_this_account) (right='DELETE')
AssertionError: unexpectedly None : a descriptor granting DELETE to this token was read as un-rewritable — the refusal would not apply

FAIL: test_the_rewrite_question_is_answered_for_owners_that_are_not_this_account (test_signature_authority.OperatorRootPinTests.test_the_rewrite_question_is_answered_for_owners_that_are_not_this_account) (right='WRITE_DAC')
AssertionError: unexpectedly None : a descriptor granting WRITE_DAC to this token was read as un-rewritable — the refusal would not apply
```

## 3. Skipped tests in `test_stop_and_audit`, with the reason each printed

```
test_a_dangling_symlink_at_the_lock_path_creates_nothing_where_it_points (test_stop_and_audit.AuditLedgerLockTests.test_a_dangling_symlink_at_the_lock_path_creates_nothing_where_it_points) ... skipped "this platform or account cannot create a symbolic link: [WinError 1314] A required privilege is not held by the client: 'C:\\\\Users\\\\Admin\\\\AppData\\\\Local\\\\Temp\\\\bro-audit-lock-kgzltqck\\\\planted-target' -> 'C:\\\\Users\\\\Admin\\\\AppData\\\\Local\\\\Temp\\\\bro-audit-lock-kgzltqck\\\\audit.jsonl.append-lock'"
test_a_forked_child_of_a_dead_holder_does_not_keep_the_lock_alive (test_stop_and_audit.AuditLedgerLockTests.test_a_forked_child_of_a_dead_holder_does_not_keep_the_lock_alive)
`flock` belongs to the open file description, which a forked child shares. Without ... skipped "a child that shares its parent's lock descriptor needs os.fork"
test_a_lock_path_that_is_a_fifo_is_refused_without_hanging (test_stop_and_audit.AuditLedgerLockTests.test_a_lock_path_that_is_a_fifo_is_refused_without_hanging) ... skipped 'a FIFO at the lock path needs os.mkfifo'
test_a_symlinked_lock_path_is_refused_and_cannot_redirect_the_lock (test_stop_and_audit.AuditLedgerLockTests.test_a_symlinked_lock_path_is_refused_and_cannot_redirect_the_lock) ... skipped "this platform or account cannot create a symbolic link: [WinError 1314] A required privilege is not held by the client: 'C:\\\\Users\\\\Admin\\\\AppData\\\\Local\\\\Temp\\\\bro-audit-lock-hbu_7h2u\\\\elsewhere' -> 'C:\\\\Users\\\\Admin\\\\AppData\\\\Local\\\\Temp\\\\bro-audit-lock-hbu_7h2u\\\\audit.jsonl.append-lock'"
test_a_waiter_does_not_take_its_lock_on_a_lock_file_that_was_replaced_under_it (test_stop_and_audit.AuditLedgerLockTests.test_a_waiter_does_not_take_its_lock_on_a_lock_file_that_was_replaced_under_it)
A waiter has the lock file OPEN while it waits. Remove and recreate the file and the ... skipped 'a lock file that is open cannot be unlinked on Windows, so the state this test builds does not exist there'
test_where_the_platform_has_no_nofollow_a_symlinked_lock_path_is_still_refused (test_stop_and_audit.AuditLedgerLockTests.test_where_the_platform_has_no_nofollow_a_symlinked_lock_path_is_still_refused)
Windows has no `O_NOFOLLOW`; the path is checked before the open instead. Run here ... skipped "this platform or account cannot create a symbolic link: [WinError 1314] A required privilege is not held by the client: 'C:\\\\Users\\\\Admin\\\\AppData\\\\Local\\\\Temp\\\\bro-audit-lock-s3jbv9hr\\\\planted-target' -> 'C:\\\\Users\\\\Admin\\\\AppData\\\\Local\\\\Temp\\\\bro-audit-lock-s3jbv9hr\\\\audit.jsonl.append-lock'"
test_concurrent_process_appends_keep_one_valid_chain (test_stop_and_audit.AuditLedgerTests.test_concurrent_process_appends_keep_one_valid_chain) ... skipped 'cross-process lock proof uses fork'
test_group_reads_alive_after_leader_reaped_with_child_alive (test_stop_and_audit.StopControllerTests.test_group_reads_alive_after_leader_reaped_with_child_alive) ... skipped 'a group outliving its reaped leader needs POSIX fork + killpg'
test_stops_a_real_process_group (test_stop_and_audit.StopControllerTests.test_stops_a_real_process_group) ... skipped 'STOP Controller manages POSIX process groups (os.killpg) and reads /proc; the real-process test is Linux/POSIX-only'
```

**What that leaves untested on Windows, stated by the Builder:** all three symlink tests were
skipped, because the account could not create a symbolic link. The Windows refusal of a symlinked
lock path — the path check that stands in for `O_NOFOLLOW` — therefore did not run on Windows in
this session.

## 4. Tests that take the real `msvcrt.locking` lock on a real file

The session's statement: `_platform_name()` returns `os.name`, which is `nt` here; `_try_lock()`
calls `msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)` on a descriptor of the real
`<ledger>.append-lock`. Only `test_the_windows_arm_seeks_locks_refuses_and_releases_against_a_fake_msvcrt`
uses the fake.

```
AuditLedgerTests.test_append_then_verify_chain
AuditLedgerTests.test_payload_secret_is_redacted
AuditLedgerTests.test_tamper_is_detected
AuditLedgerTests.test_tail_truncation_is_detected
AuditLedgerTests.test_corrupt_json_line_raises_audit_error
AuditLedgerTests.test_every_malformed_ledger_shape_is_an_audit_error_and_never_a_raw_exception
AuditLedgerTests.test_a_broken_link_is_a_plain_audit_error_not_a_malformed_ledger
AuditLedgerTests.test_concurrent_thread_appends_keep_one_valid_chain
AuditLedgerLockTests.test_the_lock_is_held_while_append_reads_the_chain_it_will_extend
AuditLedgerLockTests.test_the_lock_is_released_when_the_append_refuses
AuditLedgerLockTests.test_separately_started_processes_appending_together_keep_one_valid_chain
AuditLedgerLockTests.test_a_holder_killed_while_holding_the_lock_does_not_strand_the_ledger
AuditLedgerLockTests.test_a_writer_killed_mid_record_leaves_a_torn_tail_that_is_refused_and_not_repaired
AuditLedgerLockTests.test_a_corrupt_line_that_is_not_the_tail_is_not_called_a_torn_tail
AuditLedgerLockTests.test_a_complete_last_record_with_no_newline_is_never_appended_to
AuditLedgerLockTests.test_a_writer_killed_between_its_record_and_its_head_loses_nothing
AuditLedgerLockTests.test_only_a_head_exactly_one_record_behind_is_called_head_behind
AuditLedgerLockTests.test_a_live_holder_that_never_releases_makes_the_append_refuse_and_write_nothing
AuditLedgerLockTests.test_a_lock_file_left_by_the_old_scheme_is_neither_trusted_nor_deleted
AuditLedgerLockTests.test_the_lock_file_sits_beside_the_ledger_is_private_and_is_never_removed
StopControllerTests.test_unstoppable_process_is_recorded_as_incident
AuditLedgerLockTests.test_append_refuses_a_ledger_its_head_does_not_describe_and_writes_nothing
AuditLedgerLockTests.test_append_still_proceeds_where_it_is_the_repair_or_there_is_nothing_to_repair
AuditLedgerLockTests.test_a_truncation_is_refused_by_verify_under_its_own_name_and_is_still_an_audit_error
```

## 5. By hand, under `%TEMP%`

(a) A first process took the lock and slept. It was ended with `proc.kill()` and waited for. A
second process then called `append()` on the same ledger:

```
os.name=nt
temp_dir=C:\Users\Admin\AppData\Local\Temp\os-pr328-manual-tckpmhth
holder_pid=18584
holder=READY
termination=proc.kill()
holder_exit=1
SUCCESS seq=0 append_seconds=0.004319000
verify=1
second_exit=0 process_seconds=0.140566900
```

(b) A fresh ledger, two records, the last line deleted, the `.head` kept; then `append()`:

```
truncated_ledger=C:\Users\Admin\AppData\Local\Temp\os-pr328-manual-tckpmhth\truncated.jsonl
bro_audit_log.AuditTruncated: audit ledger truncated: head count disagrees with chain length
is_AuditTruncated=True
ledger_unchanged=True
head_unchanged=True
```

The session reported that the diff of tracked files was empty and that it made no commit, push,
pull request or comment.

## 6. An earlier Windows run, at the first head

A first session, at `e53ce35`, reported in summary only: full suite 2689 run, 10 failures,
2 errors, 253 skipped; `test_stop_and_audit` 37 tests, 9 skipped; `taskkill /F` answered
`Access denied`, `proc.kill()` ended the holder and the second append succeeded. Its failing
tests were not named. It is superseded by the run above.

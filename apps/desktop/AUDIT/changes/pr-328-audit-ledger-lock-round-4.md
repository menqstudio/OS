Audited-PR: #328
Audited-Head: 5d266284dc029c71f1c1b2f07c8edf54967c3691

VERDICT: GREEN FOR THIS CHANGE — the six Linux-suite failures and 30 errors reproduce identically on origin/main, so they are repository/environment defects rather than regressions introduced by PR #328. F-05 is fixed and independently verified. F-04 is closed by the audited GitHub Actions Windows job on this exact head, including the three symlink tests and real cross-process Windows locking tests. Separate repository findings B-03/B-04/B-09 remain outside this pull request.

## 1. Head-vs-main comparison

The audited head was an ancestor (`0`). The diff from the round-three head listed only the previously filed audit material and the newly relayed transcript; no `engine/` path was present.

### Head suite result (verbatim)

```text
Ran 2692 tests in 73.500s
FAILED (failures=6, errors=30, skipped=15)
```

Head failure IDs were captured with the requested command into `/tmp/t156-head-fails.txt`.

### Main worktree result (verbatim)

```text
Ran 2666 tests in 68.013s
FAILED (failures=6, errors=30, skipped=15)
```

Main failure IDs were captured into `/tmp/t156-main-fails.txt`.

### Requested failure-list diff (verbatim)

```text
```

`diff -u /tmp/t156-main-fails.txt /tmp/t156-head-fails.txt` produced no output: every failure/error ID was identical. Therefore no failing ID is unique to PR #328.

### Signer-path claim

`_signer_argv` at `engine/runtime/bro_audit_log.py:636-668` calls `Path(argv[0]).resolve()` before returning the executable. In the required 3.12 virtualenv:

```text
/home/gevorg/os-audit-2/.venv312/bin/python /home/gevorg/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3.12
```

The resolved executable is outside the virtualenv. The 30 anchor/backup/monitor errors are the stand-in signer failing to import `cryptography` under that resolved base interpreter. The same failures occur on main; this is B-09, not a PR-328 regression.

### visudo evidence

```text
visudo-rs 0.2.13
ii  sudo                                             1.9.17p2-1ubuntu3                          amd64        Provide limited super user privileges to specific users
ii  sudo-rs                                          0.2.13-0ubuntu1                            amd64        Rust-based sudo and su implementations
```

The two sudoers failures are B-03 and reproduce identically on main. The exact wildcard diagnostics are included in the suite failure output below.

## 2. Windows GitHub Actions evidence

Run metadata queried directly:

```text
head_sha: 5d266284dc029c71f1c1b2f07c8edf54967c3691
 event: pull_request
 conclusion: success
```

Job 110821857190:

```text
Engine · governance runtime on Windows (python)
success
GitHub Actions 1000046124
["windows-latest"]
```

The workflow uses Python 3.12 and runs:

```yaml
- name: Run the engine test suite on Windows
  run: python -B -m unittest discover -s tests -v
```

Windows log result:

```text
python-version: 3.12
Ran 2692 tests in 231.859s
OK (skipped=233)
```

The following are the complete `test_stop_and_audit` lines from that job log, verbatim:

2026-10-02T11:41:56.4517732Z test_a_complete_last_record_with_no_newline_is_never_appended_to (test_stop_and_audit.AuditLedgerLockTests.test_a_complete_last_record_with_no_newline_is_never_appended_to)
2026-10-02T11:41:56.8022251Z test_a_corrupt_line_that_is_not_the_tail_is_not_called_a_torn_tail (test_stop_and_audit.AuditLedgerLockTests.test_a_corrupt_line_that_is_not_the_tail_is_not_called_a_torn_tail) ... ok
2026-10-02T11:41:56.8035143Z test_a_dangling_symlink_at_the_lock_path_creates_nothing_where_it_points (test_stop_and_audit.AuditLedgerLockTests.test_a_dangling_symlink_at_the_lock_path_creates_nothing_where_it_points) ... ok
2026-10-02T11:41:56.8036797Z test_a_forked_child_of_a_dead_holder_does_not_keep_the_lock_alive (test_stop_and_audit.AuditLedgerLockTests.test_a_forked_child_of_a_dead_holder_does_not_keep_the_lock_alive)
2026-10-02T11:41:56.8039624Z test_a_holder_killed_while_holding_the_lock_does_not_strand_the_ledger (test_stop_and_audit.AuditLedgerLockTests.test_a_holder_killed_while_holding_the_lock_does_not_strand_the_ledger)
2026-10-02T11:41:57.3731851Z test_a_kernel_that_cannot_lock_the_file_is_a_named_refusal_and_writes_nothing (test_stop_and_audit.AuditLedgerLockTests.test_a_kernel_that_cannot_lock_the_file_is_a_named_refusal_and_writes_nothing)
2026-10-02T11:41:58.1791757Z test_a_live_holder_that_never_releases_makes_the_append_refuse_and_write_nothing (test_stop_and_audit.AuditLedgerLockTests.test_a_live_holder_that_never_releases_makes_the_append_refuse_and_write_nothing) ... ok
2026-10-02T11:41:58.1793367Z test_a_lock_file_left_by_the_old_scheme_is_neither_trusted_nor_deleted (test_stop_and_audit.AuditLedgerLockTests.test_a_lock_file_left_by_the_old_scheme_is_neither_trusted_nor_deleted)
2026-10-02T11:41:58.4164227Z test_a_lock_path_that_is_a_directory_is_refused (test_stop_and_audit.AuditLedgerLockTests.test_a_lock_path_that_is_a_directory_is_refused) ... ok
2026-10-02T11:41:58.4167166Z test_a_lock_path_that_is_a_fifo_is_refused_without_hanging (test_stop_and_audit.AuditLedgerLockTests.test_a_lock_path_that_is_a_fifo_is_refused_without_hanging) ... skipped 'a FIFO at the lock path needs os.mkfifo'
2026-10-02T11:41:58.4175811Z test_a_platform_with_no_kernel_lock_refuses_rather_than_appending_unlocked (test_stop_and_audit.AuditLedgerLockTests.test_a_platform_with_no_kernel_lock_refuses_rather_than_appending_unlocked) ... ok
2026-10-02T11:41:58.4193642Z test_a_symlinked_lock_path_is_refused_and_cannot_redirect_the_lock (test_stop_and_audit.AuditLedgerLockTests.test_a_symlinked_lock_path_is_refused_and_cannot_redirect_the_lock) ... ok
2026-10-02T11:41:58.4195469Z test_a_truncation_is_refused_by_verify_under_its_own_name_and_is_still_an_audit_error (test_stop_and_audit.AuditLedgerLockTests.test_a_truncation_is_refused_by_verify_under_its_own_name_and_is_still_an_audit_error)
2026-10-02T11:41:58.7962673Z test_a_waiter_does_not_take_its_lock_on_a_lock_file_that_was_replaced_under_it (test_stop_and_audit.AuditLedgerLockTests.test_a_waiter_does_not_take_its_lock_on_a_lock_file_that_was_replaced_under_it)
2026-10-02T11:41:59.4289669Z test_a_writer_killed_between_its_record_and_its_head_loses_nothing (test_stop_and_audit.AuditLedgerLockTests.test_a_writer_killed_between_its_record_and_its_head_loses_nothing) ... ok
2026-10-02T11:42:00.1280791Z test_a_writer_killed_mid_record_leaves_a_torn_tail_that_is_refused_and_not_repaired (test_stop_and_audit.AuditLedgerLockTests.test_a_writer_killed_mid_record_leaves_a_torn_tail_that_is_refused_and_not_repaired) ... ok
2026-10-02T11:42:00.1283782Z test_append_refuses_a_ledger_its_head_does_not_describe_and_writes_nothing (test_stop_and_audit.AuditLedgerLockTests.test_append_refuses_a_ledger_its_head_does_not_describe_and_writes_nothing)
2026-10-02T11:42:03.0241673Z test_append_still_proceeds_where_it_is_the_repair_or_there_is_nothing_to_repair (test_stop_and_audit.AuditLedgerLockTests.test_append_still_proceeds_where_it_is_the_repair_or_there_is_nothing_to_repair)
2026-10-02T11:42:03.2927733Z test_only_a_head_exactly_one_record_behind_is_called_head_behind (test_stop_and_audit.AuditLedgerLockTests.test_only_a_head_exactly_one_record_behind_is_called_head_behind)
2026-10-02T11:42:04.6977163Z test_separately_started_processes_appending_together_keep_one_valid_chain (test_stop_and_audit.AuditLedgerLockTests.test_separately_started_processes_appending_together_keep_one_valid_chain) ... ok
2026-10-02T11:42:04.6980476Z test_the_audit_lock_and_the_approval_log_lock_have_not_drifted (test_stop_and_audit.AuditLedgerLockTests.test_the_audit_lock_and_the_approval_log_lock_have_not_drifted)
2026-10-02T11:42:04.7442412Z test_the_lock_file_sits_beside_the_ledger_is_private_and_is_never_removed (test_stop_and_audit.AuditLedgerLockTests.test_the_lock_file_sits_beside_the_ledger_is_private_and_is_never_removed) ... ok
2026-10-02T11:42:04.8192549Z test_the_lock_is_held_while_append_reads_the_chain_it_will_extend (test_stop_and_audit.AuditLedgerLockTests.test_the_lock_is_held_while_append_reads_the_chain_it_will_extend) ... ok
2026-10-02T11:42:04.8821018Z test_the_lock_is_released_when_the_append_refuses (test_stop_and_audit.AuditLedgerLockTests.test_the_lock_is_released_when_the_append_refuses) ... ok
2026-10-02T11:42:04.8822625Z test_the_windows_arm_seeks_locks_refuses_and_releases_against_a_fake_msvcrt (test_stop_and_audit.AuditLedgerLockTests.test_the_windows_arm_seeks_locks_refuses_and_releases_against_a_fake_msvcrt)
2026-10-02T11:42:05.2470648Z test_where_the_platform_has_no_nofollow_a_symlinked_lock_path_is_still_refused (test_stop_and_audit.AuditLedgerLockTests.test_where_the_platform_has_no_nofollow_a_symlinked_lock_path_is_still_refused)
2026-10-02T11:42:05.2879872Z test_a_broken_link_is_a_plain_audit_error_not_a_malformed_ledger (test_stop_and_audit.AuditLedgerTests.test_a_broken_link_is_a_plain_audit_error_not_a_malformed_ledger) ... ok
2026-10-02T11:42:05.3308911Z test_append_then_verify_chain (test_stop_and_audit.AuditLedgerTests.test_append_then_verify_chain) ... ok
2026-10-02T11:42:05.3310423Z test_concurrent_process_appends_keep_one_valid_chain (test_stop_and_audit.AuditLedgerTests.test_concurrent_process_appends_keep_one_valid_chain) ... skipped 'cross-process lock proof uses fork'
2026-10-02T11:42:05.9005587Z test_concurrent_thread_appends_keep_one_valid_chain (test_stop_and_audit.AuditLedgerTests.test_concurrent_thread_appends_keep_one_valid_chain) ... ok
2026-10-02T11:42:05.9246203Z test_corrupt_json_line_raises_audit_error (test_stop_and_audit.AuditLedgerTests.test_corrupt_json_line_raises_audit_error) ... ok
2026-10-02T11:42:05.9247607Z test_every_malformed_ledger_shape_is_an_audit_error_and_never_a_raw_exception (test_stop_and_audit.AuditLedgerTests.test_every_malformed_ledger_shape_is_an_audit_error_and_never_a_raw_exception)
2026-10-02T11:42:06.0630680Z test_ledger_inside_repo_is_refused (test_stop_and_audit.AuditLedgerTests.test_ledger_inside_repo_is_refused) ... ok
2026-10-02T11:42:06.0973358Z test_payload_secret_is_redacted (test_stop_and_audit.AuditLedgerTests.test_payload_secret_is_redacted) ... ok
2026-10-02T11:42:06.1417171Z test_tail_truncation_is_detected (test_stop_and_audit.AuditLedgerTests.test_tail_truncation_is_detected) ... ok
2026-10-02T11:42:06.1835839Z test_tamper_is_detected (test_stop_and_audit.AuditLedgerTests.test_tamper_is_detected) ... ok
2026-10-02T11:42:06.1837442Z test_group_reads_alive_after_leader_reaped_with_child_alive (test_stop_and_audit.StopControllerTests.test_group_reads_alive_after_leader_reaped_with_child_alive) ... skipped 'a group outliving its reaped leader needs POSIX fork + killpg'
2026-10-02T11:42:06.1847557Z test_registry_round_trips (test_stop_and_audit.StopControllerTests.test_registry_round_trips) ... ok
2026-10-02T11:42:06.1848957Z test_stops_a_real_process_group (test_stop_and_audit.StopControllerTests.test_stops_a_real_process_group) ... skipped 'STOP Controller manages POSIX process groups (os.killpg) and reads /proc; the real-process test is Linux/POSIX-only'
2026-10-02T11:42:06.2169849Z test_unstoppable_process_is_recorded_as_incident (test_stop_and_audit.StopControllerTests.test_unstoppable_process_is_recorded_as_incident) ... ok

The three symlink tests all completed successfully (`ok`):

- `test_a_symlinked_lock_path_is_refused_and_cannot_redirect_the_lock`
- `test_a_dangling_symlink_at_the_lock_path_creates_nothing_where_it_points`
- `test_where_the_platform_has_no_nofollow_a_symlinked_lock_path_is_still_refused`

`test_a_holder_killed_while_holding_the_lock_does_not_strand_the_ledger` completed `ok`.
`test_separately_started_processes_appending_together_keep_one_valid_chain` completed `ok`.
The fork-specific child test is skipped on Windows because `os.fork` is unavailable; that is an explicit platform skip, not a failure. The tests use the real Windows arm: `test_the_windows_arm_seeks_locks_refuses_and_releases_against_a_fake_msvcrt` is only the fake-arm unit test, while the spawned-process/thread tests exercise `_try_lock` with real `msvcrt` on Windows.

Linux job 110821857399 was also queried directly:

```text
Engine · governance runtime (python)
success
GitHub Actions 1000046138
["ubuntu-latest"]
Ran 2692 tests in 58.078s
OK (skipped=13)
```

This closes F-04 for the audited head through auditable CI evidence. It is not a local Windows run by me; it is a directly inspected GitHub Actions run tied to the exact audited SHA.

## F-01 through F-06 status

- **F-01 — CLOSED AS A NON-REGRESSION.** Head and main have the same six failing IDs and 30 error IDs. The suite is not green on this host, but none of those failures was introduced by PR #328.
- **F-02 — ACCEPTED STATED LIMIT.** The at-fork hook covers copied descriptors; explicit IPC descriptor transfer remains outside the documented defense, with no current engine path found that transfers this lock descriptor.
- **F-03 — ACCEPTED STATED LIMIT.** The lock is advisory; cooperating writers are serialized and inode replacement is checked, while non-cooperating direct writers remain outside the integrity claim.
- **F-04 — VERIFIED CLOSED.** Exact-head Windows CI ran Python 3.12, 2692 tests, and the required symlink/holder/separate-process tests passed. Fork-only tests are explicitly skipped by platform.
- **F-05 — VERIFIED CLOSED.** Append checks chain and plaintext head under the lock before writing; truncation/wrong-head/mid-chain-rewrite cases refuse without changing ledger/head, while only the exact crash-shaped `AuditHeadBehind` state is repaired.
- **F-06 — ACCEPTED STATED LIMIT.** Signer execution remains inside the bounded lock section and fails closed on timeout; no production signer deployment was claimed.

## Separate open repository findings

- **B-03:** this host's `visudo-rs 0.2.13` rejects wildcard command arguments in the generated sudoers fragments. It is identical on main and outside PR #328.
- **B-04:** this host's wired `python` command is absent from PATH. Identical on main and outside PR #328.
- **B-09:** `_signer_argv` resolves a virtualenv interpreter symlink to the uv base interpreter, causing the stand-in signer to lose installed packages. Identical on main and outside PR #328.

These do not block a verdict about the T-156 change itself, but they remain repository defects requiring separate work.

## What I did not check

- I did not run Windows locally; Windows evidence is the directly inspected GitHub Actions job described above.
- I did not modify runtime code, the PR description, or any existing file.
- I did not merge or deploy.
- I did not perform production signer-custody, IPC descriptor-transfer, power-loss, full-disk, or NFS tests.

## Complete raw Linux failure/error output

The following is the full failure/error section from the required head run, preserved verbatim:

ERROR: test_an_anchor_carrying_extra_fields_is_refused (test_audit_head_anchor.AnchorPayloadShapeTests.test_an_anchor_carrying_extra_fields_is_refused)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 423, in test_an_anchor_carrying_extra_fields_is_refused
    self.fill(1)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-0zqg8pah/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_an_anchor_for_a_different_ledger_is_refused (test_audit_head_anchor.AnchorPayloadShapeTests.test_an_anchor_for_a_different_ledger_is_refused)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 444, in test_an_anchor_for_a_different_ledger_is_refused
    self.fill(1)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-vkug4db7/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_an_anchor_missing_a_field_is_refused (test_audit_head_anchor.AnchorPayloadShapeTests.test_an_anchor_missing_a_field_is_refused)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 434, in test_an_anchor_missing_a_field_is_refused
    self.fill(1)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-bdrtfs8i/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_an_unreadable_anchor_is_a_refusal_not_a_pass (test_audit_head_anchor.AnchorPayloadShapeTests.test_an_unreadable_anchor_is_a_refusal_not_a_pass)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 455, in test_an_unreadable_anchor_is_a_refusal_not_a_pass
    self.fill(1)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-3pzb18b9/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_append_attaches_a_signed_head_anchor (test_audit_head_anchor.AppendProducesAnAnchorTests.test_append_attaches_a_signed_head_anchor)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 82, in test_append_attaches_a_signed_head_anchor
    self.fill(3)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-fef75u04/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_each_anchor_names_the_one_it_supersedes (test_audit_head_anchor.AppendProducesAnAnchorTests.test_each_anchor_names_the_one_it_supersedes)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 95, in test_each_anchor_names_the_one_it_supersedes
    append(self.ledger, "decision", {"i": 0})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-h5gecdpe/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_out_of_band_anchor_round_trip_still_works (test_audit_head_anchor.AppendProducesAnAnchorTests.test_out_of_band_anchor_round_trip_still_works)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 105, in test_out_of_band_anchor_round_trip_still_works
    self.fill(2)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-o4vsgixp/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_a_validly_signed_anchor_from_another_authority_is_refused_by_name (test_audit_head_anchor.OnlyTheAnchorAuthorityMayAnchorTests.test_a_validly_signed_anchor_from_another_authority_is_refused_by_name) (authority='evidence-recorder')
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 324, in test_a_validly_signed_anchor_from_another_authority_is_refused_by_name
    self.fill(1)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-_5pdaw98/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_a_validly_signed_anchor_from_another_authority_is_refused_by_name (test_audit_head_anchor.OnlyTheAnchorAuthorityMayAnchorTests.test_a_validly_signed_anchor_from_another_authority_is_refused_by_name) (authority='operator-root')
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 324, in test_a_validly_signed_anchor_from_another_authority_is_refused_by_name
    self.fill(1)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-_5pdaw98/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_the_truncation_forgery_with_a_key_the_writer_holds_is_refused (test_audit_head_anchor.OnlyTheAnchorAuthorityMayAnchorTests.test_the_truncation_forgery_with_a_key_the_writer_holds_is_refused) (authority='evidence-recorder')
THE O-2 negative, end to end, against the real verify().
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 351, in test_the_truncation_forgery_with_a_key_the_writer_holds_is_refused
    self.fill(3)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-hradfr9h/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_the_truncation_forgery_with_a_key_the_writer_holds_is_refused (test_audit_head_anchor.OnlyTheAnchorAuthorityMayAnchorTests.test_the_truncation_forgery_with_a_key_the_writer_holds_is_refused) (authority='operator-root')
THE O-2 negative, end to end, against the real verify().
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 351, in test_the_truncation_forgery_with_a_key_the_writer_holds_is_refused
    self.fill(3)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-hradfr9h/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_backup_refuses_when_the_key_registry_cannot_be_loaded (test_audit_head_anchor.ProductionVerifiersPassKeysTests.test_backup_refuses_when_the_key_registry_cannot_be_loaded)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 509, in test_backup_refuses_when_the_key_registry_cannot_be_loaded
    self.fill(1)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-apvdq43t/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_monitor_reports_a_signed_anchor_and_stays_green (test_audit_head_anchor.ProductionVerifiersPassKeysTests.test_monitor_reports_a_signed_anchor_and_stays_green)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 468, in test_monitor_reports_a_signed_anchor_and_stays_green
    self.fill(2)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-b43yzirq/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_monitor_separates_unanchored_from_tampered (test_audit_head_anchor.ProductionVerifiersPassKeysTests.test_monitor_separates_unanchored_from_tampered)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 475, in test_monitor_separates_unanchored_from_tampered
    self.fill(2)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-o594s61t/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_appending_past_an_anchor_without_custody_is_refused (test_audit_head_anchor.SignerMisbehaviourFailsClosedTests.test_appending_past_an_anchor_without_custody_is_refused)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 249, in test_appending_past_an_anchor_without_custody_is_refused
    self.fill(2)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-33mdvxa8/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_installing_an_anchor_for_a_shorter_chain_is_refused (test_audit_head_anchor.SignerMisbehaviourFailsClosedTests.test_installing_an_anchor_for_a_shorter_chain_is_refused)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 273, in test_installing_an_anchor_for_a_shorter_chain_is_refused
    self.fill(3)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-ktb1x1pq/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_the_owners_signer_refuses_to_re_anchor_a_truncated_ledger (test_audit_head_anchor.SignerMisbehaviourFailsClosedTests.test_the_owners_signer_refuses_to_re_anchor_a_truncated_ledger)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 260, in test_the_owners_signer_refuses_to_re_anchor_a_truncated_ledger
    self.fill(3)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-ko2k6tw5/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_a_forger_who_also_deletes_the_anchor_is_refused_too (test_audit_head_anchor.TheForgeryThatUsedToPassTests.test_a_forger_who_also_deletes_the_anchor_is_refused_too)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 133, in test_a_forger_who_also_deletes_the_anchor_is_refused_too
    self.fill(3)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-a2hyjlgp/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_emptied_ledger_with_both_sidecars_deleted_is_refused (test_audit_head_anchor.TheForgeryThatUsedToPassTests.test_emptied_ledger_with_both_sidecars_deleted_is_refused)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 143, in test_emptied_ledger_with_both_sidecars_deleted_is_refused
    self.fill(2)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-m23l4vu6/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_rewritten_head_over_dropped_records_is_refused (test_audit_head_anchor.TheForgeryThatUsedToPassTests.test_rewritten_head_over_dropped_records_is_refused)
THE O-2 test: append, rewrite the head, and verify() must REFUSE.
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 116, in test_rewritten_head_over_dropped_records_is_refused
    self.fill(3)
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 65, in fill
    append(self.ledger, "decision", {"i": i})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-kr7i58wr/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_a_refused_ledger_leaves_nothing_in_the_destination (test_backup_restore.BackupRestoreTests.test_a_refused_ledger_leaves_nothing_in_the_destination)
"Never archived" (the module docstring). The copy used to come BEFORE the chain
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_backup_restore.py", line 56, in setUp
    bro_audit_log.append(self.ledger, "shadow-would-block", {"reason": "one"})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-vycdzdfz/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_broken_ledger_chain_refuses_backup (test_backup_restore.BackupRestoreTests.test_broken_ledger_chain_refuses_backup)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_backup_restore.py", line 56, in setUp
    bro_audit_log.append(self.ledger, "shadow-would-block", {"reason": "one"})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-1ky9e3ny/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_nonempty_destination_is_refused (test_backup_restore.BackupRestoreTests.test_nonempty_destination_is_refused)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_backup_restore.py", line 56, in setUp
    bro_audit_log.append(self.ledger, "shadow-would-block", {"reason": "one"})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-j7qrcb98/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_restore_refuses_to_clobber_without_force (test_backup_restore.BackupRestoreTests.test_restore_refuses_to_clobber_without_force)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_backup_restore.py", line 56, in setUp
    bro_audit_log.append(self.ledger, "shadow-would-block", {"reason": "one"})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-kldp_q2y/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_round_trip_is_byte_faithful_and_chain_valid (test_backup_restore.BackupRestoreTests.test_round_trip_is_byte_faithful_and_chain_valid)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_backup_restore.py", line 56, in setUp
    bro_audit_log.append(self.ledger, "shadow-would-block", {"reason": "one"})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-dluf4x8l/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_symlink_in_source_is_refused (test_backup_restore.BackupRestoreTests.test_symlink_in_source_is_refused)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_backup_restore.py", line 56, in setUp
    bro_audit_log.append(self.ledger, "shadow-would-block", {"reason": "one"})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-42zwqtx5/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_tampered_archive_is_caught_before_restore (test_backup_restore.BackupRestoreTests.test_tampered_archive_is_caught_before_restore)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_backup_restore.py", line 56, in setUp
    bro_audit_log.append(self.ledger, "shadow-would-block", {"reason": "one"})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-0myurr2t/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_broken_shadow_chain_raises_attention (test_monitor.MonitorTests.test_broken_shadow_chain_raises_attention)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_monitor.py", line 96, in test_broken_shadow_chain_raises_attention
    led = self._shadow()
          ^^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/tests/test_monitor.py", line 44, in _shadow
    bro_audit_log.append(led, "shadow-would-block", {"kind": "pre-tool-deny", "reason": "a"})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-y0kq_03r/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_shadow_record_missing_kind_does_not_crash (test_monitor.MonitorTests.test_shadow_record_missing_kind_does_not_crash)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_monitor.py", line 248, in test_shadow_record_missing_kind_does_not_crash
    bro_audit_log.append(led, "shadow-would-block", {"kind": "pre-tool-deny", "reason": "x"})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-luqvo_gb/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
ERROR: test_shadow_records_are_counted_by_kind (test_monitor.MonitorTests.test_shadow_records_are_counted_by_kind)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_monitor.py", line 73, in test_shadow_records_are_counted_by_kind
    report = bro_monitor.scan(shadow_ledger=self._shadow())
                                            ^^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/tests/test_monitor.py", line 44, in _shadow
    bro_audit_log.append(led, "shadow-would-block", {"kind": "pre-tool-deny", "reason": "a"})
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 964, in append
    document = _sign_anchor(
               ^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/runtime/bro_audit_log.py", line 742, in _sign_anchor
    raise AuditError(
bro_audit_log.AuditError: audit-head signing command refused (exit 1): Traceback (most recent call last):
  File "/tmp/bro-anchor-custody-kejni6va/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
FAIL: test_a_signer_that_signs_a_different_payload_is_refused (test_audit_head_anchor.SignerMisbehaviourFailsClosedTests.test_a_signer_that_signs_a_different_payload_is_refused)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 237, in test_a_signer_that_signs_a_different_payload_is_refused
    self.assertIn("DIFFERENT payload", str(caught.exception))
AssertionError: 'DIFFERENT payload' not found in 'audit-head signing command refused (exit 1): Traceback (most recent call last):\n  File "/tmp/bro-anchor-custody-lo0ghosa/signer_lying.py", line 5, in <module>\n    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey\nModuleNotFoundError: No module named \'cryptography\''

======================================================================
FAIL: test_the_wired_interpreter_really_disables_bytecode_writing (test_bytecode_shadow.HookInterpreterFlagTests.test_the_wired_interpreter_really_disables_bytecode_writing)
Live proof, not a string match: launch the actual wired token with the
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_bytecode_shadow.py", line 327, in test_the_wired_interpreter_really_disables_bytecode_writing
    self.assertIsNotNone(
AssertionError: unexpectedly None : SessionStart: settings.json wires 'python', which is not on PATH

======================================================================
FAIL: test_wired_command_denies_out_of_scope (test_live_hook_deny.LiveHookWiringTests.test_wired_command_denies_out_of_scope)
The refusal must NAME the missing binding.
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/_prerequisites.py", line 283, in wrapper
    return target(self, *args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/tests/test_live_hook_deny.py", line 129, in test_wired_command_denies_out_of_scope
    block = self._run_wired_hook_out_of_scope()
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/gevorg/os-audit-2/engine/tests/test_live_hook_deny.py", line 75, in _run_wired_hook_out_of_scope
    self.assertIsNotNone(argv[0], "the wired interpreter does not resolve on PATH")
AssertionError: unexpectedly None : the wired interpreter does not resolve on PATH

======================================================================
FAIL: test_wired_interpreter_resolves_on_path (test_live_hook_deny.LiveHookWiringTests.test_wired_interpreter_resolves_on_path)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_live_hook_deny.py", line 67, in test_wired_interpreter_resolves_on_path
    self.assertIsNotNone(
AssertionError: unexpectedly None : settings.json wires the PreToolUse hook to 'python', which does not resolve on PATH; the live enforcement wall would never execute (dead wiring)

======================================================================
FAIL: test_the_real_visudo_accepts_all_three_and_rejects_a_broken_one_through_the_block (test_live_sudoers_install.FragmentTextTests.test_the_real_visudo_accepts_all_three_and_rejects_a_broken_one_through_the_block) (kit='run_ladder_turn.sh', heredoc='PYSUDO')
The stand-in answers what it is told. Where a real visudo is installed, ask it too.
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_live_sudoers_install.py", line 803, in test_the_real_visudo_accepts_all_three_and_rejects_a_broken_one_through_the_block
    self.assertEqual(self.rc_of(done), 0, done.stderr)
AssertionError: 1 != 0 : /tmp/tmpp85agej5/etc/.brops-sudoers-stage.HtuFyb/brops-x:1:49: syntax error: wildcards are not allowed in command arguments
brops-supervisor ALL=(brops-recorder) NOPASSWD: /opt/brops-live/bin/governed_recorder --store /opt/brops-live/store --launcher /opt/brops-live/tcb/privileged-launcher.bin --executor /opt/brops-live/bin/proof_executor --lease /opt/brops-live/tcb/executor.lease --cgroup brops-live --out /opt/brops-live/report/ladder-*.out --containment-out /opt/brops-live/report/ladder-*.out.containment.json --evidence-out /opt/brops-live/evidence-state/*.evidence.json --evidence-state /opt/brops-live/evidence-state
                                                ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
visudo: invalid sudoers file
sudoers: /usr/sbin/visudo rejected /tmp/tmpp85agej5/etc/.brops-sudoers-stage.HtuFyb/brops-x; /tmp/tmpp85agej5/etc/sudoers.d/brops-x was NOT installed


======================================================================
FAIL: test_the_real_visudo_accepts_all_three_and_rejects_a_broken_one_through_the_block (test_live_sudoers_install.FragmentTextTests.test_the_real_visudo_accepts_all_three_and_rejects_a_broken_one_through_the_block) (kit='run_live_turn.sh', heredoc='PYSUDO')
The stand-in answers what it is told. Where a real visudo is installed, ask it too.
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_live_sudoers_install.py", line 803, in test_the_real_visudo_accepts_all_three_and_rejects_a_broken_one_through_the_block
    self.assertEqual(self.rc_of(done), 0, done.stderr)
AssertionError: 1 != 0 : /tmp/tmpp85agej5/etc/.brops-sudoers-stage.eWf7zN/brops-x:1:54: syntax error: wildcards are not allowed in command arguments
brops-verifier_broker ALL=(brops-recorder) NOPASSWD: /opt/brops-live/bin/governed_recorder --store /opt/brops-live/store --launcher /opt/brops-live/tcb/privileged-launcher.bin --executor /opt/brops-live/bin/proof_executor --lease /opt/brops-live/tcb/executor.lease --cgroup brops-live --out /opt/brops-live/report/live-*.out --containment-out /opt/brops-live/report/live-*.out.containment.json --evidence-out /opt/brops-live/evidence-state/*.evidence.json --evidence-state /opt/brops-live/evidence-state
                                                     ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
visudo: invalid sudoers file
sudoers: /usr/sbin/visudo rejected /tmp/tmpp85agej5/etc/.brops-sudoers-stage.eWf7zN/brops-x; /tmp/tmpp85agej5/etc/sudoers.d/brops-x was NOT installed


----------------------------------------------------------------------
Ran 2692 tests in 73.500s

FAILED (failures=6, errors=30, skipped=15)

Audited-PR: #328
Audited-Head: 5d266284dc029c71f1c1b2f07c8edf54967c3691

VERDICT: RED — F-05 is closed by the new append-time chain/head checks, but this round cannot certify the required full suite because the locked dependency installation fails on the host's Python 3.14 `rpds-py` wheel hash. The focused T-156 suite passes 40/40. Windows was not run by me, so the Windows lock arm remains unverified in this round.

## Setup and evidence

`gh auth status` verified the active account is `menqstudio`. I created the requested fresh clone, checked out PR #328, and verified the exact audited head. The required virtualenv was created successfully. The required command

`python -m pip install --require-hashes -r engine/requirements-ci.txt`

failed before installing dependencies: the published `rpds-py==2026.6.3` Python 3.14 wheel has SHA-256 `dc319e5a...`, while the lock file lists four different hashes. I did not bypass hash verification and did not run the full suite on the bare host interpreter.

The first report comparison was exact: `git diff 1665da5:engine/AUDIT/changes/pr-328-audit-ledger-lock.md HEAD:apps/desktop/AUDIT/changes/pr-328-audit-ledger-lock.md` produced no diff.

Using the new virtualenv, the focused command

`cd engine && ../.venv/bin/python -B -m unittest tests.test_stop_and_audit`

measured **40 tests, OK**.

The required full-suite count for this round is **NOT MEASURED** because the required hashed environment could not be installed. The prior-round bare-host result (**2689 run, 5 failures, 1 error, 15 skips**) is historical evidence only and is not claimed as this head's result.

## Findings F-01 through F-06

### F-01 — full suite not green / not independently re-run

**Status: STILL OPEN.** The locked install is blocked by the `rpds-py` hash mismatch above, so I could not independently establish the Builder's “2692 OK, 13 skipped” claim. I did not repeat the bare-host run. No test output is claimed for this head.

### F-02 — descriptor transfer outside fork defense

**Status: ACCEPTED AS A STATED LIMIT.** `bro_audit_log.py:332-353` closes descriptors copied by `fork()` in the child. The updated documentation states that explicit IPC descriptor transfer is outside that hook, and no engine path was found that transfers this lock descriptor. This is a boundary, not a silently false guarantee.

### F-03 — advisory lock / inode replacement

**Status: ACCEPTED AS A STATED LIMIT.** `bro_audit_log.py:114-123` continues to state that the lock is advisory. The round-two focused tests and independent probes show cooperating writers re-contend after inode replacement; a non-cooperating direct writer can still bypass an advisory lock. That is expressly outside the integrity claim.

### F-04 — Windows lock arm

**Status: STILL OPEN FOR THIS AUDIT.** I did not run Windows. The repository's fake-`msvcrt` test is not a live Windows certification, and the relayed prior Windows session is not evidence I independently collected. No Windows claim is made here.

### F-05 — append overwrote a truncated ledger

**Status: VERIFIED CLOSED.** New checks at `engine/runtime/bro_audit_log.py:897-953` call `_check_chain()` and `_check_head()` while holding the lock, before any write. `AuditTruncated` is defined at `:315`; `_check_chain` is `:993-1021`; `_check_head` is `:1023-1049`.

Independent `/tmp/t156_r2_shapes.py` results, each checking ledger/head byte identity after the refusal:

- dropped last record, original head retained: `AuditTruncated`; ledger unchanged `True`; head unchanged `True`.
- head rewritten to a different count/tail: `AuditTruncated`; both unchanged `True`.
- head deleted while records remain: `AuditTruncated`; both unchanged `True` (head remains absent).
- one-behind count with another chain's hash: `AuditTruncated`; both unchanged `True`.
- record rewritten mid-chain: `AuditError`; both unchanged `True`.
- exactly one valid record behind the head: append repairs it; verify succeeds with all records retained.

The focused test `test_append_refuses_a_ledger_its_head_does_not_describe_and_writes_nothing`, the complementary repair test, and the kill-between-record-and-head test all passed.

### F-06 — signer runs inside lock

**Status: ACCEPTED AS A STATED LIMIT.** `_SIGNER_TIMEOUT` and `_LOCK_TIMEOUT` remain equal at `:198-210`, and signing remains inside the critical section. A wedged signer intentionally causes bounded fail-closed refusal for competing writers. No production signer was available for a live slow-signer test.

## F-05 truncation matrix and plaintext-head limits

The plaintext-head checks stop all of the following before writing: a shortened record chain with the old head; a head count/tail for another chain; a missing head on a nonempty chain; a one-behind count with a nonmatching hash; and a record hash/link rewrite. They also preserve both files byte-for-byte on refusal.

The exact one-behind count with the preceding record's correct hash is intentionally allowed through because it is the crash state produced between record fsync and head replacement. A malicious actor can create the same shape; the next append repairs the head. This does not provide tamper evidence. A party able to rewrite the entire ledger and plaintext head can still recompute a self-consistent chain; only signed external anchor custody addresses that threat. The updated docstring accurately describes this boundary.

## Questions 10 and 11

### 10. Full chain walk and denial-of-service risk

`append()` now performs a complete `_check_chain()` walk plus `_check_head()` on every append (`:940-953`). This is O(n) record parsing and hashing per append, so a large ledger makes the governed path progressively slower and can become an availability/DoS concern. I attempted a synthetic growth benchmark, but the 5,000-record run became I/O-bound and was terminated rather than allowing an uncontrolled long-running probe; no numeric performance threshold is claimed. The code currently has no size/record bound, checkpoint, or compaction policy. This is an open performance risk, though not a correctness bypass.

### 11. Availability trade for a pre-existing break

The plaintext-head check adds no tamper evidence, but refusing all appends after a detected chain/head break is the correct fail-closed audit-ledger trade: continuing would append evidence to an already-untrusted history and could hide the break. The operator must repair/reconcile out of band. The exact one-behind crash state is the sole automatic repair exception and is structurally distinguishable by count plus prior hash.

## Mutation testing of new append/head lines

Each mutation was applied to a saved temporary copy of `bro_audit_log.py`, the targeted test was run, and the original bytes were restored immediately:

1. Removed `_check_chain(existing)` at `:946`: `test_append_refuses_a_ledger_its_head_does_not_describe_and_writes_nothing` went RED (`AuditError not raised`).
2. Changed `except AuditHeadBehind: pass` at `:950-951` to re-raise: `test_append_still_proceeds_where_it_is_the_repair_or_there_is_nothing_to_repair` went RED with `AuditHeadBehind`.
3. Removed the effective `_check_head()` call at `:947-951`: the same truncation refusal test went RED (`AuditMalformed not raised`).

## Lock probes re-run on this head

The first-round `/tmp` probes were rerun against this head:

- two independent processes: both exit 0; 100 records; 100 unique sequence numbers; verify succeeds.
- holder killed with SIGKILL: next append succeeds.
- killed between record and head: verify reports `AuditHeadBehind`; next append recovers; all records remain.
- symlink lock path: `AuditLockUnavailable`.
- fork while holding lock: child exits; parent releases; next append succeeds.

## What I did NOT check

- The required full engine suite on this head, because the required `--require-hashes` install is blocked by the `rpds-py` Python 3.14 hash mismatch.
- Any Windows execution, including real `msvcrt` cross-process behavior.
- Production signer/anchor custody and trusted-key registry.
- IPC descriptor passing / SCM_RIGHTS integration.
- Power-loss, full-disk, or NFS durability.
- Production deployment or merge.
- Any code or PR-description changes; only this report was added.

## Required path to GREEN

Resolve the dependency-lock/platform mismatch without bypassing `--require-hashes`, then rerun the complete suite in that clean virtualenv and include every failure/error output if any remain. Independently run the Windows arm or retain it as the sole explicit blocker. Consider an explicit ledger-size/checkpoint policy before claiming unbounded append performance.

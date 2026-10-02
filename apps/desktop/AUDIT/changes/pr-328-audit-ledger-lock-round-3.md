Audited-PR: #328
Audited-Head: 5d266284dc029c71f1c1b2f07c8edf54967c3691

VERDICT: RED — Python 3.12 and the locked dependency installation succeeded, but the required full suite measured 2692 tests with 3 failures, 30 errors, and 15 skips. The Builder's 2692-OK/13-skipped claim is not reproduced. F-05 remains closed; F-01 and F-04 remain open. The full failure/error output is reproduced verbatim below.

## Environment and exact commands

- Active GitHub account: `menqstudio`.
- Audited head verified: `5d266284dc029c71f1c1b2f07c8edf54967c3691`.
- Ancestor check against the round-two head returned `0`.
- Diff from the round-two head listed only `apps/desktop/AUDIT/changes/pr-328-audit-ledger-lock-round-2.md` before this report was added.
- Python: `3.12.15` from uv.
- Requirements: `uv pip install --require-hashes -r engine/requirements-ci.txt` succeeded.
- Suite command: `BRO_ENV=ci PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests`.
- Measured result: **Ran 2692 tests in 87.376s; FAILED (failures=3, errors=30, skipped=15)**.

## Findings F-01 through F-06

### F-01 — full-suite status

**STILL OPEN.** The clean Python 3.12 run is not green: 3 failures, 30 errors, 15 skips. The full verbatim output is below. The errors are not silently reclassified as skips.

### F-02 — descriptor passing outside fork defense

**ACCEPTED AS A STATED LIMIT.** The code closes descriptors copied by `fork()` and documents that explicit descriptor transfer over IPC is outside this defense. No current engine path was found that transfers the lock descriptor.

### F-03 — advisory lock/inode replacement

**ACCEPTED AS A STATED LIMIT.** Cooperating writers are serialized and replacement is detected; a non-cooperating direct writer can bypass an advisory lock. The implementation documents this boundary accurately.

### F-04 — Windows lock arm

**STILL OPEN.** I did not run Windows. A relayed Windows transcript would not be independent evidence for this audit; I would accept it only as supplemental evidence, not as my verification. To close this finding independently, I require a reproducible Windows run of the focused lock tests (including real cross-process `msvcrt` locking and holder termination) from an auditable environment, with the exact command, commit, interpreter, and complete result.

Windows is not the only thing between this and GREEN: the Python 3.12 full suite is currently red on this Linux host. Once those failures/errors are resolved or correctly isolated by the owning environment without weakening assertions, Windows would be the remaining platform-certification item.

### F-05 — append-time truncation protection

**VERIFIED CLOSED.** At `engine/runtime/bro_audit_log.py:897-953`, append checks `_check_chain()` and `_check_head()` under the lock before writing. Independent round-two probes verified refusal and byte preservation for dropped records, wrong/re-written heads, missing heads, mismatched one-behind hashes, and mid-chain rewrites; exactly one valid head-behind record remains the intentional recovery case.

### F-06 — signer inside the lock

**ACCEPTED AS A STATED LIMIT.** Signer and lock timeouts remain bounded at 10 seconds; a wedged signer makes competing writers fail closed. No production signer deployment was available for a live slow-signer test.

## Current suite failures and errors — verbatim

The following is the complete failure/error section emitted by the required suite command, copied without summarization:

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
  File "/tmp/bro-anchor-custody-q645c3ze/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-nrslobyg/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-ifsnsph0/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-scv074gg/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-5zfkbf65/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-ajdb0aed/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-piodu31e/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-qyuyc8kw/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-qyuyc8kw/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-svu0z4fg/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-svu0z4fg/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-34u2w8zm/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-sq5jbl5w/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-26lspwj8/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-0n_t49ic/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-2g1p3r5k/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-yqudjmup/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-g3ysa1r1/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-vwqhurm8/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-5bt2_tja/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-vtuk3kqo/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-1771u36a/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-zj2pa84t/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-l7f0rdcj/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-nbjnpq37/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-_sgdzzv_/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-i5b55b8a/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-3dgc0dp8/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-s78z0f6u/signer.py", line 5, in <module>
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
  File "/tmp/bro-anchor-custody-p8trtihk/signer.py", line 5, in <module>
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ModuleNotFoundError: No module named 'cryptography'

======================================================================
FAIL: test_a_signer_that_signs_a_different_payload_is_refused (test_audit_head_anchor.SignerMisbehaviourFailsClosedTests.test_a_signer_that_signs_a_different_payload_is_refused)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_audit_head_anchor.py", line 237, in test_a_signer_that_signs_a_different_payload_is_refused
    self.assertIn("DIFFERENT payload", str(caught.exception))
AssertionError: 'DIFFERENT payload' not found in 'audit-head signing command refused (exit 1): Traceback (most recent call last):\n  File "/tmp/bro-anchor-custody-lo81hfnm/signer_lying.py", line 5, in <module>\n    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey\nModuleNotFoundError: No module named \'cryptography\''

======================================================================
FAIL: test_the_real_visudo_accepts_all_three_and_rejects_a_broken_one_through_the_block (test_live_sudoers_install.FragmentTextTests.test_the_real_visudo_accepts_all_three_and_rejects_a_broken_one_through_the_block) (kit='run_ladder_turn.sh', heredoc='PYSUDO')
The stand-in answers what it is told. Where a real visudo is installed, ask it too.
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_live_sudoers_install.py", line 803, in test_the_real_visudo_accepts_all_three_and_rejects_a_broken_one_through_the_block
    self.assertEqual(self.rc_of(done), 0, done.stderr)
AssertionError: 1 != 0 : /tmp/tmpwz6sittg/etc/.brops-sudoers-stage.WF0WBv/brops-x:1:49: syntax error: wildcards are not allowed in command arguments
brops-supervisor ALL=(brops-recorder) NOPASSWD: /opt/brops-live/bin/governed_recorder --store /opt/brops-live/store --launcher /opt/brops-live/tcb/privileged-launcher.bin --executor /opt/brops-live/bin/proof_executor --lease /opt/brops-live/tcb/executor.lease --cgroup brops-live --out /opt/brops-live/report/ladder-*.out --containment-out /opt/brops-live/report/ladder-*.out.containment.json --evidence-out /opt/brops-live/evidence-state/*.evidence.json --evidence-state /opt/brops-live/evidence-state
                                                ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
visudo: invalid sudoers file
sudoers: /usr/sbin/visudo rejected /tmp/tmpwz6sittg/etc/.brops-sudoers-stage.WF0WBv/brops-x; /tmp/tmpwz6sittg/etc/sudoers.d/brops-x was NOT installed


======================================================================
FAIL: test_the_real_visudo_accepts_all_three_and_rejects_a_broken_one_through_the_block (test_live_sudoers_install.FragmentTextTests.test_the_real_visudo_accepts_all_three_and_rejects_a_broken_one_through_the_block) (kit='run_live_turn.sh', heredoc='PYSUDO')
The stand-in answers what it is told. Where a real visudo is installed, ask it too.
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/gevorg/os-audit-2/engine/tests/test_live_sudoers_install.py", line 803, in test_the_real_visudo_accepts_all_three_and_rejects_a_broken_one_through_the_block
    self.assertEqual(self.rc_of(done), 0, done.stderr)
AssertionError: 1 != 0 : /tmp/tmpwz6sittg/etc/.brops-sudoers-stage.o7wxai/brops-x:1:54: syntax error: wildcards are not allowed in command arguments
brops-verifier_broker ALL=(brops-recorder) NOPASSWD: /opt/brops-live/bin/governed_recorder --store /opt/brops-live/store --launcher /opt/brops-live/tcb/privileged-launcher.bin --executor /opt/brops-live/bin/proof_executor --lease /opt/brops-live/tcb/executor.lease --cgroup brops-live --out /opt/brops-live/report/live-*.out --containment-out /opt/brops-live/report/live-*.out.containment.json --evidence-out /opt/brops-live/evidence-state/*.evidence.json --evidence-state /opt/brops-live/evidence-state
                                                     ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
visudo: invalid sudoers file
sudoers: /usr/sbin/visudo rejected /tmp/tmpwz6sittg/etc/.brops-sudoers-stage.o7wxai/brops-x; /tmp/tmpwz6sittg/etc/sudoers.d/brops-x was NOT installed


----------------------------------------------------------------------
Ran 2692 tests in 87.376s

FAILED (failures=3, errors=30, skipped=15)

## What I did not check

- No Windows execution.
- No production signer/anchor-custody deployment.
- No IPC descriptor-passing integration.
- No power-loss, full-disk, or NFS durability test.
- No merge or deployment.
- No runtime or PR-description changes; this report is the only new file.

## Required next action

Resolve the 30 signer-related errors in the Python 3.12 test environment without weakening tests, and resolve or explicitly environment-gate the two real-visudo failures without hiding them. Re-run the exact suite and provide independent Windows evidence as specified above. Do not claim GREEN from the 2692 test count alone.

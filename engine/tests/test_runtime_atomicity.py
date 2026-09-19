import json
import multiprocessing
import os
import pathlib
import shutil
import sys
import tempfile
import time
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_orchestration_runtime import OrchestrationRuntimeError, _exclusive_json
from bro_orchestration_runtime import STALE_LOCK_SECONDS
from bro_orchestration_runtime import DurableOrchestrationRuntime
from bro_orchestration_runtime_v1 import DurableOrchestrationRuntimeV1


def _writer(args):
    """Two processes racing to create the same record path.

    Run at module scope because Windows spawns rather than forks and cannot
    pickle a closure.
    """
    path, payload = args
    try:
        _exclusive_json(pathlib.Path(path), {"payload": payload})
        return "wrote"
    except OrchestrationRuntimeError:
        return "refused"
    except FileExistsError:
        return "refused"


class ExclusiveCreateTests(unittest.TestCase):
    """The append path computed `sequence = len(records) + 1`, checked
    `path.exists()`, then wrote with os.replace. Two processes could both read
    the same length, both find the path absent, and both write: os.replace is
    atomic but it overwrites, so one record vanished and the hash chain forked
    with nobody the wiser. Exclusive creation is what makes the check and the
    write the same operation."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-atomic-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_first_write_succeeds(self):
        path = self.tmp / "00000001.json"
        _exclusive_json(path, {"sequence": 1})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["sequence"], 1)

    def test_second_write_to_the_same_path_is_refused(self):
        path = self.tmp / "00000001.json"
        _exclusive_json(path, {"sequence": 1, "who": "first"})
        with self.assertRaises(OrchestrationRuntimeError):
            _exclusive_json(path, {"sequence": 1, "who": "second"})
        # The first record must survive untouched.
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["who"], "first")

    def test_no_temporary_files_are_left_behind(self):
        path = self.tmp / "00000001.json"
        _exclusive_json(path, {"sequence": 1})
        try:
            _exclusive_json(path, {"sequence": 1})
        except OrchestrationRuntimeError:
            pass
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["00000001.json"])

    def test_concurrent_writers_produce_exactly_one_winner(self):
        path = str(self.tmp / "00000001.json")
        with multiprocessing.Pool(4) as pool:
            outcomes = pool.map(_writer, [(path, f"writer-{i}") for i in range(4)])
        self.assertEqual(outcomes.count("wrote"), 1, outcomes)
        self.assertEqual(outcomes.count("refused"), 3, outcomes)
        self.assertEqual(len(list(self.tmp.iterdir())), 1)




class BaseClaimGuardTests(unittest.TestCase):
    """The claim guard on the class everyone inherits, not only on the V1 subclass.

    The Windows delete-pending retry lived ONLY in `DurableOrchestrationRuntimeV1._claim_guard` until
    2026-09-20, together with byte-identical copies of `_lock_owner` and `_break_stale_lock`. Every
    claim test in this file instantiated the subclass, so the base class's claim path — the one
    `bridge/engine_sidecar.py` and anything that does not need leases would take — surfaced a raw
    `PermissionError` and nothing noticed. The guard is one implementation now; these drive it through
    the base.
    """

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-base-lock-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.runtime = DurableOrchestrationRuntime(self.tmp)

    def test_the_base_class_has_a_claim_lock_at_all(self):
        """`claim_lock` was set in the V1 constructor. If the base has none, the guard below is not
        testing the base's own path but a subclass attribute that happens to exist."""
        self.assertTrue(hasattr(self.runtime, "claim_lock"), "the base runtime has no claim lock")
        with self.runtime._claim_guard():
            self.assertTrue(self.runtime.claim_lock.exists())
        self.assertFalse(self.runtime.claim_lock.exists())

    def test_a_delete_pending_open_is_retried_on_the_base_class(self):
        """The defect, on the class that carried it: one EACCES from an `O_EXCL` open against a
        delete-pending lock must be retried, not raised. Windows answers a contended claim that way
        and the answer means the same thing as `FileExistsError`."""
        real_open = os.open
        calls = []

        def flaky_open(path, flags, *args, **kwargs):
            if str(path).endswith(".claim.lock") and not calls:
                calls.append(path)
                raise PermissionError(13, "Permission denied")
            return real_open(path, flags, *args, **kwargs)

        with unittest.mock.patch("bro_orchestration_runtime.os.open", flaky_open):
            try:
                with self.runtime._claim_guard():
                    self.assertTrue(self.runtime.claim_lock.exists())
            except (PermissionError, OrchestrationRuntimeError) as exc:
                self.fail(f"a delete-pending open was not retried on the base class: {exc!r}")
        self.assertEqual(len(calls), 1, "the delete-pending open was never attempted")
        self.assertFalse(self.runtime.claim_lock.exists())

    def test_a_persistent_permission_error_still_fails_closed_on_the_base_class(self):
        """The retry must not swallow a genuinely unwritable state directory: it runs out the same
        bounded deadline and names both possibilities rather than asserting one."""
        def always_denied(path, flags, *args, **kwargs):
            raise PermissionError(13, "Permission denied")

        with unittest.mock.patch("bro_orchestration_runtime.os.open", always_denied), \
                unittest.mock.patch("bro_orchestration_runtime.LOCK_TIMEOUT_SECONDS", 0.05):
            try:
                with self.assertRaises(OrchestrationRuntimeError) as caught:
                    with self.runtime._claim_guard():
                        pass
            except PermissionError as exc:
                self.fail(f"the raw error escaped instead of the typed refusal: {exc!r}")
        self.assertIn("permission denied", str(caught.exception))

    def test_the_subclass_no_longer_carries_its_own_copy_of_the_guard(self):
        """One implementation, asserted rather than assumed.

        The three methods were byte-identical between the two modules except for the retry, which is
        how they drifted: a fix applied to one was invisible in the other. If a copy comes back, this
        fails and the reason has to be argued for in a diff.
        """
        for name in ("_claim_guard", "_lock_owner", "_break_stale_lock"):
            with self.subTest(method=name):
                self.assertNotIn(
                    name, vars(DurableOrchestrationRuntimeV1),
                    f"{name} is overridden in V1 again; the base and the subclass can now drift")
                self.assertIs(
                    getattr(DurableOrchestrationRuntimeV1, name),
                    getattr(DurableOrchestrationRuntime, name),
                    f"{name} resolves to a different function on the subclass")


class ClaimLockOwnershipTests(unittest.TestCase):
    """The lock wrote an owner token and never read it back. Staleness was decided
    on mtime alone and the release unlinked the path unconditionally, so a slow
    holder whose lock had already been broken and retaken would delete the new
    holder's lock on its way out — putting two processes inside the guard at
    once, which is precisely what the guard exists to prevent."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-lock-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.runtime = DurableOrchestrationRuntimeV1(self.tmp)

    def test_lock_carries_an_owner_token(self):
        with self.runtime._claim_guard():
            record = json.loads(self.runtime.claim_lock.read_text(encoding="utf-8"))
        self.assertIn("owner_token", record)
        self.assertEqual(len(record["owner_token"]), 32)

    def test_guard_releases_its_own_lock(self):
        with self.runtime._claim_guard():
            self.assertTrue(self.runtime.claim_lock.exists())
        self.assertFalse(self.runtime.claim_lock.exists())

    def test_overrunning_holder_does_not_delete_a_newer_lock(self):
        other = DurableOrchestrationRuntimeV1(self.tmp)
        with self.assertRaises(OrchestrationRuntimeError):
            with self.runtime._claim_guard():
                # The lock is broken and retaken by someone else while we are
                # still inside the guard; ours is gone and theirs is live.
                self.runtime.claim_lock.write_text(
                    json.dumps({"owner_token": "newer-holder", "pid": 1,
                                "created_at_epoch": 0}), encoding="utf-8")
                raise OrchestrationRuntimeError("body ends")
        self.assertEqual(
            json.loads(self.runtime.claim_lock.read_text(encoding="utf-8"))["owner_token"],
            "newer-holder", "the overrunning holder deleted a lock that was not its own")
        self.runtime.claim_lock.unlink()

    def test_stale_lock_is_broken_and_reacquired(self):
        self.runtime.claim_lock.write_text(
            json.dumps({"owner_token": "dead", "pid": 999999, "created_at_epoch": 0}),
            encoding="utf-8")
        old = time.time() - (STALE_LOCK_SECONDS + 5)
        os.utime(self.runtime.claim_lock, (old, old))
        with self.runtime._claim_guard():
            owner = json.loads(self.runtime.claim_lock.read_text(encoding="utf-8"))["owner_token"]
        self.assertNotEqual(owner, "dead")

    def test_stale_break_leaves_no_debris(self):
        self.runtime.claim_lock.write_text(
            json.dumps({"owner_token": "dead", "pid": 1, "created_at_epoch": 0}),
            encoding="utf-8")
        old = time.time() - (STALE_LOCK_SECONDS + 5)
        os.utime(self.runtime.claim_lock, (old, old))
        with self.runtime._claim_guard():
            pass
        self.assertEqual([p.name for p in self.tmp.iterdir() if "stale" in p.name], [])

    def test_lock_retaken_before_the_break_is_left_alone(self):
        """Observed token no longer matches, so the breaker must stand down."""
        self.runtime.claim_lock.write_text(
            json.dumps({"owner_token": "current", "pid": 1, "created_at_epoch": 0}),
            encoding="utf-8")
        self.runtime._break_stale_lock("someone-else")
        self.assertTrue(self.runtime.claim_lock.exists())
        self.runtime.claim_lock.unlink()

    def test_delete_pending_lock_is_retried_not_reported_as_failure(self):
        """A contended claim must not surface a transient EACCES.

        On Windows a lock file another claimant is unlinking or replacing is
        briefly delete-pending: O_EXCL open fails with PermissionError instead of
        FileExistsError. Only FileExistsError was retried, so eight threads racing
        for one task intermittently produced PermissionError(13) out of
        claim_next. Simulated here rather than raced, so it fails every run
        instead of one in eight.
        """
        real_open = os.open
        calls = []

        def flaky_open(path, flags, *args, **kwargs):
            if str(path).endswith(".claim.lock") and not calls:
                calls.append(path)
                raise PermissionError(13, "Permission denied")
            return real_open(path, flags, *args, **kwargs)

        with unittest.mock.patch("bro_orchestration_runtime.os.open", flaky_open):
            try:
                with self.runtime._claim_guard():
                    self.assertTrue(self.runtime.claim_lock.exists())
            except (PermissionError, OrchestrationRuntimeError) as exc:
                # Caught and NAMED rather than allowed to escape: an ERROR says "something blew up",
                # a FAILURE says "the retry is gone", and only the second is a verdict. Both types are
                # caught because both are ways the retry can be absent -- the raw EACCES escaping, or
                # a refusal raised on the first attempt instead of after the deadline.
                self.fail(f"a delete-pending open was not retried: {exc!r}")
        self.assertEqual(len(calls), 1, "the delete-pending open was never attempted")
        self.assertFalse(self.runtime.claim_lock.exists())

    def test_a_persistent_permission_error_still_fails_closed(self):
        """The retry above must not swallow a genuinely unwritable state directory."""
        def always_denied(path, flags, *args, **kwargs):
            raise PermissionError(13, "Permission denied")

        with unittest.mock.patch("bro_orchestration_runtime.os.open", always_denied), \
                unittest.mock.patch("bro_orchestration_runtime.LOCK_TIMEOUT_SECONDS", 0.05):
            try:
                with self.assertRaises(OrchestrationRuntimeError) as caught:
                    with self.runtime._claim_guard():
                        pass
            except PermissionError as exc:
                self.fail(f"the raw error escaped instead of the typed refusal: {exc!r}")
        self.assertIn("permission denied", str(caught.exception))

    def test_fresh_lock_blocks_and_times_out(self):
        self.runtime.claim_lock.write_text(
            json.dumps({"owner_token": "live", "pid": 1, "created_at_epoch": 0}),
            encoding="utf-8")
        with unittest.mock.patch("bro_orchestration_runtime.LOCK_TIMEOUT_SECONDS", 0.05):
            with self.assertRaises(OrchestrationRuntimeError) as caught:
                with self.runtime._claim_guard():
                    pass
        self.assertIn("timed out", str(caught.exception))
        self.runtime.claim_lock.unlink()

if __name__ == "__main__":
    unittest.main()

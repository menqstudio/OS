import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import bro_audit_log
import bro_stop_controller
from bro_audit_log import (
    AuditError,
    AuditHeadBehind,
    AuditLockUnavailable,
    AuditMalformed,
    AuditTornTail,
    append,
    read_all,
    verify,
)
from bro_stop_controller import is_group_alive, list_registered, register, stop_all


def _append_once(ledger_path: str, index: int) -> None:
    """Module-level so it survives being sent to a forked process."""
    import pathlib as _pathlib
    import sys as _sys
    _sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1] / "runtime"))
    from bro_audit_log import append as _append
    _append(_pathlib.Path(ledger_path), "concurrent", {"index": index})


#: How long a CONTENDED writer may wait inside these two tests, in place of the production
#: `_LOCK_TIMEOUT`.
#:
#: The production bound is 10 s and it is deliberate: it answers "has the holder wedged?", and a
#: wedged holder must surface rather than starve every other writer. It is NOT a budget for `n`
#: threads racing each other, and these tests are exactly that race.
#:
#: `_append_lock` polls a non-blocking kernel lock every 10 ms (`T-156`; it polled an `O_EXCL`
#: lock file before, and the arithmetic below was measured under that scheme). Polling is a race,
#: not a queue: a losing writer does not keep its place, so the wall-clock the LAST writer needs
#: grows like `n * H(n)` poll cycles, not `n`. For `n = 24`, `H(24) ~ 3.78`, so ~91 cycles — and
#: a cycle on a loaded Windows runner was a create, a write, an fsync, a replace and an unlink. At
#: ~100 ms per cycle that lands at ~9 s, just under the production bound, which is why this test
#: passed on `main` for weeks and then failed on `7eb6bf0` with nine of twenty-four writers timing
#: out — on a tree byte-identical to the one that had just passed the same job on PR #181. The
#: new lock drops the create and the unlink from the cycle and keeps the race, and it has not
#: been timed on a Windows runner, so the raised bound stays.
#:
#: So the runner's speed was deciding the verdict of a test about chain integrity. The property
#: here is *the chain never forks under concurrency*; the production constant is not what is under
#: test and is left untouched (`CLAUDE.md` §6: prefer the path that does not modify audited
#: security code). The bound is raised HERE, in proportion to the contention the test creates, so
#: a genuine deadlock still fails in bounded time rather than hanging.
_CONTENDED_LOCK_TIMEOUT = 5.0 * 24


class AuditLedgerTests(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-audit-"))
        self.ledger = self.dir / "audit.jsonl"

    def test_append_then_verify_chain(self):
        append(self.ledger, "approval", {"action": "git-push", "target": "main"})
        append(self.ledger, "incident", {"detail": "something"})
        self.assertEqual(verify(self.ledger), 2)

    def test_payload_secret_is_redacted(self):
        append(self.ledger, "incident", {"detail": "leaked token=ghp_1234567890abcdefghij1234ABCD"})
        raw = self.ledger.read_text(encoding="utf-8")
        self.assertNotIn("ghp_1234567890abcdefghij1234ABCD", raw)
        self.assertIn("REDACTED", raw)

    def test_tamper_is_detected(self):
        import json
        append(self.ledger, "a", {"x": 1})
        append(self.ledger, "b", {"x": 2})
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[0])
        rec["payload"]["x"] = 999  # change the value but keep the stored hash
        lines[0] = json.dumps(rec, sort_keys=True)
        self.ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(AuditError):
            verify(self.ledger)

    def test_tail_truncation_is_detected(self):
        append(self.ledger, "a", {"x": 1})
        append(self.ledger, "b", {"x": 2})
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        self.ledger.write_text(lines[0] + "\n", encoding="utf-8")  # drop last, keep head
        with self.assertRaises(AuditError):
            verify(self.ledger)

    def test_corrupt_json_line_raises_audit_error(self):
        # A corrupt record is a broken ledger; verify() must fail closed as AuditError,
        # not surface a raw JSONDecodeError that AuditError-only callers would miss.
        append(self.ledger, "a", {"x": 1})
        self.ledger.write_text(self.ledger.read_text(encoding="utf-8") + "{not json\n",
                               encoding="utf-8")
        with self.assertRaises(AuditError):
            verify(self.ledger)

    def test_every_malformed_ledger_shape_is_an_audit_error_and_never_a_raw_exception(self):
        """`verify()` documents "Raises AuditError on any break". Four shapes a tamperer can
        write in one line each raised something else, and a caller that catches AuditError
        alone (`bro_backup`) got a traceback."""
        import json

        def fresh():
            for name in list(self.dir.iterdir()):
                name.unlink()
            append(self.ledger, "a", {"x": 1})
            self.assertEqual(verify(self.ledger), 1)        # the control: it verifies first

        head = self.ledger.with_suffix(self.ledger.suffix + ".head")
        record = lambda: json.loads(self.ledger.read_text(encoding="utf-8").splitlines()[0])

        def without(field):
            document = record()
            del document[field]
            self.ledger.write_text(json.dumps(document) + "\n", encoding="utf-8")

        for name, tamper in (
            ("a corrupt head", lambda: head.write_text("{not json", encoding="utf-8")),
            ("a head that is not an object", lambda: head.write_text("[1, 2]", encoding="utf-8")),
            ("a head that is not UTF-8", lambda: head.write_bytes(b"\xff\xfe")),
            ("a record that is not an object",
             lambda: self.ledger.write_text("[1, 2]\n", encoding="utf-8")),
            ("a record with no kind", lambda: without("kind")),
            ("a record with no payload", lambda: without("payload")),
            ("a ledger that is not UTF-8", lambda: self.ledger.write_bytes(b"\xff\xfe\n")),
        ):
            with self.subTest(shape=name):
                fresh()
                self.assertTrue(head.exists(), "the fixture must have a head to tamper with")
                tamper()
                with self.assertRaises(AuditError) as caught:
                    verify(self.ledger)
                # ...and the SUBCLASS, so `bro_monitor` can still tell content it cannot read
                # from a chain that was written and then broken.
                self.assertIsInstance(caught.exception, AuditMalformed)

    def test_a_broken_link_is_a_plain_audit_error_not_a_malformed_ledger(self):
        import json
        append(self.ledger, "a", {"x": 1})
        append(self.ledger, "b", {"x": 2})
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[0])
        rec["payload"]["x"] = 999
        lines[0] = json.dumps(rec, sort_keys=True)
        self.ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(AuditError) as caught:
            verify(self.ledger)
        self.assertNotIsInstance(caught.exception, AuditMalformed)

    def test_ledger_inside_repo_is_refused(self):
        with self.assertRaises(AuditError):
            append(ROOT / "inside.jsonl", "x", {}, repo_root=ROOT)

    def test_concurrent_thread_appends_keep_one_valid_chain(self):
        import threading
        n = 24
        gate = threading.Barrier(n)
        errors = []

        def worker(index):
            try:
                gate.wait()                       # all threads race the lock at once
                append(self.ledger, "concurrent", {"index": index})
            except Exception as exc:              # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        with patch("bro_audit_log._LOCK_TIMEOUT", _CONTENDED_LOCK_TIMEOUT):
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual(errors, [])
        records = read_all(self.ledger)
        # No forked chain: exactly n records, strictly sequential seqs, every append
        # present once, and the hash chain + head verify.
        self.assertEqual([r["seq"] for r in records], list(range(n)))
        self.assertEqual(verify(self.ledger), n)
        self.assertEqual(sorted(r["payload"]["index"] for r in records), list(range(n)))

    @unittest.skipUnless(hasattr(os, "fork"), "cross-process lock proof uses fork")
    def test_concurrent_process_appends_keep_one_valid_chain(self):
        import multiprocessing
        n = 16
        ctx = multiprocessing.get_context("fork")
        procs = [ctx.Process(target=_append_once, args=(str(self.ledger), i)) for i in range(n)]
        # `fork` copies this process's memory, so the patch reaches the children. Same reasoning as
        # the thread test above; this one is POSIX-only, so it has never been the failing one.
        with patch("bro_audit_log._LOCK_TIMEOUT", _CONTENDED_LOCK_TIMEOUT):
            for p in procs:
                p.start()
            for p in procs:
                p.join(timeout=30)
        self.assertTrue(all(p.exitcode == 0 for p in procs),
                        [p.exitcode for p in procs])
        records = read_all(self.ledger)
        self.assertEqual([r["seq"] for r in records], list(range(n)))
        self.assertEqual(verify(self.ledger), n)
        self.assertEqual(sorted(r["payload"]["index"] for r in records), list(range(n)))


#: A writer that is going to be killed, run as a real second process. `mode` chooses how far
#: into `append()`'s critical section it gets before it says READY and stops:
#:
#:   hold            inside the section, nothing written
#:   torn            part of a record line on disk, no newline
#:   record-no-head  the whole record fsynced, the head's rename not yet done
#:   fork-then-hold  as `hold`, after forking a child that never execs and outlives it
#:
#: Each stops at a seam rather than on a timer, so the kill lands on a known state.
_DYING_WRITER = r"""
import os, pathlib, sys, time
sys.path.insert(0, {runtime!r})
import bro_audit_log as A

ledger = pathlib.Path({ledger!r})
mode = {mode!r}

def ready_and_wait(*_args, **_kwargs):
    sys.stdout.write("READY\n")
    sys.stdout.flush()
    time.sleep(300)

if mode == "hold":
    with A._append_lock(ledger):
        ready_and_wait()
elif mode == "torn":
    with A._append_lock(ledger):
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write('{{"seq": 1, "prev_hash": "ab')
            fh.flush()
            os.fsync(fh.fileno())
        ready_and_wait()
elif mode == "record-no-head":
    A.os.replace = ready_and_wait          # the head's rename is where this writer stops
    A.append(ledger, "dead-writer", {{"n": 1}})
elif mode == "fork-then-hold":
    with A._append_lock(ledger):
        child = os.fork()
        if child == 0:
            time.sleep(300)
            os._exit(0)
        sys.stdout.write(str(child) + "\n")
        ready_and_wait()
"""

#: One of several writers started as separate interpreters (no fork, so this runs on Windows
#: too). Each says UP once it has imported the module, then waits for the go-file so they all
#: reach the lock together.
_SPAWNED_WRITER = r"""
import pathlib, sys, time
sys.path.insert(0, {runtime!r})
import bro_audit_log as A

A._LOCK_TIMEOUT = {timeout!r}
ledger, go = pathlib.Path({ledger!r}), pathlib.Path({go!r})
sys.stdout.write("UP\n")
sys.stdout.flush()
deadline = time.monotonic() + 60
while not go.exists():
    if time.monotonic() > deadline:
        sys.exit(3)
    time.sleep(0.002)
for i in range({each}):
    A.append(ledger, "concurrent", {{"writer": {writer}, "i": i}})
"""


class AuditLedgerLockTests(unittest.TestCase):
    """`T-156`: the append lock is the kernel's, so it dies with its holder.

    Every refusal that protects the ledger's content is asserted here beside the one thing
    that changed, because the change is only safe if those stayed.
    """

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-audit-lock-"))
        self.ledger = self.dir / "audit.jsonl"
        self.lock = bro_audit_log._lock_path(self.ledger)
        self.head = self.ledger.with_suffix(self.ledger.suffix + ".head")

    # -- helpers -----------------------------------------------------------------------
    def _spawn(self, source):
        proc = subprocess.Popen([sys.executable, "-B", "-c", source],
                                stdout=subprocess.PIPE, text=True)
        self.addCleanup(proc.stdout.close)

        def reap():
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=30)
        self.addCleanup(reap)
        return proc

    def _kill_a_writer_at(self, mode):
        """Start a writer, let it reach `mode`, and kill it there. Returns what it printed
        before READY (the forked child's pid, in the one mode that prints one)."""
        proc = self._spawn(_DYING_WRITER.format(
            runtime=str(ROOT / "runtime"), ledger=str(self.ledger), mode=mode))
        said = []
        while True:
            line = proc.stdout.readline()
            self.assertTrue(line, f"the writer exited before READY (mode {mode!r}): {said}")
            if line.strip() == "READY":
                break
            said.append(line.strip())
        proc.kill()                      # SIGKILL on POSIX, TerminateProcess on Windows
        proc.wait(timeout=30)
        return said

    def _lock_is_held(self):
        """Probe with a SECOND descriptor. Both primitives conflict across descriptors even
        inside one process, so this is certain without a second process or a race."""
        fd = bro_audit_log._open_lock_file(self.lock)
        try:
            if bro_audit_log._try_lock(fd):
                return False
            return True
        finally:
            bro_audit_log._close_lock(fd)

    # -- (a) two appenders never interleave ---------------------------------------------
    def test_the_lock_is_held_while_append_reads_the_chain_it_will_extend(self):
        append(self.ledger, "a", {"x": 1})
        real_read_all = bro_audit_log.read_all
        held = []

        def probing_read_all(path):
            held.append(self._lock_is_held())
            return real_read_all(path)

        with patch("bro_audit_log.read_all", probing_read_all):
            append(self.ledger, "b", {"x": 2})
        self.assertEqual(held, [True], "append() read the chain with no lock held")
        self.assertFalse(self._lock_is_held(), "append() returned still holding the lock")

    def test_the_lock_is_released_when_the_append_refuses(self):
        append(self.ledger, "a", {"x": 1})
        with patch("bro_audit_log.read_all", side_effect=AuditError("refused inside the section")):
            with self.assertRaises(AuditError):
                append(self.ledger, "b", {"x": 2})
        self.assertFalse(self._lock_is_held(), "a refusal inside the section kept the lock")
        self.assertEqual(append(self.ledger, "c", {"x": 3})["seq"], 1)

    def test_separately_started_processes_appending_together_keep_one_valid_chain(self):
        writers, each = 6, 8
        go = self.dir / "go"
        procs = [self._spawn(_SPAWNED_WRITER.format(
            runtime=str(ROOT / "runtime"), ledger=str(self.ledger), go=str(go),
            timeout=_CONTENDED_LOCK_TIMEOUT, each=each, writer=n)) for n in range(writers)]
        for proc in procs:
            self.assertEqual(proc.stdout.readline().strip(), "UP")
        go.write_text("go", encoding="utf-8")            # all of them are waiting on this
        for proc in procs:
            proc.wait(timeout=120)
        self.assertEqual([proc.returncode for proc in procs], [0] * writers)
        records = read_all(self.ledger)
        self.assertEqual([r["seq"] for r in records], list(range(writers * each)))
        self.assertEqual(verify(self.ledger), writers * each)
        self.assertEqual(sorted((r["payload"]["writer"], r["payload"]["i"]) for r in records),
                         [(n, i) for n in range(writers) for i in range(each)])

    # -- (b) a holder that dies does not strand the ledger -------------------------------
    def test_a_holder_killed_while_holding_the_lock_does_not_strand_the_ledger(self):
        """THE BEHAVIOUR CHANGE. Under the O_EXCL lock file this append was refused, and so
        was every one after it, until a person deleted the file."""
        append(self.ledger, "a", {"x": 1})
        self._kill_a_writer_at("hold")
        # Bounded well under the production timeout: a stranded ledger fails here, it does
        # not make the suite wait.
        with patch("bro_audit_log._LOCK_TIMEOUT", 5.0):
            record = append(self.ledger, "after-the-holder-died", {"x": 2})
        self.assertEqual(record["seq"], 1)
        self.assertEqual(verify(self.ledger), 2)

    @unittest.skipUnless(hasattr(os, "fork"),
                         "a child that shares its parent's lock descriptor needs os.fork")
    def test_a_forked_child_of_a_dead_holder_does_not_keep_the_lock_alive(self):
        """`flock` belongs to the open file description, which a forked child shares. Without
        `_drop_inherited_locks` the child IS a holder, and the ledger is stranded for as long
        as it lives."""
        append(self.ledger, "a", {"x": 1})
        (child_pid,) = self._kill_a_writer_at("fork-then-hold")

        def reap_orphan():
            try:
                os.kill(int(child_pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        self.addCleanup(reap_orphan)
        os.kill(int(child_pid), 0)                       # the control: the child is alive
        with patch("bro_audit_log._LOCK_TIMEOUT", 3.0):
            self.assertEqual(append(self.ledger, "after", {"x": 2})["seq"], 1)
        self.assertEqual(verify(self.ledger), 2)

    # -- (c) what a dead writer leaves is never silently accepted ------------------------
    def test_a_writer_killed_mid_record_leaves_a_torn_tail_that_is_refused_and_not_repaired(self):
        append(self.ledger, "a", {"x": 1})
        self._kill_a_writer_at("torn")
        torn = self.ledger.read_bytes()
        self.assertFalse(torn.endswith(b"\n"), "the fixture must leave a torn tail")
        for name, call in (("verify", lambda: verify(self.ledger)),
                           ("read_all", lambda: read_all(self.ledger)),
                           ("append", lambda: append(self.ledger, "b", {"x": 2}))):
            with self.subTest(call=name), patch("bro_audit_log._LOCK_TIMEOUT", 5.0):
                with self.assertRaises(AuditTornTail):
                    call()
        self.assertEqual(self.ledger.read_bytes(), torn,
                         "a refusal must leave the torn bytes exactly as the writer left them")

    def test_a_corrupt_line_that_is_not_the_tail_is_not_called_a_torn_tail(self):
        append(self.ledger, "a", {"x": 1})
        whole = self.ledger.read_text(encoding="utf-8")
        for name, text in (("corrupt, newline-terminated", whole + "{not json\n"),
                           ("corrupt in the middle", "{not json\n" + whole.rstrip("\n"))):
            with self.subTest(shape=name):
                self.ledger.write_text(text, encoding="utf-8")
                with self.assertRaises(AuditError) as caught:
                    verify(self.ledger)
                self.assertNotIsInstance(caught.exception, AuditTornTail)

    def test_a_complete_last_record_with_no_newline_is_never_appended_to(self):
        """One byte short of a record boundary. The record still reads, so `verify()` passes;
        appending to it used to write two objects on one line and lose both."""
        append(self.ledger, "a", {"x": 1})
        append(self.ledger, "b", {"x": 2})
        self.ledger.write_bytes(self.ledger.read_bytes()[:-1])
        before = self.ledger.read_bytes()
        self.assertEqual(verify(self.ledger), 2)             # the record is intact
        with self.assertRaises(AuditTornTail):
            append(self.ledger, "c", {"x": 3})
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(verify(self.ledger), 2)             # ...and still is

    def test_a_writer_killed_between_its_record_and_its_head_loses_nothing(self):
        append(self.ledger, "a", {"x": 1})
        self._kill_a_writer_at("record-no-head")
        self.assertEqual([r["kind"] for r in read_all(self.ledger)], ["a", "dead-writer"])
        with self.assertRaises(AuditHeadBehind):             # refused, and by its own name
            verify(self.ledger)
        with patch("bro_audit_log._LOCK_TIMEOUT", 5.0):
            record = append(self.ledger, "b", {"x": 2})
        self.assertEqual(record["seq"], 2)
        self.assertEqual(verify(self.ledger), 3)
        self.assertEqual([r["kind"] for r in read_all(self.ledger)], ["a", "dead-writer", "b"])

    def test_only_a_head_exactly_one_record_behind_is_called_head_behind(self):
        """`AuditHeadBehind` says "nothing is missing". Every other disagreement between the
        head and the chain keeps the name it had, because for those something may be."""
        import json

        def fresh(count):
            for name in list(self.dir.iterdir()):
                name.unlink()
            for i in range(count):
                append(self.ledger, "k", {"i": i})
            self.assertEqual(verify(self.ledger), count)
            return [record["hash"] for record in read_all(self.ledger)]

        def set_head(count, last_hash):
            self.head.write_text(json.dumps({"count": count, "last_hash": last_hash}),
                                 encoding="utf-8")

        def drop_records(keep):
            lines = self.ledger.read_text(encoding="utf-8").splitlines()
            self.ledger.write_text("".join(line + "\n" for line in lines[:keep]),
                                   encoding="utf-8")

        genesis = bro_audit_log.GENESIS
        cases = (
            ("one behind", 3, lambda h: set_head(2, h[1]), True),
            ("first append, no head yet", 1, lambda h: self.head.unlink(), True),
            ("first append, an empty head", 1, lambda h: set_head(0, genesis), True),
            ("no records at all, and a head that says -1", 0,
             lambda h: set_head(-1, genesis), False),
            ("two behind", 3, lambda h: set_head(1, h[0]), False),
            ("one behind in count, another chain's hash", 3, lambda h: set_head(2, h[0]), False),
            ("count is True, not 1", 2, lambda h: set_head(True, h[0]), False),
            ("no head on a longer chain", 2, lambda h: self.head.unlink(), False),
            ("TRUNCATED: the head is ahead of the chain", 3, lambda h: drop_records(2), False),
            ("the right count, the wrong tail hash", 2, lambda h: set_head(2, h[0]), False),
        )
        for name, count, tamper, head_behind in cases:
            with self.subTest(shape=name):
                tamper(fresh(count))
                with self.assertRaises(AuditError) as caught:
                    verify(self.ledger)
                self.assertEqual(isinstance(caught.exception, AuditHeadBehind), head_behind,
                                 str(caught.exception))

    # -- (d) a bounded wait that fails closed --------------------------------------------
    def test_a_live_holder_that_never_releases_makes_the_append_refuse_and_write_nothing(self):
        import threading

        append(self.ledger, "a", {"x": 1})
        before = {p.name: p.read_bytes() for p in self.dir.iterdir()}
        outcome = []

        def blocked_append():
            try:
                outcome.append(append(self.ledger, "b", {"x": 2}))
            except Exception as exc:                      # noqa: BLE001
                outcome.append(exc)

        with patch("bro_audit_log._LOCK_TIMEOUT", 0.3), bro_audit_log._append_lock(self.ledger):
            worker = threading.Thread(target=blocked_append, daemon=True)
            started = time.monotonic()
            worker.start()
            worker.join(timeout=10)
            waited = time.monotonic() - started
            self.assertFalse(worker.is_alive(),
                             "the append is still waiting: the lock has no deadline")
            self.assertEqual(len(outcome), 1)
            self.assertIsInstance(outcome[0], AuditLockUnavailable, outcome[0])
            self.assertIn("not acquired within", str(outcome[0]))
            self.assertGreaterEqual(waited, 0.3, "it refused before the bound it names")
            self.assertEqual({p.name: p.read_bytes() for p in self.dir.iterdir()}, before,
                             "a writer that could not take the lock wrote anyway")
        self.assertEqual(append(self.ledger, "c", {"x": 3})["seq"], 1)   # released: it works

    def test_a_platform_with_no_kernel_lock_refuses_rather_than_appending_unlocked(self):
        with patch("bro_audit_log._platform_name", lambda: "java"):
            with self.assertRaises(AuditLockUnavailable) as caught:
                append(self.ledger, "a", {"x": 1})
        self.assertIn("no way to serialize", str(caught.exception))
        self.assertFalse(self.ledger.exists())

    def test_a_kernel_that_cannot_lock_the_file_is_a_named_refusal_and_writes_nothing(self):
        """A filesystem with no lock support answers `flock` with an error that is not "held".
        Every caller of `append()` fails closed on `AuditError`; this must be one."""
        import errno

        with patch("bro_audit_log._try_lock",
                   side_effect=OSError(errno.ENOLCK, "No locks available")):
            with self.assertRaises(AuditLockUnavailable) as caught:
                append(self.ledger, "a", {"x": 1})
        self.assertIn("No locks available", str(caught.exception))
        self.assertFalse(self.ledger.exists())

    def test_the_windows_arm_seeks_locks_refuses_and_releases_against_a_fake_msvcrt(self):
        """NOT a proof that the lock works on Windows - only `windows-latest` can give that,
        and there the thread and spawned-process tests above are that proof. This runs the
        `nt` arm's own control flow on any platform against a stand-in for `msvcrt.locking`,
        so a mistake in that arm is found before CI rather than by it: it must seek to
        `_LOCK_OFFSET` before every call, treat "held" as a wait and not a pass, refuse at the
        deadline, and unlock on release."""
        import errno
        import types

        held = {}                                    # inode -> the descriptor holding it
        calls = []

        def locking(fd, mode, nbytes):
            self.assertEqual(os.lseek(fd, 0, os.SEEK_CUR), bro_audit_log._LOCK_OFFSET,
                             "msvcrt.locking locks from the current position")
            self.assertEqual(nbytes, 1)
            key = (os.fstat(fd).st_dev, os.fstat(fd).st_ino)
            calls.append(mode)
            if mode == fake.LK_NBLCK:
                if key in held:
                    raise OSError(errno.EACCES, "Permission denied")
                held[key] = fd
            elif mode == fake.LK_UNLCK:
                if held.get(key) != fd:
                    raise OSError(errno.EACCES, "Permission denied")
                del held[key]
            else:
                self.fail(f"unexpected locking mode {mode!r}")

        fake = types.SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0, LK_LOCK=1, locking=locking)
        with patch.dict(sys.modules, {"msvcrt": fake}), \
                patch("bro_audit_log._platform_name", lambda: "nt"), \
                patch("bro_audit_log._LOCK_TIMEOUT", 0.3):
            append(self.ledger, "a", {"x": 1})
            append(self.ledger, "b", {"x": 2})
            self.assertEqual(calls, [fake.LK_NBLCK, fake.LK_UNLCK] * 2)
            self.assertEqual(held, {}, "the lock was not released")
            before = self.ledger.read_bytes()
            with bro_audit_log._append_lock(self.ledger):
                self.assertEqual(len(held), 1)
                with self.assertRaises(AuditLockUnavailable) as caught:
                    append(self.ledger, "c", {"x": 3})
                self.assertIn("not acquired within", str(caught.exception))
                self.assertEqual(self.ledger.read_bytes(), before)
            self.assertEqual(held, {})
            self.assertEqual(append(self.ledger, "d", {"x": 4})["seq"], 2)
        self.assertEqual(verify(self.ledger), 3)

    # -- (e) the old scheme's lock file --------------------------------------------------
    def test_a_lock_file_left_by_the_old_scheme_is_neither_trusted_nor_deleted(self):
        """An existing deployment can have `<ledger>.lock` on disk: under the old scheme it
        was the lock, and a crashed holder left it there."""
        legacy = self.ledger.with_suffix(self.ledger.suffix + ".lock")
        self.assertNotEqual(legacy, self.lock, "the new lock must not reuse the old name")
        legacy.write_bytes(b"left by a writer that crashed")
        with patch("bro_audit_log._LOCK_TIMEOUT", 5.0):
            append(self.ledger, "a", {"x": 1})
            append(self.ledger, "b", {"x": 2})
        self.assertEqual(verify(self.ledger), 2)
        self.assertEqual(legacy.read_bytes(), b"left by a writer that crashed")

    # -- (f) which file the lock is on ---------------------------------------------------
    def test_the_lock_file_sits_beside_the_ledger_is_private_and_is_never_removed(self):
        append(self.ledger, "a", {"x": 1})
        self.assertEqual(self.lock.parent, self.ledger.parent)
        self.assertTrue(self.lock.is_file())
        first = os.stat(self.lock)
        if os.name == "posix":
            self.assertEqual(first.st_mode & 0o077, 0, oct(first.st_mode))
        append(self.ledger, "b", {"x": 2})
        second = os.stat(self.lock)
        # Unlinking it between appends is what would let two writers hold "the" lock on
        # two different inodes.
        self.assertEqual((first.st_dev, first.st_ino), (second.st_dev, second.st_ino))
        self.assertEqual(self.lock.read_bytes(), b"")

    def _symlink_or_skip(self, target, link):
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError, AttributeError) as exc:
            self.skipTest(f"this platform or account cannot create a symbolic link: {exc}")

    def test_a_symlinked_lock_path_is_refused_and_cannot_redirect_the_lock(self):
        elsewhere = self.dir / "elsewhere"
        elsewhere.write_bytes(b"not a lock")
        self._symlink_or_skip(elsewhere, self.lock)
        with patch("bro_audit_log._LOCK_TIMEOUT", 0.5):
            with self.assertRaises(AuditLockUnavailable) as caught:
                append(self.ledger, "a", {"x": 1})
        self.assertIn("symbolic link", str(caught.exception))
        self.assertFalse(self.ledger.exists(), "nothing may be written without the lock")
        self.assertEqual(elsewhere.read_bytes(), b"not a lock")
        self.assertTrue(os.path.islink(self.lock))

    def test_a_dangling_symlink_at_the_lock_path_creates_nothing_where_it_points(self):
        target = self.dir / "planted-target"
        self._symlink_or_skip(target, self.lock)
        with patch("bro_audit_log._LOCK_TIMEOUT", 0.5):
            with self.assertRaises(AuditLockUnavailable) as caught:
                append(self.ledger, "a", {"x": 1})
        self.assertIn("symbolic link", str(caught.exception))
        self.assertFalse(target.exists(), "O_CREAT followed the symlink")
        self.assertFalse(self.ledger.exists())

    def test_where_the_platform_has_no_nofollow_a_symlinked_lock_path_is_still_refused(self):
        """Windows has no `O_NOFOLLOW`; the path is checked before the open instead. Run here
        by taking the flag away, so the arm CI's Linux job never reaches is not untested."""
        target = self.dir / "planted-target"
        self._symlink_or_skip(target, self.lock)
        with patch.object(bro_audit_log.os, "O_NOFOLLOW", 0, create=True), \
                patch("bro_audit_log._LOCK_TIMEOUT", 0.5):
            with self.assertRaises(AuditLockUnavailable) as caught:
                append(self.ledger, "a", {"x": 1})
        self.assertIn("symbolic link", str(caught.exception))
        self.assertFalse(target.exists(), "O_CREAT followed the symlink")
        self.assertFalse(self.ledger.exists())

    def test_a_lock_path_that_is_a_directory_is_refused(self):
        self.lock.mkdir()
        with patch("bro_audit_log._LOCK_TIMEOUT", 0.5):
            with self.assertRaises(AuditLockUnavailable):
                append(self.ledger, "a", {"x": 1})
        self.assertFalse(self.ledger.exists())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "a FIFO at the lock path needs os.mkfifo")
    def test_a_lock_path_that_is_a_fifo_is_refused_without_hanging(self):
        import threading

        os.mkfifo(self.lock)
        outcome = []

        def attempt():
            try:
                outcome.append(append(self.ledger, "a", {"x": 1}))
            except Exception as exc:                      # noqa: BLE001
                outcome.append(exc)

        with patch("bro_audit_log._LOCK_TIMEOUT", 0.5):
            worker = threading.Thread(target=attempt, daemon=True)
            worker.start()
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive(), "opening the FIFO blocked")
        self.assertIsInstance(outcome[0], AuditLockUnavailable, outcome[0])
        self.assertIn("not a regular file", str(outcome[0]))
        self.assertFalse(self.ledger.exists())

    @unittest.skipUnless(os.name == "posix",
                         "a lock file that is open cannot be unlinked on Windows, so the "
                         "state this test builds does not exist there")
    def test_a_waiter_does_not_take_its_lock_on_a_lock_file_that_was_replaced_under_it(self):
        """A waiter has the lock file OPEN while it waits. Remove and recreate the file and the
        waiter is polling an inode nobody else will ever open: it would get that lock the
        moment the first holder left, while a newer writer holds the file now at the path."""
        import fcntl
        import threading

        append(self.ledger, "a", {"x": 1})
        opened = threading.Event()
        real_open = bro_audit_log._open_lock_file

        def signalling_open(path):
            fd = real_open(path)
            opened.set()
            return fd

        outcome = []

        def waiter():
            try:
                outcome.append(append(self.ledger, "waiter", {}))
            except Exception as exc:                      # noqa: BLE001
                outcome.append(exc)

        with patch("bro_audit_log._LOCK_TIMEOUT", 30.0):
            first = bro_audit_log._append_lock(self.ledger)
            first.__enter__()                             # a holder, on the ORIGINAL inode
            try:
                with patch("bro_audit_log._open_lock_file", signalling_open):
                    worker = threading.Thread(target=waiter, daemon=True)
                    worker.start()
                    self.assertTrue(opened.wait(10), "the waiter never opened the lock file")
                self.lock.unlink()                        # ...which is then replaced
                second = os.open(self.lock, os.O_RDWR | os.O_CREAT, 0o600)
                closed = []
                self.addCleanup(lambda: closed or os.close(second))
                fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)   # a second, newer holder
            finally:
                first.__exit__(None, None, None)          # the original inode is free now
            time.sleep(0.5)                               # fifty of the waiter's poll cycles
            self.assertTrue(worker.is_alive() and not outcome,
                            f"the waiter appended while another writer held the lock: {outcome}")
            self.assertEqual(len(read_all(self.ledger)), 1)
            fcntl.flock(second, fcntl.LOCK_UN)
            os.close(second)
            closed.append(True)
            worker.join(timeout=20)
        self.assertFalse(worker.is_alive())
        self.assertIsInstance(outcome[0], dict, outcome[0])
        self.assertEqual(verify(self.ledger), 2)

    # -- the approval log's lock is the same shape, and the two are held together ---------
    def test_the_audit_lock_and_the_approval_log_lock_have_not_drifted(self):
        """Two modules, one mechanism, deliberately not one helper: `_write_lock` yields the
        handle of the log it locks and blocks without a deadline on POSIX, this one locks a
        file beside the ledger and has a deadline everywhere. What they must keep in common
        is the PRIMITIVE - so a fix to one that the other needs shows up here."""
        import inspect

        import bro_approval_requests

        self.assertEqual(bro_audit_log._LOCK_OFFSET, bro_approval_requests._LOCK_OFFSET)
        self.assertEqual(bro_audit_log._LOCK_TIMEOUT, bro_approval_requests._LOCK_TIMEOUT_SECONDS)
        approval = inspect.getsource(bro_approval_requests._write_lock)
        audit = (inspect.getsource(bro_audit_log._try_lock)
                 + inspect.getsource(bro_audit_log._close_lock))
        for name, source in (("bro_approval_requests._write_lock", approval),
                             ("bro_audit_log._try_lock/_close_lock", audit)):
            for primitive in ("fcntl.flock(", "fcntl.LOCK_EX", "fcntl.LOCK_UN",
                              "msvcrt.LK_NBLCK, 1)", "msvcrt.LK_UNLCK, 1)",
                              "_LOCK_OFFSET, os.SEEK_SET)",
                              '_platform_name() == "posix"', '_platform_name() == "nt"'):
                with self.subTest(module=name, primitive=primitive):
                    self.assertIn(primitive, source)
        # ...and neither went back to a lock FILE whose existence is the lock.
        for module in (bro_audit_log, bro_approval_requests):
            with self.subTest(module=module.__name__):
                self.assertNotIn("os.O_EXCL", inspect.getsource(module))


class StopControllerTests(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-stop-"))
        self.registry = self.dir / "processes.jsonl"
        self.audit = self.dir / "incidents.jsonl"

    @unittest.skipUnless(
        hasattr(os, "killpg"),
        "STOP Controller manages POSIX process groups (os.killpg) and reads "
        "/proc; the real-process test is Linux/POSIX-only",
    )
    def test_stops_a_real_process_group(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        # A session leader's pgid equals its pid.
        register(self.registry, "task-1", proc.pid, proc.pid)
        report = stop_all(self.registry, self.audit)
        self.assertTrue(any(e["pid"] == proc.pid for e in report["stopped"]))
        proc.wait(timeout=5)
        self.assertFalse(is_group_alive(proc.pid))

    def test_unstoppable_process_is_recorded_as_incident(self):
        register(self.registry, "task-stuck", 424242, 424242)
        with patch.object(bro_stop_controller, "terminate_group", return_value=False):
            report = stop_all(self.registry, self.audit, repo_root=ROOT)
        self.assertEqual(len(report["unstopped"]), 1)
        records = read_all(self.audit)
        self.assertTrue(any(r["kind"] == "unstopped-process" for r in records))
        self.assertEqual(verify(self.audit), len(records))

    def test_registry_round_trips(self):
        register(self.registry, "t", 10, 10)
        self.assertEqual(list_registered(self.registry)[0]["task_id"], "t")

    @unittest.skipUnless(
        hasattr(os, "killpg") and hasattr(os, "fork"),
        "a group outliving its reaped leader needs POSIX fork + killpg",
    )
    def test_group_reads_alive_after_leader_reaped_with_child_alive(self):
        # The false negative this guards: a process group outlives its leader. The
        # leader spawns a child in its group, then exits and is reaped, so
        # /proc/<pgid> is gone while the orphaned child keeps running. Checking the
        # leader pid alone would report the group dead and STOP would walk away from
        # a live grandchild — the exact state it exists to catch. is_group_alive
        # must scan the whole group and still read it as alive.
        script = (
            "import os,sys,time,signal\n"
            "os.setsid()\n"                 # own the new group; pgid == this pid
            "if os.fork()==0:\n"
            # Survive being orphaned: an orphaned session child is sent SIGHUP when
            # its leader exits, and it inherited the leader's stdout pipe. Ignore the
            # hangup and drop the pipe so the child genuinely outlives the leader —
            # that is the state under test.
            "    signal.signal(signal.SIGHUP, signal.SIG_IGN)\n"
            "    os.close(1)\n"
            "    time.sleep(30)\n"          # child keeps the group alive
            "    os._exit(0)\n"
            "sys.stdout.write(str(os.getpid()))\n"
            "sys.stdout.flush()\n"
            "os._exit(0)\n"                 # leader exits immediately
        )
        proc = subprocess.Popen([sys.executable, "-c", script],
                                stdout=subprocess.PIPE, text=True)
        self.addCleanup(proc.stdout.close)
        pgid = int(proc.stdout.readline().strip())
        proc.wait(timeout=5)               # reap the leader; only the child remains

        def _cleanup():
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        self.addCleanup(_cleanup)

        self.assertTrue(
            is_group_alive(pgid),
            "leader reaped but child still alive → group must read as alive")


if __name__ == "__main__":
    unittest.main()

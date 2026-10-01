"""The shared AF_UNIX machinery: the total connection budget and the two Linux-only helpers.

This module had NO test file of its own until 2026-09-20, which is part of why the bound it now owns
lived in only one of the five accept loops in ``engine/runtime/``. Measured that day:

    governed_supervisor_server.py:1250  BOUNDED    CONNECTION_BUDGET_S = 120.0
    floor_writer.py:976                 BOUNDED    CONNECTION_BUDGET_S = 30.0
    brops_socket.py:97                  UNBOUNDED  blocking read_frame, no timeout
    challenge_authority_server.py:352   UNBOUNDED  `while remaining > 0: recv(...)`
    isolated_signer_server.py:482       UNBOUNDED  the same loop, byte-identical class

Everything here runs on ANY host. That is the point of the shape the arithmetic is written in: the
socket is reached through ``recv`` / ``arm_timeout`` / ``now`` seams, so the decision that refuses a
stalled peer is testable where no AF_UNIX socket exists — which is where it was previously invisible.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "runtime"))

import brops_socket  # noqa: E402


class ConnectionBudgetTests(unittest.TestCase):
    """The TOTAL deadline that bounds one connection."""

    def test_budget_is_the_remaining_time(self):
        self.assertEqual(brops_socket.recv_budget_s(100.0, 40.0), 60.0)

    def test_an_exhausted_budget_is_none_and_never_zero(self):
        # settimeout(0) is NON-BLOCKING, and the POSIX SO_RCVTIMEO it maps to reads 0 as INFINITE.
        # Returning 0.0 as the deadline lands would arm the opposite of a deadline at exactly the
        # moment it matters most.
        self.assertIsNone(brops_socket.recv_budget_s(100.0, 100.0))
        self.assertIsNone(brops_socket.recv_budget_s(100.0, 100.5))

    def test_the_budget_is_finite_and_generous_enough_not_to_bite_a_real_peer(self):
        """The number is derived, not chosen: the signer's own client gives up at 20 s
        (`isolated_signer_server.request_sign_result`) and `brops_socket.request` at 30 s, so the
        server's budget must exceed both by a wide margin and still be finite."""
        self.assertGreater(brops_socket.CONNECTION_BUDGET_S, 30.0)
        self.assertLess(brops_socket.CONNECTION_BUDGET_S, float("inf"))

    def test_a_drip_peer_is_cut_off_by_the_total_budget(self):
        """One byte per call, forever. A per-recv timeout would never fire — it restarts on every
        byte that arrives — so only a TOTAL budget can end this."""
        clock = {"t": 0.0}
        armed = []

        def recv(_n):
            clock["t"] += 10.0          # each byte costs ten seconds of the budget
            return b"x"

        got = brops_socket.recv_exactly_bounded(
            recv, 1000, deadline=100.0, arm_timeout=armed.append, now=lambda: clock["t"])

        self.assertEqual(len(got), 10)          # 100 s of budget at 10 s per byte
        self.assertLess(len(got), 1000)         # the read did NOT complete
        self.assertTrue(all(t > 0 for t in armed), armed)

    def test_a_prompt_peer_is_unaffected(self):
        payload = [b"hello ", b"world"]
        got = brops_socket.recv_exactly_bounded(
            lambda n: payload.pop(0) if payload else b"", 11,
            deadline=100.0, arm_timeout=lambda _s: None, now=lambda: 0.0)
        self.assertEqual(got, b"hello world")

    def test_a_peer_that_closes_early_gives_a_short_read_not_a_hang(self):
        got = brops_socket.recv_exactly_bounded(
            lambda _n: b"", 8, deadline=100.0, arm_timeout=lambda _s: None, now=lambda: 0.0)
        self.assertEqual(got, b"")

    def test_a_socket_timeout_ends_the_read_rather_than_propagating(self):
        """The armed timeout firing is the budget working, not an error for the caller to handle:
        a short read is already a framing refusal one layer up."""
        import socket as _socket

        def recv(_n):
            raise _socket.timeout("armed and fired")

        self.assertEqual(
            brops_socket.recv_exactly_bounded(
                recv, 8, deadline=100.0, arm_timeout=lambda _s: None, now=lambda: 0.0),
            b"")

    def test_an_already_spent_budget_reads_nothing_at_all(self):
        calls = []
        got = brops_socket.recv_exactly_bounded(
            lambda n: calls.append(n) or b"x" * n, 8,
            deadline=0.0, arm_timeout=lambda _s: None, now=lambda: 5.0)
        self.assertEqual(got, b"")
        self.assertEqual(calls, [], "a spent budget must not reach the socket at all")


class LinuxOnlyHelperTests(unittest.TestCase):
    """The two helpers three servers each had a byte-identical copy of."""

    class Boom(Exception):
        pass

    def test_read_peercred_uid_refuses_off_linux_with_the_CALLERS_error(self):
        """The injected class is the whole reason three copies existed. Each service keeps its own
        refusal vocabulary; the logic exists once."""
        if sys.platform == "linux":
            self.skipTest("this asserts the non-Linux refusal")
        with self.assertRaises(self.Boom) as caught:
            brops_socket.read_peercred_uid(object(), error=self.Boom)
        self.assertIn("SO_PEERCRED", str(caught.exception))

    def test_bind_listener_refuses_off_linux_and_names_the_service(self):
        if sys.platform == "linux":
            self.skipTest("this asserts the non-Linux refusal")
        with self.assertRaises(self.Boom) as caught:
            brops_socket.bind_listener("/tmp/nope.sock", error=self.Boom, subject="signer")
        message = str(caught.exception)
        self.assertIn("requires Linux", message)
        self.assertIn("signer", message,
                      "an operator reading the refusal must be told WHICH service refused")

    def test_the_refusal_is_the_callers_type_and_not_a_generic_one(self):
        if sys.platform == "linux":
            self.skipTest("this asserts the non-Linux refusal")
        for subject in ("authority", "supervisor front door", "signer"):
            with self.subTest(subject=subject):
                with self.assertRaises(self.Boom):
                    brops_socket.bind_listener("/x", error=self.Boom, subject=subject)


class TheAcceptLoopArmsTheBudgetTests(unittest.TestCase):
    """`serve_forever`'s own loop had no bound either, and it is the one the service entry points
    run (`engine/tools/brops_signer_service.py`, `brops_supervisor_service.py`).

    Asserted against the SOURCE because the loop cannot run here: it raises `SocketAclError` off
    AF_UNIX before the first accept. A source assertion is the only kind that can hold a
    platform's code to account from a platform that cannot execute it — and it is checked against
    code with full-line comments stripped, so a comment mentioning the call cannot satisfy it.
    """

    @staticmethod
    def _code() -> str:
        src = pathlib.Path(brops_socket.__file__).read_text(encoding="utf-8")
        return "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))

    def test_the_accept_loop_arms_the_connection_budget(self):
        """ONE deadline, taken at accept and charged by every read through `recv_exactly_bounded`.

        This used to assert `conn.settimeout(CONNECTION_BUDGET_S)`, and that line WAS the defect: a
        socket timeout restarts on every `recv`, so the loop this test called bounded was held for
        as long as a peer cared to drip. `TheAcceptLoopOnARealSocketTests` below measures it; this
        source assertion stays for the platforms that cannot run the loop at all.
        """
        code = self._code()
        self.assertIn("deadline = time.monotonic() + CONNECTION_BUDGET_S", code)
        self.assertNotIn("conn.settimeout(CONNECTION_BUDGET_S)", code,
                         "a per-recv timeout is not a budget")
        self.assertNotIn("makefile(\"rb\")\n    try:\n        request", code,
                         "the server's frame must not be read through an unbudgeted file object")

    def test_a_stalled_read_drops_the_connection(self):
        code = self._code()
        self.assertIn("recv_exactly_bounded(", code)
        self.assertIn("read_frame(_BudgetedReader(conn, deadline))", code)
        self.assertIn("def _serve_one(", code)

    def test_one_connection_cannot_end_the_loop(self):
        self.assertIn("except Exception:  # noqa: BLE001 - one connection must never kill the loop",
                      self._code())

    def test_the_loop_refuses_an_unusable_socket_path_rather_than_serving(self):
        """Fails CLOSED on a path it cannot bind, on every platform.

        This assertion used to name `SocketAclError` unconditionally against `/definitely/not/a/socket`
        and it BROKE CI. Written on a host where `hasattr(socket, "AF_UNIX")` is False, it had encoded
        "this box has no AF_UNIX" as a property of the code; on ubuntu the guard passes,
        `_harden_socket_dir` reaches `os.makedirs("/definitely")`, and the refusal is a
        `PermissionError`. Both are refusals — the CLASS is the platform's, not the contract's.

        The path is now a FILE with a name appended, which no uid can turn into a directory. The
        permission-denied version would have SUCCEEDED as root, created the directory chain, bound the
        socket and then blocked in `accept()` forever: a test that hangs the suite on a privileged
        runner, written to prove that a hang is refused.
        """
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".notadir", delete=False) as handle:
            blocker = handle.name
        self.addCleanup(lambda: pathlib.Path(blocker).unlink(missing_ok=True))
        with self.assertRaises((brops_socket.SocketAclError, OSError)):
            brops_socket.serve_forever(
                blocker + "/nope.sock", lambda _f: {}, allowed_peer_uids=None, max_requests=1)

    def test_a_host_with_no_af_unix_is_refused_by_NAME_before_any_filesystem_work(self):
        """Where AF_UNIX is absent the refusal must be this module's own, and must come before the
        directory is touched -- otherwise an operator is told about a path when the real answer is
        the platform."""
        if brops_socket._HAS_AF_UNIX:
            self.skipTest("this host HAS AF_UNIX; the branch under test is the one without it")
        with self.assertRaises(brops_socket.SocketAclError) as caught:
            brops_socket.serve_forever(
                "/definitely/not/a/socket", lambda _f: {}, allowed_peer_uids=None, max_requests=1)
        self.assertIn("AF_UNIX", str(caught.exception))


@unittest.skipUnless(sys.platform == "linux" and brops_socket._HAS_AF_UNIX,
                     "the accept loop needs AF_UNIX and SO_PEERCRED")
class TheAcceptLoopOnARealSocketTests(unittest.TestCase):
    """The loop itself, run. `engine/tools/brops_signer_service.py` and
    `brops_supervisor_service.py` are this loop and nothing else, so what ends it ends them."""

    def setUp(self):
        import os
        import tempfile
        import threading
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "svc.sock")
        self.uid = os.getuid()
        self.ready = threading.Event()
        self.outcome = {}

    def _serve(self, handle, max_requests):
        import contextlib
        import io
        import threading
        self.stderr = io.StringIO()

        def run():
            try:
                with contextlib.redirect_stderr(self.stderr):
                    brops_socket.serve_forever(
                        self.path, handle, allowed_peer_uids=frozenset({self.uid}),
                        ready=self.ready.set, max_requests=max_requests)
                self.outcome["exit"] = "returned"
            except BaseException as exc:  # noqa: BLE001 - the test reports how the loop ended
                self.outcome["exit"] = "RAISED %s" % type(exc).__name__

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.assertTrue(self.ready.wait(10), "the service never became ready")
        return thread

    def _connect(self):
        import socket
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(10)
        conn.connect(self.path)
        return conn

    def test_a_peer_that_hangs_up_before_its_reply_does_not_end_the_service(self):
        import threading
        import brops_protocol
        release = threading.Event()

        def handle(frame):
            if frame.get("n") == 1:
                release.wait(10)        # the first caller is gone by the time this returns
            return {"echo": frame.get("n"), "pad": "x" * 200000}

        thread = self._serve(handle, max_requests=2)
        first = self._connect()
        first.sendall(brops_protocol.encode_frame({"n": 1}))
        first.close()                   # hang up with the request sent and no reply read
        release.set()
        self.assertEqual(brops_socket.request(self.path, {"n": 2}, timeout=10)["echo"], 2,
                         "the service must still answer the NEXT caller")
        thread.join(10)
        self.assertEqual(self.outcome.get("exit"), "returned")

    def test_a_raising_handler_does_not_end_the_service(self):
        def handle(frame):
            if frame.get("n") == 1:
                raise RuntimeError("a handler fault")
            return {"echo": frame.get("n")}

        thread = self._serve(handle, max_requests=2)
        with self.assertRaises(Exception):
            brops_socket.request(self.path, {"n": 1}, timeout=10)
        self.assertEqual(brops_socket.request(self.path, {"n": 2}, timeout=10)["echo"], 2)
        thread.join(10)
        self.assertEqual(self.outcome.get("exit"), "returned")
        self.assertIn("RuntimeError", self.stderr.getvalue(), "the fault is logged, not swallowed")

    def test_a_drip_peer_is_dropped_at_the_budget_and_gets_no_reply(self):
        import time
        import brops_protocol
        original = brops_socket.CONNECTION_BUDGET_S
        brops_socket.CONNECTION_BUDGET_S = 0.4
        self.addCleanup(setattr, brops_socket, "CONNECTION_BUDGET_S", original)
        handled = []
        thread = self._serve(lambda frame: handled.append(frame) or {"ok": True}, max_requests=1)
        wire = brops_protocol.encode_frame({"n": 1, "pad": "x" * 40})
        self.assertGreater(len(wire) * 0.05, 2.0, "the drip must outlast the budget by a margin")
        conn = self._connect()
        self.addCleanup(conn.close)
        started = time.monotonic()
        try:
            for byte in wire:           # each byte lands well inside a 0.4 s per-recv timeout
                conn.sendall(bytes([byte]))
                time.sleep(0.05)
        except OSError:
            pass                        # the service hung up on us, which is the point
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(handled, [], "a starved frame must never reach the handler")
        self.assertLess(time.monotonic() - started, 2.0)


if __name__ == "__main__":
    unittest.main()

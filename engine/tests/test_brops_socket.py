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
        self.assertIn("conn.settimeout(CONNECTION_BUDGET_S)", self._code())

    def test_a_stalled_read_drops_the_connection(self):
        code = self._code()
        self.assertIn("except (socket.timeout, TimeoutError):", code)
        self.assertIn("def _serve_one(", code)

    def test_the_loop_refuses_a_host_with_no_af_unix_before_binding(self):
        with self.assertRaises(brops_socket.SocketAclError):
            brops_socket.serve_forever(
                "/definitely/not/a/socket", lambda _f: {}, allowed_peer_uids=None, max_requests=1)


if __name__ == "__main__":
    unittest.main()

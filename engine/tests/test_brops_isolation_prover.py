"""Wave 3b-1 — tests for the isolation PROVER's own verdicts (audit P0-1; this round).

The prover is the artifact that certifies the same-login-user containment. Until this
round it scored a bare `except Exception` as "denied = good" and `FileNotFoundError` as
"not reachable is also denied", so a mistyped key path, a down service, a renamed socket
or a wrong platform all printed `ISOLATION PROOF PASSED`. A proof that cannot fail for
the right reason is the repo's recurring defect at its worst, because it sits on top of
the security property it claims to establish and gets quoted as evidence.

These tests exist so that the prover's THREE-valued judgement can itself go red:

  DENIED       the containment refused, attributably (specific errno / wire behaviour /
               refusal reason) AND the attack path was proven live
  BREACH       the attack succeeded
  INCONCLUSIVE the attack could not be attempted — which must NEVER render as proven

Each test names the single line it would catch the deletion of. The real end-to-end
(dedicated UIDs, SO_PEERCRED, 0700 key dirs, 2770 store) is `engine/ci/isolation_proof.sh`
on Linux CI; what is unit-testable here is every branch of the judgement, plus a real
AF_UNIX round trip where the platform has one.
"""

import errno
import io
import os
import pathlib
import socket
import sys
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

import brops_isolation_prover as prover
import brops_protocol

_POSIX = os.name == "posix"
_HAS_AF_UNIX = hasattr(socket, "AF_UNIX")


def _exchange_script(*exchanges):
    """A fake transport returning the given `Exchange`s in order (attack 4 makes two
    calls: the honest control, then the forged attack). It also records the frames it was
    asked to send, so a test can assert what the attack actually put on the wire."""
    queue = list(exchanges)

    def _fake(socket_path, frame, timeout=5.0):
        _fake.sent.append(frame)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    _fake.sent = []
    return _fake


def _answered(reply):
    return prover.Exchange(connected=True, reply=reply, reply_bytes=len(str(reply)), error=None)


def _hung_up():
    """Connected, then closed without a byte — `brops_socket._serve_one`'s ACL deny."""
    return prover.Exchange(
        connected=True, reply=None, reply_bytes=0,
        error=brops_protocol.ProtocolError("unexpected EOF: wanted 4 bytes, short by 4"),
    )


def _never_connected(exc):
    return prover.Exchange(connected=False, reply=None, reply_bytes=0, error=exc)


def _control_passes(directory, label):
    """A positive control that succeeds, so the classification under test is isolated from
    the control's own logic. The control has its own tests below."""
    return None, f"(test) {label} {directory} is live and foreign"


class ConnectSignerTests(unittest.TestCase):
    """Attack 1 — SO_PEERCRED must be what refuses us, and it must have had the chance."""

    def _run(self, ex):
        return prover.attack_connect_signer("/nowhere.sock", exchange=_exchange_script(ex))

    def test_a_socket_that_is_not_there_is_inconclusive_not_denied(self):
        # Deleting `if not ex.connected: return _unreachable(...)` makes a nonexistent
        # socket fall through to the "not a recognizable ACL deny" branch or worse.
        out = self._run(_never_connected(FileNotFoundError(errno.ENOENT, "no such file")))
        self.assertEqual(out.verdict, prover.INCONCLUSIVE)
        self.assertIn("not there", out.detail)
        self.assertIn("none", out.control)

    def test_a_service_that_is_down_is_inconclusive_not_denied(self):
        out = self._run(_never_connected(ConnectionRefusedError(errno.ECONNREFUSED, "refused")))
        self.assertEqual(out.verdict, prover.INCONCLUSIVE)
        self.assertIn("nothing is listening", out.detail)

    def test_a_host_without_af_unix_is_inconclusive_not_denied(self):
        out = self._run(_never_connected(prover.TransportUnavailable("AF_UNIX unavailable")))
        self.assertEqual(out.verdict, prover.INCONCLUSIVE)
        self.assertIn("no AF_UNIX", out.detail)

    def test_any_answer_from_the_signer_is_a_breach_even_a_refusal(self):
        # THE bar this round raised. The old prover scored `status != "signed"` as denial,
        # so deleting `allowed_peer_uids` from the signer left it green: the attacker's
        # fabricated frame is refused by input validation either way. The boundary under
        # test is "the signer does not talk to this uid at all".
        out = self._run(_answered({"status": "refused", "reason": "malformed"}))
        self.assertEqual(out.verdict, prover.BREACH)
        self.assertIn("ANSWERED", out.detail)

    def test_a_signature_is_a_breach(self):
        out = self._run(_answered({"status": "signed", "signature_b64": "AAAA"}))
        self.assertEqual(out.verdict, prover.BREACH)

    def test_connect_then_hangup_is_the_only_denial(self):
        out = self._run(_hung_up())
        self.assertEqual(out.verdict, prover.DENIED)
        self.assertIn("SO_PEERCRED", out.detail)
        # A denial must carry the evidence its path was live, or it is indistinguishable
        # from an unreachable target.
        self.assertIn("connect()", out.control)
        self.assertIn("succeeded", out.control)

    def test_a_truncated_reply_is_inconclusive(self):
        # Bytes arrived, so this was not the clean zero-byte hangup of an ACL deny.
        # Deleting the `ex.reply_bytes != 0` term in `_hung_up_without_answering` turns
        # a garbled/partial answer into a "denial".
        out = self._run(prover.Exchange(
            connected=True, reply=None, reply_bytes=3,
            error=brops_protocol.ProtocolError("unexpected EOF: wanted 4 bytes, short by 1"),
        ))
        self.assertEqual(out.verdict, prover.INCONCLUSIVE)
        self.assertIn("bytes received: 3", out.detail)

    def test_a_hung_service_is_inconclusive_not_denied(self):
        out = self._run(prover.Exchange(
            connected=True, reply=None, reply_bytes=0, error=socket.timeout("timed out")
        ))
        self.assertEqual(out.verdict, prover.INCONCLUSIVE)


class CustodyControlTests(unittest.TestCase):
    """The positive control shared by attacks 2 and 3: is there a foreign secret store
    there at all? "I could not read it" and "there was nothing to read" are the same
    observation from the attacker's seat unless something separates them."""

    def test_a_missing_directory_fails_the_control(self):
        outcome, text = prover._control_foreign_dir(
            str(pathlib.Path(tempfile.mkdtemp()) / "not-provisioned"), "key store"
        )
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.verdict, prover.INCONCLUSIVE)
        self.assertIn("not there", outcome.detail)
        self.assertEqual(text, "none")

    def test_a_file_where_a_directory_should_be_fails_the_control(self):
        path = pathlib.Path(tempfile.mkdtemp()) / "f"
        path.write_text("x")
        outcome, _ = prover._control_foreign_dir(str(path), "key store")
        self.assertEqual(outcome.verdict, prover.INCONCLUSIVE)
        self.assertIn("not a directory", outcome.detail)

    @unittest.skipUnless(_POSIX, "POSIX ownership is the custody boundary")
    def test_a_store_owned_by_the_attacker_is_a_breach_not_a_control_failure(self):
        # Custody the attacker owns is a failed containment, not an unprovable one — the
        # attacker can chmod it back at any moment.
        outcome, _ = prover._control_foreign_dir(tempfile.mkdtemp(), "key store")
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.verdict, prover.BREACH)
        self.assertIn("OWNED by the attacking uid", outcome.detail)

    @unittest.skipUnless(_POSIX, "POSIX ownership is the custody boundary")
    def test_a_foreign_directory_passes_and_names_its_owner(self):
        # Every POSIX host has a root-owned directory the test user does not own.
        if os.getuid() == 0:
            self.skipTest("running as root — no directory is foreign to uid 0")
        outcome, text = prover._control_foreign_dir("/root", "key store")
        if outcome is not None:  # /root absent on some images
            self.skipTest("/root is not present on this host")
        self.assertIn("owned by uid 0", text)
        self.assertIn("foreign", text)


class ReadKeyTests(unittest.TestCase):
    """Attack 2 — reading a service principal's private key."""

    def _run(self, path, opener=open):
        return prover.attack_read_file(path, opener=opener, control_fn=_control_passes)

    def test_a_missing_key_is_inconclusive_not_denied(self):
        # THE headline defect: `except FileNotFoundError: return True  # not reachable is
        # also denied`. A mistyped BROPS_PROVE_SIGNER_KEY scored as proof of custody.
        out = self._run(str(pathlib.Path(tempfile.mkdtemp()) / "brops-receipt-signer.json"))
        self.assertEqual(out.verdict, prover.INCONCLUSIVE)
        self.assertIn("Not reachable is NOT denied", out.detail)

    def test_a_readable_key_is_a_breach(self):
        key = pathlib.Path(tempfile.mkdtemp()) / "brops-receipt-signer.json"
        key.write_text('{"key_id": "rk", "private_key": "00"}')
        out = self._run(str(key))
        self.assertEqual(out.verdict, prover.BREACH)
        self.assertIn("READ", out.detail)

    def test_a_missing_key_directory_is_inconclusive_end_to_end(self):
        # The tests above inject a passing control to isolate the classification. This one
        # runs `attack_read_file` exactly as the prover calls it — real control, real
        # filesystem — because that is the path a mistyped BROPS_PROVE_SIGNER_KEY takes,
        # and a mutation that disables the control has to be caught by SOMETHING that uses
        # it. (It was not, until this test: two injected-control tests stayed green with
        # the control removed.)
        missing = pathlib.Path(tempfile.mkdtemp()) / "signerkeys-TYPO"
        out = prover.attack_read_file(str(missing / "brops-receipt-signer.json"))
        self.assertEqual(out.verdict, prover.INCONCLUSIVE)
        self.assertIn("not there", out.detail)

    def test_only_a_permission_error_is_a_denial(self):
        def _denying_opener(path, mode):
            raise PermissionError(errno.EACCES, "Permission denied")

        out = self._run("/svc/keys/brops-receipt-signer.json", opener=_denying_opener)
        self.assertEqual(out.verdict, prover.DENIED)
        self.assertIn("EACCES", out.detail)

    def test_an_unexpected_oserror_is_inconclusive(self):
        # Deleting the narrow `except PermissionError` in favour of `except OSError` (the
        # old shape) makes an I/O error, a stale mount or a symlink loop read as denial.
        def _broken_opener(path, mode):
            raise OSError(errno.EIO, "I/O error")

        out = self._run("/svc/keys/brops-receipt-signer.json", opener=_broken_opener)
        self.assertEqual(out.verdict, prover.INCONCLUSIVE)
        self.assertIn("EIO", out.detail)


class StoreTests(unittest.TestCase):
    """Attack 3 — writing to / listing the protected evidence store."""

    def _run(self, store_dir, writer=prover._probe_write, lister=prover._probe_list):
        return prover.attack_store(
            store_dir, writer=writer, lister=lister, control_fn=_control_passes
        )

    def test_a_missing_store_is_inconclusive_not_denied(self):
        # The old code caught `(PermissionError, FileNotFoundError, OSError)` for BOTH
        # halves and returned `not wrote and not listed`, so a store path that did not
        # exist was a perfect double denial.
        out = self._run(str(pathlib.Path(tempfile.mkdtemp()) / "no-such-store"))
        self.assertEqual(out.verdict, prover.INCONCLUSIVE)
        self.assertIn("the store path is wrong", out.detail)

    def test_a_writable_store_is_a_breach(self):
        out = self._run(tempfile.mkdtemp(), lister=lambda d: (prover.DENIED, "(test) refused"))
        self.assertEqual(out.verdict, prover.BREACH)
        self.assertIn("WROTE", out.detail)

    def test_a_listable_store_is_a_breach(self):
        out = self._run(
            tempfile.mkdtemp(), writer=lambda p: (prover.DENIED, "(test) refused")
        )
        self.assertEqual(out.verdict, prover.BREACH)
        self.assertIn("LISTED", out.detail)

    def test_both_halves_refused_with_eacces_is_the_denial(self):
        out = self._run(
            tempfile.mkdtemp(),
            writer=lambda p: (prover.DENIED, "refused with PermissionError/EACCES"),
            lister=lambda d: (prover.DENIED, "refused with PermissionError/EACCES"),
        )
        self.assertEqual(out.verdict, prover.DENIED)

    def test_an_inconclusive_half_is_never_masked_by_a_denied_half(self):
        out = self._run(
            tempfile.mkdtemp(),
            writer=lambda p: (prover.INCONCLUSIVE, "could not attempt"),
            lister=lambda d: (prover.DENIED, "refused with PermissionError/EACCES"),
        )
        self.assertEqual(out.verdict, prover.INCONCLUSIVE)

    def test_a_breach_half_outranks_an_inconclusive_half(self):
        out = self._run(
            tempfile.mkdtemp(),
            writer=lambda p: (prover.BREACH, "WROTE"),
            lister=lambda d: (prover.INCONCLUSIVE, "could not attempt"),
        )
        self.assertEqual(out.verdict, prover.BREACH)

    def test_a_missing_store_directory_is_inconclusive_end_to_end(self):
        # As above: `attack_store` with its REAL control, the way the prover calls it.
        missing = pathlib.Path(tempfile.mkdtemp()) / "store-TYPO"
        out = prover.attack_store(str(missing))
        self.assertEqual(out.verdict, prover.INCONCLUSIVE)
        self.assertIn("not there", out.detail)

    def test_the_real_probes_call_a_missing_path_inconclusive_not_denied(self):
        # Each probe is judged on its own. Testing only the pair lets one half revert to
        # "missing = denied" while the other half's INCONCLUSIVE keeps the total honest —
        # which is precisely how a delete-test can stay green on a real regression.
        missing = pathlib.Path(tempfile.mkdtemp()) / "gone"
        self.assertEqual(prover._probe_write(missing / "p")[0], prover.INCONCLUSIVE)
        self.assertEqual(prover._probe_list(str(missing))[0], prover.INCONCLUSIVE)

    @unittest.skipUnless(_POSIX, "POSIX modes")
    def test_the_real_probes_report_eacces_against_an_unwritable_store(self):
        if os.getuid() == 0:
            self.skipTest("root ignores file modes")
        d = tempfile.mkdtemp()
        os.chmod(d, 0o000)
        try:
            self.assertEqual(prover._probe_write(pathlib.Path(d) / "p")[0], prover.DENIED)
            self.assertEqual(prover._probe_list(d)[0], prover.DENIED)
        finally:
            os.chmod(d, 0o700)


class SupervisorOracleTests(unittest.TestCase):
    """Attack 4 — the P0-2 shape gate, and only the shape gate, must refuse."""

    def _run(self, *exchanges):
        fake = _exchange_script(*exchanges)
        return prover.attack_supervisor_oracle("/nowhere.sock", exchange=fake), fake

    def test_an_unreachable_supervisor_is_inconclusive(self):
        out, _ = self._run(_never_connected(FileNotFoundError(errno.ENOENT, "no such file")))
        self.assertEqual(out.verdict, prover.INCONCLUSIVE)
        self.assertIn("not there", out.detail)

    def test_a_supervisor_that_will_not_answer_the_honest_frame_is_inconclusive(self):
        out, _ = self._run(_hung_up())
        self.assertEqual(out.verdict, prover.INCONCLUSIVE)
        self.assertIn("well-formed handle", out.detail)

    def test_a_control_that_answers_the_wrong_thing_is_inconclusive(self):
        # If the honest handle is itself refused as `malformed`, the deep path is not in
        # the state attack 4's attribution depends on, so `malformed` on the forged frame
        # would prove nothing.
        out, _ = self._run(_answered({"status": "refused", "reason": "malformed"}))
        self.assertEqual(out.verdict, prover.INCONCLUSIVE)
        self.assertIn("the deep path is not in the state", out.detail)

    def test_signing_caller_supplied_evidence_is_a_breach(self):
        out, _ = self._run(
            _answered({"status": "refused", "reason": prover.REASON_NO_SUCH_RUN}),
            _answered({"status": "signed", "receipt": {}}),
        )
        self.assertEqual(out.verdict, prover.BREACH)
        self.assertIn("SIGNED caller-supplied evidence", out.detail)

    def test_a_refusal_for_the_wrong_reason_is_inconclusive(self):
        # This is the shape-gate-deleted case: without `set(frame) != {...}` the forged
        # frame falls through to the same `run_binding_invalid` the honest control gets.
        # Scoring that as denial is the "any refusal will do" defect `expect_blocked()`
        # exists to prevent.
        out, _ = self._run(
            _answered({"status": "refused", "reason": prover.REASON_NO_SUCH_RUN}),
            _answered({"status": "refused", "reason": prover.REASON_NO_SUCH_RUN}),
        )
        self.assertEqual(out.verdict, prover.INCONCLUSIVE)
        self.assertIn("wrong reason", out.detail)

    def test_a_shape_gate_refusal_is_the_denial(self):
        out, _ = self._run(
            _answered({"status": "refused", "reason": prover.REASON_NO_SUCH_RUN}),
            _answered({"status": "refused", "reason": prover.REASON_SHAPE_GATE}),
        )
        self.assertEqual(out.verdict, prover.DENIED)
        self.assertIn("shape gate", out.detail)
        self.assertIn(prover.REASON_NO_SUCH_RUN, out.control)

    def test_the_attack_reaches_the_shape_gate_and_differs_from_the_control_by_one_member(self):
        # Recorded audit finding R2/P2: the old attack sent the SIGNER's protocol name to
        # the SUPERVISOR, so the protocol-name check refused it and the shape guard — the
        # thing "no evidence oracle" means — was never reached.
        _, fake = self._run(
            _answered({"status": "refused", "reason": prover.REASON_NO_SUCH_RUN}),
            _answered({"status": "refused", "reason": prover.REASON_SHAPE_GATE}),
        )
        honest, forged = fake.sent
        self.assertEqual(honest["protocol"], "brops.evidence-request.v1")
        self.assertEqual(set(honest), {"protocol", "run_id", "execution_attempt_id"})
        self.assertEqual(set(forged) - set(honest), {"evidence"})
        self.assertEqual({k: forged[k] for k in honest}, honest)


class ReportTests(unittest.TestCase):
    """The hard rule: an inconclusive result must never render as proven."""

    def _report(self, checks):
        out, err = io.StringIO(), io.StringIO()
        code = prover.report(checks, stream=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def _row(self, verdict):
        return prover.Outcome(verdict, "detail", "control")

    def test_all_denied_is_the_only_pass(self):
        code, out, _ = self._report({f"a{i}": self._row(prover.DENIED) for i in range(5)})
        self.assertEqual(code, 0)
        self.assertIn("ISOLATION PROOF PASSED", out)

    def test_a_breach_exits_one_and_never_prints_passed(self):
        code, out, err = self._report(
            {"ok": self._row(prover.DENIED), "bad": self._row(prover.BREACH)}
        )
        self.assertEqual(code, 1)
        self.assertNotIn("PASSED", out)
        self.assertIn("at least one attack succeeded: bad", err)

    def test_an_inconclusive_exits_two_and_never_prints_passed(self):
        code, out, err = self._report(
            {"ok": self._row(prover.DENIED), "unknown": self._row(prover.INCONCLUSIVE)}
        )
        self.assertEqual(code, 2)
        self.assertNotIn("PASSED", out)
        self.assertIn("INCONCLUSIVE", err)
        self.assertIn("unknown", err)

    def test_a_breach_outranks_an_inconclusive(self):
        code, _, _ = self._report(
            {"a": self._row(prover.INCONCLUSIVE), "b": self._row(prover.BREACH)}
        )
        self.assertEqual(code, 1)

    def test_every_row_prints_its_positive_control(self):
        # A DENIED row whose control is not stated is indistinguishable from a target the
        # attack never reached — which is the whole failure this round fixes.
        _, out, _ = self._report({"a": prover.Outcome(prover.DENIED, "d", "the path was live")})
        self.assertIn("positive control: the path was live", out)


class MainTests(unittest.TestCase):
    def _main_with(self, env):
        real = dict(os.environ)
        os.environ.clear()
        os.environ.update(env)
        err = io.StringIO()
        real_err, sys.stderr = sys.stderr, err
        try:
            return prover.main([]), err.getvalue()
        finally:
            sys.stderr = real_err
            os.environ.clear()
            os.environ.update(real)

    def test_a_missing_env_var_is_an_operator_error_not_a_denial(self):
        # The old code read BROPS_SIGNER_SOCKET / BROPS_SUPERVISOR_SOCKET *inside* a
        # `try: ... except Exception: return True`, so forgetting to export them scored as
        # two clean denials.
        code, err = self._main_with({"BROPS_PROVE_STORE_DIR": "/tmp/x"})
        self.assertEqual(code, 2)
        self.assertIn("required env not set", err)
        self.assertIn("BROPS_SIGNER_SOCKET", err)

    @unittest.skipIf(_POSIX, "the non-POSIX gate")
    def test_a_non_posix_host_cannot_produce_a_proof(self):
        code, err = self._main_with({name: "x" for name in prover._REQUIRED_ENV})
        self.assertEqual(code, 2)
        self.assertIn("POSIX", err)


class _OneShotServer:
    """A real AF_UNIX server that either hangs up on the peer (the ACL-deny wire
    behaviour) or answers one frame. Used to prove `unix_exchange` reads the real wire the
    way the classifier assumes."""

    def __init__(self, path, reply=None):
        self.path, self.reply = path, reply
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        self.sock.listen(1)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            conn, _ = self.sock.accept()
        except OSError:  # pragma: no cover — closed before a peer arrived
            return
        try:
            if self.reply is not None:
                conn.recv(4096)
                conn.sendall(brops_protocol.encode_frame(self.reply))
        finally:
            conn.close()

    def close(self):
        self.sock.close()
        self.thread.join(timeout=5)


@unittest.skipUnless(_HAS_AF_UNIX, "AF_UNIX is the transport this boundary is built on")
class RealSocketTests(unittest.TestCase):
    """The classifier's socket assumptions, against a real socket rather than a fake."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = str(pathlib.Path(self.dir) / "s.sock")

    def test_a_real_accept_then_close_reads_as_the_acl_denial(self):
        server = _OneShotServer(self.path)
        try:
            out = prover.attack_connect_signer(self.path)
        finally:
            server.close()
        self.assertEqual(out.verdict, prover.DENIED, out.detail)
        self.assertIn("without a byte", out.detail)

    def test_a_real_server_that_answers_reads_as_a_breach(self):
        server = _OneShotServer(self.path, reply={"status": "refused", "reason": "malformed"})
        try:
            out = prover.attack_connect_signer(self.path)
        finally:
            server.close()
        self.assertEqual(out.verdict, prover.BREACH, out.detail)

    def test_a_real_absent_socket_reads_as_inconclusive(self):
        out = prover.attack_connect_signer(str(pathlib.Path(self.dir) / "absent.sock"))
        self.assertEqual(out.verdict, prover.INCONCLUSIVE, out.detail)
        self.assertIn("not there", out.detail)

    def test_the_oracle_control_and_attack_ride_the_real_wire(self):
        # Two connections, two frames: the honest handle then the forged one. A one-shot
        # server per connection mirrors `brops_socket.serve_forever`'s one-frame-per-conn.
        replies = [
            {"protocol": "brops.governed-result.v1", "status": "refused",
             "reason": prover.REASON_NO_SUCH_RUN},
            {"protocol": "brops.governed-result.v1", "status": "refused",
             "reason": prover.REASON_SHAPE_GATE},
        ]
        sent = []

        def _exchange(path, frame, timeout=5.0):
            sent.append(frame)
            server = _OneShotServer(path, reply=replies[len(sent) - 1])
            try:
                return prover.unix_exchange(path, frame, timeout)
            finally:
                server.close()
                os.unlink(path)

        out = prover.attack_supervisor_oracle(self.path, exchange=_exchange)
        self.assertEqual(out.verdict, prover.DENIED, out.detail)
        self.assertEqual(len(sent), 2)
        self.assertNotIn("evidence", sent[0])
        self.assertIn("evidence", sent[1])


if __name__ == "__main__":
    unittest.main()

"""A supervisor-side fault must not be able to happen silently.

`handle_connection` answers an internal fault with `{"ok": false, "error": …}` — the broker's
op shape, carrying no `protocol`. That reply is the ONLY account of the fault, and §4.10(h)
(**NOT IMPLEMENTED**) is the diagnostic carrier that would let a sidecar tell it apart from a
transport failure. The one §4.10(g) client in the tree keeps just the protocol name from it,
so on that path the account is lost entirely.

That is not a hypothetical. The first live run of the §4.10(g) ladder walked every hop, ran a
REAL contained execution to completion, and then raised `SupervisorError` out of the
isolated-signer seam — and left NOTHING behind: this branch printed no traceback, and the
sidecar reported only `the evidence-request reply names protocol None`. Finding the cause cost
a full CI round trip.

Two properties are pinned here, and the SECOND is the one that keeps the first honest:

  1. a `SupervisorError` — this supervisor's own machinery or an injected seam disagreeing
     with itself, i.e. a broken deployment — reaches the operator's stderr;
  2. a PEER-ATTRIBUTABLE fault (`ServerError` from an unknown op, a malformed body) does NOT.
     An authorized-but-hostile peer produces those at will, so printing them would be a
     log-flooding vector, and the reply already says everything there is to say.

Without (2) the fix is "print everything", which is not a fix — it is the same silence one
`grep -v` away.
"""

import contextlib
import io
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import governed_supervisor_server as gss  # noqa: E402
from governed_supervisor import SupervisorConfig  # noqa: E402


class _Conn:
    """The minimal peer the front door needs: a uid, a framed read, a framed write."""

    def __init__(self, body: bytes, peer_uid: int) -> None:
        payload = len(body).to_bytes(gss.LENGTH_PREFIX_BYTES, "big") + body
        self._inbox = io.BytesIO(payload)
        self.peer_uid = peer_uid
        self.written = b""

    def recv_exactly(self, n: int) -> bytes:
        return self._inbox.read(n)

    def send_all(self, data: bytes) -> None:
        self.written += data

    def close(self) -> None:
        return None


BROKER_UID = 5001


def _config() -> SupervisorConfig:
    return SupervisorConfig(
        launcher_executable_sha256="1" * 64,
        executor_executable_sha256="2" * 64,
        id_fn=lambda: "id-1",
        supervisor_id="sup-1",
        executor_id="exec-1",
        builder_id="build-1",
        policy_id="policy-1",
        policy_version="v1",
        policy_bundle_handle="3" * 64,
        challenge_registry_handle="4" * 64,
        challenge_registry_hash="5" * 64,
        challenge_registry_epoch=1,
        challenge_registry_root_key_id="root-1",
    )


def _serve(body: bytes, *, ledger_conn):
    """One connection through the REAL front door, with stderr captured."""
    conn = _Conn(body, BROKER_UID)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        reply = gss.handle_connection(
            conn, BROKER_UID, _config(), lambda _m, _s: True,
            gss.default_recompute_request_sha256, lambda: 1,
            ledger_conn=ledger_conn,
        )
    return reply, err.getvalue()


class TheOperatorSeesSupervisorSideFaultsTests(unittest.TestCase):

    def test_a_deployment_that_disagrees_with_itself_reaches_stderr(self):
        """A supervisor serving with NO durable ledger is the smallest honest member of the
        class: nothing a peer sent caused it, no peer can fix it, and it is invisible in the
        reply. It is the same class the live signer-transport fault belonged to — an injected
        seam this supervisor provisioned, behaving as no peer asked it to."""
        reply, stderr = _serve(b'{"op": "launch-gate", "execution_attempt_id": "a"}',
                               ledger_conn=None)
        self.assertIs(reply["ok"], False)
        self.assertIsNone(reply.get("protocol"),
                          "the fault reply carries no protocol — that is why it must be logged")
        self.assertIn("SupervisorError", stderr)
        self.assertIn("Traceback", stderr)

    def test_a_hostile_peer_cannot_flood_the_operator_log(self):
        """An unknown op is PEER-attributable: it is `ServerError`, the reply already names
        it, and an authorized-but-hostile peer can send one per connection forever."""
        reply, stderr = _serve(b'{"op": "delete-everything"}', ledger_conn=object())
        self.assertIs(reply["ok"], False)
        self.assertIn("unknown op", reply["error"])
        self.assertEqual(stderr, "",
                         "a peer-attributable refusal must not be written to the operator log")

    def test_a_malformed_frame_is_also_silent(self):
        reply, stderr = _serve(b"not json at all", ledger_conn=object())
        self.assertIs(reply["ok"], False)
        self.assertEqual(stderr, "")

    def test_the_fault_reply_still_reaches_the_peer(self):
        """Logging is ADDED, never substituted: the peer's reply is unchanged, because a
        supervisor that answered a fault with silence would hang every client."""
        conn = _Conn(b'{"op": "launch-gate", "execution_attempt_id": "a"}', BROKER_UID)
        with contextlib.redirect_stderr(io.StringIO()):
            gss.handle_connection(
                conn, BROKER_UID, _config(), lambda _m, _s: True,
                gss.default_recompute_request_sha256, lambda: 1,
                ledger_conn=None)
        self.assertTrue(conn.written, "the peer must still receive a framed reply")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

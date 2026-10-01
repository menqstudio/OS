"""Wave 3b-1 — signer + supervisor services over the ACL'd Unix-socket transport
(design §1.1; audit P0-1).

Cross-platform where AF_UNIX exists: the framed round-trip and the supervisor's
"only {run_id, attempt_id}" rejection. Linux-only (SO_PEERCRED): the peer-UID allow-list
denial. The full four same-login-user denials are machine-proven by the Linux CI job
`signer-isolation` (dedicated service users; it runs `engine/ci/isolation_proof.sh`) — see
`.github/workflows/ci.yml`.
"""

import json
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
sys.path.insert(0, str(ROOT / "tests"))  # _brops_fixtures

import brops_protocol
import brops_receipt_signer as signer
import brops_signer_service
import brops_socket
from brops_evidence_store import EvidenceStore
from brops_supervisor_attest import produce_sign_request
from brops_supervisor_service import SupervisorService

from _brops_fixtures import keypair as _keypair
from _brops_fixtures import run_state as _run_state
from _brops_fixtures import signer_env

_HAS_UNIX = hasattr(socket, "AF_UNIX")
_HAS_PEERCRED = hasattr(socket, "SO_PEERCRED") and os.name == "posix"


@unittest.skipUnless(_HAS_UNIX, "AF_UNIX unavailable on this platform")
class SignerServiceTests(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())
        keydir = self.d / "keys"
        keydir.mkdir()
        if os.name == "posix":
            os.chmod(keydir, 0o700)  # the signer refuses a group/other-accessible key dir
        sig_priv, _ = _keypair()
        self.att_priv, self.att_pub = _keypair()
        (keydir / signer.RECEIPT_SIGNER_KEY_FILENAME).write_text(
            json.dumps({"key_id": "rk", "private_key": sig_priv})
        )
        store_dir = self.d / "store"
        self.store = EvidenceStore(str(store_dir))
        self.sock = str(self.d / "sock" / "signer.sock")
        self.env = signer_env(store_dir=store_dir, keydir=keydir, attestation_pubkey=self.att_pub)
        self.env["BROPS_SIGNER_SOCKET"] = self.sock

    def _request(self):
        return produce_sign_request(
            "run-1", "attempt-1",
            run_state_provider=type("P", (), {"terminal_run_state": lambda s, r, a: _run_state()})(),
            store=self.store, attestation_key={"key_id": "sup-att-1", "private_key": self.att_priv},
        )

    def _serve_once(self, env):
        ready = threading.Event()
        t = threading.Thread(
            target=lambda: brops_signer_service.run(env, max_requests=1, ready=ready.set), daemon=True
        )
        t.start()
        self.assertTrue(ready.wait(5), "service did not bind")
        return t

    def test_signer_service_signs_a_framed_request(self):
        env = dict(self.env)
        env["BROPS_ALLOWED_PEER_UIDS"] = str(os.getuid()) if hasattr(os, "getuid") else ""
        self._serve_once(env)
        result = brops_socket.request(self.sock, self._request())
        self.assertEqual(result["status"], "signed")
        self.assertTrue(result["envelope_jcs_b64"] and result["signature_b64"])

    @unittest.skipUnless(_HAS_PEERCRED, "SO_PEERCRED unavailable — peer-UID ACL proven in Linux CI")
    def test_signer_service_denies_a_disallowed_peer_uid(self):
        env = dict(self.env)
        env["BROPS_ALLOWED_PEER_UIDS"] = "999999"  # not our uid
        self._serve_once(env)
        # A denied peer is dropped without a response: the client sees EOF (ProtocolError)
        # or a broken pipe / reset depending on timing — those mean DENIED. A bare `OSError`
        # is NOT accepted: a timeout or a refused connection is one too, and a service that
        # hung or never bound has denied nothing (`brops_isolation_prover` calls that case
        # INCONCLUSIVE for the same reason).
        with self.assertRaises((brops_protocol.ProtocolError, ConnectionResetError,
                                BrokenPipeError)) as caught:
            brops_socket.request(self.sock, self._request(), timeout=5)
        self.assertNotIsInstance(caught.exception, TimeoutError)


class SupervisorServiceRejectionTests(unittest.TestCase):
    """The input-gate is pure logic (no socket) — runs everywhere."""

    def test_supervisor_accepts_only_a_run_handle_never_evidence(self):
        d = pathlib.Path(tempfile.mkdtemp())
        # A minimally-constructed service is enough to exercise the input gate: the
        # malformed check runs before any state is touched.
        svc = SupervisorService.__new__(SupervisorService)
        # An evidence-bearing frame (the forbidden oracle shape) is refused.
        bad = {"protocol": "brops.sign-request.v1", "evidence": {"forged": True}}
        self.assertEqual(svc.handle(bad)["reason"], "malformed")
        # An evidence-request with extra fields is refused.
        extra = {"protocol": "brops.evidence-request.v1", "run_id": "r",
                 "execution_attempt_id": "a", "evidence": {}}
        self.assertEqual(svc.handle(extra)["reason"], "malformed")

    def test_supervisor_refuses_a_run_handle_that_could_name_another_path(self):
        # The handle becomes a file name under the protected run-state directory. The
        # gate checked only that both parts were strings, so "../outside/evil" and an
        # absolute path went on to the provider. Refused here, before any state is
        # touched — the bare service below has none to touch.
        svc = SupervisorService.__new__(SupervisorService)
        for run_id, attempt in (("../outside/evil", "a"), ("/etc/passwd", "a"), ("r", "../a"),
                                ("r\\x", "a"), ("", "a"), (".", "a"), ("r", "a\n")):
            frame = {"protocol": "brops.evidence-request.v1", "run_id": run_id,
                     "execution_attempt_id": attempt}
            self.assertEqual(svc.handle(frame)["reason"], "malformed", frame)

    def test_the_contract_schema_carries_the_same_handle_pattern(self):
        import json
        import brops_protocol
        from brops_live_runstate import HANDLE_COMPONENT
        schema = json.loads((ROOT / "contracts" / "brops-evidence-request.v1.schema.json")
                            .read_text(encoding="utf-8"))
        for field in ("run_id", "execution_attempt_id"):
            self.assertEqual(schema["properties"][field]["pattern"],
                             "^" + HANDLE_COMPONENT.pattern + "$")
        good = {"protocol": "brops.evidence-request.v1", "run_id": "run-1",
                "execution_attempt_id": "attempt-1"}
        brops_protocol.validate(good, schema)
        with self.assertRaises(brops_protocol.ProtocolError):
            brops_protocol.validate(dict(good, run_id="../outside/evil"), schema)


if __name__ == "__main__":
    unittest.main()

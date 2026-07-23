"""Wave 3b-1 — signer + supervisor services over the ACL'd Unix-socket transport
(design §1.1; audit P0-1).

Cross-platform where AF_UNIX exists: the framed round-trip and the supervisor's
"only {run_id, attempt_id}" rejection. Linux-only (SO_PEERCRED): the peer-UID allow-list
denial. The full four same-login-user denials are machine-proven by the Linux CI job
`engine-isolation` (dedicated service users) — see `.github/workflows/ci.yml`.
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

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import brops_canonical as bc
import brops_protocol
import brops_receipt_signer as signer
import brops_signer_service
import brops_socket
from brops_evidence_store import EvidenceStore
from brops_supervisor_attest import RunState, produce_sign_request
from brops_supervisor_service import SupervisorService

_HAS_UNIX = hasattr(socket, "AF_UNIX")
_HAS_PEERCRED = hasattr(socket, "SO_PEERCRED") and os.name == "posix"


def _keypair():
    p = Ed25519PrivateKey.generate()
    return (
        p.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()).hex(),
        p.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex(),
    )


def _run_state():
    return RunState(
        run_id="run-1", execution_attempt_id="attempt-1", lease_id="lease-1",
        request_nonce="00000000-0000-4000-8000-000000000000",
        receipt_id="11111111-1111-4111-8111-111111111111", decision="completed",
        workspace_id="ws-1", install_id="install-1", supervisor_id="sup-1",
        executor_id="exec-1", builder_id="builder-1", policy_id="policy-1", policy_version="1",
        requested_at="1000", completed_at="2000", system="s",
        history=[{"role": "user", "content": "hi"}], output="out", generation_config="{}",
        containment_evidence={"contained": True}, policy_bundle=b"pb",
    )


@unittest.skipUnless(_HAS_UNIX, "AF_UNIX unavailable on this platform")
class SignerServiceTests(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())
        keydir = self.d / "keys"
        keydir.mkdir()
        sig_priv, _ = _keypair()
        self.att_priv, self.att_pub = _keypair()
        (keydir / signer.RECEIPT_SIGNER_KEY_FILENAME).write_text(
            json.dumps({"key_id": "rk", "private_key": sig_priv})
        )
        store_dir = self.d / "store"
        self.store = EvidenceStore(str(store_dir))
        self.sock = str(self.d / "sock" / "signer.sock")
        self.env = {
            "BROPS_EVIDENCE_STORE_DIR": str(store_dir),
            "BROPS_RECEIPT_SIGNER_KEYDIR": str(keydir),
            "BROPS_SUPERVISOR_ATTESTATION_PUBKEY": self.att_pub,
            "BROPS_SUPERVISOR_ATTESTATION_KEY_ID": "sup-att-1",
            "BROPS_ALLOWED_EXECUTOR_IDS": "exec-1",
            "BROPS_ALLOWED_BUILDER_IDS": "builder-1",
            "BROPS_ALLOWED_SUPERVISOR_IDS": "sup-1",
            "BROPS_EXPECTED_POLICY_ID": "policy-1",
            "BROPS_EXPECTED_POLICY_VERSION": "1",
            "BROPS_EXPECTED_POLICY_BUNDLE_SHA256": bc.policy_bundle_sha256(b"pb"),
            "BROPS_SIGNER_SOCKET": self.sock,
        }

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
        # or a broken pipe / reset (OSError) depending on timing — both mean DENIED.
        with self.assertRaises((brops_protocol.ProtocolError, OSError)):
            brops_socket.request(self.sock, self._request(), timeout=5)


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


if __name__ == "__main__":
    unittest.main()

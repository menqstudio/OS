"""Wave 3b-1 — same-login-user isolation + custody (design §1.1-1.2, §5 P1-4).

The four acceptance conditions: a process running as the sidecar/desktop login user
cannot (1) connect to the signer channel, (2) read the signer/attestation keys, (3)
read/write the protected store, (4) get the supervisor to sign caller-supplied evidence.

The OS-principal / ACL enforcement of (1)-(3) is Linux-first (dedicated service SID/UID +
socket/pipe + key/dir ACLs, design §1.1) and is exercised on Linux in CI; here we prove
the portable custody discipline (dirs refuse group/other access) and the no-oracle
behavior, and skip-guard the parts that need a real dedicated principal on this host.
"""

import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import brops_receipt_signer as signer
import brops_supervisor_attest as attest_mod
from brops_evidence_store import EvidenceStore, EvidenceStoreError
from brops_supervisor_attest import RunState, produce_sign_request

_POSIX = os.name == "posix"


def _keypair():
    priv = Ed25519PrivateKey.generate()
    raw_priv = priv.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    ).hex()
    raw_pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()
    return raw_priv, raw_pub


def _run_state():
    return RunState(
        run_id="run-1", execution_attempt_id="attempt-1", lease_id="lease-1",
        request_nonce="00000000-0000-4000-8000-000000000000",
        receipt_id="11111111-1111-4111-8111-111111111111", decision="completed",
        workspace_id="ws-1", install_id="install-1", supervisor_id="sup-1",
        executor_id="exec-1", builder_id="builder-1", policy_id="policy-1", policy_version="1",
        requested_at="1000", completed_at="2000",
        system="s", history=[{"role": "user", "content": "hi"}], output="out",
        generation_config="{}", containment_evidence={"contained": True}, policy_bundle=b"pb",
    )


class CustodyTests(unittest.TestCase):
    """(2)/(3): the store + key dirs refuse group/other access (POSIX)."""

    @unittest.skipUnless(_POSIX, "POSIX file-mode custody; ACLs enforce this on Windows")
    def test_store_refuses_group_or_other_accessible_dir(self):
        d = tempfile.mkdtemp()
        os.chmod(d, 0o777)
        with self.assertRaises(EvidenceStoreError):
            EvidenceStore(d)

    @unittest.skipUnless(_POSIX, "POSIX file-mode custody")
    def test_receipt_signer_keydir_refuses_group_or_other_access(self):
        d = tempfile.mkdtemp()
        os.chmod(d, 0o750)
        (pathlib.Path(d) / signer.RECEIPT_SIGNER_KEY_FILENAME).write_text(
            json.dumps({"key_id": "k", "private_key": "00" * 32})
        )
        with self.assertRaises(ValueError):
            signer.load_receipt_signing_key(d)

    @unittest.skipUnless(_POSIX, "POSIX file-mode custody")
    def test_attestation_keydir_refuses_group_or_other_access(self):
        d = tempfile.mkdtemp()
        os.chmod(d, 0o705)
        (pathlib.Path(d) / attest_mod.SUPERVISOR_ATTESTATION_KEY_FILENAME).write_text(
            json.dumps({"key_id": "k", "private_key": "00" * 32})
        )
        with self.assertRaises(ValueError):
            attest_mod.load_attestation_key(d)

    def test_store_created_owner_only_on_posix(self):
        store = EvidenceStore(tempfile.mkdtemp() + "/sub")
        if _POSIX:
            mode = stat.S_IMODE(os.stat(store.root).st_mode)
            self.assertEqual(mode, 0o700)


class NoOracleTests(unittest.TestCase):
    """(4): the supervisor signs only from {run_id, attempt_id}; no attest(caller bytes)."""

    def test_supervisor_entry_takes_only_run_handles_not_evidence(self):
        # produce_sign_request's signature accepts a run handle, never an evidence object.
        import inspect

        params = list(inspect.signature(produce_sign_request).parameters)
        self.assertEqual(params[:2], ["run_id", "execution_attempt_id"])
        self.assertNotIn("evidence", params)

    def test_supervisor_refuses_unknown_run(self):
        class _Empty:
            def terminal_run_state(self, *_):
                return None

        att_priv, _ = _keypair()
        with self.assertRaises(attest_mod.AttestationError):
            produce_sign_request(
                "ghost", "attempt-x",
                run_state_provider=_Empty(),
                store=EvidenceStore(tempfile.mkdtemp()),
                attestation_key={"key_id": "k", "private_key": att_priv},
            )

    def test_signer_refuses_evidence_not_signed_by_pinned_supervisor(self):
        # An attacker who fabricates evidence but cannot produce the pinned supervisor's
        # signature is refused — recompute-consistency is not authenticity (design §1.3).
        att_priv, att_pub = _keypair()
        forged_priv, _ = _keypair()  # attacker key, NOT the pinned one
        sig_priv, _ = _keypair()
        store = EvidenceStore(tempfile.mkdtemp())
        state = _run_state()
        # Build a valid request, then re-sign the evidence with the attacker key.
        request = produce_sign_request(
            state.run_id, state.execution_attempt_id,
            run_state_provider=type("P", (), {"terminal_run_state": lambda self, r, a: state})(),
            store=store, attestation_key={"key_id": "sup-1", "private_key": forged_priv},
        )
        result = signer.sign(
            request, store=store, signing_key={"key_id": "rk", "private_key": sig_priv},
            supervisor_attestation_pubkey_hex=att_pub, supervisor_key_id="sup-1",
        )
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "attestation_invalid")


class SignerProcessBoundaryTests(unittest.TestCase):
    """(1): the signer runs as its OWN process reading a request in / result out. The
    dedicated-principal socket/pipe ACL is Linux deployment (skip-guarded below)."""

    def _provision(self):
        d = tempfile.mkdtemp()
        store_dir = pathlib.Path(d) / "store"
        keydir = pathlib.Path(d) / "keys"
        keydir.mkdir()
        sig_priv, _ = _keypair()
        att_priv, att_pub = _keypair()
        (keydir / signer.RECEIPT_SIGNER_KEY_FILENAME).write_text(
            json.dumps({"key_id": "receipt-key-1", "private_key": sig_priv})
        )
        store = EvidenceStore(str(store_dir))
        state = _run_state()
        request = produce_sign_request(
            state.run_id, state.execution_attempt_id,
            run_state_provider=type("P", (), {"terminal_run_state": lambda self, r, a: state})(),
            store=store, attestation_key={"key_id": "sup-att-1", "private_key": att_priv},
        )
        env = dict(os.environ)
        env["BROPS_EVIDENCE_STORE_DIR"] = str(store_dir)
        env["BROPS_RECEIPT_SIGNER_KEYDIR"] = str(keydir)
        env["BROPS_SUPERVISOR_ATTESTATION_PUBKEY"] = att_pub
        env["BROPS_SUPERVISOR_ATTESTATION_KEY_ID"] = "sup-att-1"
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "runtime"), str(ROOT / "tools")])
        return request, env

    def test_signer_subprocess_signs_a_request_over_stdin(self):
        request, env = self._provision()
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "brops_receipt_signer.py")],
            input=json.dumps(request), capture_output=True, text=True, env=env, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["status"], "signed")
        self.assertTrue(result["envelope_jcs_b64"] and result["signature_b64"])

    def test_signer_subprocess_refuses_garbage_over_stdin(self):
        _, env = self._provision()
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "brops_receipt_signer.py")],
            input="not json", capture_output=True, text=True, env=env, timeout=30,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["status"], "refused")

    @unittest.skip(
        "Dedicated-OS-principal socket/pipe ACL denying the same-login-user peer is "
        "Linux-first deployment (design §1.1); exercised on Linux in CI, not on this host."
    )
    def test_same_user_cannot_connect_to_signer_channel(self):  # pragma: no cover
        raise AssertionError("placeholder — see CI Linux isolation job")


if __name__ == "__main__":
    unittest.main()

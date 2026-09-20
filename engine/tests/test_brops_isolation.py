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
import re
import stat
import subprocess
import sys
import tempfile
import unittest
import socket
import struct
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import io

import brops_canonical as bc
import brops_protocol
import brops_receipt_signer as signer
import brops_supervisor_attest as attest_mod
from brops_evidence_store import EvidenceStore, EvidenceStoreError
from brops_supervisor_attest import RunState, produce_sign_request

_POSIX = os.name == "posix"

# The signer's authorization policy matching the `_run_state()` fixture (policy_bundle=b"pb").
_POLICY_BUNDLE = b"pb"


def _policy():
    return signer.SignerAuthorizationPolicy(
        allowed_executor_ids=frozenset({"exec-1"}),
        allowed_builder_ids=frozenset({"builder-1"}),
        allowed_supervisor_ids=frozenset({"sup-1"}),
        expected_policy_id="policy-1",
        expected_policy_version="1",
        expected_policy_bundle_sha256=bc.policy_bundle_sha256(_POLICY_BUNDLE),
    )


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

    # The reason used to read "ACLs enforce this on Windows". Nothing did: `_harden_dir`
    # kept the whole rule inside `if os.name == "posix"`, so the skip was asserting a
    # protection that did not exist. The Windows half is now implemented and covered by
    # `test_evidence_store_shared_artifacts.StoreCustodyTests`, which runs the same claim
    # on both platforms; this case stays POSIX-only because the MECHANISM here is a mode.
    @unittest.skipUnless(_POSIX, "POSIX file-mode custody; the Windows ACL equivalent is "
                                 "covered by StoreCustodyTests in "
                                 "test_evidence_store_shared_artifacts")
    def test_store_refuses_a_world_accessible_dir(self):
        d = tempfile.mkdtemp()
        os.chmod(d, 0o777)  # world-accessible
        with self.assertRaises(EvidenceStoreError):
            EvidenceStore(d)

    @unittest.skipUnless(_POSIX, "POSIX file-mode custody")
    def test_store_allows_a_group_shared_but_not_world_dir(self):
        # The store is legitimately shared by the two dedicated principals via a group
        # (supervisor writes, signer reads) — group access is allowed, world is not.
        d = tempfile.mkdtemp()
        os.chmod(d, 0o770)  # owner + group, no other
        EvidenceStore(d)  # must NOT raise

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
        # The Windows counterpart (a PROTECTED owner/SYSTEM/Administrators DACL, asserted by
        # reading the descriptor back) is `StoreCustodyTests.test_a_created_store_is_private_
        # to_its_owner`. It is not repeated here; what matters is that it exists at all —
        # this `if` used to be the whole story, and off POSIX the test asserted nothing.


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
            policy=_policy(), now_ms=10_000,
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
        if _POSIX:
            os.chmod(keydir, 0o700)  # the signer refuses a group/other-accessible key dir
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
        # The signer's own authorization policy (P1-7).
        env["BROPS_ALLOWED_EXECUTOR_IDS"] = "exec-1"
        env["BROPS_ALLOWED_BUILDER_IDS"] = "builder-1"
        env["BROPS_ALLOWED_SUPERVISOR_IDS"] = "sup-1"
        env["BROPS_EXPECTED_POLICY_ID"] = "policy-1"
        env["BROPS_EXPECTED_POLICY_VERSION"] = "1"
        env["BROPS_EXPECTED_POLICY_BUNDLE_SHA256"] = bc.policy_bundle_sha256(_POLICY_BUNDLE)
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "runtime"), str(ROOT / "tools")])
        return request, env

    def _run_signer(self, env, stdin_bytes: bytes):
        return subprocess.run(
            [sys.executable, str(ROOT / "tools" / "brops_receipt_signer.py")],
            input=stdin_bytes, capture_output=True, env=env, timeout=30,
        )

    def test_signer_subprocess_signs_a_framed_request(self):
        request, env = self._provision()
        proc = self._run_signer(env, brops_protocol.encode_frame(request))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = brops_protocol.read_frame(io.BytesIO(proc.stdout))
        self.assertEqual(result["status"], "signed")
        self.assertTrue(result["envelope_jcs_b64"] and result["signature_b64"])

    def test_signer_subprocess_refuses_an_unframed_garbage_stream(self):
        _, env = self._provision()
        proc = self._run_signer(env, b"not a valid frame")
        self.assertEqual(proc.returncode, 0)
        result = brops_protocol.read_frame(io.BytesIO(proc.stdout))
        self.assertEqual(result["status"], "refused")

    @unittest.skip(
        "Dedicated-OS-principal socket/pipe ACL denying the same-login-user peer is "
        "Linux-first deployment (design §1.1); exercised on Linux in CI, not on this host."
    )
    def test_same_user_cannot_connect_to_signer_channel(self):  # pragma: no cover
        raise AssertionError("placeholder — see CI Linux isolation job")



class UcredFormatTests(unittest.TestCase):
    """`struct ucred` is read in five places; one of them read it signed.

    `uid_t` is UNSIGNED 32-bit on Linux. `brops_socket._peer_uid` unpacked `"3i"` — three SIGNED ints —
    until 2026-09-20, which agrees with `=III` for every uid below 2^31 and differs above it: the
    kernel's `(uid_t)-1` "no uid" arrived as `-1`, and `(uid_t)-2` (`nobody` on some systems) as `-2`.

    That was fail-closed, because the gate is `uid not in allowed_peer_uids` and an allow-list built from
    `os.getuid()` holds no negative numbers — so a negative could only deny. What it broke was the number
    a refusal reports, and the agreement between five readers of one structure.
    """

    class _StubConn:
        """A socket that answers one `getsockopt` with the bytes the kernel would have written."""

        def __init__(self, pid: int, uid: int, gid: int) -> None:
            self.payload = struct.pack("=III", pid, uid, gid)
            self.asked = []

        def getsockopt(self, level, option, length):
            self.asked.append((level, option, length))
            return self.payload[:length]

    def test_the_reader_reports_the_uid_the_kernel_wrote(self):
        import brops_socket

        # 4294967294 is `(uid_t)-2`; the old `3i` read returned -2 for it. 4294967295 is the kernel's
        # "no uid". Both are above 2^31, which is exactly where the two formats part company.
        for uid in (0, 1000, 65534, 2**31, 2**32 - 2, 2**32 - 1):
            with self.subTest(uid=uid):
                conn = self._StubConn(4242, uid, uid)
                with unittest.mock.patch.object(socket, "SO_PEERCRED", 17, create=True):
                    got = brops_socket._peer_uid(conn)
                self.assertEqual(got, uid, f"the reader did not report the kernel's uid {uid}")
                self.assertGreaterEqual(got, 0, "a uid can never be negative")
        # It asked for exactly the struct's size, not a guess.
        conn = self._StubConn(1, 2, 3)
        with unittest.mock.patch.object(socket, "SO_PEERCRED", 17, create=True):
            brops_socket._peer_uid(conn)
        self.assertEqual(conn.asked[0][2], struct.calcsize("=III"))

    def test_a_platform_without_so_peercred_answers_none_rather_than_guessing(self):
        """The control case: without the option there is no peer uid to report, and `None` is what the
        caller turns into a refusal. A reader that invented a number here would be worse than one that
        read it signed."""
        import brops_socket

        conn = self._StubConn(1, 2, 3)
        # `create=True` because on a host without the option the attribute does not exist at all —
        # which is the very condition under test, and `patch.object` refuses to patch an absent name
        # otherwise. `_peer_uid` reads it with `getattr(socket, "SO_PEERCRED", None)`, so absent and
        # None are the same answer to it.
        with unittest.mock.patch.object(socket, "SO_PEERCRED", None, create=True):
            self.assertIsNone(brops_socket._peer_uid(conn))
        self.assertEqual(conn.asked, [], "it asked the kernel despite having no option to ask with")

    def test_every_so_peercred_read_in_the_tree_uses_the_same_format(self):
        """Five readers of one kernel structure is already one place too many; while they exist, they
        have to agree. A sixth that drifts fails here.

        MEASURED BY SHAPE, NOT BY DISTANCE. A first version looked for `struct.unpack` within three
        lines of the word `SO_PEERCRED`; in the four servers those sit together, but in
        `brops_socket.py` the option is read into a local thirteen lines above the unpack, so the sweep
        skipped the very file this test was written for and passed for the wrong reason — the `"3i"`
        mutant did not kill it. Now every file that mentions `SO_PEERCRED` at all has EVERY
        three-integer struct format in it checked, whatever line it is on.

        Unifying the five into one helper touches three security-critical AF_UNIX servers and belongs in
        its own change, so until then the agreement is CHECKED rather than hoped for.
        """
        root = pathlib.Path(__file__).resolve().parents[1]
        ucred_shape = re.compile(r'(?:struct\.unpack|struct\.calcsize)\(\s*"([^"]+)"')
        # A three-integer native read of `struct ucred` is spelled one of these; `=III` is the only one
        # that is also correct, because `uid_t` is unsigned.
        three_ints = {"3i", "3I", "iii", "III", "=3i", "=3I", "=iii", "=III", "@3i", "@III"}
        offenders, readers, files = [], 0, 0
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            body = path.read_text(encoding="utf-8", errors="replace")
            if "SO_PEERCRED" not in body:
                continue
            files += 1
            for n, line in enumerate(body.splitlines(), 1):
                for fmt in ucred_shape.findall(line):
                    if fmt not in three_ints:
                        continue
                    readers += 1
                    if fmt != "=III":
                        offenders.append(
                            f"{path.relative_to(root).as_posix()}:{n} reads struct ucred as {fmt!r}")
        self.assertGreaterEqual(files, 4, "the sweep found almost no files naming SO_PEERCRED")
        self.assertGreaterEqual(readers, 5, f"the sweep found only {readers} ucred format(s); it is not looking")
        self.assertEqual(offenders, [], f"struct ucred is read inconsistently: {offenders}")

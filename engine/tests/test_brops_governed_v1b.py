from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import socket
import threading
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = pathlib.Path(__file__).resolve().parents[1]
for sub in ("runtime", "tools"):
    sys.path.insert(0, str(ROOT / sub))
# governed_v1b is the sidecar routing module; it lives in the sibling bridge/ tree.
# Insert it explicitly so `cd engine && python -m unittest discover` (the CI command)
# can import it regardless of CWD.
sys.path.insert(0, str(ROOT.parent / "bridge"))

import brops_socket
from bro_signature import canonical_bytes
from brops_challenge_authority import AuthorityConfig, ChallengeAuthority
from brops_evidence_store import NamespacedEvidenceStore as EvidenceStore
from brops_governed_common import (
    DEFAULT_GENERATION_CONFIG, OUTPUT_STREAM_RETENTION_MS, OUTPUT_STREAM_TTL_MS,
    PINNED_GENERATION_CONFIG_SHA256, STAGING_CHUNK_BYTES,
    b64url_encode, governed_generation_config_bytes, history_bytes, sha256_hex, system_bytes,
)
from brops_governed_recorder import RecorderComponents, record_governed_turn
from brops_governed_signer import GovernedSignerComponents, sign_governed
from brops_governed_supervisor import ChallengeRegistry, GovernedSupervisor, SupervisorConfig
from governed_v1b import submit as sidecar_submit, output_read as sidecar_output_read


def keypair(key_id: str):
    priv = Ed25519PrivateKey.generate()
    raw_priv = priv.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    ).hex()
    raw_pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    return {"key_id": key_id, "private_key": raw_priv}, raw_pub


@unittest.skipUnless(hasattr(socket, "AF_UNIX"), "governed IPC requires AF_UNIX (linux CI)")
class GovernedV1BTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.now = 1_800_000_000_000
        self.challenge_key, challenge_pub = keypair("challenge-k1")
        self.root_key, root_pub = keypair("challenge-root")
        self.attestation_key, attestation_pub = keypair("supervisor-attest")
        self.lease_key, lease_pub = keypair("lease-k1")
        self.evidence_recorder_key, evidence_recorder_pub = keypair("evidence-recorder-k1")
        self.governed_turn_recorder_key, governed_turn_recorder_pub = keypair("governed-turn-recorder-k1")
        self.signer_key, signer_pub = keypair("receipt-k1")
        self.signer_pub = signer_pub
        registry_payload = {
            "artifact_type": "brops.challenge-key-registry.v1",
            "root_key_id": "challenge-root", "registry_epoch": 7,
            "registry_issued_at_ms": self.now - 10_000,
            "keys": [{
                "challenge_key_id": "challenge-k1", "public_key": b64url_encode(challenge_pub),
                "valid_from_ms": self.now - 100_000, "valid_to_ms": self.now + 100_000,
                "key_epoch": 1, "revoked": False, "revoked_at_ms": None,
            }],
        }
        root_priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(self.root_key["private_key"]))
        registry_doc = {"payload": registry_payload, "root_sig": b64url_encode(root_priv.sign(canonical_bytes(registry_payload)))}
        registry_path = self.root / "registry.json"
        registry_path.write_bytes(canonical_bytes(registry_doc))
        self.registry = ChallengeRegistry.load(registry_path, {"challenge-root": root_pub.hex()})
        self.store = EvidenceStore(self.root / "store")
        self.record_dir = self.root / "records"

        executor = self.root / "executor.py"
        executor.write_text(
            "import json,os\n"
            "system=os.read(3,1<<20)\n"
            "history=os.read(4,9<<20)\n"
            "config=os.read(5,1<<20)\n"
            "assert json.loads(config.decode())['model']=='claude-sonnet-5'\n"
            "os.write(1,b'GOVERNED OK: '+history)\n",
            encoding="utf-8",
        )
        config = SupervisorConfig(
            workspace_id="ws", install_id="install", supervisor_id="sup",
            executor_id="exec", runner_id="runner", agent_id="Bro", session_id="session",
            policy_id="policy", policy_version="1", policy_bundle=b"policy bundle",
            launcher_executable_sha256="a" * 64,
            executor_command=(sys.executable, str(executor)),
            generation_config_allowlist=frozenset({PINNED_GENERATION_CONFIG_SHA256}),
            record_dir=self.record_dir,
        )
        self.socket = str(self.root / "signer.sock")
        self.components = GovernedSignerComponents(
            store=self.store, receipt_signing_key=self.signer_key,
            supervisor_attestation_pubkey_hex=attestation_pub.hex(),
            supervisor_attestation_key_id="supervisor-attest",
            lease_issuer_pubkey_hex=lease_pub.hex(), lease_issuer_key_id="lease-k1",
            evidence_recorder_pubkey_hex=evidence_recorder_pub.hex(), evidence_recorder_key_id="evidence-recorder-k1",
            governed_turn_recorder_pubkey_hex=governed_turn_recorder_pub.hex(), governed_turn_recorder_key_id="governed-turn-recorder-k1",
            challenge_root_pubkeys_hex={"challenge-root": root_pub.hex()},
            record_dir=self.record_dir,
            allowed_executor_ids=frozenset({"exec"}), allowed_runner_ids=frozenset({"runner"}),
            allowed_supervisor_ids=frozenset({"sup"}), expected_policy_id="policy",
            expected_policy_version="1", head_floor_db=self.root / "head_floor.db",
        )
        ready = threading.Event()
        self.signer_thread = threading.Thread(
            target=brops_socket.serve_forever,
            args=(self.socket, self._sign_handler),
            kwargs={"allowed_peer_uids": None, "max_requests": 1, "ready": ready.set},
            daemon=True,
        )
        self.signer_thread.start(); self.assertTrue(ready.wait(2))
        # §2.3/§8: the separate evidence-recorder RUNNER (holds the evidence-recorder key, writes rec/).
        self.recorder_socket = str(self.root / "recorder.sock")
        rec_components = RecorderComponents(
            rec_store=self.store.rec, evidence_recorder_key=self.evidence_recorder_key)
        rec_ready = threading.Event()
        self.recorder_thread = threading.Thread(
            target=brops_socket.serve_forever,
            args=(self.recorder_socket, lambda frame: record_governed_turn(frame, rec_components)),
            kwargs={"allowed_peer_uids": None, "max_requests": None, "ready": rec_ready.set},
            daemon=True,
        )
        self.recorder_thread.start(); self.assertTrue(rec_ready.wait(2))
        self.supervisor = GovernedSupervisor(
            db_path=self.root / "supervisor.db", store=self.store, registry=self.registry,
            signer_socket=self.socket, recorder_socket=self.recorder_socket,
            attestation_key=self.attestation_key, lease_key=self.lease_key,
            governed_turn_recorder_key=self.governed_turn_recorder_key, config=config,
            clock_ms=lambda: self.now,
        )
        self.authority = ChallengeAuthority(
            self.root / "authority.db",
            AuthorityConfig("sup", "ws", "install", "challenge-k1", self.challenge_key["private_key"]),
            clock_ms=lambda: self.now,
        )

    def _sign_handler(self, frame):
        return sign_governed(frame, self.components, self.now)

    def tearDown(self):
        self.supervisor.close(); self.authority.close(); self.tmp.cleanup()

    def prepare(self, *, nonce="nonce-1", system="system", history=None):
        history = history if history is not None else [{"role": "user", "content": "hello"}]
        sb = system_bytes(system); hb = history_bytes(history); cb = governed_generation_config_bytes(DEFAULT_GENERATION_CONFIG)
        create = self.authority.handle({
            "protocol": "brops.governed-challenge-create-pending.v1",
            "run_id": "run-1", "task_id": "task-1", "workspace_id": "ws", "install_id": "install",
            "request_nonce": nonce, "system_sha256": sha256_hex(sb), "history_sha256": sha256_hex(hb),
            "generation_config_sha256": sha256_hex(cb), "requested_at_ms": self.now - 1,
        })
        issue = self.authority.handle({
            "protocol": "brops.governed-challenge-issue.v1",
            "pending_challenge_id": create["pending_challenge_id"],
        })
        return sb, hb, cb, issue["challenge_document_b64"]

    def stage(self, challenge_doc_b64, artifacts, nonce="nonce-1"):
        opened = self.supervisor.handle({
            "protocol": "brops.governed-turn-open.v1", "install_id": "install",
            "request_nonce": nonce, "challenge_doc_b64": challenge_doc_b64,
        })
        self.assertEqual(opened["status"], "opened", opened)
        handle = opened["challenge_handle"]
        for name, data in artifacts.items():
            o = self.supervisor.handle({
                "protocol": "brops.governed-staging-open.v1", "install_id": "install",
                "challenge_handle": handle, "request_nonce": nonce, "artifact": name,
                "declared_len": len(data), "declared_sha256": sha256_hex(data),
            })
            self.assertEqual(o["status"], "opened", o)
            seq = 0
            for start in range(0, len(data), STAGING_CHUNK_BYTES):
                chunk = data[start:start + STAGING_CHUNK_BYTES]
                ack = self.supervisor.handle({
                    "protocol": "brops.governed-staging-chunk.v1",
                    "staging_session_id": o["staging_session_id"], "seq": seq,
                    "bytes_b64": b64url_encode(chunk),
                })
                self.assertEqual(ack["status"], "ack", ack); seq += 1
            final = self.supervisor.handle({
                "protocol": "brops.governed-staging-final.v1",
                "staging_session_id": o["staging_session_id"], "seq": seq,
            })
            self.assertEqual(final["status"], "published", final)
        return handle

    def test_full_signed_metadata_and_bound_output_pull(self):
        sb, hb, cb, doc = self.prepare()
        handle = self.stage(doc, {"system": sb, "history": hb, "generation_config": cb})
        result = self.supervisor.handle({
            "protocol": "brops.governed-evidence-request.v1", "install_id": "install",
            "challenge_handle": handle, "request_nonce": "nonce-1",
        })
        self.assertEqual(result["status"], "signed", result)
        self.assertNotIn("output", result)
        self.assertEqual(result["output_sha256"], sha256_hex(b"GOVERNED OK: " + hb))
        read = self.supervisor.handle({
            "protocol": "brops.governed-turn-output-read.v1",
            "output_stream_id": result["output_stream_id"], "receipt_id": result["receipt_id"],
            "execution_attempt_id": result["execution_attempt_id"], "seq": 0,
        })
        self.assertTrue(read["ok"], read)
        from brops_governed_common import b64url_decode
        self.assertEqual(b64url_decode(read["bytes_b64"]), b"GOVERNED OK: " + hb)
        wrong = self.supervisor.handle({
            "protocol": "brops.governed-turn-output-read.v1",
            "output_stream_id": result["output_stream_id"], "receipt_id": "wrong",
            "execution_attempt_id": result["execution_attempt_id"], "seq": 0,
        })
        self.assertEqual(wrong["error"]["reason"], "stream_binding_mismatch")
        replay = self.supervisor.handle({
            "protocol": "brops.governed-evidence-request.v1", "install_id": "install",
            "challenge_handle": handle, "request_nonce": "nonce-1",
        })
        self.assertEqual(replay["output_stream_id"], result["output_stream_id"])

    def test_sidecar_submit_is_metadata_only_and_output_is_separate_pull(self):
        sb, hb, cb, doc = self.prepare()
        supervisor_socket = str(self.root / "supervisor.sock")
        ready = threading.Event()
        thread = threading.Thread(
            target=brops_socket.serve_forever,
            args=(supervisor_socket, self.supervisor.handle),
            kwargs={"allowed_peer_uids": None, "max_requests": 12, "ready": ready.set},
            daemon=True,
        )
        thread.start(); self.assertTrue(ready.wait(2))
        result = sidecar_submit({
            "protocol": "bridge.governed-turn-submit.v1", "task_id": "task-1",
            "challenge_doc_b64": doc, "system": "system",
            "history": [{"role": "user", "content": "hello"}],
            "generation_config": DEFAULT_GENERATION_CONFIG,
        }, supervisor_socket)
        self.assertEqual(result["protocol"], "bridge.governed-turn-result.v1")
        self.assertTrue(result["ok"], result)
        self.assertNotIn("output", result)
        receipt = result["receipt"]
        pulled = sidecar_output_read({
            "protocol": "bridge.governed-turn-output-read.v1",
            "output_stream_id": result["output_stream_id"],
            "receipt_id": json.loads(__import__('base64').urlsafe_b64decode(receipt["envelope_jcs_b64"] + '===').decode())["receipt_id"],
            "execution_attempt_id": receipt["execution_attempt_id"], "seq": 0,
        }, supervisor_socket)
        self.assertEqual(pulled["protocol"], "bridge.governed-turn-output-read-result.v1")
        self.assertTrue(pulled["ok"], pulled)
        self.assertEqual(__import__('base64').urlsafe_b64decode(pulled["bytes_b64"] + '==='), b"GOVERNED OK: " + hb)

    def test_expired_challenges_do_not_pin_turn_quota(self):
        turns = []
        for i in range(2):
            _, _, _, doc = self.prepare(nonce=f"n{i}")
            turns.append(self.supervisor.handle({
                "protocol": "brops.governed-turn-open.v1", "install_id": "install",
                "request_nonce": f"n{i}", "challenge_doc_b64": doc,
            }))
        self.assertTrue(all(t["status"] == "opened" for t in turns))
        self.now += 30_001
        _, _, _, doc3 = self.prepare(nonce="n3")
        opened = self.supervisor.handle({
            "protocol": "brops.governed-turn-open.v1", "install_id": "install",
            "request_nonce": "n3", "challenge_doc_b64": doc3,
        })
        self.assertEqual(opened["status"], "opened", opened)

    def test_stream_lifecycle_live_expired_unknown(self):
        sb, hb, cb, doc = self.prepare()
        handle = self.stage(doc, {"system": sb, "history": hb, "generation_config": cb})
        result = self.supervisor.handle({
            "protocol": "brops.governed-evidence-request.v1", "install_id": "install",
            "challenge_handle": handle, "request_nonce": "nonce-1",
        })
        req = {"protocol": "brops.governed-turn-output-read.v1", "output_stream_id": result["output_stream_id"],
               "receipt_id": result["receipt_id"], "execution_attempt_id": result["execution_attempt_id"], "seq": 0}
        self.now += OUTPUT_STREAM_TTL_MS + 1
        self.assertEqual(self.supervisor.handle(req)["error"]["reason"], "stream_expired")
        self.now += OUTPUT_STREAM_RETENTION_MS + 1
        self.assertEqual(self.supervisor.handle(req)["error"]["reason"], "stream_unknown")

    def test_model_identity_is_hash_formula_not_mutable_registry_name(self):
        sb, hb, cb, doc = self.prepare()
        handle = self.stage(doc, {"system": sb, "history": hb, "generation_config": cb})
        self.supervisor.config.generation_config_allowlist  # permission only
        result = self.supervisor.handle({"protocol": "brops.governed-evidence-request.v1", "install_id": "install", "challenge_handle": handle, "request_nonce": "nonce-1"})
        self.assertEqual(result["status"], "signed")
        envelope = json.loads(__import__('base64').urlsafe_b64decode(result["envelope_jcs_b64"] + '===').decode())
        record = json.loads((self.record_dir / f"run-1__{result['execution_attempt_id']}.json").read_text())
        lease = json.loads(self.store.read(record["payload"]["lease_handle"]).decode())
        self.assertEqual(lease["payload"]["model_profile_id"], "cfg-sha256:" + PINNED_GENERATION_CONFIG_SHA256)
        self.assertEqual(envelope["request_sha256"], record["payload"]["request_sha256"])


if __name__ == "__main__":
    unittest.main()

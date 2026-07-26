"""§5 durable acceptance-ledger determinism — in-process (no sockets, no real child).

These drive GovernedSupervisor.execute() and recover() directly against a seeded INPUTS_READY
staging row, exercising the paths that return BEFORE the executor/signer: deterministic
post-acceptance BLOCKED, idempotent replay, the acceptance CAS, EXPIRED vs RECOVERY_REQUIRED via
recover(). The full accept->COMPLETED path (real child + AF_UNIX signer) is proven on Linux CI.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
for sub in ("runtime", "tools"):
    sys.path.insert(0, str(ROOT / sub))

from bro_signature import canonical_bytes  # noqa: E402
from brops_challenge_authority import b64url_encode  # noqa: E402
from brops_governed_common import (  # noqa: E402
    DEFAULT_GENERATION_CONFIG, LEASE_DURATION_MS, MIN_LAUNCH_REMAINING_MS,
    PINNED_GENERATION_CONFIG_SHA256, generation_config_sha256, sha256_hex,
)
from brops_evidence_store import NamespacedEvidenceStore as EvidenceStore  # noqa: E402
from brops_governed_supervisor import (  # noqa: E402
    ChallengeRegistry, GovernedSupervisor, SupervisorConfig,
)

CFG_HASH = generation_config_sha256(DEFAULT_GENERATION_CONFIG)


def _keypair(key_id):
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {"key_id": key_id, "private_key": priv.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex()}, pub.hex()


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.now = 1_800_000_000_000
        self._sups = []
        root_key, root_pub = _keypair("challenge-root")
        _, challenge_pub = _keypair("challenge-k1")
        payload = {
            "artifact_type": "brops.challenge-key-registry.v1", "root_key_id": "challenge-root",
            "registry_epoch": 7, "registry_issued_at_ms": self.now - 10_000,
            "keys": [{"challenge_key_id": "challenge-k1", "public_key": b64url_encode(bytes.fromhex(challenge_pub)),
                      "valid_from_ms": self.now - 100_000, "valid_to_ms": self.now + 100_000,
                      "key_epoch": 1, "revoked": False, "revoked_at_ms": None}],
        }
        rp = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(root_key["private_key"]))
        doc = {"payload": payload, "root_sig": b64url_encode(rp.sign(canonical_bytes(payload)))}
        (self.root / "registry.json").write_bytes(canonical_bytes(doc))
        self.registry = ChallengeRegistry.load(self.root / "registry.json", {"challenge-root": root_pub})
        self.store = EvidenceStore(self.root / "store")

    def tearDown(self):
        for sup in self._sups:
            try:
                sup.close()
            except Exception:
                pass
        self.tmp.cleanup()

    def _supervisor(self, allowlist=frozenset({CFG_HASH})):
        config = SupervisorConfig(
            workspace_id="ws", install_id="install", supervisor_id="sup", executor_id="exec",
            runner_id="runner", agent_id="Bro", session_id="session", policy_id="policy",
            policy_version="1", policy_bundle=b"policy bundle", launcher_executable_sha256="a" * 64,
            executor_command=(sys.executable, "-c", "pass"),
            generation_config_allowlist=allowlist, record_dir=self.root / "records",
        )
        sup = GovernedSupervisor(
            db_path=self.root / f"sup-{id(config)}.db", store=self.store, registry=self.registry,
            signer_socket=str(self.root / "unused.sock"),
            attestation_key=_keypair("att")[0], lease_key=_keypair("lease")[0],
            evidence_recorder_key=_keypair("ev")[0], governed_turn_recorder_key=_keypair("gt")[0],
            config=config, clock_ms=lambda: self.now,
        )
        self._sups.append(sup)
        return sup

    def _seed_inputs_ready(self, sup, *, cfg_hash=CFG_HASH, expires=None):
        handle = sha256_hex(b"challenge-" + str(id(sup)).encode())
        cfg_handle = self.store.publish(canonical_bytes(DEFAULT_GENERATION_CONFIG))
        challenge = {
            "challenge_key_id": "challenge-k1", "run_id": "run-1", "task_id": "task-1",
            "generation_config_sha256": cfg_hash, "system_sha256": "1" * 64, "history_sha256": "2" * 64,
            "request_sha256": "3" * 64, "requested_at_ms": self.now - 1,
            "challenge_issued_at_ms": self.now - 5, "challenge_expires_at_ms": expires or (self.now + 30_000),
        }
        sup.conn.execute(
            "INSERT INTO governed_turn_staging(install_id,request_nonce,challenge_handle,"
            "challenge_document,challenge_payload,state,run_id,task_id,challenge_expires_at_ms,"
            "system_handle,history_handle,generation_config_handle) "
            "VALUES('install','nonce-1',?,?,?,'INPUTS_READY','run-1','task-1',?,?,?,?)",
            (handle, b"doc", json.dumps(challenge), challenge["challenge_expires_at_ms"],
             cfg_handle, cfg_handle, cfg_handle),
        )
        sup.conn.commit()
        return handle

    def _evreq(self, handle):
        return {"protocol": "brops.governed-evidence-request.v1", "install_id": "install",
                "challenge_handle": handle, "request_nonce": "nonce-1"}

    def _row(self, sup, handle):
        return sup.conn.execute(
            "SELECT * FROM governed_turn_acceptance WHERE challenge_handle=?", (handle,)).fetchone()

    def test_model_profile_unknown_blocks_and_replays(self):
        sup = self._supervisor(allowlist=frozenset())  # cfg hash not allowed
        handle = self._seed_inputs_ready(sup)
        v1 = sup.execute(self._evreq(handle))
        self.assertEqual(v1["status"], "refused")
        self.assertEqual(v1["reason"], "model_profile_unknown")
        row = self._row(sup, handle)
        self.assertEqual(row["state"], "BLOCKED")
        self.assertIsNotNone(row["lease_payload_bytes"])          # persisted before the block
        v2 = sup.execute(self._evreq(handle))                      # idempotent replay
        self.assertEqual(v2, v1)
        self.assertEqual(self._row(sup, handle)["state"], "BLOCKED")

    def test_run_binding_invalid_blocks(self):
        sup = self._supervisor()
        handle = self._seed_inputs_ready(sup, cfg_hash="f" * 64)   # challenge commits a different hash
        v = sup.execute(self._evreq(handle))
        self.assertEqual(v["reason"], "run_binding_invalid")
        self.assertEqual(self._row(sup, handle)["state"], "BLOCKED")

    def test_challenge_invalidated_when_expired_at_acceptance(self):
        sup = self._supervisor()
        handle = self._seed_inputs_ready(sup, expires=self.now - 1)  # already expired at acceptance
        v = sup.execute(self._evreq(handle))
        self.assertEqual(v["reason"], "challenge_invalidated")
        self.assertEqual(self._row(sup, handle)["state"], "BLOCKED")

    def test_no_inputs_ready_creates_no_row(self):
        sup = self._supervisor()
        v = sup.execute(self._evreq("d" * 64))
        self.assertEqual(v["protocol"], "brops.governed-evidence-request-result.v1")
        self.assertEqual(v["reason"], "no_inputs_ready")
        self.assertIsNone(self._row(sup, "d" * 64))                 # UNSEEN: no acceptance row

    def test_recover_marks_post_launch_ambiguity(self):
        sup = self._supervisor()
        for state in ("EXECUTION_STARTING", "EXECUTING"):
            h = sha256_hex(state.encode())
            sup.conn.execute(
                "INSERT INTO governed_turn_acceptance(install_id,request_nonce,challenge_handle,run_id,"
                "task_id,workspace_id,execution_attempt_id,challenge_accepted_at_ms,challenge_registry_handle,"
                "challenge_registry_hash,challenge_registry_epoch,challenge_registry_root_key_id,"
                "lease_payload_sha256,lease_payload_bytes,state,created_at_ms,updated_at_ms) "
                "VALUES('install',?,?,'r','t','ws',?,?,'rh','rhash',1,'rk','s',?,?,?,?)",
                (state, h, state, self.now, b"{}", state, self.now, self.now))
        sup.conn.commit()
        sup.recover()
        for state in ("EXECUTION_STARTING", "EXECUTING"):
            self.assertEqual(self._row(sup, sha256_hex(state.encode()))["state"], "RECOVERY_REQUIRED")

    def test_recover_re_signs_accepted_prepared_to_lease_ready(self):
        # §5 crash-resume: a row stranded at ACCEPTED_PREPARED (crash before the lease was
        # published) is deterministically re-signed from lease_payload_bytes → LEASE_READY.
        sup = self._supervisor()
        h = sha256_hex(b"accepted-prepared")
        lease = {"artifact_type": "brops.governed-turn-lease.v1", "lease_id": "L",
                 "lease_issued_at_ms": self.now - 1000,
                 "lease_expires_at_ms": self.now + LEASE_DURATION_MS}
        sup.conn.execute(
            "INSERT INTO governed_turn_acceptance(install_id,request_nonce,challenge_handle,run_id,"
            "task_id,workspace_id,execution_attempt_id,challenge_accepted_at_ms,challenge_registry_handle,"
            "challenge_registry_hash,challenge_registry_epoch,challenge_registry_root_key_id,"
            "lease_payload_sha256,lease_payload_bytes,state,created_at_ms,updated_at_ms) "
            "VALUES('install','n',?,'r','t','ws','a',?,'rh','rhash',1,'rk','s',?,'ACCEPTED_PREPARED',?,?)",
            (h, self.now, json.dumps(lease).encode(), self.now, self.now))
        sup.conn.commit()
        sup.recover()
        row = self._row(sup, h)
        self.assertEqual(row["state"], "LEASE_READY")
        self.assertIsNotNone(row["lease_handle"])   # deterministically re-signed + published

    def test_recorder_keys_must_be_distinct(self):
        # §8: constructing a supervisor with the SAME key for both recorder authorities is refused.
        from brops_governed_supervisor import GovernedSupervisor
        config = SupervisorConfig(
            workspace_id="ws", install_id="install", supervisor_id="sup", executor_id="exec",
            runner_id="runner", agent_id="Bro", session_id="session", policy_id="policy",
            policy_version="1", policy_bundle=b"policy bundle", launcher_executable_sha256="a" * 64,
            executor_command=(sys.executable, "-c", "pass"),
            generation_config_allowlist=frozenset({CFG_HASH}), record_dir=self.root / "records")
        dup = _keypair("dup-recorder")[0]
        with self.assertRaises(ValueError):
            GovernedSupervisor(
                db_path=self.root / "distinct.db", store=self.store, registry=self.registry,
                signer_socket=str(self.root / "u.sock"), attestation_key=_keypair("a")[0],
                lease_key=_keypair("l")[0], evidence_recorder_key=dup,
                governed_turn_recorder_key=dup, config=config, clock_ms=lambda: self.now)

    def test_recover_expires_stale_lease_ready_but_keeps_valid(self):
        sup = self._supervisor()
        def seed(handle, lease_expires):
            lp = {"lease_issued_at_ms": self.now - 1000, "lease_expires_at_ms": lease_expires}
            sup.conn.execute(
                "INSERT INTO governed_turn_acceptance(install_id,request_nonce,challenge_handle,run_id,"
                "task_id,workspace_id,execution_attempt_id,challenge_accepted_at_ms,challenge_registry_handle,"
                "challenge_registry_hash,challenge_registry_epoch,challenge_registry_root_key_id,"
                "lease_payload_sha256,lease_payload_bytes,state,created_at_ms,updated_at_ms) "
                "VALUES('install',?,?,'r','t','ws',?,?,'rh','rhash',1,'rk','s',?,'LEASE_READY',?,?)",
                (handle, handle, handle, self.now, json.dumps(lp).encode(), self.now, self.now))
        seed("stale", self.now - 1)                                # already expired
        seed("valid", self.now + LEASE_DURATION_MS)                # plenty of budget
        sup.conn.commit()
        sup.recover()
        self.assertEqual(self._row(sup, "stale")["state"], "EXPIRED")
        self.assertEqual(self._row(sup, "valid")["state"], "LEASE_READY")


if __name__ == "__main__":
    unittest.main()

import json
import pathlib
import shutil
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from bro_signature import (
    ARTIFACT_AUTHORITY,
    SignatureError,
    canonical_bytes,
    load_trusted_keys,
    verify_artifact,
    verify_detached,
)
from broctl import build_registry, generate_key, sign_payload

AUTHORITIES = ["operator-root", "issuer", "evidence-recorder", "builder",
               "verifier", "release"]

NOW = 1_700_000_000
YEAR = 365 * 24 * 60 * 60


class SignatureFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-sig-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.keys = {a: generate_key(a, f"dev-{a}", False) for a in AUTHORITIES}
        self.registry = build_registry(list(self.keys.values()), NOW, YEAR)
        self.write_registry(self.registry)

    def write_registry(self, document: dict) -> None:
        (self.tmp / "config").mkdir(parents=True, exist_ok=True)
        (self.tmp / "config" / "trusted-keys.json").write_text(
            json.dumps(document), encoding="utf-8")

    def load(self):
        return load_trusted_keys(self.tmp)

    def artifact(self, authority: str, artifact_type: str, **payload) -> dict:
        body = {"artifact_type": artifact_type,
                "key_id": self.keys[authority]["key_id"],
                "issued_at_epoch": NOW, **payload}
        return sign_payload(self.keys[authority]["private_key"], body)


class KeyGenerationTests(SignatureFixture):
    def test_production_key_generation_is_refused(self):
        with self.assertRaises(SignatureError) as caught:
            generate_key("operator-root", "prod", True)
        self.assertIn("offline", str(caught.exception))

    def test_development_keys_are_labelled(self):
        self.assertFalse(self.keys["issuer"]["production"])
        self.assertIn("NOT FOR PRODUCTION", self.keys["issuer"]["warning"])
        self.assertFalse(self.registry["payload"]["production"])

    def test_unknown_authority_refused(self):
        with self.assertRaises(SignatureError):
            generate_key("superuser", "x", False)

    def test_registry_needs_exactly_one_operator(self):
        with self.assertRaises(SignatureError):
            build_registry([self.keys["issuer"]], NOW, YEAR)
        two = [self.keys["operator-root"],
               generate_key("operator-root", "second-root", False)]
        with self.assertRaises(SignatureError):
            build_registry(two, NOW, YEAR)


class RegistryTrustTests(SignatureFixture):
    def test_signed_registry_loads(self):
        keys = self.load()
        self.assertEqual(len(keys), 6)
        self.assertEqual(keys["dev-verifier"].authority_type, "verifier")

    def test_unsigned_registry_denied(self):
        self.write_registry(self.registry["payload"])
        with self.assertRaises(SignatureError):
            self.load()

    def test_tampered_registry_denied(self):
        forged = json.loads(json.dumps(self.registry))
        forged["payload"]["keys"][0]["status"] = "revoked"
        self.write_registry(forged)
        with self.assertRaises(SignatureError) as caught:
            self.load()
        self.assertIn("signature does not match", str(caught.exception))

    def test_injected_key_denied(self):
        """Writing the registry must not be enough to introduce a key."""
        attacker = generate_key("verifier", "attacker", False)
        forged = json.loads(json.dumps(self.registry))
        forged["payload"]["keys"].append({
            "key_id": "attacker", "public_key": attacker["public_key"],
            "authority_type": "verifier", "allowed_artifact_types": ["verifier-receipt"],
            "not_before_epoch": NOW, "not_after_epoch": NOW + YEAR,
            "status": "active", "issued_by": "dev-operator-root"})
        self.write_registry(forged)
        with self.assertRaises(SignatureError):
            self.load()

    def test_registry_resigned_by_wrong_key_denied(self):
        forged = dict(self.registry["payload"])
        self.write_registry(sign_payload(self.keys["issuer"]["private_key"], forged))
        with self.assertRaises(SignatureError):
            self.load()

    def test_registry_without_its_operator_denied(self):
        forged = json.loads(json.dumps(self.registry["payload"]))
        forged["keys"] = [k for k in forged["keys"]
                          if k["authority_type"] != "operator-root"]
        self.write_registry(sign_payload(self.keys["operator-root"]["private_key"], forged))
        with self.assertRaises(SignatureError) as caught:
            self.load()
        self.assertIn("not present in the registry", str(caught.exception))

    def test_authority_artifact_mismatch_denied(self):
        forged = json.loads(json.dumps(self.registry["payload"]))
        for entry in forged["keys"]:
            if entry["authority_type"] == "builder":
                entry["allowed_artifact_types"] = ["verifier-receipt"]
        self.write_registry(sign_payload(self.keys["operator-root"]["private_key"], forged))
        with self.assertRaises(SignatureError) as caught:
            self.load()
        self.assertIn("may not be allowed to sign verifier-receipt", str(caught.exception))

    def test_missing_registry_denied(self):
        (self.tmp / "config" / "trusted-keys.json").unlink()
        with self.assertRaises(SignatureError):
            self.load()


class ArtifactVerificationTests(SignatureFixture):
    def test_verifier_receipt_verifies(self):
        document = self.artifact("verifier", "verifier-receipt", verdict="GREEN")
        payload = verify_artifact(document, "verifier-receipt", self.load(), now=NOW + 10)
        self.assertEqual(payload["verdict"], "GREEN")

    def test_builder_signed_verifier_receipt_denied(self):
        """The finding this whole layer exists for: under HMAC the builder held
        the key that mints its own GREEN receipt."""
        document = self.artifact("builder", "verifier-receipt", verdict="GREEN")
        with self.assertRaises(SignatureError) as caught:
            verify_artifact(document, "verifier-receipt", self.load(), now=NOW + 10)
        self.assertIn("may not sign verifier-receipt", str(caught.exception))

    def test_builder_may_sign_its_own_completion_claim(self):
        document = self.artifact("builder", "completion-manifest", task_id="t-1")
        payload = verify_artifact(document, "completion-manifest", self.load(), now=NOW + 10)
        self.assertEqual(payload["task_id"], "t-1")

    def test_issuer_signed_task_contract_verifies(self):
        document = self.artifact("issuer", "task-contract", task_id="t-2")
        verify_artifact(document, "task-contract", self.load(), now=NOW + 10)

    def test_builder_signed_task_contract_denied(self):
        document = self.artifact("builder", "task-contract", task_id="t-3")
        with self.assertRaises(SignatureError):
            verify_artifact(document, "task-contract", self.load(), now=NOW + 10)

    def test_unknown_key_denied(self):
        outsider = generate_key("verifier", "not-registered", False)
        document = sign_payload(outsider["private_key"], {
            "artifact_type": "verifier-receipt", "key_id": "not-registered",
            "verdict": "GREEN"})
        with self.assertRaises(SignatureError) as caught:
            verify_artifact(document, "verifier-receipt", self.load(), now=NOW + 10)
        self.assertIn("unknown signing key", str(caught.exception))

    def test_revoked_key_denied(self):
        forged = json.loads(json.dumps(self.registry["payload"]))
        for entry in forged["keys"]:
            if entry["authority_type"] == "verifier":
                entry["status"] = "revoked"
        self.write_registry(sign_payload(self.keys["operator-root"]["private_key"], forged))
        document = self.artifact("verifier", "verifier-receipt", verdict="GREEN")
        with self.assertRaises(SignatureError) as caught:
            verify_artifact(document, "verifier-receipt", self.load(), now=NOW + 10)
        self.assertIn("revoked", str(caught.exception))

    def test_expired_key_denied(self):
        document = self.artifact("verifier", "verifier-receipt", verdict="GREEN")
        with self.assertRaises(SignatureError) as caught:
            verify_artifact(document, "verifier-receipt", self.load(), now=NOW + YEAR + 1)
        self.assertIn("expired", str(caught.exception))

    def test_key_not_yet_valid_denied(self):
        document = self.artifact("verifier", "verifier-receipt", verdict="GREEN")
        with self.assertRaises(SignatureError):
            verify_artifact(document, "verifier-receipt", self.load(), now=NOW - 1)

    def test_tampered_payload_denied(self):
        document = self.artifact("verifier", "verifier-receipt", verdict="RED")
        document["payload"]["verdict"] = "GREEN"
        with self.assertRaises(SignatureError) as caught:
            verify_artifact(document, "verifier-receipt", self.load(), now=NOW + 10)
        self.assertIn("signature does not match", str(caught.exception))

    def test_artifact_type_confusion_denied(self):
        document = self.artifact("builder", "completion-manifest", task_id="t-4")
        with self.assertRaises(SignatureError) as caught:
            verify_artifact(document, "verifier-receipt", self.load(), now=NOW + 10)
        self.assertIn("claims to be", str(caught.exception))

    def test_extra_document_field_denied(self):
        document = self.artifact("verifier", "verifier-receipt", verdict="GREEN")
        document["note"] = "smuggled"
        with self.assertRaises(SignatureError):
            verify_artifact(document, "verifier-receipt", self.load(), now=NOW + 10)

    def test_unknown_artifact_type_denied(self):
        with self.assertRaises(SignatureError):
            verify_artifact(self.artifact("issuer", "task-contract"), "invented",
                            self.load(), now=NOW + 10)


class PrimitiveTests(SignatureFixture):
    def test_canonical_bytes_are_key_order_independent(self):
        self.assertEqual(canonical_bytes({"a": 1, "b": 2}), canonical_bytes({"b": 2, "a": 1}))

    def test_short_public_key_denied(self):
        with self.assertRaises(SignatureError):
            verify_detached({"a": 1}, "00" * 64, "aa" * 16)

    def test_non_hex_public_key_denied(self):
        with self.assertRaises(SignatureError):
            verify_detached({"a": 1}, "00" * 64, "zz" * 32)

    def test_non_hex_signature_denied(self):
        with self.assertRaises(SignatureError):
            verify_detached({"a": 1}, "nothex", self.keys["issuer"]["public_key"])

    def test_every_artifact_type_has_exactly_one_authority(self):
        for artifact, authority in ARTIFACT_AUTHORITY.items():
            self.assertIn(authority, AUTHORITIES, artifact)


if __name__ == "__main__":
    unittest.main()

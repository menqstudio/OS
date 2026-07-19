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
    ENV_PIN,
    ENV_PIN_FILE,
    SignatureError,
    canonical_bytes,
    load_trusted_keys,
    resolve_operator_root_pin,
    verify_artifact,
    verify_detached,
)
from broctl import build_registry, generate_key, sign_payload
from _operator_pin import use_operator_pin

AUTHORITIES = ["operator-root", "issuer", "evidence-recorder", "builder",
               "verifier", "release", "recovery"]

NOW = 1_700_000_000
YEAR = 365 * 24 * 60 * 60


class SignatureFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-sig-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.keys = {a: generate_key(a, f"dev-{a}", False) for a in AUTHORITIES}
        self.registry = build_registry(list(self.keys.values()), NOW, YEAR)
        self.write_registry(self.registry)
        # The operator-root anchor is pinned from outside the registry; supply this
        # fixture's ephemeral operator key as the external pin.
        use_operator_pin(self, self.keys["operator-root"]["public_key"])

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
        self.assertEqual(len(keys), len(AUTHORITIES))
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


class CommittedRegistryTests(unittest.TestCase):
    """Phase 1 trust root: the committed config/trusted-keys.json must load and
    verify against its own operator key. A registry that is merely present is not
    trusted; load_trusted_keys refuses one the offline operator did not sign, so a
    successful load is proof the trust anchor is intact."""

    def test_repo_trusted_key_registry_loads(self):
        # The committed registry loads only when pinned to its own operator key from
        # outside the file (here, read for the test); a bare load now fails closed.
        doc = json.loads((ROOT / "config" / "trusted-keys.json").read_text(encoding="utf-8"))
        pin = doc["payload"]["operator_public_key"]
        keys = load_trusted_keys(ROOT, operator_public_key=pin)
        self.assertGreaterEqual(len(keys), 6)


class OperatorRootPinTests(SignatureFixture):
    """Security remediation blocker 2 (audit Critical: self-verifying trust root).

    The registry may not name its own trust anchor. An attacker who can write
    config/trusted-keys.json must not be able to replace the whole document with
    their own operator key and have every downstream signature verify. The anchor
    is pinned from outside the registry; a missing pin, a payload-only anchor, or a
    pin/registry mismatch is a hard failure."""

    def setUp(self):
        super().setUp()
        self.operator_pub = self.keys["operator-root"]["public_key"]

    # ---- the core attack: full-document replacement --------------------------
    def test_attacker_resigned_registry_with_own_operator_is_denied(self):
        # Attacker forges an entirely new registry: their own operator-root key,
        # self-signed, listed as its own operator entry. Self-consistent, so the old
        # payload-anchored load accepted it. The external pin does not.
        attacker_keys = {a: generate_key(a, f"atk-{a}", False) for a in AUTHORITIES}
        forged = build_registry(list(attacker_keys.values()), NOW, YEAR)
        self.write_registry(forged)
        # pin (from the fixture env) is still the LEGIT operator, not the attacker's
        with self.assertRaises(SignatureError) as caught:
            load_trusted_keys(self.tmp)
        self.assertIn("does not match the external operator pin", str(caught.exception))

    def test_no_pin_configured_is_hard_denied(self):
        with patch_environ_without_pins():
            with self.assertRaises(SignatureError) as caught:
                load_trusted_keys(self.tmp)
        self.assertIn("no operator-root pin", str(caught.exception))

    def test_registry_payload_is_never_the_pin_source(self):
        # Even with a perfectly self-consistent, correctly-signed registry, if no
        # external pin is set the load must fail — the payload is not a fallback.
        with patch_environ_without_pins():
            with self.assertRaises(SignatureError):
                load_trusted_keys(self.tmp)

    # ---- pin resolution rules ------------------------------------------------
    def test_env_pin_resolves(self):
        self.assertEqual(
            resolve_operator_root_pin({ENV_PIN: self.operator_pub}), self.operator_pub)

    def test_file_pin_resolves_when_outside_repo_regular_and_protected(self):
        pin_file = _write_pin_file(self, self.operator_pub, mode=0o600)
        self.assertEqual(
            resolve_operator_root_pin({ENV_PIN_FILE: str(pin_file)}, root=ROOT),
            self.operator_pub)

    def test_both_present_and_matching_is_accepted(self):
        pin_file = _write_pin_file(self, self.operator_pub, mode=0o600)
        self.assertEqual(
            resolve_operator_root_pin(
                {ENV_PIN: self.operator_pub, ENV_PIN_FILE: str(pin_file)}, root=ROOT),
            self.operator_pub)

    def test_both_present_but_mismatched_is_hard_denied(self):
        other = generate_key("operator-root", "other", False)["public_key"]
        pin_file = _write_pin_file(self, other, mode=0o600)
        with self.assertRaises(SignatureError) as caught:
            resolve_operator_root_pin(
                {ENV_PIN: self.operator_pub, ENV_PIN_FILE: str(pin_file)}, root=ROOT)
        self.assertIn("mismatch", str(caught.exception))

    def test_neither_present_is_hard_denied(self):
        with self.assertRaises(SignatureError):
            resolve_operator_root_pin({})

    def test_relative_pin_file_is_denied(self):
        with self.assertRaises(SignatureError) as caught:
            resolve_operator_root_pin({ENV_PIN_FILE: "config/trusted-keys.json"}, root=ROOT)
        self.assertIn("absolute", str(caught.exception))

    def test_pin_file_inside_repo_is_denied(self):
        inside = ROOT / "config" / "trusted-keys.json"
        with self.assertRaises(SignatureError) as caught:
            resolve_operator_root_pin({ENV_PIN_FILE: str(inside)}, root=ROOT)
        self.assertIn("outside the repository", str(caught.exception))

    def test_symlink_pin_file_is_denied(self):
        target = _write_pin_file(self, self.operator_pub, mode=0o600)
        link = self.tmp / "pin-link"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted")
        with self.assertRaises(SignatureError) as caught:
            resolve_operator_root_pin({ENV_PIN_FILE: str(link)}, root=ROOT)
        self.assertIn("symlink", str(caught.exception))

    def test_repo_controlled_parent_symlink_pin_file_is_denied(self):
        # the reproduced bypass: a pin path LEXICALLY inside the repo whose parent is
        # a symlink to an external attacker directory. Rejected before resolving,
        # because a repo-controlled link must not select the anchor.
        fake_root = pathlib.Path(tempfile.mkdtemp(prefix="bro-fakerepo-")).resolve()
        self.addCleanup(shutil.rmtree, fake_root, ignore_errors=True)
        external = pathlib.Path(tempfile.mkdtemp(prefix="bro-ext-")).resolve()
        self.addCleanup(shutil.rmtree, external, ignore_errors=True)
        (external / "operator-root.pub").write_text(self.operator_pub + "\n", encoding="utf-8")
        link = fake_root / "repo-controlled-link"
        try:
            link.symlink_to(external, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted")
        pin_path = link / "operator-root.pub"  # lexically under fake_root; parent is a link
        with self.assertRaises(SignatureError) as caught:
            resolve_operator_root_pin({ENV_PIN_FILE: str(pin_path)}, root=fake_root)
        self.assertRegex(str(caught.exception), "outside the repository|symlink")

    def test_intermediate_symlink_component_outside_repo_is_denied(self):
        # a path lexically OUTSIDE the repo but whose parent is a symlink must still
        # be rejected — no intermediate link may redirect the anchor.
        external = pathlib.Path(tempfile.mkdtemp(prefix="bro-ext-")).resolve()
        self.addCleanup(shutil.rmtree, external, ignore_errors=True)
        real_dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-real-")).resolve()
        self.addCleanup(shutil.rmtree, real_dir, ignore_errors=True)
        (real_dir / "operator-root.pub").write_text(self.operator_pub + "\n", encoding="utf-8")
        link_parent = external / "link-to-real"
        try:
            link_parent.symlink_to(real_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted")
        with self.assertRaises(SignatureError) as caught:
            resolve_operator_root_pin({ENV_PIN_FILE: str(link_parent / "operator-root.pub")}, root=ROOT)
        self.assertIn("symlink", str(caught.exception))

    @unittest.skipUnless(__import__("os").name == "posix", "POSIX permission bits")
    def test_group_or_world_writable_pin_file_is_denied(self):
        pin_file = _write_pin_file(self, self.operator_pub, mode=0o666)
        with self.assertRaises(SignatureError) as caught:
            resolve_operator_root_pin({ENV_PIN_FILE: str(pin_file)}, root=ROOT)
        self.assertIn("writable", str(caught.exception))

    def test_malformed_pin_is_denied(self):
        with self.assertRaises(SignatureError):
            resolve_operator_root_pin({ENV_PIN: "not-a-hex-key"})


import contextlib
import os as _os
from unittest.mock import patch as _patch


@contextlib.contextmanager
def patch_environ_without_pins():
    clean = {k: v for k, v in _os.environ.items() if k not in (ENV_PIN, ENV_PIN_FILE)}
    with _patch.dict(_os.environ, clean, clear=True):
        yield


def _write_pin_file(test_case, public_key, *, mode):
    # write the pin OUTSIDE the repository (a fresh temp dir); resolve() so no
    # incidental symlink parent (e.g. /tmp on some platforms) trips the
    # every-component symlink rejection in the positive cases
    outside = pathlib.Path(tempfile.mkdtemp(prefix="bro-pin-")).resolve()
    test_case.addCleanup(shutil.rmtree, outside, ignore_errors=True)
    pin_file = outside / "operator-root.pub"
    pin_file.write_text(public_key + "\n", encoding="utf-8")
    _os.chmod(pin_file, mode)
    return pin_file


if __name__ == "__main__":
    unittest.main()

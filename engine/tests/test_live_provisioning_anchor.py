"""The live kit's ROOT TRUST ANCHOR must state its provenance (audit F-17).

The kit used to mint a root keypair, sign the production ``KeyManifest`` with it, and hand the
matching public key back to the verifier through the same ``config.json`` the verifier read its
own knobs from. That verifies perfectly and proves nothing: the kit supplied both sides of the
signature. These tests pin the two properties that make the difference visible rather than
assumed — the anchor lives in a separate TCB file that says which case it is, and the
self-certifying inline form cannot be re-expressed by editing config.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROVISION = os.path.join(REPO_ROOT, "engine", "ci", "live", "provision_keys.py")
LIVE_DIR = os.path.join(REPO_ROOT, "engine", "ci", "live")

SHA_A = "aa" * 32
SHA_B = "bb" * 32


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _provision(root: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, PROVISION, "--root-dir", root,
         "--launcher-sha", SHA_A, "--executor-sha", SHA_B, *extra],
        capture_output=True, text=True,
    )


class LiveProvisioningAnchorTests(unittest.TestCase):
    def test_the_default_kit_labels_its_own_anchor_as_kit_generated(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(_provision(root).returncode, 0)
            anchor = _read_json(os.path.join(root, "tcb", "root-anchor.json"))
            self.assertEqual(anchor["provenance"], "kit_generated")
            self.assertEqual(len(anchor["public_key_hex"]), 64)

    def test_the_config_cannot_carry_the_anchor_inline(self):
        # The driver refuses a config with an inline anchor, so the provisioner must not write one:
        # if both existed, "which one wins" would be a question again.
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(_provision(root).returncode, 0)
            trust = _read_json(os.path.join(root, "config.json"))["trust"]
            self.assertNotIn("root_pub_hex", trust)
            self.assertNotIn("root_key_id", trust)
            self.assertTrue(trust["root_anchor_path"].endswith("root-anchor.json"))

    def test_a_partial_external_anchor_is_refused(self):
        # A public key without the manifest it signed would leave the kit signing the manifest
        # ITSELF while labelling the anchor external — strictly worse than the honest default.
        with tempfile.TemporaryDirectory() as root:
            r = _provision(root, "--root-anchor-key-id", "owner-root-1")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("external root anchor needs ALL", r.stderr)

    def test_an_external_anchor_is_labelled_external_and_its_manifest_is_served_verbatim(self):
        sys.path.insert(0, LIVE_DIR)
        import live_crypto as lc  # noqa: E402  (path-dependent import, as the live runners do)

        owner_root = lc.gen_private()
        with tempfile.TemporaryDirectory() as root:
            # A stand-in for the offline root's output: bytes it signed, and the detached signature.
            manifest_bytes = b'{"manifest_epoch":2,"root_key_id":"owner-root-1","keys":[]}'
            m_path = os.path.join(root, "external-manifest.json")
            s_path = os.path.join(root, "external-manifest.sig")
            with open(m_path, "wb") as f:
                f.write(manifest_bytes)
            with open(s_path, "w", encoding="utf-8") as f:
                f.write(lc.sign_b64std(owner_root, manifest_bytes))

            r = _provision(
                root,
                "--root-anchor-key-id", "owner-root-1",
                "--root-anchor-pub-hex", lc.pub_hex(owner_root),
                "--manifest-in", m_path,
                "--manifest-sig-in", s_path,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            anchor = _read_json(os.path.join(root, "tcb", "root-anchor.json"))
            self.assertEqual(anchor["provenance"], "external")
            self.assertEqual(anchor["root_key_id"], "owner-root-1")
            self.assertEqual(anchor["public_key_hex"], lc.pub_hex(owner_root))
            # Served VERBATIM: the kit must not rebuild or "fix up" a manifest it cannot re-sign.
            with open(os.path.join(root, "manifest.json"), "rb") as f:
                self.assertEqual(f.read(), manifest_bytes)


if __name__ == "__main__":
    unittest.main()

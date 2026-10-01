"""The live kit's ROOT TRUST ANCHOR must state its provenance (audit F-17), and only one exists.

The kit used to mint a root keypair, sign the production ``KeyManifest`` with it, and hand the
matching public key back to the verifier through the same ``config.json`` the verifier read its
own knobs from. That verifies perfectly and proves nothing: the kit supplied both sides of the
signature. These tests pin the properties that make the difference visible rather than assumed —
the anchor lives in a separate TCB file that says which case it is, the self-certifying inline form
cannot be re-expressed by editing config, and a file that CLAIMS outside custody is refused.

There is no outside-anchor mode to test. The Owner decided on 2026-08-09 (#78) that the install
mints trust and no person carries a key; the offline-root ceremony later rebuilt for the broker was
removed in T-130, and the tests below hold that it stays removed.
"""

from __future__ import annotations

import json
import os
import shutil
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


def _script(name: str) -> str:
    with open(os.path.join(LIVE_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


class LiveProvisioningAnchorTests(unittest.TestCase):
    def test_the_kit_labels_its_own_anchor_as_kit_generated(self):
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

    def test_the_provisioner_takes_no_outside_anchor(self):
        # Each of these flags existed to carry an offline root's manifest in or out. argparse refuses
        # an unknown flag with exit 2, which is the proof they are gone rather than ignored.
        for flag in ("--root-anchor-key-id", "--root-anchor-pub-hex", "--manifest-in",
                     "--manifest-sig-in", "--emit-manifest", "--keys-in"):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as root:
                r = _provision(root, flag, "x")
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertFalse(os.path.exists(os.path.join(root, "config.json")))


class KitScriptTests(unittest.TestCase):
    """The two orchestrators: they parse, read no anchor from the environment, and refuse a claim."""

    def test_every_live_shell_script_parses(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("no bash on this host, so syntax cannot be checked here")
        scripts = sorted(f for f in os.listdir(LIVE_DIR) if f.endswith(".sh"))
        self.assertGreaterEqual(len(scripts), 2, scripts)
        for name in scripts:
            with self.subTest(script=name):
                r = subprocess.run([bash, "-n", os.path.join(LIVE_DIR, name)],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"{name}: {r.stderr}")

    def test_neither_kit_reads_an_anchor_from_the_environment(self):
        for name in ("run_live_turn.sh", "run_ladder_turn.sh"):
            script = _script(name)
            for var in ("BROPS_KEYS_IN", "BROPS_ROOT_ANCHOR_KEY_ID", "BROPS_ROOT_ANCHOR_PUB_HEX",
                        "BROPS_MANIFEST_IN", "BROPS_MANIFEST_SIG_IN", "BROPS_REGISTRY_SIG_IN"):
                with self.subTest(script=name, var=var):
                    self.assertNotIn(var, script)

    def test_the_throwaway_negative_names_the_refusal_the_driver_actually_emits(self):
        # The ladder kit relabels its own root `external` and expects the driver to refuse it. The
        # outcome string is built from two languages: `setup_blocked` prefixes `root_anchor_` to the
        # reason `check_declared_external_anchor` returns. A rename on either side would leave the
        # kit expecting an outcome nothing produces.
        script = _script("run_ladder_turn.sh")
        self.assertIn("run_driver throwaway-external", script)
        self.assertIn("blocked:setup:root_anchor_external_not_the_pinned_root", script)
        tcb = os.path.join(REPO_ROOT, "apps", "desktop", "src-tauri", "broker", "src", "tcb.rs")
        with open(tcb, "r", encoding="utf-8") as f:
            self.assertIn('Err("external_not_the_pinned_root")', f.read())
        for driver in ("ladder_turn.rs", "live_turn.rs"):
            path = os.path.join(REPO_ROOT, "apps", "desktop", "src-tauri", "proof", "src", "bin",
                                driver)
            with self.subTest(driver=driver), open(path, "r", encoding="utf-8") as f:
                text = f.read()
                self.assertIn("check_declared_external_anchor", text)
                self.assertIn('format!("root_anchor_{why}")', text)


if __name__ == "__main__":
    unittest.main()

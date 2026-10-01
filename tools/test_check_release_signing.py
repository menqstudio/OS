"""Self-tests for the release signing / updater gate.

A gate is only worth its GREEN if it is proven to go RED. These drive the gate against
synthetic trees that reproduce, one by one, the silent half-wired states it exists to catch:

  * a signing key in CI with no updater config  -> no updater payload is ever produced;
  * `createUpdaterArtifacts` with no pubkey     -> payloads nothing can verify;
  * a placeholder / non-minisign pubkey         -> "verification" against a key nobody holds;
  * an http:// update endpoint                  -> an attacker-controlled update manifest;
  * a release workflow whose build does not depend on the preflight;
  * an Owner-secret list that drifted between the code, the workflow and the docs;
  * an updater payload shipped without its `.sig`.

They also assert the real repository tree passes, so the gate is live rather than aspirational.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import pathlib
import re
import shutil
import tempfile
import unittest
from unittest import mock

import check_release_signing
from check_release_signing import (
    REQUIRED_OWNER_SECRETS,
    check,
    check_tauri_config,
    missing_secrets,
    names_secret,
    pubkey_problem,
    release_ref_problem,
    render_refusal,
    unsigned_updater_artifacts,
    updater_suffixes,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

_REAL_MINISIGN = base64.b64encode(
    b"untrusted comment: minisign public key 1A2B3C4D5E6F7A8B\n"
    b"RWQdX3z1kQvBcE9mQeVrJm0uZ0oQm3lFq2xW8nT7yR4pS1aD6gH5jK2L\n"
).decode()

_WINDOWS_OK = {"digestAlgorithm": "sha256", "timestampUrl": "http://timestamp.digicert.com"}


def _conf(bundle_extra: dict | None = None, updater: dict | None = None) -> dict:
    bundle = {"active": True, "targets": "all", "windows": dict(_WINDOWS_OK)}
    bundle.update(bundle_extra or {})
    conf: dict = {"productName": "BroPS", "bundle": bundle}
    if updater is not None:
        conf["plugins"] = {"updater": updater}
    return conf


def _tree(conf: dict, cargo: str = 'tauri-plugin-dialog = "2"\n') -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp())
    tauri = root / "apps" / "desktop" / "src-tauri"
    tauri.mkdir(parents=True)
    (tauri / "tauri.conf.json").write_text(json.dumps(conf, indent=2), encoding="utf-8")
    (tauri / "Cargo.toml").write_text(cargo, encoding="utf-8")
    return root


class PubkeyTests(unittest.TestCase):
    def test_a_real_minisign_pubkey_is_accepted(self):
        self.assertIsNone(pubkey_problem(_REAL_MINISIGN))

    def test_empty_is_rejected(self):
        self.assertIn("empty", pubkey_problem("") or "")

    def test_placeholder_token_is_rejected(self):
        self.assertIn("placeholder token", pubkey_problem("REPLACE_ME_WITH_THE_REAL_KEY") or "")

    def test_non_base64_is_rejected(self):
        self.assertIn("base64", pubkey_problem("!!!not base64!!!") or "")

    def test_base64_of_something_else_is_rejected(self):
        blob = base64.b64encode(b"this is not a minisign key at all").decode()
        self.assertIn("minisign", pubkey_problem(blob) or "")

    def test_minisign_block_with_a_bad_key_line_is_rejected(self):
        blob = base64.b64encode(
            b"untrusted comment: minisign public key AAAA\nZZnope\n"
        ).decode()
        self.assertIn("RW", pubkey_problem(blob) or "")


class ConfigCouplingTests(unittest.TestCase):
    def _state(self, conf, cargo='tauri-plugin-dialog = "2"\n'):
        problems: list[str] = []
        state = check_tauri_config(_tree(conf, cargo), problems)
        return state, problems

    def test_fully_unprovisioned_is_a_coherent_state(self):
        state, problems = self._state(_conf())
        self.assertEqual(state, "UNPROVISIONED")
        self.assertEqual(problems, [])

    def test_fully_provisioned_is_a_coherent_state(self):
        state, problems = self._state(
            _conf(
                {"createUpdaterArtifacts": True},
                {"pubkey": _REAL_MINISIGN, "endpoints": ["https://example.invalid/latest.json"]},
            ),
            cargo='tauri-plugin-dialog = "2"\ntauri-plugin-updater = "2"\n',
        )
        self.assertEqual(state, "PROVISIONED")
        self.assertEqual(problems, [])

    def test_artifacts_without_a_pubkey_is_RED(self):
        state, problems = self._state(_conf({"createUpdaterArtifacts": True}))
        self.assertEqual(state, "BROKEN")
        self.assertTrue(any("plugins.updater is absent" in p for p in problems), problems)

    def test_pubkey_without_artifacts_is_RED(self):
        """The silent failure: the key is set, Tauri emits no payload, nobody can update."""
        state, problems = self._state(
            _conf(None, {"pubkey": _REAL_MINISIGN, "endpoints": ["https://x.invalid/l.json"]}),
            cargo='tauri-plugin-updater = "2"\n',
        )
        self.assertEqual(state, "BROKEN")
        self.assertTrue(any("createUpdaterArtifacts" in p for p in problems), problems)

    def test_placeholder_pubkey_is_RED(self):
        state, problems = self._state(
            _conf(
                {"createUpdaterArtifacts": True},
                {"pubkey": "PLACEHOLDER", "endpoints": ["https://x.invalid/l.json"]},
            ),
            cargo='tauri-plugin-updater = "2"\n',
        )
        self.assertEqual(state, "BROKEN")
        self.assertTrue(any("pubkey" in p for p in problems), problems)

    def test_plaintext_endpoint_is_RED(self):
        state, problems = self._state(
            _conf(
                {"createUpdaterArtifacts": True},
                {"pubkey": _REAL_MINISIGN, "endpoints": ["http://x.invalid/l.json"]},
            ),
            cargo='tauri-plugin-updater = "2"\n',
        )
        self.assertEqual(state, "BROKEN")
        self.assertTrue(any("https" in p for p in problems), problems)

    def test_missing_plugin_dependency_is_RED(self):
        state, problems = self._state(
            _conf(
                {"createUpdaterArtifacts": True},
                {"pubkey": _REAL_MINISIGN, "endpoints": ["https://x.invalid/l.json"]},
            )
        )
        self.assertEqual(state, "BROKEN")
        self.assertTrue(any("tauri-plugin-updater" in p for p in problems), problems)

    def test_committed_private_key_material_is_RED(self):
        conf = _conf()
        conf["bundle"]["copyright"] = "-----BEGIN PRIVATE KEY-----"
        _state, problems = self._state(conf)
        self.assertTrue(any("NEVER be committed" in p for p in problems), problems)

    def test_malformed_windows_thumbprint_is_RED(self):
        conf = _conf()
        conf["bundle"]["windows"]["certificateThumbprint"] = "not-a-thumbprint"
        _state, problems = self._state(conf)
        self.assertTrue(any("thumbprint" in p for p in problems), problems)

    def test_missing_authenticode_timestamp_is_RED(self):
        conf = _conf()
        conf["bundle"]["windows"].pop("timestampUrl")
        _state, problems = self._state(conf)
        self.assertTrue(any("timestampUrl" in p for p in problems), problems)

    def test_sha1_digest_is_RED(self):
        conf = _conf()
        conf["bundle"]["windows"]["digestAlgorithm"] = "sha1"
        _state, problems = self._state(conf)
        self.assertTrue(any("digestAlgorithm" in p for p in problems), problems)


class UpdaterSignatureTests(unittest.TestCase):
    def test_a_payload_without_a_sig_is_caught(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "BroPS.app.tar.gz").write_bytes(b"payload")
        found, unsigned = unsigned_updater_artifacts(d)
        self.assertEqual(found, ["BroPS.app.tar.gz"])
        self.assertEqual(unsigned, ["BroPS.app.tar.gz"])

    def test_an_empty_sig_is_not_a_signature(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "BroPS.nsis.zip").write_bytes(b"payload")
        (d / "BroPS.nsis.zip.sig").write_bytes(b"")
        _found, unsigned = unsigned_updater_artifacts(d)
        self.assertEqual(unsigned, ["BroPS.nsis.zip"])

    def test_a_signed_payload_passes(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "BroPS.AppImage.tar.gz").write_bytes(b"payload")
        (d / "BroPS.AppImage.tar.gz.sig").write_bytes(b"dW50cnVzdGVk")
        found, unsigned = unsigned_updater_artifacts(d)
        self.assertEqual((found, unsigned), (["BroPS.AppImage.tar.gz"], []))


class Tauri2UpdaterPayloads(unittest.TestCase):
    """The payload names depend on `bundle.createUpdaterArtifacts`, and the gate knew only
    the Tauri 1 set while the app builds with Tauri 2. The v2 names here are from Tauri's
    documentation, not from a bundle built in this repository -- see `updater_suffixes`."""

    def _bundle(self, *names: str) -> pathlib.Path:
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        for name in names:
            path = d / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
        return d

    def test_each_setting_selects_its_own_set(self):
        self.assertIn(".AppImage", updater_suffixes(True))
        self.assertIn(".exe", updater_suffixes(True))
        self.assertIn(".msi", updater_suffixes(True))
        self.assertIn(".nsis.zip", updater_suffixes("v1Compatible"))
        self.assertNotIn(".exe", updater_suffixes("v1Compatible"))
        for nothing in (None, False, "", "yes", 1):
            with self.subTest(value=nothing):
                self.assertIsNone(updater_suffixes(nothing))

    def test_a_signed_tauri_2_bundle_is_found_and_passes(self):
        """The defect: under `true` these are the payloads, and the v1 list saw none of
        them -- a correctly signed Linux or Windows release was refused as empty."""
        d = self._bundle("appimage/BroPS_0.1.0_amd64.AppImage",
                         "appimage/BroPS_0.1.0_amd64.AppImage.sig",
                         "nsis/BroPS_0.1.0_x64-setup.exe", "nsis/BroPS_0.1.0_x64-setup.exe.sig",
                         "msi/BroPS_0.1.0_x64_en-US.msi", "msi/BroPS_0.1.0_x64_en-US.msi.sig",
                         "deb/BroPS_0.1.0_amd64.deb")
        self.assertEqual(unsigned_updater_artifacts(d), ([], []), "the v1 list sees nothing here")
        found, unsigned = unsigned_updater_artifacts(d, updater_suffixes(True))
        self.assertEqual(sorted(found), ["BroPS_0.1.0_amd64.AppImage",
                                         "BroPS_0.1.0_x64-setup.exe",
                                         "BroPS_0.1.0_x64_en-US.msi"])
        self.assertEqual(unsigned, [])

    def test_an_unsigned_tauri_2_installer_is_caught(self):
        d = self._bundle("nsis/BroPS_0.1.0_x64-setup.exe", "msi/BroPS.msi", "msi/BroPS.msi.sig")
        _, unsigned = unsigned_updater_artifacts(d, updater_suffixes(True))
        self.assertEqual(unsigned, ["BroPS_0.1.0_x64-setup.exe"])

    def test_a_v1_compatible_build_does_not_demand_a_sig_on_the_bare_installer(self):
        """There the WRAPPER is the payload; the installer beside it is unsigned by design."""
        d = self._bundle("nsis/BroPS-setup.exe", "nsis/BroPS-setup.nsis.zip",
                         "nsis/BroPS-setup.nsis.zip.sig")
        self.assertEqual(unsigned_updater_artifacts(d, updater_suffixes("v1Compatible")),
                         (["BroPS-setup.nsis.zip"], []))

    def _verify(self, mode, *names: str) -> tuple[int, str]:
        conf = _conf({"createUpdaterArtifacts": mode} if mode is not None else None)
        root = _tree(conf)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_release_signing.main(
                ["--root", str(root), "--verify-updater-signatures", str(self._bundle(*names))])
        return code, out.getvalue()

    def test_the_verify_mode_reads_the_setting_from_the_config(self):
        signed_v2 = ("a/BroPS.AppImage", "a/BroPS.AppImage.sig")
        code, out = self._verify(True, *signed_v2)
        self.assertEqual(code, 0, out)
        self.assertIn("GREEN: 1 updater payload(s)", out)
        code, out = self._verify("v1Compatible", *signed_v2)
        self.assertEqual(code, 1, "a v2 bundle satisfied a v1Compatible config")
        self.assertIn("no updater payloads", out)
        code, out = self._verify(True, "a/BroPS.AppImage")
        self.assertEqual(code, 1)
        self.assertIn("BroPS.AppImage (expected BroPS.AppImage.sig)", out)

    def test_a_config_that_never_asked_for_updater_artifacts_is_red(self):
        code, out = self._verify(None, "a/BroPS.AppImage", "a/BroPS.AppImage.sig")
        self.assertEqual(code, 1)
        self.assertIn("never asked for updater payloads", out)


class SecretNamesAreWholeIdentifiers(unittest.TestCase):
    """`name not in text` let three secrets be satisfied by their own `_PASSWORD` sibling."""

    PREFIXES = ("TAURI_SIGNING_PRIVATE_KEY", "WINDOWS_CERTIFICATE", "APPLE_CERTIFICATE")

    def test_a_password_line_does_not_name_the_key(self):
        for name in self.PREFIXES:
            with self.subTest(name=name):
                self.assertIn(name + "_PASSWORD", REQUIRED_OWNER_SECRETS)
                self.assertFalse(names_secret(f"env:\n  {name}_PASSWORD: x\n", name))
                self.assertTrue(names_secret(f"env:\n  {name}: ${{{{ secrets.{name} }}}}\n", name))
                self.assertTrue(names_secret(f"`{name}`", name))

    def _full_tree(self) -> pathlib.Path:
        root = _tree(_conf())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        for rel in (".github/workflows/release.yml", "docs/RELEASE_SETUP.md"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / rel, root / rel)
        return root

    def _drop_whole_name(self, path: pathlib.Path, name: str) -> None:
        text = path.read_text(encoding="utf-8")
        cut = re.sub(rf"(?<![A-Za-z0-9_]){name}(?![A-Za-z0-9_])", "REDACTED", text)
        self.assertNotEqual(cut, text)
        self.assertIn(name + "_PASSWORD", cut)
        path.write_text(cut, encoding="utf-8")

    def test_the_real_files_copied_are_green(self):
        """The control: the fixture is the real workflow and document, untouched."""
        problems, _ = check(self._full_tree())
        self.assertEqual(problems, [])

    def test_a_workflow_that_keeps_only_the_password_is_red(self):
        for name in self.PREFIXES:
            with self.subTest(name=name):
                root = self._full_tree()
                self._drop_whole_name(root / ".github" / "workflows" / "release.yml", name)
                problems, _ = check(root)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(f"Owner secret {name} is required", problems[0])
                self.assertIn("release.yml", problems[0])

    def test_a_document_that_keeps_only_the_password_is_red(self):
        for name in self.PREFIXES:
            with self.subTest(name=name):
                root = self._full_tree()
                self._drop_whole_name(root / "docs" / "RELEASE_SETUP.md", name)
                problems, _ = check(root)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(f"does not name the Owner secret {name},", problems[0])


class TheReleaseRef(unittest.TestCase):
    """release.yml has `workflow_dispatch`, and names the release after `github.ref_name`."""

    def test_a_v_tag_is_a_release(self):
        for name in ("v0.1.0", "v1", "v2.0.0-rc.1"):
            with self.subTest(name=name):
                self.assertIsNone(release_ref_problem(
                    {"GITHUB_REF_TYPE": "tag", "GITHUB_REF_NAME": name}))

    def test_anything_else_is_refused_and_says_what_it_saw(self):
        for ref_type, name in (("branch", "main"), ("branch", "v-looking-branch"),
                               ("tag", "nightly"), ("tag", "v"), ("tag", ""), ("", "v0.1.0")):
            with self.subTest(ref_type=ref_type, name=name):
                problem = release_ref_problem({"GITHUB_REF_TYPE": ref_type,
                                               "GITHUB_REF_NAME": name})
                self.assertIn("not for a `v*` tag", problem)
        self.assertIn("branch 'main'", release_ref_problem(
            {"GITHUB_REF_TYPE": "branch", "GITHUB_REF_NAME": "main"}))

    def test_a_run_with_no_ref_at_all_is_refused_not_passed(self):
        self.assertIn("no GITHUB_REF_TYPE at all", release_ref_problem({}))

    def _provisioned(self) -> pathlib.Path:
        root = _tree(
            _conf({"createUpdaterArtifacts": True},
                  {"pubkey": _REAL_MINISIGN, "endpoints": ["https://example.invalid/latest.json"]}),
            cargo='tauri-plugin-dialog = "2"\ntauri-plugin-updater = "2"\n')
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        for rel in (".github/workflows/release.yml", "docs/RELEASE_SETUP.md"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / rel, root / rel)
        return root

    def _preflight(self, env: dict) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.dict("os.environ", env, clear=True), contextlib.redirect_stdout(out):
            code = check_release_signing.main(
                ["--root", str(self._provisioned()), "--require-release-ready"])
        return code, out.getvalue()

    def test_the_preflight_passes_on_a_tag_with_everything_present(self):
        """The control for the refusal below: everything else about the run is in order."""
        env = {name: "present" for name in REQUIRED_OWNER_SECRETS}
        code, out = self._preflight({**env, "GITHUB_REF_TYPE": "tag", "GITHUB_REF_NAME": "v0.1.0"})
        self.assertEqual(code, 0, out)

    def test_the_preflight_refuses_a_dispatch_from_a_branch(self):
        env = {name: "present" for name in REQUIRED_OWNER_SECRETS}
        code, out = self._preflight({**env, "GITHUB_REF_TYPE": "branch", "GITHUB_REF_NAME": "main"})
        self.assertEqual(code, 1)
        self.assertIn("RELEASE REFUSED — this run is not a release.", out)
        self.assertIn("REF: this run is not for a `v*` tag (it is for branch 'main')", out)
        self.assertNotIn("MISSING repository secrets", out)

    def test_the_preflight_never_prints_a_secrets_value(self):
        """What the old test's name promised and its body could not check: it called
        `render_refusal`, which is handed names and a state and never a value."""
        values = {name: f"VALUE-{i:02d}-do-not-print" for i, name in enumerate(REQUIRED_OWNER_SECRETS)}
        del values["APPLE_TEAM_ID"]
        code, out = self._preflight({**values, "GITHUB_REF_TYPE": "branch",
                                     "GITHUB_REF_NAME": "main"})
        self.assertEqual(code, 1)
        self.assertIn("APPLE_TEAM_ID", out)
        for value in values.values():
            self.assertNotIn(value, out)
        self.assertNotIn("do-not-print", out)


class PreflightTests(unittest.TestCase):
    def test_every_missing_secret_is_named(self):
        self.assertEqual(sorted(missing_secrets({})), sorted(REQUIRED_OWNER_SECRETS))

    def test_a_whitespace_only_secret_counts_as_missing(self):
        env = {name: "x" for name in REQUIRED_OWNER_SECRETS}
        env["APPLE_TEAM_ID"] = "   "
        self.assertEqual(missing_secrets(env), ["APPLE_TEAM_ID"])

    def test_a_fully_populated_environment_is_not_missing_anything(self):
        env = {name: "x" for name in REQUIRED_OWNER_SECRETS}
        self.assertEqual(missing_secrets(env), [])

    def test_the_refusal_names_the_secrets_and_the_state(self):
        # Renamed: it was `..._and_never_prints_a_value`, and `render_refusal` is never
        # handed a value. That half is `TheReleaseRef.test_the_preflight_never_prints_a_
        # secrets_value`, which drives the preflight with a populated environment.
        text = render_refusal(["APPLE_ID", "APPLE_TEAM_ID"], "UNPROVISIONED")
        self.assertIn("RELEASE REFUSED", text)
        self.assertIn("APPLE_ID", text)
        self.assertIn("APPLE_TEAM_ID", text)
        self.assertIn("UNPROVISIONED", text)
        self.assertIn("docs/RELEASE_SETUP.md", text)

    def test_the_refusal_still_speaks_when_only_the_config_is_missing(self):
        text = render_refusal([], "UNPROVISIONED")
        self.assertIn("createUpdaterArtifacts", text)


class LiveRepositoryTests(unittest.TestCase):
    """The gate must be GREEN on the real tree — and for the honest reason."""

    def test_the_repository_passes(self):
        problems, state = check(REPO_ROOT)
        self.assertEqual(problems, [], "\n".join(problems))
        self.assertEqual(state, "UNPROVISIONED")

    def test_the_release_workflow_runs_the_preflight_and_gates_the_build(self):
        text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("check_release_signing.py --require-release-ready", text)
        self.assertIn("needs: preflight", text)

    def test_the_owner_secret_list_has_not_drifted(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        doc = (REPO_ROOT / "docs" / "RELEASE_SETUP.md").read_text(encoding="utf-8")
        for name in REQUIRED_OWNER_SECRETS:
            self.assertIn(name, workflow, f"{name} missing from release.yml")
            self.assertIn(name, doc, f"{name} missing from docs/RELEASE_SETUP.md")

    def test_a_workflow_whose_build_skips_the_preflight_is_RED(self):
        """Reconstruct the previous behaviour and prove the gate refuses it."""
        root = _tree(_conf())
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "release.yml").write_text(
            "jobs:\n  build:\n    steps:\n"
            "      - name: Build + bundle (signed if secrets present)\n"
            "        uses: tauri-apps/tauri-action@v0\n",
            encoding="utf-8",
        )
        (root / "docs").mkdir()
        (root / "docs" / "RELEASE_SETUP.md").write_text("nothing here\n", encoding="utf-8")
        problems, _state = check(root)
        self.assertTrue(any("preflight" in p for p in problems), problems)
        self.assertTrue(any("--require-release-ready" in p for p in problems), problems)
        self.assertTrue(any("APPLE_TEAM_ID" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()

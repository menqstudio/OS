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
import json
import pathlib
import tempfile
import unittest

from check_release_signing import (
    REQUIRED_OWNER_SECRETS,
    check,
    check_tauri_config,
    missing_secrets,
    pubkey_problem,
    render_refusal,
    unsigned_updater_artifacts,
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

    def test_the_refusal_names_the_secrets_and_never_prints_a_value(self):
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

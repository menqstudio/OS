import json
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from bro_deploy_preflight import preflight
from bro_signature import ENV_PIN, ENV_PIN_FILE
from broctl import build_registry, generate_key

NOW = 1_700_000_000
YEAR = 365 * 24 * 60 * 60
AUTHORITIES = ["operator-root", "issuer", "evidence-recorder", "builder",
               "verifier", "release", "recovery"]


class PreflightFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-preflight-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "repo"           # stand-in for the bro repository root
        (self.root / "config").mkdir(parents=True)
        # builder/verifier keys are subject-bound; the rest are not identity-bound.
        self.keys = {
            auth: generate_key(auth, f"dev-{auth}", False,
                               subject_agent_id=("agt-p01-r01" if auth in ("builder", "verifier") else None))
            for auth in AUTHORITIES
        }
        self._write_registry(self.keys.values())
        # The operator-root pin lives in a file OUTSIDE the repo (a sibling of it).
        self.pin_file = self.tmp / "operator-root.pub"
        self.pin_file.write_text(self.keys["operator-root"]["public_key"], encoding="utf-8")
        self.pin_file.chmod(0o600)              # owner-only, as _pin_from_file requires
        self.env = {ENV_PIN_FILE: str(self.pin_file)}

    def _write_registry(self, keys):
        registry = build_registry(list(keys), NOW, YEAR)
        (self.root / "config" / "trusted-keys.json").write_text(json.dumps(registry), encoding="utf-8")

    def run_preflight(self, **env_over):
        env = dict(self.env)
        env.update(env_over)
        return preflight(env=env, root=self.root)


class DeployPreflightTests(PreflightFixture):
    def test_hardened_environment_passes(self):
        self.assertEqual(self.run_preflight(), [])

    def test_no_pin_file_fails(self):
        failures = preflight(env={}, root=self.root)
        self.assertTrue(any(ENV_PIN_FILE in f for f in failures), failures)

    def test_ci_env_pin_alone_is_not_production_hardened(self):
        # The raw env pin authenticates the registry, but a hardened deployment must
        # pin from an operator-controlled file, so this still fails posture.
        env = {ENV_PIN: self.keys["operator-root"]["public_key"]}
        failures = preflight(env=env, root=self.root)
        self.assertTrue(any(ENV_PIN_FILE in f for f in failures), failures)

    def test_ledger_inside_repo_fails(self):
        failures = self.run_preflight(BRO_EXECUTION_LEASE_LEDGER=str(self.root / "state" / "leases"))
        self.assertTrue(any("outside the repository" in f for f in failures), failures)

    def test_relative_ledger_fails(self):
        failures = self.run_preflight(BRO_RECOVERY_STORE="var/recovery")
        self.assertTrue(any("absolute" in f for f in failures), failures)

    def test_external_absolute_ledger_passes(self):
        external = self.tmp / "leases"
        external.mkdir()
        self.assertEqual(self.run_preflight(BRO_EXECUTION_LEASE_LEDGER=str(external)), [])

    def test_shadow_without_ledger_fails_open_and_is_caught(self):
        failures = self.run_preflight(BRO_ENFORCEMENT="shadow")
        self.assertTrue(any("BRO_SHADOW_LEDGER" in f for f in failures), failures)

    def test_missing_recovery_authority_fails(self):
        self._write_registry(v for k, v in self.keys.items() if k != "recovery")
        failures = self.run_preflight()
        self.assertTrue(any("recovery authority" in f for f in failures), failures)

    def test_builder_key_without_subject_identity_fails(self):
        keys = dict(self.keys)
        keys["builder"] = generate_key("builder", "dev-builder", False)  # no subject
        self._write_registry(keys.values())
        failures = self.run_preflight()
        self.assertTrue(any("subject_agent_id" in f for f in failures), failures)


if __name__ == "__main__":
    unittest.main()

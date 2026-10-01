import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from bro_deploy_preflight import preflight
from bro_signature import (
    ENV_PIN,
    ENV_PIN_FILE,
    ENV_PIN_SELF_OWNED_ACK,
    PIN_SELF_OWNED_ACK_VALUE,
)
from broctl import build_registry, generate_key

sys.path.insert(0, str(ROOT / "tests"))
import _self_owned_ack  # noqa: E402

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
        # (audit F-06) This process wrote the pin, so it owns it, and a self-owned anchor
        # is refused by default — correctly, since the reader can rewrite it. A test
        # harness has no second principal, which is the case the acknowledgement exists
        # for; state it rather than weaken the check for everyone.
        # Declared through the FILE form: the raw variable is honoured only under
        # `BRO_ENV=ci` now (a test host is not CI), because ungated it handed the pin's own
        # named adversary the short-circuit for one extra `export`.
        ack = _self_owned_ack.patch(self.tmp)
        ack.start()
        self.addCleanup(ack.stop)
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

    def test_every_ledger_and_store_the_runtime_reads_is_checked(self):
        """The preflight says it checks "every machine-local ledger/store that is configured".
        Its list held six names and the runtime read ten. Each one is driven here, both ways."""
        import bro_deploy_preflight
        for var in bro_deploy_preflight.LEDGER_VARS:
            with self.subTest(var=var):
                inside = self.run_preflight(**{var: str(self.root / "state" / "x")})
                self.assertTrue(any(var in f and "outside the repository" in f for f in inside),
                                inside)
                relative = self.run_preflight(**{var: "var/x"})
                self.assertTrue(any(var in f and "absolute" in f for f in relative), relative)
                self.assertEqual(self.run_preflight(**{var: str(self.tmp / "external")}), [])

    def test_the_list_is_the_runtimes_own_and_cannot_fall_behind_it(self):
        """Derived from the runtime's source: every `BRO_*` name the engine reads that ends in a
        ledger/store/directory/floor word must be in the preflight's list. The three it lacked
        -- the audit ledger, the mode-grant nonce ledger and the session-state directory -- are
        named so this test cannot be satisfied by an edit that drops them again."""
        import re
        import bro_deploy_preflight
        pattern = re.compile(r'"(BRO_[A-Z_]*(?:LEDGER|STORE|STATE_DIR|HEAD_FLOOR))"')
        read = set()
        for directory in (ROOT / "runtime", ROOT / "tools"):
            for path in directory.glob("*.py"):
                read |= set(pattern.findall(path.read_text(encoding="utf-8")))
        self.assertGreaterEqual(len(read), 10, sorted(read))
        self.assertEqual(sorted(read - set(bro_deploy_preflight.LEDGER_VARS)), [],
                         "the runtime reads a store the deployment preflight does not check")
        for var in ("BRO_AUDIT_LEDGER", "BRO_MODE_GRANT_NONCE_LEDGER", "BRO_SESSION_STATE_DIR"):
            self.assertIn(var, bro_deploy_preflight.LEDGER_VARS)

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

    def keygen(self, keydir, *argv):
        import contextlib
        import io
        import broctl
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = broctl.main(["keygen", "--out", str(keydir), *argv])
        return code, out.getvalue() + err.getvalue()

    def test_keygen_can_mint_the_subject_bound_key_this_preflight_requires(self):
        # The check above refuses every builder/verifier key without a subject, and
        # `broctl keygen` had no way to set one: only a test calling generate_key
        # directly, or a hand-edited key file, could ever pass it.
        keydir = self.tmp / "keys"
        keys = dict(self.keys)
        for authority, agent in (("builder", "agt-p01-r01"), ("verifier", "agt-p01-r05")):
            code, text = self.keygen(keydir, "--authority", authority, "--subject-agent-id", agent)
            self.assertEqual(code, 0, text)
            keys[authority] = json.loads((keydir / f"{authority}.json").read_text(encoding="utf-8"))
            self.assertEqual(keys[authority]["subject_agent_id"], agent)
            self.assertFalse(keys[authority]["production"])
        self._write_registry(keys.values())
        self.assertEqual(self.run_preflight(), [])

    def test_keygen_refuses_a_subject_on_an_authority_that_is_not_identity_bound(self):
        keydir = self.tmp / "keys"
        code, text = self.keygen(keydir, "--authority", "issuer", "--subject-agent-id", "agt-p01-r01")
        self.assertEqual(code, 1)
        self.assertIn("not identity-bound", text)
        self.assertFalse((keydir / "issuer.json").exists())
        code, text = self.keygen(keydir, "--authority", "builder", "--subject-agent-id", " ")
        self.assertEqual(code, 1)
        self.assertFalse((keydir / "builder.json").exists())


if __name__ == "__main__":
    unittest.main()

import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

import bro_env_health
from bro_env_health import EnvHealthError, check_environment, resolve, satisfies


class VersionTests(unittest.TestCase):
    def test_satisfies_lower_bound(self):
        self.assertTrue(satisfies("3.13.5", ">=3.11"))
        self.assertFalse(satisfies("3.10.0", ">=3.11"))

    def test_satisfies_range(self):
        self.assertTrue(satisfies("43.0.0", ">=41,<45"))
        self.assertFalse(satisfies("45.0.0", ">=41,<45"))
        self.assertTrue(satisfies("4.19.2", ">=4.18,<5"))
        self.assertFalse(satisfies("5.0.0", ">=4.18,<5"))


class ResolveTests(unittest.TestCase):
    def test_missing_library_is_unavailable(self):
        available, version, _ = resolve({"id": "ghost", "kind": "library", "resolve": "definitely_not_a_module_xyz", "version": ">=1"})
        self.assertFalse(available)

    def test_present_interpreter_reports_version(self):
        available, version, _ = resolve({"id": "python3", "kind": "interpreter", "resolve": "python3", "version": ">=3.11"})
        self.assertTrue(available)
        self.assertTrue(version)


class CheckEnvironmentTests(unittest.TestCase):
    def test_live_required_dependencies_resolve(self):
        # Allow-path: on this environment every required dependency is present.
        report = check_environment(ROOT)
        self.assertTrue(report["ok"])

    def test_missing_required_dependency_is_fail_closed(self):
        fake = {"phantom": {"id": "phantom", "kind": "library", "resolve": "no_such_module_zzz",
                            "version": ">=1", "required_for": ["runtime"], "optionality": "required"}}
        with patch.object(bro_env_health, "load_runtime_dependencies", return_value=fake):
            with self.assertRaises(EnvHealthError):
                check_environment(ROOT)

    def test_incompatible_version_is_fail_closed(self):
        fake = {"jsonschema": {"id": "jsonschema", "kind": "library", "resolve": "jsonschema",
                               "version": ">=999", "required_for": ["validation"], "optionality": "required"}}
        with patch.object(bro_env_health, "load_runtime_dependencies", return_value=fake):
            with self.assertRaises(EnvHealthError):
                check_environment(ROOT)

    def test_missing_optional_dependency_does_not_fail(self):
        fake = {"opt": {"id": "opt", "kind": "library", "resolve": "no_such_module_zzz",
                        "version": ">=1", "required_for": ["runtime"], "optionality": "optional"}}
        with patch.object(bro_env_health, "load_runtime_dependencies", return_value=fake):
            report = check_environment(ROOT)  # must not raise
            self.assertTrue(report["ok"])


if __name__ == "__main__":
    unittest.main()

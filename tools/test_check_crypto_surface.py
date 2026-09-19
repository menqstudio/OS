#!/usr/bin/env python3
"""Self-tests for tools/check_crypto_surface.py.

Each test builds a throwaway repository root on disk and runs the gate's own functions over
it, so nothing here asserts against the real tree: a test that passes only because this
repository happens to be clean would go green on a repository that is not.

The tests that matter are the ones that reconstruct the two defects the gate was written for:
`test_patch_level_fix_is_refused` is 2026-09-19's actual state (pin 46.0.3, three advisories
fixed in 46.0.5/6/7 waived under a major-bump excuse), and `test_pem_loader_is_refused` is the
future edit that would silently make four accepted HIGHs reachable.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest

import check_crypto_surface as gate


PIN = """\
jsonschema==4.25.1 \\
    --hash=sha256:aaaa
cryptography=={version} \\
    --hash=sha256:bbbb \\
    --hash=sha256:cccc
attrs==26.1.0 \\
    --hash=sha256:dddd
"""


class Fixture:
    """A minimal repository root: the pin, the waiver file, and any Python sources."""

    def __init__(self, stack: unittest.TestCase, version: str = "46.0.7"):
        self.root = pathlib.Path(tempfile.mkdtemp())
        stack.addCleanup(self._clean)
        (self.root / "engine").mkdir(parents=True)
        (self.root / ".github/supply-chain").mkdir(parents=True)
        self.pin(version)
        self.waivers([])

    def _clean(self) -> None:
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)

    def pin(self, version: str | None) -> None:
        text = "" if version is None else PIN.format(version=version)
        (self.root / gate.REQUIREMENTS).write_text(text, encoding="utf-8")

    def waivers(self, lines: list[str]) -> None:
        body = "# a comment line, ignored\n" + "".join(line + "\n" for line in lines)
        (self.root / gate.IGNORE_FILE).write_text(body, encoding="utf-8")

    def source(self, relative: str, body: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


class VersionKeyTests(unittest.TestCase):
    def test_compares_numerically_not_as_text(self):
        self.assertLess(gate.version_key("46.0.9"), gate.version_key("46.0.10"))
        self.assertLess(gate.version_key("46.0.7"), gate.version_key("48.0.1"))
        self.assertEqual(gate.version_key("46.0.7")[:2], gate.version_key("46.0.3")[:2])


class PinReadingTests(unittest.TestCase):
    def test_reads_the_pinned_version_past_the_hash_continuations(self):
        fixture = Fixture(self)
        self.assertEqual(gate.pinned_cryptography(fixture.root), "46.0.7")

    def test_no_pin_reads_as_none(self):
        fixture = Fixture(self)
        fixture.pin(None)
        self.assertIsNone(gate.pinned_cryptography(fixture.root))

    def test_an_unpinned_requirements_file_refuses_rather_than_passing(self):
        fixture = Fixture(self)
        fixture.pin(None)
        fixture.waivers(["GHSA-537c-gmf6-5ccf  # fixed=48.0.1 — unused surface"])
        problems, pinned, count = gate.scan_waivers(fixture.root)
        self.assertIsNone(pinned)
        self.assertEqual(count, 1)
        self.assertTrue(any("names no `cryptography==` pin" in p for p in problems))


class WaiverParsingTests(unittest.TestCase):
    def test_reads_ids_the_way_the_workflow_does(self):
        fixture = Fixture(self)
        fixture.waivers(
            [
                "GHSA-537c-gmf6-5ccf  # fixed=48.0.1 — bundled OpenSSL",
                "# a whole-line comment carrying fixed=1.0.0 is not an entry",
                "",
                "GHSA-g6cj-pr64-35w5  # fixed=50.0.0 — PKCS#7",
            ]
        )
        entries = gate.waived_entries(fixture.root)
        self.assertEqual(
            [(identifier, fixed) for _, identifier, fixed in entries],
            [("GHSA-537c-gmf6-5ccf", "48.0.1"), ("GHSA-g6cj-pr64-35w5", "50.0.0")],
        )

    def test_a_missing_ignore_file_is_no_waiver_rather_than_a_crash(self):
        fixture = Fixture(self)
        (fixture.root / gate.IGNORE_FILE).unlink()
        self.assertEqual(gate.waived_entries(fixture.root), [])


class WaiverFreshnessTests(unittest.TestCase):
    def test_a_fix_above_the_pin_is_the_legitimate_case(self):
        fixture = Fixture(self, version="46.0.7")
        fixture.waivers(
            [
                "GHSA-537c-gmf6-5ccf  # fixed=48.0.1 — bundled OpenSSL, unused",
                "GHSA-m2h6-j472-rp4c  # fixed=49.0.0 — X.509, unused",
                "GHSA-g6cj-pr64-35w5  # fixed=50.0.0 — PKCS#7, unused",
            ]
        )
        problems, pinned, count = gate.scan_waivers(fixture.root)
        self.assertEqual((pinned, count), ("46.0.7", 3))
        self.assertEqual(problems, [])

    def test_patch_level_fix_is_refused(self):
        """2026-09-19's real state: pin 46.0.3, three fixes inside the same 46.0 line."""
        fixture = Fixture(self, version="46.0.3")
        fixture.waivers(
            [
                "PYSEC-2026-2141  # fixed=46.0.5 — HIGH",
                "PYSEC-2026-35  # fixed=46.0.6",
                "PYSEC-2026-36  # fixed=46.0.7",
            ]
        )
        problems, _, _ = gate.scan_waivers(fixture.root)
        self.assertEqual(len(problems), 3, problems)
        for problem in problems:
            self.assertIn("PATCH release of the pinned 46.0.3", problem)

    def test_a_pin_that_reached_the_fix_kills_the_waiver(self):
        fixture = Fixture(self, version="49.0.0")
        fixture.waivers(["GHSA-m2h6-j472-rp4c  # fixed=49.0.0 — X.509, unused"])
        problems, _, _ = gate.scan_waivers(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("the waiver is dead", problems[0])

    def test_a_waiver_with_no_fixed_marker_is_refused(self):
        fixture = Fixture(self)
        fixture.waivers(["GHSA-g6cj-pr64-35w5  # PKCS#7 EnvelopedData, unused"])
        problems, _, _ = gate.scan_waivers(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("records no `fixed=<version>`", problems[0])

    def test_a_bare_package_name_is_refused_because_pip_audit_would_waive_nothing(self):
        fixture = Fixture(self)
        fixture.waivers(["cryptography  # fixed=99.0.0 — waive the package"])
        problems, _, _ = gate.scan_waivers(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("is not a GHSA / PYSEC / CVE id", problems[0])

    def test_a_cve_id_is_a_valid_advisory_id(self):
        fixture = Fixture(self)
        fixture.waivers(["CVE-2026-45447  # fixed=48.0.1 — PKCS7_verify, unused"])
        problems, _, _ = gate.scan_waivers(fixture.root)
        self.assertEqual(problems, [])


class SurfaceTests(unittest.TestCase):
    def test_the_ed25519_raw_surface_passes(self):
        fixture = Fixture(self)
        fixture.source(
            "engine/runtime/signing.py",
            "from cryptography.hazmat.primitives import serialization\n"
            "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey\n"
            "def mint():\n"
            "    key = Ed25519PrivateKey.generate()\n"
            "    return key.private_bytes(\n"
            "        serialization.Encoding.Raw,\n"
            "        serialization.PrivateFormat.Raw,\n"
            "        serialization.NoEncryption(),\n"
            "    )\n",
        )
        self.assertEqual(gate.scan_surface(fixture.root), [])

    def test_pem_loader_is_refused(self):
        fixture = Fixture(self)
        fixture.source(
            "bridge/sidecar.py",
            "from cryptography.hazmat.primitives.serialization import load_pem_private_key\n",
        )
        problems = gate.scan_surface(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("load_pem_private_key", problems[0])
        self.assertIn("bridge/sidecar.py:1", problems[0])

    def test_an_x509_import_is_refused_and_names_the_advisories(self):
        fixture = Fixture(self)
        fixture.source("engine/verify.py", "from cryptography import x509\n")
        problems = gate.scan_surface(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("GHSA-m2h6-j472-rp4c", problems[0])

    def test_a_submodule_import_is_refused(self):
        fixture = Fixture(self)
        fixture.source("engine/p7.py", "import cryptography.hazmat.primitives.serialization.pkcs7\n")
        problems = gate.scan_surface(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("PKCS#7", problems[0])

    def test_a_loader_called_as_an_attribute_is_refused_without_any_import(self):
        fixture = Fixture(self)
        fixture.source(
            "engine/attr.py",
            "def read(serialization, blob):\n    return serialization.load_der_public_key(blob)\n",
        )
        problems = gate.scan_surface(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("load_der_public_key", problems[0])

    def test_writing_pem_is_not_parsing_pem(self):
        """Encoding OUT touches no ASN.1 parser, so it is deliberately allowed."""
        fixture = Fixture(self)
        fixture.source(
            "engine/out.py",
            "from cryptography.hazmat.primitives import serialization\n"
            "def dump(key):\n"
            "    return key.public_bytes(\n"
            "        serialization.Encoding.PEM,\n"
            "        serialization.PublicFormat.SubjectPublicKeyInfo,\n"
            "    )\n",
        )
        self.assertEqual(gate.scan_surface(fixture.root), [])

    def test_skipped_directories_are_not_scanned(self):
        fixture = Fixture(self)
        fixture.source(
            "node_modules/vendor/thing.py",
            "from cryptography import x509\n",
        )
        fixture.source(".venv/lib/other.py", "from cryptography import x509\n")
        self.assertEqual(gate.scan_surface(fixture.root), [])

    def test_a_file_that_will_not_parse_is_reported_rather_than_skipped(self):
        fixture = Fixture(self)
        fixture.source("engine/broken.py", "from cryptography import x509\ndef (:\n")
        problems = gate.scan_surface(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("will not parse", problems[0])


class ExitCodeTests(unittest.TestCase):
    def test_green_exits_zero(self):
        fixture = Fixture(self)
        fixture.waivers(["GHSA-537c-gmf6-5ccf  # fixed=48.0.1 — unused"])
        self.assertEqual(gate.main(["--root", str(fixture.root)]), 0)

    def test_a_dead_waiver_exits_one(self):
        fixture = Fixture(self, version="48.0.1")
        fixture.waivers(["GHSA-537c-gmf6-5ccf  # fixed=48.0.1 — unused"])
        self.assertEqual(gate.main(["--root", str(fixture.root)]), 1)

    def test_a_reached_surface_exits_one(self):
        fixture = Fixture(self)
        fixture.waivers(["GHSA-537c-gmf6-5ccf  # fixed=48.0.1 — unused"])
        fixture.source("engine/v.py", "from cryptography import x509\n")
        self.assertEqual(gate.main(["--root", str(fixture.root)]), 1)


if __name__ == "__main__":
    unittest.main()
